# review_observation SSOT 設計書（確定版 rev2）

作成日: 2026-03-02（JST）  
改訂: rev1の欠落項目（テスト配置 / raw保存単位 / alert_type / Cloud Run認証 等）を復元・統合

---

## 0. 目的 / 方針

- SSOTは **BigQuery**。
- 履歴（全スナップショット）は BigQuery に保存する。
- スプレッドシートは閲覧UI用途。更新は **LATEST / ALERT のみ（全置換）**。
- 将来 Yahoo / Apple を追加できるように、データモデルは `provider` 列で1本化。
- `store_code` は既存 BigQuery 店舗マスタを参照（店舗名等はJOINで取得）。
- 冪等性（上書きMERGE）  
  - 日次: `snapshot_date + store_code + provider`  
  - 月次: `snapshot_month + store_code + provider`
- 初期実装は Google（GBP）のみ（Yahoo/Appleはスキーマ対応のみ先行）。

デプロイ:
- Cloud Run
- Cloud Scheduler（09:00 JST）

---

## 1. リポジトリ / 運用前提

対象リポジトリ:  
https://github.com/masaakiuenoya-ike/review_observation

- main への push で CI 実行
- Artifact Registry 経由で Cloud Run へ deploy
- 機密情報は Secret Manager / GitHub Secrets で管理（リポジトリに平文禁止）

---

## 2. 認証（確定）

### 2.1 GBP（Google Business Profile）
- 認証方式: OAuth 2.0（Refresh Token）
- Secret Manager の実体は **JSON 1本**（3要素を同居）

```json
{
  "client_id": "...",
  "client_secret": "...",
  "refresh_token": "..."
}
```

ENV:
- `GBP_OAUTH_SECRET_NAME`（Secret名）

### 2.2 Cloud Run（公開範囲）
- **未認証アクセス禁止（認証必須）**
- Cloud Scheduler から **OIDC** で呼び出す
- `run.invoker` は Scheduler 用サービスアカウントのみに付与

---

## 3. BigQuery テーブル（SSOT）

### 3.1 places_provider_map
目的: `store_code` とプロバイダ側の店舗識別子の対応表（運用で差し替え可能なSSOT）

- store_code（STRING, PK相当）
- provider（STRING: 'google'|'yahoo'|'apple'）
- provider_place_id（STRING）  
  - Googleは **GBP location resource name** を格納（例: `accounts/{accountId}/locations/{locationId}`）
- provider_account_id（STRING, 任意）
- display_name（STRING, 任意）
- is_active（BOOL）
- created_at / updated_at

運用:
- 初期投入・店舗追加は **手動INSERT**（README/infraに手順を記載）

### 3.2 ratings_daily_snapshot（レビュー評価のスナップショット）
- snapshot_date（DATE, PARTITION）
- store_code
- provider
- provider_place_id
- rating_value（FLOAT64）
- review_count（INT64）
- fetched_at（TIMESTAMP）
- ingest_run_id（STRING）
- status（STRING: ok/error）
- error_code / error_message

CLUSTER:
- store_code, provider

MERGEキー:
- snapshot_date + store_code + provider

### 3.3 reviews（レビュー明細）
- store_code
- provider
- provider_place_id
- provider_review_id（STRING, PK相当）
- rating（FLOAT64）
- review_text（STRING）
- review_created_at（TIMESTAMP）
- review_updated_at（TIMESTAMP, 任意）
- reviewer_display_name（STRING, 任意）
- ingested_at（TIMESTAMP）
- ingest_run_id（STRING）

PARTITION:
- DATE(ingested_at)

CLUSTER:
- store_code, provider

重複排除:
- provider_review_id

### 3.4 raw_provider_payloads（生レスポンス保管：保険）
- ingest_run_id
- snapshot_date（PARTITION）
- store_code
- provider
- endpoint（STRING）
- payload（JSON STRING もしくは JSON型）
- created_at
- status（ok/error）
- error_code / error_message

CLUSTER:
- store_code, provider, endpoint

保存単位（確定）:
- **店舗（store_code）× provider × endpoint ごとに 1 行**

---

## 4. GBP パフォーマンス指標（追加）

「ユーザ数」は厳密なユニークユーザーではなく、GBPが提供する表示回数（impressions/views）を“ユーザ数相当”として扱う。

- impressions（ユーザ数相当）
- calls（電話）
- direction_requests（ルート検索/経路）
- website_clicks（Webサイト）

### 4.1 performance_daily_snapshot
- snapshot_date（DATE, PARTITION）
- store_code
- provider
- provider_place_id
- impressions / calls / direction_requests / website_clicks（INT64）
- fetched_at
- ingest_run_id
- status（ok/error）
- error_code / error_message

