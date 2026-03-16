-- 既存行の store_name を places_provider_map.display_name で埋める（NULL/空の行のみ）
-- 適用: YOUR_DATASET を mart_gbp に置換してから、1 文ずつ BigQuery で実行

-- ratings_daily_snapshot
UPDATE `YOUR_DATASET.ratings_daily_snapshot` T
SET store_name = COALESCE(TRIM(P.display_name), '')
FROM `YOUR_DATASET.places_provider_map` P
WHERE T.store_code = P.store_code AND T.provider = P.provider
  AND (T.store_name IS NULL OR TRIM(COALESCE(T.store_name, '')) = '');

-- reviews
UPDATE `YOUR_DATASET.reviews` T
SET store_name = COALESCE(TRIM(P.display_name), '')
FROM `YOUR_DATASET.places_provider_map` P
WHERE T.store_code = P.store_code AND T.provider = P.provider
  AND (T.store_name IS NULL OR TRIM(COALESCE(T.store_name, '')) = '');
