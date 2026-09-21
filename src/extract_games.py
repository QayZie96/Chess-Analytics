"""Stream PGN headers into a small Parquet dataset.

The script deliberately skips movetext. It keeps only one game header block
and a bounded insert batch in memory at a time.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import re
import secrets
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import zstandard as zstd


HEADER_PATTERN = re.compile(r'^\[([^\s]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')
FIELDS = (
    "game_id",
    "utc_date",
    "utc_time",
    "white_player_id",
    "black_player_id",
    "white_elo",
    "black_elo",
    "white_rating_diff",
    "black_rating_diff",
    "result",
    "eco",
    "opening",
    "time_control",
    "termination",
    "event",
)
HEADER_TO_FIELD = {
    "UTCDate": "utc_date",
    "UTCTime": "utc_time",
    "WhiteElo": "white_elo",
    "BlackElo": "black_elo",
    "WhiteRatingDiff": "white_rating_diff",
    "BlackRatingDiff": "black_rating_diff",
    "Result": "result",
    "ECO": "eco",
    "Opening": "opening",
    "TimeControl": "time_control",
    "Termination": "termination",
    "Event": "event",
}


def parse_arguments() -> argparse.Namespace:
    """Read command-line options with beginner-friendly project defaults."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/lichess_db_standard_rated_2026-08.pgn.zst"),
        help="Compressed PGN input file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/games_sample.parquet"),
        help="Parquet output file.",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=Path("secrets/player_hash.key"),
        help="Local ignored file containing the persistent HMAC key.",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=10_000,
        help="Maximum number of games to extract (default: 10000).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1_000,
        help="Number of rows inserted into DuckDB at a time.",
    )
    return parser.parse_args()


def load_or_create_key(key_file: Path) -> bytes:
    """Reuse a local HMAC key, creating it only when it does not exist."""
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


def unescape_pgn_value(value: str) -> str:
    """Decode the escaped quote and backslash characters used in PGN tags."""
    return value.replace(r'\"', '"').replace(r"\\", "\\")


def iter_header_blocks(
    input_path: Path,
    max_games: int,
) -> Iterator[tuple[dict[str, str], int | None]]:
    """Yield header dictionaries without retaining movetext in memory."""
    headers: dict[str, str] = {}
    in_headers = False
    error_line: int | None = None
    games_seen = 0

    with input_path.open("rb") as compressed:
        with zstd.ZstdDecompressor().stream_reader(compressed) as decompressed:
            text = io.TextIOWrapper(
                decompressed, encoding="utf-8", errors="replace", newline=""
            )
            for line_number, raw_line in enumerate(text, start=1):
                line = raw_line.rstrip("\r\n")

                if line.startswith("[Event "):
                    if headers:
                        yield headers, error_line
                        games_seen += 1
                        if games_seen >= max_games:
                            return
                    headers = {}
                    error_line = None
                    in_headers = True

                if not in_headers:
                    continue
                if not line:
                    in_headers = False
                    continue

                match = HEADER_PATTERN.match(line)
                if match:
                    tag, value = match.groups()
                    headers[tag] = unescape_pgn_value(value)
                elif error_line is None:
                    error_line = line_number

            if headers and games_seen < max_games:
                yield headers, error_line


