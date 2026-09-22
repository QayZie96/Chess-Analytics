-- Chess Analytics MVP: descriptive opening performance in the first 100,000 games.
-- Opening results are not causal evidence; ratings, colors, and player choices differ.

CREATE OR REPLACE TEMP VIEW source_games AS
SELECT * FROM read_parquet(['data/processed/mvp_500k_batches/games_000001.parquet', 'data/processed/mvp_500k_batches/games_000002.parquet', 'data/processed/mvp_500k_batches/games_000003.parquet', 'data/processed/mvp_500k_batches/games_000004.parquet', 'data/processed/mvp_500k_batches/games_000005.parquet']);

-- Keep valid records and label each player's own pre-game rating.
CREATE OR REPLACE TEMP VIEW valid_games AS
SELECT *,
  white_elo BETWEEN 100 AND 4000 AND black_elo BETWEEN 100 AND 4000 AS valid_ratings,
  result IN ('1-0', '0-1', '1/2-1/2') AS valid_result,
  opening IS NOT NULL AND opening NOT IN ('', '?') AS valid_opening,
  CASE WHEN white_elo NOT BETWEEN 100 AND 4000 THEN NULL
       WHEN white_elo < 800 THEN 'Below 800' WHEN white_elo < 1200 THEN '800-1199'
       WHEN white_elo < 1500 THEN '1200-1499' WHEN white_elo < 1800 THEN '1500-1799'
       WHEN white_elo < 2100 THEN '1800-2099' ELSE '2100+' END AS white_rating_band,
  CASE WHEN black_elo NOT BETWEEN 100 AND 4000 THEN NULL
       WHEN black_elo < 800 THEN 'Below 800' WHEN black_elo < 1200 THEN '800-1199'
       WHEN black_elo < 1500 THEN '1200-1499' WHEN black_elo < 1800 THEN '1500-1799'
       WHEN black_elo < 2100 THEN '1800-2099' ELSE '2100+' END AS black_rating_band
FROM source_games;

-- One game becomes two player-color perspectives; no player ID is selected.
CREATE OR REPLACE TEMP VIEW player_games AS
SELECT game_id, opening, eco, speed_category, white_rating_band AS rating_band,
       'White' AS player_color, ABS(white_elo-black_elo) AS rating_gap,
       CASE WHEN result='1-0' THEN 'win' WHEN result='0-1' THEN 'loss' ELSE 'draw' END AS outcome
FROM valid_games WHERE valid_ratings AND valid_result AND valid_opening
UNION ALL
SELECT game_id, opening, eco, speed_category, black_rating_band, 'Black', ABS(white_elo-black_elo),
       CASE WHEN result='0-1' THEN 'win' WHEN result='1-0' THEN 'loss' ELSE 'draw' END
FROM valid_games WHERE valid_ratings AND valid_result AND valid_opening;

-- A. Opening popularity using the same valid-opening, rating, and result rules.
SELECT opening, eco, COUNT(*) AS games,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS share_pct
FROM valid_games WHERE valid_opening AND valid_result AND valid_ratings
GROUP BY opening, eco ORDER BY games DESC, opening LIMIT 20;

-- B. Player-color opening performance by rating band (all opponent strengths).
SELECT opening, rating_band, player_color, COUNT(*) AS eligible_games,
       SUM(outcome='win')::BIGINT AS wins, SUM(outcome='draw')::BIGINT AS draws,
       SUM(outcome='loss')::BIGINT AS losses,
       ROUND(100.0*SUM(outcome='win')/COUNT(*),2) AS win_rate_pct,
       ROUND(100.0*SUM(outcome='draw')/COUNT(*),2) AS draw_rate_pct
FROM player_games GROUP BY opening, rating_band, player_color;

-- C. Main comparison: similar opponents and at least 100 games per opening/band/color.
WITH grouped AS (
  SELECT opening, rating_band, player_color, COUNT(*) AS eligible_games,
         SUM(outcome='win')::BIGINT AS wins, SUM(outcome='draw')::BIGINT AS draws,
         SUM(outcome='loss')::BIGINT AS losses
  FROM player_games WHERE rating_gap <= 100 GROUP BY opening, rating_band, player_color
)
SELECT *, ROUND(100.0*wins/eligible_games,2) AS win_rate_pct,
          ROUND(100.0*draws/eligible_games,2) AS draw_rate_pct
FROM grouped WHERE eligible_games >= 100
ORDER BY rating_band, player_color, eligible_games DESC, opening;

-- D. Opening performance by all recorded speed categories, including unknown/other.
SELECT opening, speed_category, COUNT(*) AS eligible_games,
       SUM(outcome='win')::BIGINT AS wins, SUM(outcome='draw')::BIGINT AS draws,
       SUM(outcome='loss')::BIGINT AS losses,
       ROUND(100.0*SUM(outcome='win')/COUNT(*),2) AS win_rate_pct,
       ROUND(100.0*SUM(outcome='draw')/COUNT(*),2) AS draw_rate_pct
FROM player_games GROUP BY opening, speed_category;

-- E. Data-quality exclusions, plus comparable-opponent and threshold coverage.
SELECT COUNT(*) AS total_games,
       SUM(NOT valid_opening)::BIGINT AS excluded_missing_opening,
       SUM(NOT valid_result)::BIGINT AS excluded_invalid_result,
       SUM(NOT valid_ratings)::BIGINT AS excluded_invalid_rating,
       SUM(valid_opening AND valid_result AND valid_ratings AND ABS(white_elo-black_elo)<=100)::BIGINT AS comparable_games
FROM valid_games;
