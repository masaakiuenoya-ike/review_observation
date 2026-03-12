# Sheets 連携（ダッシュボード用）

review_observation の `POST /` 実行後、BigQuery の VIEW を参照して **Google スプレッドシートの LATEST / ALERT タブを全置換**します。スプレッドシートをダッシュボードとして閲覧・共有するための手順です。

---

## 1. 前提

- BigQuery に **v_latest_with_delta_ratings** と **v_rating_alerts** の VIEW が作成済みであること（`sql/002_create_views.sql` を `mart_gbp` で適用）。
- Cloud Run の実行サービスアカウント（`sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com`）で Sheets API にアクセスするため、**スプレッドシートをこの SA に共有**する必要があります。

---

## 2. スプレッドシートの準備

1. 新規または既存の Google スプレッドシートを開く。
2. **LATEST** と **ALERT** という名前のシート（タブ）を用意する。  
   - 既存タブ名を変えたい場合は、環境変数 `SHEET_TAB_LATEST` / `SHEET_TAB_ALERT` で指定可能（デフォルトは `LATEST` / `ALERT`）。
3. 中身は空でよい。アプリが **全置換** するため、既存の内容は上書きされます。

---

## 3. 実行 SA への共有

1. スプレッドシート右上の **「共有」** をクリック。
2. **ユーザーやグループを追加** に次を入力:
   ```
   sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com
   ```
3. 権限を **編集者** にし、**送信** する。

詳細は [infra/gcloud_commands.md §11](../infra/gcloud_commands.md) を参照。

---

## 4. 環境変数

| 変数 | 説明 | 必須 |
|------|------|------|
| **SHEET_ID** | スプレッドシート ID（URL の `https://docs.google.com/spreadsheets/d/<ここ>/edit` の「ここ」） | Sheets 更新を行う場合必須 |
| SHEET_TAB_LATEST | LATEST 用のタブ名 | 任意（既定: LATEST） |
| SHEET_TAB_ALERT | ALERT 用のタブ名 | 任意（既定: ALERT） |

- **SHEET_ID** が空または未設定のときは、Sheets 更新はスキップされ、取込処理のみ実行されます。
- ローカル実行時は `export SHEET_ID=...` で設定。Cloud Run では deploy.yml が `secrets.SHEET_ID` を注入します。

---

## 5. 出力内容

### LATEST タブ

- **元データ**: BigQuery VIEW `v_latest_with_delta_ratings`（今日の ratings_daily_snapshot ＋ 前日比）。
- **列**: snapshot_date, store_code, provider, provider_place_id, rating_value, review_count, fetched_at, ingest_run_id, status, delta_rating, delta_review_count.

### ALERT タブ

- **元データ**: BigQuery VIEW `v_rating_alerts`（閾値でフィルタした行）。
- **列**: snapshot_date, store_code, provider, alert_type, rating_value, delta_rating, delta_review_count.
- **alert_type**: `low_rating`（評価 &lt; 4.2）, `rating_drop`（前日比 ≤ -0.2）, `review_surge`（レビュー増加 ≥ 10）。

閾値は VIEW 定義（`sql/002_create_views.sql` の v_rating_alerts）で変更できます。

---

## 6. 動作確認

1. `SHEET_ID` を設定して `POST /` を実行（手動 curl または Scheduler）。
2. レスポンスの `"sheets_updated": true` で Sheets 更新が成功したことを確認。
3. スプレッドシートの LATEST / ALERT タブに、上記の列でデータが入っていることを確認。

Sheets 更新で例外が発生した場合は、取込は 200 のまま完了し、`sheets_updated` は `false` になります。ログに `[review_observation] Sheets update failed: ...` が出力されます。
