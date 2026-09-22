# Chess Analytics

An end-to-end analytics portfolio project that examines rating upsets and
opening performance in a 500,000-game early-August 2026 Lichess sample. The
project demonstrates a privacy-aware workflow with Python, DuckDB SQL, Python
EDA, and Power BI.

> **Sample limitation:** the data is the first 500,000 games encountered in
> the August archive. It is not a random or representative sample of the full
> month, all Lichess players, or chess generally.

## Project questions

- How often does a lower-rated player win when the rating gap is at least 100 Elo?
- How do observed opening outcomes vary by player rating, color, and speed when opponents are similarly rated?

The results are descriptive. They do not establish that an opening or time control causes a result.

## Validated highlights

| Measure | Result |
| --- | ---: |
| Sampled games | 500,000 |
| Upset-eligible games | 118,787 |
| Observed upsets | 30,779 |
| Observed upset rate | 25.91% |
| 100–199 Elo gap upset rate | 35.41% |
| 200–399 Elo gap upset rate | 23.43% |
| 400+ Elo gap upset rate | 11.06% |
| Comparable-opponent games for opening analysis | 382,097 |
| Opening player-side observations | 764,194 |
| Opening wins / draws / losses | 367,980 / 28,234 / 367,980 |
| Unfiltered opening win rate | 48.15% |

An opening comparison represents each eligible game twice: once from White's perspective and once from Black's. Therefore, 764,194 player-side observations are **not** 764,194 unique games.

## Data source and privacy

The source is the [Lichess Open Database](https://database.lichess.org/): the August 2026 rated standard-games archive. Lichess states that its database exports are released under CC0, allowing use, modification, and redistribution. This repository retains source context and the sample limitation even though CC0 does not require attribution.

The extraction pipeline reads PGN headers only and uses an ignored HMAC key to pseudonymize player names before writing local Parquet. Raw PGN, Parquet, player identifiers, keys, credentials, and machine-local exports are excluded from Git. Public dashboard assets contain aggregate counts only.

`Opening` and `ECO` are copied from the corresponding source PGN headers. This repository does not independently document how Lichess produced those header annotations; this is a provenance limitation to retain in any public write-up.

## Workflow

1. `src/extract_games.py` streams the compressed archive and writes bounded, resumable Parquet batches.
2. `sql/01_rating_upsets.sql` calculates upset populations and weighted rates.
3. `sql/02_opening_performance.sql` creates White/Black opening perspectives and comparable-opponent analysis.
4. `src/mvp_eda.py` and `notebooks/01_mvp_eda.ipynb` validate the dataset and render three exploratory charts.
5. `src/export_powerbi_data.py` produces privacy-safe aggregate CSVs for the Power BI model.
6. `tools/build_public_dashboard_data.py` creates validated browser JSON from those aggregate CSVs only.

## Analytical definitions

### Rating upsets

Both pre-game ratings must be 100–4000, the result must be `1-0`, `0-1`, or `1/2-1/2`, and the absolute rating gap must be at least 100 Elo. An upset is a win by the lower-rated player. Draws stay in the eligible-game denominator.

The public upset dataset is grouped by speed category, rating-gap band, and lower-rated-player band. Rates must always be calculated as summed upsets / summed eligible games, never by averaging row rates.

### Opening performance

The opening analysis requires valid ratings/results, a recorded opening, and an opponent gap of no more than 100 Elo. Each game contributes one White and one Black player-side observation. Ratings use these non-overlapping bands: below 800, 800–1199, 1200–1499, 1500–1799, 1800–2099, and 2100+.

The 100-game minimum is a **dynamic display rule**. It is applied after the active opening, rating-band, player-color, and speed filters and grouping; it does not delete sparse groups from the public source data.

## Python EDA

Stage 1 validates schemas, missing values, ratings, results, openings, rating changes, comparable-opponent eligibility, and SQL-aligned upset totals. Stage 2 adds three matplotlib visualizations:

- White/Black game-side rating appearances;
- observed upset rate by 100–199, 200–399, and 400+ Elo bands;
- White wins, Black wins, and draws by speed category.

Run the script with the existing environment:

```powershell
.\.venv\Scripts\python.exe src\mvp_eda.py
```

The notebook uses the same validated implementation. Configure project-local Jupyter runtime directories if your user-profile Jupyter paths are not writable.

## Power BI report

`powerbi/Chess Analytics.pbip` contains two interactive pages:

1. **Rating Upsets** — KPI cards; speed, gap-band, and lower-rated-band slicers; weighted upset-rate charts; methodology note.
2. **Opening Performance Explorer** — opening, rating-band, player-color, and speed slicers; outcome chart; KPI cards; dynamically thresholded comparison table.

The two fact tables have no relationship. Power BI measures calculate weighted rates from summed counts. The report expects two local aggregate CSVs, which are intentionally ignored. To reproduce it without raw data, obtain the reviewed aggregate release assets, place CSV copies in your local data folder, then update the two Power Query `File.Contents` source paths in Power BI Desktop before refreshing. Do not commit local source paths or Power BI cache directories.

<!-- Screenshot placeholder: Rating Upsets dashboard -->
<!-- Screenshot placeholder: Opening Performance Explorer dashboard -->

## Public browser data

`data/public/` contains compact, versioned row-array JSON for a future static Astro dashboard. See [data/public/README.md](data/public/README.md) for schema and use rules. These assets are generated from reviewed aggregates, not from the raw archive or Parquet files:

```powershell
.\.venv\Scripts\python.exe tools\build_public_dashboard_data.py
.\.venv\Scripts\python.exe tools\build_public_dashboard_data.py --validate-existing
```

The JSON is intended for a separate portfolio implementation, not as a claim that the dashboard is already live.

<!-- Live dashboard placeholder: /projects/chess-analytics/rating-upsets/ -->
<!-- Live dashboard placeholder: /projects/chess-analytics/opening-performance/ -->
<!-- GitHub repository placeholder -->

## Repository structure

```text
src/         Extraction, validation, EDA, and Power BI aggregate-export scripts
sql/         DuckDB analyses
notebooks/   Executed Python EDA notebook and preserved original backup
powerbi/     Enhanced PBIR report and TMDL semantic model definitions
tools/       Reproducible report and public-data builders
data/public/ Versioned aggregate browser data only
```

## Reproduction requirements

Use Python 3.14 with the existing virtual environment and these packages:

```text
duckdb 1.5.5
zstandard 0.25.0
pandas 3.0.6
matplotlib 3.11.2
ipykernel 7.3.0
nbconvert 7.17.1
```

Full extraction additionally requires the official archive and a local, ignored 32-byte HMAC key. It is not required for inspecting the public aggregate dashboard data.

## Publication checklist

Before pushing this repository or deploying a dashboard:

- confirm the PBIP opens and refreshes after setting local CSV paths;
- review Git history as well as the working tree for private material;
- retain the Lichess source link, CC0 context, sample limitation, and opening/ECO provenance limitation;
- verify that only aggregate public data is staged;
- add final dashboard screenshots and live portfolio links.
