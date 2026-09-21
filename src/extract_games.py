"""Stream PGN headers into typed, resumable Parquet batches with bounded memory."""
from __future__ import annotations

import argparse, hashlib, hmac, io, json, re, secrets, time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import zstandard as zstd

HEADER_PATTERN = re.compile(r'^\[([^\s]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')
URL_SUFFIX_PATTERN = re.compile(r"\s+https?://\S+$")
PLAYER_ID_PATTERN = r"^player_[0-9a-f]{24}$"
FIELDS = ("game_id", "utc_timestamp", "white_player_id", "black_player_id", "white_elo", "black_elo", "white_rating_diff", "black_rating_diff", "result", "eco", "opening", "time_control", "speed_category", "termination", "event")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/lichess_db_standard_rated_2026-08.pgn.zst"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/august_2026_batches"), help="New directory for numbered Parquet batches.")
    parser.add_argument("--key-file", type=Path, default=Path("secrets/player_hash.key"), help="Existing ignored HMAC key; never printed.")
    parser.add_argument("--max-games", type=int, default=None, help="Optional limit; omit for the full archive.")
    parser.add_argument("--batch-size", type=int, default=100_000, help="Games per durable batch (default: 100000).")
    parser.add_argument("--resume", action="store_true", help="Continue after completed batches in --output-dir.")
    return parser.parse_args()


def load_or_create_key(key_file: Path) -> bytes:
    if key_file.exists():
        key = key_file.read_bytes()
        if len(key) != 32:
            raise ValueError(f"Key file must contain exactly 32 bytes: {key_file}")
        return key
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    with key_file.open("xb") as handle:
        handle.write(key)
    return key


def clean(value: str | None) -> str | None:
    return None if value in (None, "", "?") else value


def iter_header_blocks(input_path: Path) -> Iterator[tuple[dict[str, str], int | None]]:
    """Decompress sequentially; retain only headers for the current game."""
    headers: dict[str, str] = {}
    in_headers = False
    error_line: int | None = None
    with input_path.open("rb") as compressed:
        with zstd.ZstdDecompressor().stream_reader(compressed) as stream:
            for line_number, raw in enumerate(io.TextIOWrapper(stream, encoding="utf-8", errors="replace", newline=""), 1):
                line = raw.rstrip("\r\n")
                if line.startswith("[Event "):
                    if headers:
                        yield headers, error_line
                    headers, error_line, in_headers = {}, None, True
                if not in_headers:
                    continue
                if not line:
                    in_headers = False
                    continue
                match = HEADER_PATTERN.match(line)
                if match:
                    tag, value = match.groups()
                    headers[tag] = value.replace(r'\"', '"').replace(r"\\", "\\")
                elif error_line is None:
                    error_line = line_number
            if headers:
                yield headers, error_line


