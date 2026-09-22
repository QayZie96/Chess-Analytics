-- Chess Analytics MVP: rating upsets in the first completed 100,000-game batch.
-- An upset means the lower-rated player wins with a pre-game gap of at least 100 Elo.

CREATE OR REPLACE TEMP VIEW games AS
SELECT *
FROM read_parquet(['data/processed/mvp_500k_batches/games_000001.parquet', 'data/processed/mvp_500k_batches/games_000002.parquet', 'data/processed/mvp_500k_batches/games_000003.parquet', 'data/processed/mvp_500k_batches/games_000004.parquet', 'data/processed/mvp_500k_batches/games_000005.parquet']);

-- Keep valid outcome and rating rules in one reusable, readable view.
CREATE OR REPLACE TEMP VIEW classified_games AS
SELECT
    *,
    ABS(white_elo - black_elo) AS rating_gap,
    CASE
        WHEN white_elo IS NULL OR black_elo IS NULL
          OR white_elo < 100 OR white_elo > 4000
          OR black_elo < 100 OR black_elo > 4000 THEN FALSE
        ELSE TRUE
    END AS has_valid_ratings,
    result IN ('1-0', '0-1', '1/2-1/2') AS has_valid_result,
    CASE
        WHEN white_elo IS NULL OR black_elo IS NULL
          OR white_elo < 100 OR white_elo > 4000
          OR black_elo < 100 OR black_elo > 4000 THEN NULL
        WHEN ABS(white_elo - black_elo) < 50 THEN '0-49 Closely matched'
        WHEN ABS(white_elo - black_elo) < 100 THEN '50-99 Small difference'
        WHEN ABS(white_elo - black_elo) < 200 THEN '100-199 Moderate difference'
        WHEN ABS(white_elo - black_elo) < 400 THEN '200-399 Large difference'
        ELSE '400+ Very large difference'
    END AS rating_gap_category,
    CASE
        WHEN white_elo < black_elo AND result = '1-0' THEN TRUE
        WHEN black_elo < white_elo AND result = '0-1' THEN TRUE
        ELSE FALSE
    END AS lower_rated_player_won
FROM games;

-- A. Outcome reconciliation and exclusions.
SELECT COUNT(*) AS total_games,
       COUNT(*) FILTER (WHERE result = '1-0') AS white_wins,
       COUNT(*) FILTER (WHERE result = '0-1') AS black_wins,
       COUNT(*) FILTER (WHERE result = '1/2-1/2') AS draws,
       COUNT(*) FILTER (WHERE NOT has_valid_result) AS excluded_invalid_results
FROM classified_games;

-- C. Gap categories. Equal-rated games are retained but cannot be lower-rated wins.
SELECT rating_gap_category,
       COUNT(*) AS eligible_games,
       SUM(lower_rated_player_won)::BIGINT AS lower_rated_player_wins,
       ROUND(100.0 * SUM(lower_rated_player_won) / NULLIF(COUNT(*), 0), 2) AS lower_rated_win_rate_pct,
       SUM(result = '1/2-1/2')::BIGINT AS draws,
       ROUND(100.0 * SUM(result = '1/2-1/2') / NULLIF(COUNT(*), 0), 2) AS draw_rate_pct
FROM classified_games
WHERE has_valid_ratings AND has_valid_result
GROUP BY rating_gap_category
ORDER BY MIN(rating_gap);

-- D. Overall upset denominators: all valid-rating games vs only 100+-gap games.
SELECT COUNT(*) FILTER (WHERE has_valid_ratings AND has_valid_result) AS valid_rating_result_games,
       COUNT(*) FILTER (WHERE has_valid_ratings AND has_valid_result AND rating_gap >= 100) AS eligible_100_plus_games,
       SUM(has_valid_ratings AND has_valid_result AND rating_gap >= 100
           AND lower_rated_player_won)::BIGINT AS rating_upsets,
       ROUND(100.0 * SUM(has_valid_ratings AND has_valid_result AND rating_gap >= 100
                           AND lower_rated_player_won) /
             NULLIF(COUNT(*) FILTER (WHERE has_valid_ratings AND has_valid_result AND rating_gap >= 100), 0), 2) AS upset_rate_among_100_plus_pct,
       ROUND(100.0 * SUM(has_valid_ratings AND has_valid_result AND rating_gap >= 100
                           AND lower_rated_player_won) /
             NULLIF(COUNT(*) FILTER (WHERE has_valid_ratings AND has_valid_result), 0), 2) AS upset_proportion_all_eligible_pct,
       COUNT(*) FILTER (WHERE NOT has_valid_ratings) AS excluded_invalid_ratings,
       COUNT(*) FILTER (WHERE has_valid_ratings AND NOT has_valid_result) AS excluded_invalid_results
FROM classified_games;

-- E. Upsets by non-overlapping 100+ Elo gap category.
SELECT rating_gap_category,
       COUNT(*) AS eligible_games,
       SUM(lower_rated_player_won)::BIGINT AS upsets,
       ROUND(100.0 * SUM(lower_rated_player_won) / NULLIF(COUNT(*), 0), 2) AS upset_rate_pct
FROM classified_games
WHERE has_valid_ratings AND has_valid_result AND rating_gap >= 100
GROUP BY rating_gap_category
ORDER BY MIN(rating_gap);

-- F. Keep every speed category, including unknown, rather than silently dropping it.
SELECT speed_category,
       COUNT(*) AS eligible_100_plus_games,
       SUM(lower_rated_player_won)::BIGINT AS upsets,
       ROUND(100.0 * SUM(lower_rated_player_won) / NULLIF(COUNT(*), 0), 2) AS upset_rate_pct,
       SUM(result = '1/2-1/2')::BIGINT AS draws,
       ROUND(100.0 * SUM(result = '1/2-1/2') / NULLIF(COUNT(*), 0), 2) AS draw_rate_pct
FROM classified_games
WHERE has_valid_ratings AND has_valid_result AND rating_gap >= 100
GROUP BY speed_category
ORDER BY eligible_100_plus_games DESC;

-- G. Joint view: retain every speed label (including unknown) and show sample sizes.
SELECT rating_gap_category,
       speed_category,
       COUNT(*) AS eligible_100_plus_games,
       SUM(lower_rated_player_won)::BIGINT AS upsets,
       ROUND(100.0 * SUM(lower_rated_player_won) / NULLIF(COUNT(*), 0), 2) AS upset_rate_pct,
       SUM(result = '1/2-1/2')::BIGINT AS draws,
       ROUND(100.0 * SUM(result = '1/2-1/2') / NULLIF(COUNT(*), 0), 2) AS draw_rate_pct
FROM classified_games
WHERE has_valid_ratings AND has_valid_result AND rating_gap >= 100
GROUP BY rating_gap_category, speed_category
ORDER BY MIN(rating_gap), eligible_100_plus_games DESC;
