"""Create privacy-safe aggregate CSV exports for the Power BI dashboard."""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "mvp_500k_batches"
DEFAULT_OUTPUT = ROOT / "data" / "exports" / "powerbi"
EXPECTED_GAMES = 500_000
EXPECTED_UPSET_ELIGIBLE = 118_787
EXPECTED_UPSETS = 30_779
EXPECTED_COMPARABLE_OPENING_GAMES = 382_097


def open_analysis_connection() -> duckdb.DuckDBPyConnection:
    """Create only the privacy-safe analytical views needed for the exports."""
    files = [DATA / f"games_{number:06d}.parquet" for number in range(1, 6)]
    if not all(path.is_file() for path in files):
        raise FileNotFoundError("Expected five completed Parquet batches were not found.")

    file_list = ", ".join(repr(path.as_posix()) for path in files)
    connection = duckdb.connect()
    connection.execute(
        f"""CREATE VIEW games AS
        SELECT white_elo, black_elo, result, eco, opening, speed_category
        FROM read_parquet([{file_list}])"""
    )
    connection.execute(
        """CREATE VIEW featured AS
        SELECT *,
          white_elo BETWEEN 100 AND 4000 AND black_elo BETWEEN 100 AND 4000 AS valid_ratings,
          result IN ('1-0', '0-1', '1/2-1/2') AS valid_result,
          opening IS NOT NULL AND opening NOT IN ('', '?') AS valid_opening,
          ABS(white_elo - black_elo) AS rating_gap
        FROM games"""
    )
    return connection


def export_queries() -> tuple[str, str]:
    """Return SQL for the two dashboard grains, without player or game identifiers."""
    rating_band = """CASE
      WHEN rating < 800 THEN 'Below 800'
      WHEN rating < 1200 THEN '800-1199'
      WHEN rating < 1500 THEN '1200-1499'
      WHEN rating < 1800 THEN '1500-1799'
      WHEN rating < 2100 THEN '1800-2099'
      ELSE '2100+'
    END"""
    upset_query = f"""WITH eligible AS (
      SELECT
        COALESCE(speed_category, 'Unknown') AS speed_category,
        CASE
          WHEN rating_gap < 200 THEN '100-199'
          WHEN rating_gap < 400 THEN '200-399'
          ELSE '400+'
        END AS rating_gap_band,
        {rating_band.replace('rating', 'CASE WHEN white_elo < black_elo THEN white_elo ELSE black_elo END')} AS lower_rated_player_band,
        CASE
          WHEN white_elo < black_elo AND result = '1-0' THEN TRUE
          WHEN black_elo < white_elo AND result = '0-1' THEN TRUE
          ELSE FALSE
        END AS is_upset
      FROM featured
      WHERE valid_ratings AND valid_result AND rating_gap >= 100
    )
    SELECT speed_category, rating_gap_band, lower_rated_player_band,
      COUNT(*)::BIGINT AS eligible_games,
      SUM(is_upset)::BIGINT AS upset_games
    FROM eligible
    GROUP BY 1, 2, 3
    ORDER BY speed_category, rating_gap_band, lower_rated_player_band"""

    opening_query = f"""WITH comparable_games AS (
      SELECT *
      FROM featured
      WHERE valid_ratings AND valid_result AND valid_opening AND rating_gap <= 100
    ), player_perspectives AS (
      SELECT opening AS opening_name, eco AS eco_code,
        {rating_band.replace('rating', 'white_elo')} AS rating_band,
        'White' AS player_color,
        COALESCE(speed_category, 'Unknown') AS speed_category,
        CASE WHEN result = '1-0' THEN 'win' WHEN result = '0-1' THEN 'loss' ELSE 'draw' END AS outcome
      FROM comparable_games
      UNION ALL
      SELECT opening, eco,
        {rating_band.replace('rating', 'black_elo')},
        'Black', COALESCE(speed_category, 'Unknown'),
        CASE WHEN result = '0-1' THEN 'win' WHEN result = '1-0' THEN 'loss' ELSE 'draw' END
      FROM comparable_games
    )
    SELECT opening_name, eco_code, rating_band, player_color, speed_category,
      COUNT(*)::BIGINT AS games,
      SUM(outcome = 'win')::BIGINT AS wins,
      SUM(outcome = 'draw')::BIGINT AS draws,
      SUM(outcome = 'loss')::BIGINT AS losses
    FROM player_perspectives
    GROUP BY 1, 2, 3, 4, 5
    ORDER BY opening_name, eco_code, rating_band, player_color, speed_category"""
    return upset_query, opening_query


def validate(connection: duckdb.DuckDBPyConnection, upset_query: str, opening_query: str) -> dict[str, int]:
    """Validate source populations and aggregate-table reconciliation invariants."""
    source_games = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    upset_rows = connection.execute(
        f"SELECT SUM(eligible_games), SUM(upset_games), MIN(upset_games >= 0 AND upset_games <= eligible_games) FROM ({upset_query})"
    ).fetchone()
    opening_rows = connection.execute(
        f"""SELECT SUM(games), MIN(games = wins + draws + losses),
          MIN(games >= 0 AND wins >= 0 AND draws >= 0 AND losses >= 0),
          SUM(opening_name IS NULL OR opening_name IN ('', '?'))
        FROM ({opening_query})"""
    ).fetchone()
    comparable_games = connection.execute(
        """SELECT COUNT(*) FROM featured
        WHERE valid_ratings AND valid_result AND valid_opening AND rating_gap <= 100"""
    ).fetchone()[0]

    assert source_games == EXPECTED_GAMES
    assert upset_rows == (EXPECTED_UPSET_ELIGIBLE, EXPECTED_UPSETS, True)
    assert comparable_games == EXPECTED_COMPARABLE_OPENING_GAMES
    assert opening_rows == (comparable_games * 2, True, True, 0)
    return {
        "source_games": source_games,
        "upset_eligible_games": upset_rows[0],
        "upset_games": upset_rows[1],
        "opening_comparable_games": comparable_games,
        "opening_player_color_observations": opening_rows[0],
    }