def player_id(username: str | None, key: bytes) -> str | None:
    if not username or username == "?":
        return None
    return "player_" + hmac.new(key, username.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def integer(value: str | None) -> tuple[int | None, bool]:
    value = clean(value)
    if value is None:
        return None, False
    try:
        return int(value), False
    except ValueError:
        return None, True


def timestamp(headers: dict[str, str]) -> tuple[datetime | None, bool]:
    date, clock = clean(headers.get("UTCDate")), clean(headers.get("UTCTime"))
    if date is None or clock is None:
        return None, False
    try:
        return datetime.strptime(f"{date} {clock}", "%Y.%m.%d %H:%M:%S"), False
    except ValueError:
        return None, True


def normalized_event(event: str | None) -> tuple[str | None, str]:
    """Retain useful labels but strip tournament URLs; infer speeds only from Event."""
    event = clean(event)
    if event:
        event = URL_SUFFIX_PATTERN.sub("", event)
    lowered = (event or "").lower()
    for speed in ("ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence"):
        if speed in lowered:
            return event, speed
    return event, "unknown"


def make_row(headers: dict[str, str], key: bytes) -> tuple[tuple[Any, ...], int]:
    stamp, bad_stamp = timestamp(headers)
    white_elo, bad_white = integer(headers.get("WhiteElo"))
    black_elo, bad_black = integer(headers.get("BlackElo"))
    white_diff, bad_white_diff = integer(headers.get("WhiteRatingDiff"))
    black_diff, bad_black_diff = integer(headers.get("BlackRatingDiff"))
    event, speed = normalized_event(headers.get("Event"))
    site = clean(headers.get("Site"))
    game_id = site.rstrip("/").rsplit("/", 1)[-1] if site else None
    return (game_id, stamp, player_id(headers.get("White"), key), player_id(headers.get("Black"), key), white_elo, black_elo, white_diff, black_diff, clean(headers.get("Result")), clean(headers.get("ECO")), clean(headers.get("Opening")), clean(headers.get("TimeControl")), speed, clean(headers.get("Termination")), event), sum((bad_stamp, bad_white, bad_black, bad_white_diff, bad_black_diff))


def create_table(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("""CREATE TABLE games (game_id VARCHAR, utc_timestamp TIMESTAMP,
      white_player_id VARCHAR, black_player_id VARCHAR, white_elo INTEGER, black_elo INTEGER,
      white_rating_diff INTEGER, black_rating_diff INTEGER, result VARCHAR, eco VARCHAR,
      opening VARCHAR, time_control VARCHAR, speed_category VARCHAR, termination VARCHAR, event VARCHAR)""")


def batches(output_dir: Path) -> list[Path]:
    return sorted(output_dir.glob("games_*.parquet")) if output_dir.exists() else []


def output_size(output_dir: Path) -> int:
    return sum(path.stat().st_size for path in batches(output_dir))


def write_batch(rows: list[tuple[Any, ...]], output_path: Path) -> None:
    partial = output_path.with_suffix(".partial")
    if output_path.exists() or partial.exists():
        raise FileExistsError(f"Refusing to overwrite batch path: {output_path}")
    connection = duckdb.connect()
    try:
        create_table(connection)
        connection.executemany(f"INSERT INTO games ({', '.join(FIELDS)}) VALUES ({', '.join('?' for _ in FIELDS)})", rows)
        connection.execute("COPY games TO ? (FORMAT PARQUET)", [str(partial)])
    finally:
        connection.close()
    partial.replace(output_path)


def existing_count(files: list[Path]) -> int:
    connection = duckdb.connect()
    try:
        return sum(connection.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0] for path in files)
    finally:
        connection.close()


def validate(output_dir: Path) -> dict[str, Any]:
    files = batches(output_dir)
    if not files:
        return {"row_count": 0, "completed_batches": 0}
    connection = duckdb.connect()
    glob = str(output_dir / "games_*.parquet")
    try:
        checks = connection.execute("""SELECT COUNT(*), COUNT(*)-COUNT(DISTINCT game_id),
          SUM(utc_timestamp IS NULL)::BIGINT,
          SUM(white_elo IS NOT NULL AND (white_elo<100 OR white_elo>4000))::BIGINT,
          SUM(black_elo IS NOT NULL AND (black_elo<100 OR black_elo>4000))::BIGINT,
          SUM(result IS NULL OR result NOT IN ('1-0','0-1','1/2-1/2'))::BIGINT,
          SUM(white_player_id IS NULL OR black_player_id IS NULL OR NOT regexp_matches(white_player_id, ?) OR NOT regexp_matches(black_player_id, ?))::BIGINT FROM read_parquet(?)""", [PLAYER_ID_PATTERN, PLAYER_ID_PATTERN, glob]).fetchone()
        missing = dict(zip(FIELDS, connection.execute("SELECT " + ", ".join(f"COUNT(*)-COUNT({field})" for field in FIELDS) + " FROM read_parquet(?)", [glob]).fetchone()))
    finally:
        connection.close()
    names = ("row_count", "duplicate_game_ids", "missing_or_invalid_timestamps", "invalid_white_ratings", "invalid_black_ratings", "invalid_results", "invalid_player_ids")
    return {"completed_batches": len(files), "output_size_bytes": output_size(output_dir), "missing_value_counts": missing, **dict(zip(names, checks))}


def progress(processed: int, started: float, output_dir: Path, errors: int) -> dict[str, Any]:
    elapsed = time.perf_counter() - started
    return {"processed_games": processed, "elapsed_seconds": round(elapsed, 3), "games_per_second": round(processed / elapsed, 2) if elapsed else 0, "completed_batches": len(batches(output_dir)), "extraction_errors": errors, "output_size_bytes": output_size(output_dir)}


def extract_games(args: argparse.Namespace) -> dict[str, Any]:
    if (args.max_games is not None and args.max_games <= 0) or args.batch_size <= 0:
        raise ValueError("--max-games (when supplied) and --batch-size must be positive")
    if not args.input.exists():
        raise FileNotFoundError(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prior = batches(args.output_dir)
    if prior and not args.resume:
        raise FileExistsError("Output directory contains batches; choose a new directory or use --resume.")
    key = load_or_create_key(args.key_file)
    processed = existing_count(prior) if args.resume else 0
    start, errors, rows, batch_number = time.perf_counter(), 0, [], len(prior) + 1
    for number, (headers, header_error) in enumerate(iter_header_blocks(args.input), 1):
        if args.max_games is not None and number > args.max_games:
            break
        if number <= processed:
            continue
        row, row_errors = make_row(headers, key)
        rows.append(row); errors += int(header_error is not None) + row_errors
        if len(rows) == args.batch_size:
            write_batch(rows, args.output_dir / f"games_{batch_number:06d}.parquet")
            processed += len(rows); rows.clear(); batch_number += 1
            print(json.dumps(progress(processed, start, args.output_dir, errors), ensure_ascii=True), flush=True)
    if rows:
        write_batch(rows, args.output_dir / f"games_{batch_number:06d}.parquet")
        processed += len(rows)
        print(json.dumps(progress(processed, start, args.output_dir, errors), ensure_ascii=True), flush=True)
    report = progress(processed, start, args.output_dir, errors)
    report["validation"] = validate(args.output_dir)
    return report


if __name__ == "__main__":
    print(json.dumps(extract_games(parse_arguments()), indent=2, ensure_ascii=True))
