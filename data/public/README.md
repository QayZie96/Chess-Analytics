# Public dashboard aggregates

These files are proposed browser data for the Chess Analytics portfolio. They
contain aggregate counts only; they do not contain game identifiers, player
identifiers, usernames, private keys, raw PGN, or Parquet data.

They are generated deterministically from the reviewed Power BI aggregate CSV
exports by `tools/build_public_dashboard_data.py`.

## Files

- `rating-upsets.v1.json`: grain is speed category × rating-gap band ×
  lower-rated-player band. `eligible_games` is the denominator and
  `upset_games` is the lower-rated player winning. Draws remain in the
  denominator.
- `opening-performance.v1.json`: grain is opening name × ECO code × rating
  band × player color × speed category. Each comparable game contributes two
  player-side observations. `games = wins + draws + losses`.

The JSON uses a compact `row-array` format. Read the `columns` array first,
then map each row position to the matching column name.

## Dashboard rule

The opening 100-game rule is a dynamic display rule. Apply it after active
filters and grouping; do not remove sparse source rows from this dataset.

## Source and limitation

Source: Lichess Open Database, August 2026 rated standard-games archive. The
analysis uses the first 500,000 games encountered in that archive, so it is
not a random or representative sample of the month. Lichess states its open
database exports are CC0; retain a source link and this limitation wherever
these aggregates are used publicly.

Opening and ECO labels are copied from the archive headers. This project does
not independently document how those labels were originally produced.
