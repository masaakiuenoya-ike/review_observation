
# review_observation SSOT 設計書（確定版）

作成日: 2026-03-02  
プロジェクト: review_observation

---

# 0. 目的 / 方針

- SSOTは **BigQuery**。
- 履歴（全スナップショット）は BigQuery に保存する。
- スプレッドシートは閲覧UI用途。更新は **LATEST / ALERT のみ（全置換）**。
- 将来 Yahoo / Apple を追加できるように、データモデルは `provider` 列で1本化。
- `store_code` は既存 BigQuery 店舗マスタを参照。
- 冪等性：`snapshot_date + store_code + provider` で MERGE。
- 初期実装は Google（GBP）のみ。

デプロイ:
- Cloud Run
- Cloud Scheduler（09:00 JST）

---

# 1. リポジトリ前提

対象リポジトリ:
https://github.com/masaakiuenoya-ike/review_observation

- main への push で CI 実行
- Artifact Registry 経由で Cloud Run へ deploy
- 機密情報は Secret Manager / GitHub Secrets で管理

---

# 2. データモデル（SSOT）

## 2.1 places_provider_map

- store_code
- provider
- provider_place_id（GBP: accounts/.../locations/...）
- is_active
- created_at
- updated_at

小規模マスタのためパーティションなし。

---

## 2.2 ratings_daily_snapshot

- snapshot_date（DATE）※PARTITION
- store_code
- provider
- provider_place_id
- rating_value（averageRating）
- review_count（totalReviewCount）
- fetched_at
- ingest_run_id
- status
- error_code
- error_message

CLUSTER BY store_code, provider

MERGEキー:
snapshot_date + store_code + provider

---

## 2.3 reviews

- store_code
- provider
- provider_review_id（PK）
- rating（starRating）
- review_text（comment）
- review_created_at（createTime）
- reviewer_display_name
- ingested_at

PARTITION BY DATE(ingested_at)  
CLUSTER BY store_code, provider

重複排除: provider_review_id

---

## 2.4 raw_provider_payloads

- ingest_run_id
- snapshot_date
- store_code
- provider
- payload（JSON STRING）
- created_at

PARTITION BY snapshot_date  
CLUSTER BY store_code, provider

保存単位:
店舗 × provider × endpoint ごとに1行

---

# 3. GBP パフォーマンス指標（追加）

## 3.1 方針

- ユーザ数 = impressions（表示回数）
- 電話 = calls
- ルート検索 = direction_requests
- Webサイト = website_clicks

日次・月次で取得し履歴保存する。

---

## 3.2 performance_daily_snapshot

- snapshot_date（DATE）※PARTITION
- store_code
- provider
- provider_place_id
- impressions
- calls
- direction_requests
- website_clicks
- fetched_at
- ingest_run_id
- status
- error_code
- error_message

CLUSTER BY store_code, provider

MERGEキー:
snapshot_date + store_code + provider

---

## 3.3 performance_monthly_snapshot

- snapshot_month（DATE 月初日）※PARTITION
- store_code
- provider
- provider_place_id
- impressions
- calls
- direction_requests
- website_clicks
- fetched_at
- ingest_run_id
- status
- error_code
- error_message

CLUSTER BY store_code, provider

MERGEキー:
snapshot_month + store_code + provider

---

# 4. VIEW

## v_latest_with_delta
当日と前日をJOINし差分算出。

## v_rating_alerts
alert_type:
- low_rating
- rating_drop
- review_surge

閾値（SQL固定）:
- rating_value < 4.2
- delta_rating <= -0.2
- delta_review_count >= 10

---

# 5. Cloud Run 処理フロー

POST /

1. ingest_run_id = UUID
2. snapshot_date = Asia/Tokyo
3. places_provider_map 読込
4. GBP API 呼出
5. raw_provider_payloads 保存
6. ratings_daily_snapshot MERGE
7. reviews INSERT/MERGE
8. performance_daily_snapshot MERGE
9. 必要に応じ performance_monthly_snapshot MERGE
10. Sheets LATEST 更新
11. Sheets ALERT 更新
12. CSV 出力
13. summary JSON 返却

エラー:
店舗単位で error 記録。全体は200返却。

---

# 6. Sheets 出力

LATEST:
- snapshot_date
- store_code
- provider
- rating_value
- review_count
- impressions
- calls
- direction_requests
- website_clicks
- delta_rating
- delta_review_count
- status

ALERT:
- snapshot_date
- store_code
- provider
- alert_type
- rating_value
- delta_rating
- delta_review_count

---

# 7. CSV 出力

出力先（GCS）:

gs://<bucket>/exports/ratings/provider=google/snapshot_date=YYYY-MM-DD/ratings.csv  
gs://<bucket>/exports/reviews/provider=google/snapshot_date=YYYY-MM-DD/reviews.csv  
gs://<bucket>/exports/performance/provider=google/snapshot_date=YYYY-MM-DD/performance_daily.csv  

CSVは派生物。正はBigQuery。

---

# 8. CI/CD

CI:
- Python 3.11
- ruff
- pytest（tests/）

Deploy:
- Artifact Registry → Cloud Run
- WIF 推奨
- GET /health で確認

---

# 9. 実装順

Phase1:
- SQL適用
- ダミーMERGE確認
- Sheets疎通

Phase2:
- GBP OAuth接続
- ratings / reviews 実装

Phase2.5:
- performance_daily / monthly 実装

Phase3:
- 並列化
- リトライ
- 構造化ログ

Phase4:
- CSV出力

Phase5:
- CI/CD整備
- Scheduler設定

---

# 10. 認証

- GBP: OAuth2（Secret Manager管理）
- Cloud Run: 認証必須
- Scheduler: OIDC 呼び出し

---

設計状態: 完全確定版
