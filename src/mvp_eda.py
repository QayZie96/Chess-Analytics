"""Stage 1 privacy-safe EDA summaries for the five completed MVP batches."""
from pathlib import Path
import duckdb
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "mvp_500k_batches"

def open_analysis_connection():
    """Open DuckDB with the privacy-safe views shared by the EDA steps."""
    files = sorted(DATA.glob("games_*.parquet"))
    assert len(files) == 5, f"expected 5 batches, found {len(files)}"
    con = duckdb.connect()
    path = str(DATA / "games_*.parquet").replace("'", "''")
    con.execute(f"""CREATE VIEW games AS SELECT game_id,utc_timestamp,white_elo,black_elo,
    white_rating_diff,black_rating_diff,result,eco,opening,time_control,speed_category,termination,event
    FROM read_parquet('{path}')""")
    con.execute("""CREATE VIEW featured AS SELECT *,
    white_elo BETWEEN 100 AND 4000 AND black_elo BETWEEN 100 AND 4000 valid_ratings,
    result IN ('1-0','0-1','1/2-1/2') valid_result, ABS(white_elo-black_elo) gap,
    CASE WHEN white_elo<black_elo AND result='1-0' OR black_elo<white_elo AND result='0-1' THEN TRUE ELSE FALSE END lower_win
    FROM games""")
    return con


def rating_distribution_chart(bin_width=100):
    """Plot valid White/Black rating appearances from DuckDB bin aggregates."""
    query = f"""WITH sides AS (
      SELECT white_elo AS rating, 'White' AS color FROM featured WHERE valid_ratings
      UNION ALL SELECT black_elo, 'Black' FROM featured WHERE valid_ratings
    ), binned AS (
      SELECT color, FLOOR(rating / {bin_width}) * {bin_width} AS bin_start, COUNT(*) AS appearances
      FROM sides WHERE rating BETWEEN 100 AND 4000 GROUP BY 1, 2
    ) SELECT color, bin_start, appearances FROM binned ORDER BY bin_start, color"""
    con = open_analysis_connection()
    data = con.execute(query).df()
    pivot = data.pivot(index="bin_start", columns="color", values="appearances").fillna(0)
    ax = pivot.plot(kind="bar", figsize=(11, 5), width=0.85, color=["#f4f4f4", "#333333"])
    ax.set(title="Player rating appearances by game color (early-August sample)", xlabel="Rating bin", ylabel="Game-side appearances")
    ax.legend(title="Piece color")
    ax.text(0.01, -0.34, "Ratings are game-side appearances, not unique players. This is not the full August archive.", transform=ax.transAxes, fontsize=9)
    plt.subplots_adjust(bottom=0.27, left=0.09, right=0.98, top=0.90)
    return ax.figure, data


def upset_rate_by_gap_chart():
    """Plot SQL-aligned upset rates for the three eligible rating-gap bands."""
    con = open_analysis_connection()
    data = con.execute("""WITH eligible AS (
      SELECT CASE
        WHEN gap BETWEEN 100 AND 199 THEN '100-199'
        WHEN gap BETWEEN 200 AND 399 THEN '200-399'
        WHEN gap >= 400 THEN '400+'
      END AS rating_gap_band,
      lower_win
      FROM featured
      WHERE valid_ratings AND valid_result AND gap >= 100
    )
    SELECT rating_gap_band,
      COUNT(*) AS eligible_games,
      SUM(lower_win) AS upsets,
      100.0 * SUM(lower_win) / COUNT(*) AS upset_rate_pct
    FROM eligible
    GROUP BY 1
    ORDER BY CASE rating_gap_band
      WHEN '100-199' THEN 1 WHEN '200-399' THEN 2 WHEN '400+' THEN 3 END""").df()

    assert data['eligible_games'].sum() == 118787
    assert data['upsets'].sum() == 30779
    assert len(data) == 3

    figure, axis = plt.subplots(figsize=(8, 5))
    bars = axis.bar(data['rating_gap_band'], data['upset_rate_pct'], color='#4c78a8')
    axis.set(
        title='Observed upset rate by rating-gap band (early-August sample)',
        xlabel='Rating-gap band (Elo)',
        ylabel='Observed upset rate (%)',
    )
    axis.set_ylim(0, max(data['upset_rate_pct']) * 1.2)
    for bar, eligible_games in zip(bars, data['eligible_games']):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f'n={eligible_games:,}',
            ha='center', va='bottom', fontsize=9,
        )
    axis.text(
        0.01, -0.22,
        'Eligible games have valid ratings and results; draws remain in the denominator.',
        transform=axis.transAxes, fontsize=9,
    )
    plt.subplots_adjust(bottom=0.24, left=0.11, right=0.98, top=0.90)
    return figure, data


