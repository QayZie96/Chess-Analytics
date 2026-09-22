"""Build and validate privacy-safe browser data for the Chess Analytics dashboard.

Only the reviewed aggregate CSV exports are read. The generated JSON has no
player identifiers, game identifiers, raw PGN headers, or local source paths.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "exports" / "powerbi"
OUTPUT = ROOT / "data" / "public"

UPSET_COLUMNS = (
    "speed_category",
    "rating_gap_band",
    "lower_rated_player_band",
    "eligible_games",
    "upset_games",
)
OPENING_COLUMNS = (
    "opening_name",
    "eco_code",
    "rating_band",
    "player_color",
    "speed_category",
    "games",
    "wins",
    "draws",
    "losses",
)
COUNT_COLUMNS = {"eligible_games", "upset_games", "games", "wins", "draws", "losses"}
EXPECTED = {
    "upset_rows": 101,
    "opening_rows": 43_482,
    "eligible_games": 118_787,
    "upset_games": 30_779,
    "opening_player_side_observations": 764_194,
    "opening_unique_comparable_games": 382_097,
}


def read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    """Read one reviewed aggregate CSV and enforce its exact public schema."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"Unexpected schema in {path.name}: {reader.fieldnames}")
        records: list[dict[str, Any]] = []
        for line_number, row in enumerate(reader, 2):
            record: dict[str, Any] = {}
            for field in columns:
                value = row.get(field)
                if value is None or value == "":
                    raise ValueError(f"Missing {field} in {path.name} row {line_number}")
                if field in COUNT_COLUMNS:
                    if not value.isdigit():
                        raise ValueError(f"Non-integer {field} in {path.name} row {line_number}")
                    record[field] = int(value)
                else:
                    record[field] = value
            records.append(record)
    return records


def validate_records(upsets: list[dict[str, Any]], openings: list[dict[str, Any]]) -> dict[str, int]:
    """Validate public-data invariants and the dashboard's weighted logic."""
    if len(upsets) != EXPECTED["upset_rows"] or len(openings) != EXPECTED["opening_rows"]:
        raise AssertionError("Unexpected aggregate export row count")

    eligible_games = sum(row["eligible_games"] for row in upsets)
    upset_games = sum(row["upset_games"] for row in upsets)
    if not all(0 <= row["upset_games"] <= row["eligible_games"] for row in upsets):
        raise AssertionError("Invalid upset count invariant")
    if (eligible_games, upset_games) != (EXPECTED["eligible_games"], EXPECTED["upset_games"]):
        raise AssertionError("Upset totals do not match the validated baseline")

    player_side_observations = sum(row["games"] for row in openings)
    wins = sum(row["wins"] for row in openings)
    draws = sum(row["draws"] for row in openings)
    losses = sum(row["losses"] for row in openings)
    if not all(row["games"] == row["wins"] + row["draws"] + row["losses"] for row in openings):
        raise AssertionError("Opening outcome counts do not reconcile")
    if player_side_observations != EXPECTED["opening_player_side_observations"]:
        raise AssertionError("Opening player-side observations do not match the validated baseline")
    if player_side_observations // 2 != EXPECTED["opening_unique_comparable_games"]:
        raise AssertionError("Opening unique-game reconciliation failed")
    if (wins, draws, losses) != (367_980, 28_234, 367_980):
        raise AssertionError("Opening outcome totals do not match the validated baseline")

    # Representative weighted aggregation: never average precomputed rates.
    bullet_moderate = [row for row in upsets if row["speed_category"] == "bullet" and row["rating_gap_band"] == "100-199"]
    if not bullet_moderate or sum(row["eligible_games"] for row in bullet_moderate) <= 0:
        raise AssertionError("Representative upset filter returned no data")

    # The threshold is deliberately evaluated after filter/group aggregation.
    grouped_games: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
    for row in openings:
        grouped_games[(row["opening_name"], row["rating_band"], row["player_color"], row["speed_category"])] += row["games"]
    qualifying = sum(games >= 100 for games in grouped_games.values())
    sparse = sum(games < 100 for games in grouped_games.values())
    if qualifying == 0 or sparse == 0:
        raise AssertionError("Dynamic opening sample eligibility was not preserved")

    return {
        "eligible_games": eligible_games,
        "upset_games": upset_games,
        "opening_player_side_observations": player_side_observations,
        "opening_unique_comparable_games": player_side_observations // 2,
        "opening_wins": wins,
        "opening_draws": draws,
        "opening_losses": losses,
        "dynamic_eligible_groups": qualifying,
        "dynamic_sparse_groups": sparse,
    }


