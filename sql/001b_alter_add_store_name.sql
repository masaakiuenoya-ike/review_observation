-- 既存テーブルに store_name 列を追加する（初回のみ。既に列がある場合は「Already exists」でエラーになるのでスキップ）
-- 適用: YOUR_DATASET を mart_gbp に置換してから、1 文ずつ BigQuery で実行

ALTER TABLE `YOUR_DATASET.ratings_daily_snapshot` ADD COLUMN store_name STRING;
ALTER TABLE `YOUR_DATASET.reviews` ADD COLUMN store_name STRING;
