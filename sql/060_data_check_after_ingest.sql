-- 取込完了後のデータチェック用（review_observation POST / 実行後）
-- 実行: bq query --project_id=ikeuchi-ga4 --location=asia-northeast1 --use_legacy_sql=false "< 各クエリをコピーして実行"
-- データセットは mart_gbp。必要なら YOUR_DATASET を置換。

-- ========== 1. 今日の ratings_daily_snapshot 件数・status 内訳 ==========
-- 想定: processed 数（例: 31）と一致。status='ok' が対象店舗数と一致すること。
SELECT
  snapshot_date,
  status,
  COUNT(*) AS cnt
FROM `ikeuchi-ga4.mart_gbp.ratings_daily_snapshot`
WHERE snapshot_date = CURRENT_DATE('Asia/Tokyo')
GROUP BY 1, 2
ORDER BY 1, 2;

-- ========== 2. 直近の取込 run 情報（ingest_run_id / snapshot_date） ==========
SELECT
  snapshot_date,
  ingest_run_id,
  COUNT(*) AS store_count,
  SUM(review_count) AS total_review_count
FROM `ikeuchi-ga4.mart_gbp.ratings_daily_snapshot`
WHERE snapshot_date = CURRENT_DATE('Asia/Tokyo')
GROUP BY snapshot_date, ingest_run_id
ORDER BY snapshot_date DESC, store_count DESC
LIMIT 5;

-- ========== 3. 店舗別レビュー件数（reviews テーブル・今回の取込） ==========
-- 直近の ingest_run_id で投入されたレビュー数を店舗別に集計。
WITH latest_run AS (
  SELECT ingest_run_id
  FROM (
    SELECT ingest_run_id
    FROM `ikeuchi-ga4.mart_gbp.ratings_daily_snapshot`
    WHERE snapshot_date = CURRENT_DATE('Asia/Tokyo')
    ORDER BY fetched_at DESC
    LIMIT 1
  )
)
SELECT
  r.store_code,
  COUNT(*) AS review_rows
FROM `ikeuchi-ga4.mart_gbp.reviews` r
CROSS JOIN latest_run l
WHERE r.ingest_run_id = l.ingest_run_id
GROUP BY r.store_code
ORDER BY r.store_code;

-- ========== 4. 整合性チェック（snapshot の review_count と reviews 件数の比較） ==========
-- 同一 ingest_run で、店舗ごとの ratings_daily_snapshot.review_count と reviews の件数が一致するか。
WITH latest_run AS (
  SELECT ingest_run_id
  FROM (
    SELECT ingest_run_id
    FROM `ikeuchi-ga4.mart_gbp.ratings_daily_snapshot`
    WHERE snapshot_date = CURRENT_DATE('Asia/Tokyo')
    ORDER BY fetched_at DESC
    LIMIT 1
  )
),
snapshot_counts AS (
  SELECT store_code, review_count AS snapshot_review_count
  FROM `ikeuchi-ga4.mart_gbp.ratings_daily_snapshot`
  WHERE snapshot_date = CURRENT_DATE('Asia/Tokyo')
),
review_counts AS (
  SELECT r.store_code, COUNT(*) AS actual_review_count
  FROM `ikeuchi-ga4.mart_gbp.reviews` r
  CROSS JOIN latest_run l
  WHERE r.ingest_run_id = l.ingest_run_id
  GROUP BY r.store_code
)
SELECT
  COALESCE(s.store_code, c.store_code) AS store_code,
  s.snapshot_review_count,
  c.actual_review_count,
  (s.snapshot_review_count - c.actual_review_count) AS diff
FROM snapshot_counts s
FULL OUTER JOIN review_counts c ON s.store_code = c.store_code
WHERE COALESCE(s.snapshot_review_count, 0) != COALESCE(c.actual_review_count, 0)
ORDER BY store_code;
