
# review_observation SSOT 設計書（確定版 rev1）

作成日: 2026-03-02
改訂: Cursor疑問点反映

---

# 0. 目的 / 方針

- SSOTは BigQuery。
- 履歴（全スナップショット）は BigQuery に保存。
- Sheetsは LATEST / ALERT のみ更新（全置換）。
- provider列でGoogle/Yahoo/Apple将来拡張。
- 冪等MERGEキーは snapshot_date + store_code + provider。
- 初期実装は Google（GBP）。

---

# 1. 認証（確定）

## 1.1 GBP OAuth

Secret Managerの実体はJSON1本：

{
  "client_id": "...",
  "client_secret": "...",
  "refresh_token": "..."
}

ENV:
- GBP_OAUTH_SECRET_NAME

---

# 2. テーブル設計（SSOT）

## 2.1 places_provider_map

- store_code
- provider
- provider_place_id（accounts/.../locations/...）
- is_active
- created_at
- updated_at

初期投入は手動INSERT（infraに手順記載）。

---

## 2.2 ratings_daily_snapshot

- snapshot_date（PARTITION）
- store_code
- provider
- provider_place_id
- rating_value
- review_count
- fetched_at
- ingest_run_id
- status
- error_code
- error_message

MERGEキー:
snapshot_date + store_code + provider

---

## 2.3 reviews

- store_code
- provider
- provider_review_id（PK）
- rating
- review_text
- review_created_at
- reviewer_display_name
- ingested_at

PARTITION BY DATE(ingested_at)
CLUSTER BY store_code, provider

---

## 2.4 raw_provider_payloads

- ingest_run_id
- snapshot_date
- store_code
- provider
- payload（JSON STRING）
- created_at

保存単位:
店舗 × provider × endpoint

---

# 3. GBP パフォーマンス指標

ユーザ数相当 = impressions
電話 = calls
ルート検索 = direction_requests
Webサイト = website_clicks

---

## 3.1 performance_daily_snapshot

- snapshot_date（PARTITION）
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

MERGEキー:
snapshot_date + store_code + provider

---

## 3.2 performance_monthly_snapshot

- snapshot_month（PARTITION）
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

MERGEキー:
snapshot_month + store_code + provider

月次は毎月1日 09:00 JST のSchedulerで実行。

---

# 4. VIEW設計

## 4.1 v_latest_with_delta_ratings
rating差分算出用。

## 4.2 v_latest_with_delta_performance
performance差分算出用。

Sheets生成時にJOINして出力。

## v_rating_alerts
閾値（SQL固定）:
- rating_value < 4.2
- delta_rating <= -0.2
- delta_review_count >= 10

---

# 5. Cloud Run フロー

1. ingest_run_id生成
2. GBP取得
3. ratings MERGE
4. reviews INSERT
5. performance_daily MERGE
6. 月初なら performance_monthly MERGE
7. Sheets LATEST更新（fetched_at含む）
8. Sheets ALERT更新
9. CSV出力
10. 200返却

---

# 6. Sheets LATEST 列（確定）

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
- fetched_at
- status

---

# 7. CSV出力

ENV追加:
- GCS_EXPORT_BUCKET

出力:
gs://<bucket>/exports/...

CSVは派生物。

---

# 8. SQL運用

010_merge_snapshot.sql は雛形。
実行は bq_writer.py が実施。

---

# 9. CI/CD

CI:
- ruff
- pytest

Deploy:
- Artifact Registry → Cloud Run
- WIF推奨
- /health 確認

---

設計状態: 確定（Cursor疑問点反映済）