def result_distribution_by_speed_chart():
    """Plot valid-result White wins, Black wins, and draws for every speed category."""
    con = open_analysis_connection()
    data = con.execute("""SELECT
      COALESCE(speed_category, 'Unknown') AS speed_category,
      COUNT(*) AS valid_games,
      SUM(result = '1-0') AS white_wins,
      SUM(result = '0-1') AS black_wins,
      SUM(result = '1/2-1/2') AS draws
    FROM featured
    WHERE valid_result
    GROUP BY 1
    ORDER BY valid_games DESC, speed_category""").df()

    outcome_columns = ['white_wins', 'black_wins', 'draws']
    assert data['valid_games'].sum() == 499981
    assert (data[outcome_columns].sum(axis=1) == data['valid_games']).all()

    percentage_columns = ['white_win_pct', 'black_win_pct', 'draw_pct']
    data[percentage_columns] = data[outcome_columns].div(data['valid_games'], axis=0) * 100
    assert ((data[percentage_columns].sum(axis=1) - 100).abs() < 0.000001).all()

    figure, axis = plt.subplots(figsize=(10, 5.5))
    bottom = [0.0] * len(data)
    colors = ['#f4f4f4', '#333333', '#4c78a8']
    labels = ['White wins', 'Black wins', 'Draws']
    for column, color, label in zip(percentage_columns, colors, labels):
        axis.bar(data['speed_category'], data[column], bottom=bottom, color=color, label=label)
        bottom = [current + value for current, value in zip(bottom, data[column])]

    for index, valid_games in enumerate(data['valid_games']):
        axis.text(index, 102, f'n={valid_games:,}', ha='center', va='bottom', fontsize=9)
    axis.set(
        title='Game results by speed category (early-August sample)',
        xlabel='Speed category',
        ylabel='Share of valid-result games (%)',
        ylim=(0, 112),
    )
    axis.legend(title='Result', loc='center left', bbox_to_anchor=(1.01, 0.5))
    axis.text(
        0.01, -0.22,
        'All speed categories are retained. Percentages exclude 19 invalid-result records.',
        transform=axis.transAxes, fontsize=9,
    )
    plt.subplots_adjust(bottom=0.24, left=0.10, right=0.80, top=0.90)
    return figure, data


def run():
    con = open_analysis_connection()
    row = con.execute("""SELECT COUNT(*),COUNT(*)-COUNT(DISTINCT game_id),
    SUM(NOT valid_ratings),SUM(NOT valid_result),SUM(opening IS NULL OR opening IN ('','?')),
    SUM(white_rating_diff IS NOT NULL AND black_rating_diff IS NOT NULL),
    SUM(valid_ratings AND valid_result AND gap>=100),SUM(valid_ratings AND valid_result AND gap>=100 AND lower_win),
    SUM(valid_ratings AND valid_result AND gap<=100) FROM featured""").fetchone()
    assert row[0] == 500000 and row[7] <= row[6]
    assert con.execute("SELECT COUNT(*) FROM featured WHERE valid_ratings AND gap IS NULL").fetchone()[0] == 0
    print(dict(zip(('games','duplicate_ids','invalid_ratings','invalid_results','missing_openings','rating_change_pairs','upset_eligible','upsets','comparable'),row)))
    return row

if __name__ == '__main__': run()