def encode(columns: tuple[str, ...], records: list[dict[str, Any]], grain: str) -> dict[str, Any]:
    """Use compact row arrays while retaining a self-describing browser schema."""
    return {
        "schema_version": 1,
        "format": "row-array",
        "columns": list(columns),
        "grain": grain,
        "rows": [[record[column] for column in columns] for record in records],
    }


def decode(payload: dict[str, Any], columns: tuple[str, ...]) -> list[dict[str, Any]]:
    """Recover records for export-equivalence checks and consumer examples."""
    if payload.get("schema_version") != 1 or payload.get("format") != "row-array":
        raise ValueError("Unsupported public data format")
    if tuple(payload.get("columns", ())) != columns:
        raise ValueError("Public data columns do not match the documented schema")
    return [dict(zip(columns, row, strict=True)) for row in payload.get("rows", [])]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def build(output_directory: Path = OUTPUT) -> dict[str, int]:
    upsets = read_csv(SOURCE / "rating_upsets_powerbi.csv", UPSET_COLUMNS)
    openings = read_csv(SOURCE / "opening_performance_powerbi.csv", OPENING_COLUMNS)
    report = validate_records(upsets, openings)
    output_directory.mkdir(parents=True, exist_ok=True)
    upset_payload = encode(UPSET_COLUMNS, upsets, "speed_category x rating_gap_band x lower_rated_player_band")
    opening_payload = encode(OPENING_COLUMNS, openings, "opening_name x eco_code x rating_band x player_color x speed_category")
    write_json(output_directory / "rating-upsets.v1.json", upset_payload)
    write_json(output_directory / "opening-performance.v1.json", opening_payload)
    if decode(json.loads((output_directory / "rating-upsets.v1.json").read_text(encoding="utf-8")), UPSET_COLUMNS) != upsets:
        raise AssertionError("Rating-upset JSON is not equivalent to its aggregate source")
    if decode(json.loads((output_directory / "opening-performance.v1.json").read_text(encoding="utf-8")), OPENING_COLUMNS) != openings:
        raise AssertionError("Opening JSON is not equivalent to its aggregate source")
    return report


def validate_existing(output_directory: Path = OUTPUT) -> dict[str, int]:
    upsets = read_csv(SOURCE / "rating_upsets_powerbi.csv", UPSET_COLUMNS)
    openings = read_csv(SOURCE / "opening_performance_powerbi.csv", OPENING_COLUMNS)
    report = validate_records(upsets, openings)
    for filename, columns, source_rows in (
        ("rating-upsets.v1.json", UPSET_COLUMNS, upsets),
        ("opening-performance.v1.json", OPENING_COLUMNS, openings),
    ):
        payload = json.loads((output_directory / filename).read_text(encoding="utf-8"))
        if decode(payload, columns) != source_rows:
            raise AssertionError(f"{filename} is not equivalent to its aggregate source")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=OUTPUT)
    parser.add_argument("--validate-existing", action="store_true")
    arguments = parser.parse_args()
    result = validate_existing(arguments.output_directory) if arguments.validate_existing else build(arguments.output_directory)
    print(json.dumps(result, sort_keys=True))