def write_csv(connection: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    """Write a UTF-8 CSV from an aggregate query without a pandas data load."""
    escaped_path = path.as_posix().replace("'", "''")
    connection.execute(f"COPY ({query}) TO '{escaped_path}' (HEADER, DELIMITER ',')")


def write_data_dictionary(path: Path) -> None:
    """Write a short local guide for the two dashboard tables."""
    path.write_text(
        """# Power BI aggregate exports

These UTF-8 CSVs contain aggregate counts only: no player or game identifiers.

## rating_upsets_powerbi.csv

Grain: `speed_category` x `rating_gap_band` x `lower_rated_player_band`.
Rows include valid-rating, valid-result games with a rating gap of at least 100.
`eligible_games` is the denominator; `upset_games` is the lower-rated player winning.
Draws remain in `eligible_games`.

## opening_performance_powerbi.csv

Grain: `opening_name` x `eco_code` x `rating_band` x `player_color` x `speed_category`.
Rows include valid ratings/results, known openings, and opponents within 100 Elo.
Each eligible game contributes two player-color observations. `games = wins + draws + losses`.
The export deliberately has no fixed 100-game threshold, so Power BI can apply a dynamic threshold after slicers.
""",
        encoding="utf-8",
    )


def validate_export_files(output_directory: Path) -> dict[str, object]:
    """Read existing CSVs through DuckDB and verify their export-level invariants."""
    upset_path = output_directory / "rating_upsets_powerbi.csv"
    opening_path = output_directory / "opening_performance_powerbi.csv"
    if not upset_path.is_file() or not opening_path.is_file():
        raise FileNotFoundError("Both Power BI CSV exports must exist for read-back validation.")

    connection = duckdb.connect()
    upset_schema = connection.execute(
        "DESCRIBE SELECT * FROM read_csv_auto(?)", [str(upset_path)]
    ).fetchall()
    opening_schema = connection.execute(
        "DESCRIBE SELECT * FROM read_csv_auto(?)", [str(opening_path)]
    ).fetchall()
    upset_checks = connection.execute(
        """SELECT COUNT(*), SUM(eligible_games), SUM(upset_games),
          MIN(upset_games >= 0 AND upset_games <= eligible_games)
        FROM read_csv_auto(?)""",
        [str(upset_path)],
    ).fetchone()
    opening_checks = connection.execute(
        """SELECT COUNT(*), SUM(games),
          MIN(games = wins + draws + losses),
          MIN(games >= 0 AND wins >= 0 AND draws >= 0 AND losses >= 0),
          SUM(opening_name IS NULL OR opening_name IN ('', '?')),
          MIN(games), MAX(games), SUM(games < 5), SUM(games < 100),
          COUNT(DISTINCT speed_category)
        FROM read_csv_auto(?)""",
        [str(opening_path)],
    ).fetchone()

    assert upset_checks == (101, EXPECTED_UPSET_ELIGIBLE, EXPECTED_UPSETS, True)
    assert opening_checks[1:5] == (EXPECTED_COMPARABLE_OPENING_GAMES * 2, True, True, 0)
    return {
        "upset_schema": [(column, data_type) for column, data_type, *_ in upset_schema],
        "opening_schema": [(column, data_type) for column, data_type, *_ in opening_schema],
        "upset_rows": upset_checks[0],
        "opening_rows": opening_checks[0],
        "opening_min_games": opening_checks[5],
        "opening_max_games": opening_checks[6],
        "opening_groups_under_5_games": opening_checks[7],
        "opening_groups_under_100_games": opening_checks[8],
        "opening_speed_categories": opening_checks[9],
    }


def run(output_directory: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    """Create the two exports and return a compact validation report."""
    output_directory.mkdir(parents=True, exist_ok=True)
    upset_path = output_directory / "rating_upsets_powerbi.csv"
    opening_path = output_directory / "opening_performance_powerbi.csv"
    for path in (upset_path, opening_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite an existing export: {path}")

    connection = open_analysis_connection()
    upset_query, opening_query = export_queries()
    checks = validate(connection, upset_query, opening_query)
    write_csv(connection, upset_query, upset_path)
    write_csv(connection, opening_query, opening_path)
    write_data_dictionary(output_directory / "README.md")

    report: dict[str, object] = {
        **checks,
        "upset_bytes": upset_path.stat().st_size,
        "opening_bytes": opening_path.stat().st_size,
    }
    report.update(validate_export_files(output_directory))
    print(report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--validate-existing",
        action="store_true",
        help="Read and validate existing exports without writing files.",
    )
    arguments = parser.parse_args()
    if arguments.validate_existing:
        print(validate_export_files(arguments.output_directory))
    else:
        run(arguments.output_directory)