MERGEキー:
- snapshot_date + store_code + provider

### 4.2 performance_monthly_snapshot
- snapshot_month（DATE: 月初日, PARTITION）
- store_code
- provider
- provider_place_id
- impressions / calls / direction_requests / website_clicks（INT64）
- fetched_at
- ingest_run_id
- status（ok/error）
- error_code / error_message

MERGEキー:
- snapshot_month + store_code + provider

取得頻度（確定）:
- 日次: 毎日 09:00 JST（既存日次ジョブ）
- 月次: **毎月1日 09:00 JST のScheduler**（別ジョブ推奨）

---

## 5. VIEW

### 5.1 v_latest_with_delta_ratings
- 当日と前日をJOINし、rating系の差分（delta_rating, delta_review_count）を算出

### 5.2 v_latest_with_delta_performance
- 当日と前日をJOINし、performance系の差分（delta_impressions 等）を算出（必要な項目のみ）

### 5.3 v_rating_alerts
alert_type（固定値・確定）:
- `low_rating`
- `rating_drop`
- `review_surge`

閾値（SQL固定）:
- rating_value < 4.2
- delta_rating <= -0.2
- delta_review_count >= 10

---

## 6. Cloud Run 処理フロー（概要）

HTTP:
- `GET /health`（200）
- `POST /`（定点観測実行）

POST /:
1. ingest_run_id = UUID
2. snapshot_date = Asia/Tokyo
3. places_provider_map 読込（provider='google' AND is_active=true）
4. GBP API 呼出（評価・レビュー・performance）
5. raw_provider_payloads 保存（店舗×provider×endpoint）
6. ratings_daily_snapshot MERGE
7. reviews INSERT/MERGE（provider_review_idで重複排除）
8. performance_daily_snapshot MERGE
9. 月初ジョブで performance_monthly_snapshot MERGE
10. VIEW参照 → Sheets LATEST/ALERT を全置換
11. CSV出力（GCS）
12. summary JSON返却（失敗店舗数を含める）

エラー方針:
- 店舗単位で status='error' を記録し、全体は200を返す（Scheduler運用を止めない）

---

## 7. Sheets 出力（確定）

### 7.1 LATEST（全置換）
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
- fetched_at（確定：含める）
- status

### 7.2 ALERT（全置換）
- snapshot_date
- store_code
- provider
- alert_type
- rating_value
- delta_rating
- delta_review_count

---

## 8. CSV 出力（GCS）

ENV（確定）:
- `GCS_EXPORT_BUCKET`（必須）

出力先例:
- gs://<bucket>/exports/ratings/provider=google/snapshot_date=YYYY-MM-DD/ratings.csv
- gs://<bucket>/exports/reviews/provider=google/snapshot_date=YYYY-MM-DD/reviews.csv
- gs://<bucket>/exports/performance/provider=google/snapshot_date=YYYY-MM-DD/performance_daily.csv
- （月次）gs://<bucket>/exports/performance/provider=google/snapshot_month=YYYY-MM-01/performance_monthly.csv

位置づけ:
- CSVは派生物。正はBigQuery。

---

## 9. SQL運用

- `sql/001_create_tables.sql` / `sql/002_create_views.sql` を手動適用（初回）
- `sql/010_merge_snapshot.sql` は **雛形（ドキュメント）**。本番実行は `src/bq_writer.py` が実施。

---

## 10. テスト配置（確定）

- テストは `tests/` 配下に配置
- CIでは `pytest tests` を実行

---

## 11. CI/CD（要点）

CI:
- Python 3.11
- ruff
- pytest（tests/）

Deploy:
- Artifact Registry → Cloud Run
- WIF推奨
- デプロイ後 `GET /health` で確認

---

## 12. 実装順（確定）

Phase 1（基盤）:
1. SQL適用（テーブル/VIEW）
2. places_provider_map 手動INSERT（1店舗）
3. Cloud Run最小実装（ダミーMERGE → Sheets更新）
4. GET /health

Phase 2（GBP連携）:
5. Secret Manager（OAuth JSON）
6. GBPレビュー取得（ratings/reviews）

Phase 2.5（performance追加）:
7. performance_daily / monthly 取得＋MERGE
8. 月次Scheduler（毎月1日09:00 JST）

Phase 3（安定化）:
9. 並列化 / リトライ / 構造化ログ

Phase 4（CSV）:
10. BQ Extract → GCS

Phase 5（CI/CD）:
11. ci.yml / deploy.yml
12. Scheduler（OIDC）

---

設計状態: **完全確定（欠落項目復元済み）**