def player_id(username: str | None, key: bytes) -> str | None:
    """Return a stable pseudonymous ID without storing the username."""
    if not username or username == "?":
        return None
    digest = hmac.new(key, username.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"player_{digest[:24]}"


def game_id_from_site(site: str | None) -> str | None:
    """Extract the Lichess game ID from its Site URL."""
    if not site or site == "?":
        return None
    return site.rstrip("/").rsplit("/", maxsplit=1)[-1] or None


def make_row(headers: dict[str, str], key: bytes) -> tuple[Any, ...]:
    """Convert PGN tags into the fixed Parquet row schema."""
    row: dict[str, Any] = {field: None for field in FIELDS}
    row["game_id"] = game_id_from_site(headers.get("Site"))
    row["white_player_id"] = player_id(headers.get("White"), key)
    row["black_player_id"] = player_id(headers.get("Black"), key)
    for header, field in HEADER_TO_FIELD.items():
        value = headers.get(header)
        row[field] = None if value in (None, "", "?") else value
    return tuple(row[field] for field in FIELDS)


def create_table(connection: duckdb.DuckDBPyConnection) -> None:
    """Create the typed staging table used for batched inserts and reporting."""
    connection.execute(
        """
        CREATE TABLE games (
            game_id VARCHAR,
            utc_date VARCHAR,
            utc_time VARCHAR,
            white_player_id VARCHAR,
            black_player_id VARCHAR,
            white_elo VARCHAR,
            black_elo VARCHAR,
            white_rating_diff VARCHAR,
            black_rating_diff VARCHAR,
            result VARCHAR,
            eco VARCHAR,
            opening VARCHAR,
            time_control VARCHAR,
            termination VARCHAR,
            event VARCHAR
        )
        """
    )


def build_report(
    connection: duckdb.DuckDBPyConnection,
    output_path: Path,
    processing_seconds: float,
    extraction_errors: int,
) -> dict[str, Any]:
    """Calculate quality checks and write the table to Parquet."""
    connection.execute("COPY games TO ? (FORMAT PARQUET)", [str(output_path)])
    row_count = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    missing = {
        field: count
        for field, count in zip(
            FIELDS,
            connection.execute(
                "SELECT "
                + ", ".join(f"COUNT(*) - COUNT({field})" for field in FIELDS)
                + " FROM games"
            ).fetchone(),
        )
    }
    distinct_values = {}
    for field in ("result", "termination", "time_control"):
        distinct_values[field] = [
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT {field} FROM games WHERE {field} IS NOT NULL ORDER BY {field}"
            ).fetchall()
        ]
    duplicate_ids = connection.execute(
        """
        SELECT COALESCE(SUM(game_count - 1), 0)
        FROM (
            SELECT game_id, COUNT(*) AS game_count
            FROM games
            WHERE game_id IS NOT NULL
            GROUP BY game_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    report = {
        "row_count": row_count,
        "processing_seconds": round(processing_seconds, 3),
        "output_size_bytes": output_path.stat().st_size,
        "missing_value_counts": missing,
        "distinct_values": distinct_values,
        "eco_available": missing["eco"] < row_count,
        "opening_available": missing["opening"] < row_count,
        "rating_change_available": (
            missing["white_rating_diff"] < row_count
            or missing["black_rating_diff"] < row_count
        ),
        "duplicate_game_ids": duplicate_ids,
        "extraction_errors": extraction_errors,
    }
    return report


def extract_games(args: argparse.Namespace) -> dict[str, Any]:
    """Run the bounded stream, batch inserts, Parquet export, and reporting."""
    if args.max_games <= 0 or args.batch_size <= 0:
        raise ValueError("--max-games and --batch-size must be positive")
    if not args.input.exists():
        raise FileNotFoundError(args.input)

    key = load_or_create_key(args.key_file)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    connection = duckdb.connect()
    try:
        create_table(connection)
        insert_sql = f"INSERT INTO games ({', '.join(FIELDS)}) VALUES ({', '.join('?' for _ in FIELDS)})"
        batch: list[tuple[Any, ...]] = []
        extraction_errors = 0
        for headers, error_line in iter_header_blocks(args.input, args.max_games):
            extraction_errors += error_line is not None
            batch.append(make_row(headers, key))
            if len(batch) >= args.batch_size:
                connection.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            connection.executemany(insert_sql, batch)
        return build_report(
            connection,
            args.output,
            time.perf_counter() - start,
            extraction_errors,
        )
    finally:
        connection.close()


def main() -> None:
    args = parse_arguments()
    report = extract_games(args)
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()