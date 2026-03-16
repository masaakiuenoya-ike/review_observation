# infra/gcloud_commands.md

作成日: 2026-03-02（JST）  
対象: `review_observation`（Cloud Run + Scheduler + BigQuery SSOT + Sheets + GCS CSV Export）

---

## 0. 前提（確定値）

- 実行基盤プロジェクト（Cloud Run / Scheduler / Secret / AR）：`ikeuchi-data-sync`（プロジェクト番号: 957418534824）
- BigQuery SSOTプロジェクト：`ikeuchi-ga4`
- リージョン/ロケーション：`asia-northeast1`
- Cloud Run サービス名（想定）：`review-observation`
- Cloud Run 実行SA（確定）  
  `sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com`
- BigQuery データセット（新規作成）  
  `raw_gbp` / `stg_gbp` / `mart_gbp`
- Secret 名（想定）  
  `gbp-oauth-json`
- CSV出力用 GCS バケット（作成/指定が必要）  
  `GCS_EXPORT_BUCKET=<YOUR_BUCKET_NAME>`

---

## 1. ローカル準備

```bash
gcloud auth login
gcloud auth application-default login
```

プロジェクト切替を明示して作業すること。

---

## 2. BigQuery（ikeuchi-ga4）: データセット作成

> ※BigQueryのデータセットは「作成したいプロジェクト側」で作成します。

```bash
# BQ datasets list
bq ls --project_id=ikeuchi-ga4

# raw_gbp
bq --location=asia-northeast1 mk --dataset \
  --description "GBP raw payloads (review_observation)" \
  ikeuchi-ga4:raw_gbp

# stg_gbp
bq --location=asia-northeast1 mk --dataset \
  --description "GBP staging (review_observation)" \
  ikeuchi-ga4:stg_gbp

# mart_gbp
bq --location=asia-northeast1 mk --dataset \
  --description "GBP mart/SSOT (review_observation)" \
  ikeuchi-ga4:mart_gbp
```

---

## 3. GCS（ikeuchi-data-sync）: CSV出力バケット作成（必要な場合）

> すでにバケットがある場合は作成不要。  
> 「リージョン」は Cloud Run と揃える（asia-northeast1）推奨。

```bash
gcloud config set project ikeuchi-data-sync

# 例: バケット名はグローバル一意
export GCS_EXPORT_BUCKET="<YOUR_BUCKET_NAME>"

gcloud storage buckets create "gs://${GCS_EXPORT_BUCKET}" \
  --location=asia-northeast1 \
  --uniform-bucket-level-access
```

---

## 4. サービスアカウント（ikeuchi-data-sync）: 作成（新規）

```bash
gcloud config set project ikeuchi-data-sync

gcloud iam service-accounts create sa-review-observation-run \
  --display-name="review_observation Cloud Run runtime SA"

# 確認
gcloud iam service-accounts list \
  --filter="email:sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com" \
  --format="value(email)"
```

---

## 5. IAM: Secret Manager / GCS 付与（ikeuchi-data-sync）

### 5.1 Secret Manager（GBP OAuth JSON）

Secret（例: `gbp-oauth-json`）を作成し、JSONを登録します。

#### 5.1.1 Secret 作成（初回のみ）
```bash
gcloud config set project ikeuchi-data-sync

gcloud secrets create gbp-oauth-json \
  --replication-policy="automatic"
```

#### 5.1.2 Secret の値登録（JSON）※未登録の場合はここを実施

**1. GBP 用 OAuth 2.0 の取得**

**1a. Google Cloud Console で OAuth 2.0 クライアント ID を作成**

1. [Google Cloud Console](https://console.cloud.google.com/) にログインし、プロジェクト **ikeuchi-data-sync**（または GBP API を有効化したプロジェクト）を選択する。
2. 左メニュー **「API とサービス」** → **「認証情報」** を開く。
3. **「+ 認証情報を作成」** → **「OAuth クライアント ID」** を選ぶ。
4. 初回の場合は **「OAuth 同意画面」** を先に設定するよう促される。
   - ユーザータイプ: **内部** の場合は、同じ Google Workspace 組織のユーザーのみが認証可能。**外部** の場合は一般公開前に「テスト」公開にし、テストユーザを指定する。
   - アプリ名・ユーザーサポートメールを入力して保存する。
   - **スコープ** で **「スコープを追加または削除」** → `https://www.googleapis.com/auth/business.manage` を追加して保存する。
   - **ユーザータイプが「外部」の場合のみ**：「OAuth 同意画面」の画面で **「テストユーザ」** セクションがあり、ここに **「+ ADD USERS」** で、GBP を管理する Google アカウントのメールアドレスを追加する。認証できるのはこの一覧に載っているユーザのみ（本番公開前）。
   - **ユーザータイプが「内部」の場合**：テストユーザの設定はない。組織内のユーザーがそのまま認証できるため、GBP を管理するアカウントでログインした状態で後述の認証フロー（Playground 等）を実行すればよい。
5. 再度 **「認証情報」** → **「+ 認証情報を作成」** → **「OAuth クライアント ID」**。
6. アプリケーションの種類: **「デスクトップアプリ」** を選ぶ（ローカルで認証フローを回して refresh_token を取得しやすい）。  
   または **「ウェブアプリケーション」** の場合は「承認済みのリダイレクト URI」を 1 つ登録する（例: `http://localhost:8080/`）。
7. 名前（例: `review_observation_gbp`）を入力して **「作成」**。
8. 表示された **クライアント ID** と **クライアント シークレット** を控える → これが JSON の `client_id` と `client_secret`。

**1b. refresh_token の取得**

- デスクトップアプリの場合: [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/) や、自作の小さなスクリプトで認証フローを実行し、認証後に返ってくる **refresh_token** を控える。Playground では「Step 1」でスコープに `https://www.googleapis.com/auth/business.manage` を追加し、「Step 2」で認証して refresh token を取得する。
- 取得する 3 要素: `client_id`, `client_secret`, `refresh_token`。

**2. ローカルに JSON ファイルを作成（リポジトリにコミットしない）**

リポジトリの `infra/gbp_oauth.json.example` をコピーして `gbp_oauth.json` を作成し、実値で埋める。

```bash
cp infra/gbp_oauth.json.example gbp_oauth.json
# エディタで client_id / client_secret / refresh_token を実値に置き換える
```

**3. Secret Manager に登録**

```bash
gcloud config set project ikeuchi-data-sync
gcloud secrets versions add gbp-oauth-json --data-file=gbp_oauth.json
```

登録後は `gbp_oauth.json` を削除するか、少なくともリポジトリにコミットしないこと（`.gitignore` で `*.json` を除外済み）。

#### 5.1.3 Cloud Run実行SAに Secret Accessor
```bash
gcloud secrets add-iam-policy-binding gbp-oauth-json \
  --member="serviceAccount:sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 5.2 GCS（CSV出力）権限
```bash
gcloud storage buckets add-iam-policy-binding "gs://${GCS_EXPORT_BUCKET}" \
  --member="serviceAccount:sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

---

## 6. IAM: BigQuery 書き込み権限（ikeuchi-ga4）

> クロスプロジェクト書き込みのため、BigQuery側（ikeuchi-ga4）で権限付与が必要。

### 6.1 Project-level: BigQuery Job User
```bash
gcloud projects add-iam-policy-binding ikeuchi-ga4 \
  --member="serviceAccount:sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"
```

### 6.2 Dataset-level: BigQuery Data Editor
```bash
bq update --dataset \
  --add_iam_member="serviceAccount:sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com:roles/bigquery.dataEditor" \
  ikeuchi-ga4:raw_gbp

bq update --dataset \
  --add_iam_member="serviceAccount:sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com:roles/bigquery.dataEditor" \
  ikeuchi-ga4:stg_gbp

bq update --dataset \
  --add_iam_member="serviceAccount:sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com:roles/bigquery.dataEditor" \
  ikeuchi-ga4:mart_gbp
```

---

## 7. BigQuery: SQL適用（初回）

> リポジトリの `sql/001_create_tables.sql` と `sql/002_create_views.sql` を適用。  
> `YOUR_DATASET` は `mart_gbp` 等に置換してください。

例（ローカルで適用）:

```bash
# 例: mart_gbpにSSOTテーブルを作る
bq query --project_id=ikeuchi-ga4 --location=asia-northeast1 --use_legacy_sql=false \
  "$(sed 's/YOUR_DATASET/mart_gbp/g' sql/001_create_tables.sql)"

bq query --project_id=ikeuchi-ga4 --location=asia-northeast1 --use_legacy_sql=false \
  "$(sed 's/YOUR_DATASET/mart_gbp/g' sql/002_create_views.sql)"
```

---

## 7.5 BigQuery（ikeuchi-ga4）: ジョブ確認（CLI）

> コンソールの「運用の健全性」で権限不足のときは、CLI でジョブ一覧・状態を確認する。

```bash
# 直近のジョブ一覧（全ユーザー・プロジェクト指定）
bq ls -j -a --project_id=ikeuchi-ga4 --max_results=20

# 直近のジョブ一覧（自分のジョブのみ）
bq ls -j --project_id=ikeuchi-ga4 --max_results=20
```

出力例: `jobId`, `jobType`, `state` (RUNNING / DONE / PENDING), `creationTime`, `startTime`, `endTime` など。

```bash
# 特定ジョブの詳細（RUNNING で止まっていないか確認）
bq show -j --project_id=ikeuchi-ga4 JOB_ID

# JSON で詳細（クエリ文・エラーなど）
bq show --format=prettyjson -j --project_id=ikeuchi-ga4 JOB_ID
```

**補足**: `merge_reviews` はレビュー1件ごとに MERGE を投げるため、1店舗で多数のレビューがあるとジョブが連続する。`state=RUNNING` のジョブが長時間残っていれば、アプリが `job.result(timeout=60)` で待っている可能性がある。

---

## 8. Artifact Registry（ikeuchi-data-sync）: 作成

> Cloud Run デプロイ用のコンテナレジストリ。

```bash
gcloud config set project ikeuchi-data-sync

gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com
```

```bash
# 例: repo名
export AR_REPO="containers"

gcloud artifacts repositories create "${AR_REPO}" \
  --repository-format=docker \
  --location=asia-northeast1 \
  --description="Container images for ikeuchi-data-sync"
```

---

## 9. Cloud Run（ikeuchi-data-sync）: 初回デプロイ（手動例）

> deploy.yml（GitHub Actions）が完成するまでの手動デプロイ例です。

```bash
gcloud config set project ikeuchi-data-sync

export REGION="asia-northeast1"
export SERVICE_NAME="review-observation"
export IMAGE="${REGION}-docker.pkg.dev/ikeuchi-data-sync/${AR_REPO}/${SERVICE_NAME}:manual"
```

### 9.1 ビルド＆プッシュ
```bash
gcloud auth configure-docker "${REGION}-docker.pkg.dev"

docker build -t "${IMAGE}" .
docker push "${IMAGE}"
```

### 9.2 デプロイ
```bash
# 書き込み先スプレッドシートの ID を指定（必須）
export SHEET_ID="<YOUR_SPREADSHEET_ID>"

gcloud run deploy "${SERVICE_NAME}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --service-account="sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com" \
  --no-allow-unauthenticated \
  --set-env-vars="TZ=Asia/Tokyo,BQ_PROJECT=ikeuchi-ga4,BQ_LOCATION=asia-northeast1,BQ_DATASET=mart_gbp,GCS_EXPORT_BUCKET=${GCS_EXPORT_BUCKET},SHEET_ID=${SHEET_ID}" \
  --set-env-vars="SHEET_TAB_LATEST=LATEST,SHEET_TAB_ALERT=ALERT,PROVIDER=google" \
  --set-env-vars="ALERT_LOW_RATING=4.2,ALERT_DROP_RATING=-0.2,ALERT_SURGE_REVIEWS=10,MAX_WORKERS=5" \
  --set-env-vars="GBP_OAUTH_SECRET_NAME=gbp-oauth-json"
```

---

## 10. Cloud Scheduler（ikeuchi-data-sync）: 定期実行（OIDC）

> Cloud Runが「認証必須」なので、SchedulerはOIDCで呼び出します。

### 10.1 呼び出し用SA（例）
Scheduler専用のSAを作る（推奨）。※ SA の ID は 30 文字以内のため `sa-review-obs-scheduler` を使用。

```bash
gcloud config set project ikeuchi-data-sync

gcloud iam service-accounts create sa-review-obs-scheduler \
  --display-name="review_observation Scheduler SA"
```

Cloud Run invoker権限（**初回デプロイ後に実行**）:

```bash
export REGION="asia-northeast1"
export SERVICE_NAME="review-observation"
export SCHEDULER_SA="sa-review-obs-scheduler@ikeuchi-data-sync.iam.gserviceaccount.com"

gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${SCHEDULER_SA}" \
  --role="roles/run.invoker"
```

### 10.2 デプロイ（Cloud Run）

- **main に push** すると GitHub Actions でビルド・デプロイが走る（`.github/workflows/deploy.yml`）。
- 手動実行: GitHub の Actions タブで「Deploy to Cloud Run」を **Run workflow**。
- 初回または Scheduler 用 SA 作成後は **10.1** の `run.invoker` 付与を実行する。

### 10.3 1時間ごとジョブ（推奨: レビュー取得）

毎時 0 分（JST）に `POST /` を実行するジョブ。**Cloud Run デプロイ後に** 実行する。

```bash
export REGION="asia-northeast1"
export SERVICE_NAME="review-observation"
export SCHEDULER_SA="sa-review-obs-scheduler@ikeuchi-data-sync.iam.gserviceaccount.com"
export RUN_URL="$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format="value(status.url)")"

gcloud scheduler jobs create http review-observation-hourly \
  --location="${REGION}" \
  --schedule="0 * * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="${RUN_URL}/" \
  --http-method=POST \
  --oidc-service-account-email="${SCHEDULER_SA}" \
  --oidc-token-audience="${RUN_URL}" \
  --headers="Content-Type=application/json" \
  --message-body="{}"
```

- `0 * * * *` = 毎時 0 分（1日 24 回）。
- 既に同名ジョブがある場合は `gcloud scheduler jobs delete review-observation-hourly --location=${REGION}` で削除してから再作成。
- 取込に数分かかるため、**attemptDeadline** を延長すること（デフォルト 180 秒だと code: 4 になる）。**Scheduler の上限は 30 分（1800s）**。Cloud Run は deploy で `--timeout=3600`:
  ```bash
  gcloud scheduler jobs update http review-observation-hourly --location=asia-northeast1 --attempt-deadline=1800s
  gcloud scheduler jobs update http review-observation-daily --location=asia-northeast1 --attempt-deadline=1800s
  ```

### 10.4 日次ジョブ（毎日 09:00 JST・任意）

1時間ごとで十分な場合は不要。日次だけにしたい場合は 10.3 の代わりにこちらを使用。

```bash
gcloud scheduler jobs create http review-observation-daily \
  --location="${REGION}" \
  --schedule="0 9 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="${RUN_URL}/" \
  --http-method=POST \
  --oidc-service-account-email="${SCHEDULER_SA}" \
  --oidc-token-audience="${RUN_URL}" \
  --headers="Content-Type=application/json" \
  --message-body="{}"
```

### 10.5 月次ジョブ（毎月1日 09:00 JST）
```bash
gcloud scheduler jobs create http review-observation-monthly \
  --location="${REGION}" \
  --schedule="0 9 1 * *" \
  --time-zone="Asia/Tokyo" \
  --uri="${RUN_URL}/" \
  --http-method=POST \
  --oidc-service-account-email="${SCHEDULER_SA}" \
  --oidc-token-audience="${RUN_URL}" \
  --headers="Content-Type=application/json" \
  --message-body="{\"run_monthly\": true}"
```

> 実装側で `run_monthly: true` を見て monthly を実行する、または別エンドポイントに分けてもOK。

### 10.6 ジョブ一覧・手動実行

```bash
gcloud scheduler jobs list --location=asia-northeast1
# 手動で 1 回実行
gcloud scheduler jobs run review-observation-hourly --location=asia-northeast1
```

### 10.7 実行状況の確認

**ジョブ一覧（スケジュール・状態・最終実行時刻）**

```bash
gcloud config set project ikeuchi-data-sync
gcloud scheduler jobs list --location=asia-northeast1 \
  --format="table(name.basename(), schedule, state, lastAttemptTime)"
```

**特定ジョブの詳細（次回実行予定・最終実行結果など）**

```bash
gcloud scheduler jobs describe review-observation-hourly --location=asia-northeast1
```

**実行履歴（ログ）**

- **コンソール**: [Cloud Scheduler](https://console.cloud.google.com/cloudscheduler?project=ikeuchi-data-sync) → ジョブを選択 → **「ログを表示」** で Logs Explorer が開く（実行開始・終了・成否が分かる）。
- **CLI**: 直近の Scheduler 実行ログを引く例（プロジェクト要指定）:
  ```bash
  gcloud logging read 'resource.type="cloud_scheduler_job" resource.labels.job_id="review-observation-hourly"' \
    --project=ikeuchi-data-sync --limit=20 --format="table(timestamp, severity, textPayload)"
  ```

### 10.8 実行状態報告（まとめて出力）

認証済みのターミナルで以下を実行すると、報告用の実行状態がまとめて出力される。

```bash
# リポジトリルートで
bash scripts/report_scheduler_status.sh
```

出力内容: ジョブ一覧（review_observation のみ）・各ジョブの詳細（state / lastAttemptTime / status）・ hourly の直近実行ログ。

### 10.9 Scheduler は動いているが ratings_daily_snapshot に新しい日付が入らないとき

**状況**: ジョブは ENABLED で lastAttemptTime も更新されているが、BQ の `ratings_daily_snapshot` は 3/12 など古い日付のまま。

**原因の目安**: Scheduler は「呼び出し」しているが、**Cloud Run が 200 を返していない**（403 / 500 / タイムアウトなど）。その場合、アプリは完了まで到達せず、`merge_ratings_daily_snapshot` が実行されないため、その日の行が書き込まれない。

**確認手順**

1. **Scheduler ジョブの status**
   ```bash
   gcloud scheduler jobs describe review-observation-hourly --location=asia-northeast1 --format="yaml(status)"
   ```
   - `status.code: 0` → Cloud Run は 2xx を返している（別原因を疑う）。
   - `status.code: 4`（DEADLINE_EXCEEDED）→ Scheduler が応答を待つ時間（attemptDeadline、デフォルト 180 秒）を超えた。Cloud Run のタイムアウトと Scheduler の `--attempt-deadline=600s` を両方延長する。
   - `status.code: 13`（INTERNAL）→ Cloud Run がエラーまたはタイムアウトで応答している。

2. **Cloud Run のログ**
   - [Logs Explorer](https://console.cloud.google.com/logs/query?project=ikeuchi-data-sync) でプロジェクト `ikeuchi-data-sync` を選択。
   - リソースで **Cloud Run リビジョン** を選び、`review-observation` を指定。
   - 直近で `POST /` が来ている時間帯に、`[review_observation] POST / started` のあと `Sheets ... updated` や 200 が出ているか、それとも 500 やタイムアウトのエラーが出ているかを確認する。

3. **よくある原因と対処**

   | 原因 | 対処 |
   |------|------|
   | **403 Forbidden**（OIDC 認証） | Scheduler 用 SA に Cloud Run の **invoker** が付いているか確認。§10.1 の `run.invoker` 付与を再実行。 |
   | **タイムアウト** | 31 店舗の取込は数分かかることがある。**Gunicorn**（Dockerfile で `--timeout 600`）、**Cloud Run**（deploy で `--timeout=1200`）、**Scheduler**（`--attempt-deadline=1200s`）の 3 つを揃える。手動で延長する場合は `gcloud run services update review-observation --region=asia-northeast1 --timeout=1200` と Scheduler の attempt-deadline。 |
   | **500 Internal Server Error** | ログのスタックトレースを確認（BQ / Secret Manager / GBP API のエラー）。ADC や OAuth トークン期限など。 |

4. **手動実行で確認**
   ```bash
   gcloud scheduler jobs run review-observation-hourly --location=asia-northeast1
   ```
   実行直後に Logs Explorer で `review-observation` のログを「ストリーミング」または直近 5 分で見ると、POST / の成否が分かる。

**補足**: `status.code: 13` は、Cloud Run が 5xx を返した場合や、接続がタイムアウトした場合などに付く。まず Cloud Run のログで実際の HTTP ステータスとエラー内容を確認する。

**500 かつ latency が約 30 秒で gunicorn handle_abort / job.result(timeout=...) のトレースバック**: Gunicorn の **worker タイムアウト**（デフォルト 30 秒）でリクエストが打ち切られている。Dockerfile で `--timeout 600` を指定して再デプロイし、Cloud Run のリクエストタイムアウトも 600 秒にすること。

---

## 11. Sheets 書き込み権限

- 対象スプレッドシートを Cloud Run 実行SA（`sa-review-observation-run@...`）に **編集者**として共有する。
- デプロイ時に **SHEET_ID**（スプレッドシートの ID）を Cloud Run の環境変数に渡す。GitHub Actions では Secret `SHEET_ID` を登録し、deploy.yml が `--set-env-vars` で注入する。スプレッドシートの URL が `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit` のとき、`<SHEET_ID>` をそのまま使う。

### 11.1 実施手順（スプレッドシートを runtime SA に共有）

1. 書き込み先にする Google スプレッドシートを開く（LATEST / ALERT / サマリ タブをアプリが更新する想定）。
2. 右上の **「共有」** をクリック。
3. **ユーザーやグループを追加** の欄に、次のメールアドレスを入力する（コピー＆ペースト可）:
   ```
   sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com
   ```
4. 権限を **編集者** にし、**送信**（または共有）をクリック。
5. （任意）GitHub Secrets に **SHEET_ID** が未登録なら、スプレッドシート URL の `https://docs.google.com/spreadsheets/d/` と `/edit` のあいだの文字列をコピーし、Settings → Secrets and variables → Actions で `SHEET_ID` として登録する。

---

## 12. デプロイ用SA（GitHub Actions WIF用）の作成と権限

> deploy.yml は **runtime SA**（Cloud Run 実行用）と **deploy SA**（GitHub Actions からデプロイする用）を分ける前提です。

### 12.1 デプロイ用SAの作成

```bash
gcloud config set project ikeuchi-data-sync

gcloud iam service-accounts create sa-review-observation-deploy \
  --display-name="review_observation GitHub Actions deploy SA"
```

### 12.2 デプロイ用SAに付与する権限（最低限の例）

| ロール | 用途 |
|--------|------|
| `roles/run.admin` | Cloud Run サービスのデプロイ・更新 |
| `roles/iam.serviceAccountUser` | runtime SA（sa-review-observation-run）を指定してデプロイするため |
| `roles/artifactregistry.writer` | Artifact Registry へイメージを push |
| （必要なら）`roles/secretmanager.secretAccessor` | デプロイ時に Secret 参照する場合 |

付与コマンド例:

```bash
export DEPLOY_SA="sa-review-observation-deploy@ikeuchi-data-sync.iam.gserviceaccount.com"
export PROJECT_NUM="957418534824"

# Cloud Run Admin
gcloud projects add-iam-policy-binding ikeuchi-data-sync \
  --member="serviceAccount:${DEPLOY_SA}" \
  --role="roles/run.admin"

# Service Account User（runtime SA を act-as するため）
gcloud iam service-accounts add-iam-policy-binding \
  sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com \
  --member="serviceAccount:${DEPLOY_SA}" \
  --role="roles/iam.serviceAccountUser" \
  --project=ikeuchi-data-sync

# Artifact Registry Writer
gcloud artifacts repositories add-iam-policy-binding containers \
  --location=asia-northeast1 \
  --member="serviceAccount:${DEPLOY_SA}" \
  --role="roles/artifactregistry.writer" \
  --project=ikeuchi-data-sync

# （任意）Secret Manager をデプロイ時に参照する場合
# gcloud secrets add-iam-policy-binding gbp-oauth-json \
#   --member="serviceAccount:${DEPLOY_SA}" \
#   --role="roles/secretmanager.secretAccessor" \
#   --project=ikeuchi-data-sync
```

---

## 13. Workload Identity Federation（WIF）設定

> GitHub Actions から鍵 JSON を使わず、WIF で ikeuchi-data-sync に認証するための設定です。

### 13.1 必要な API 有効化

```bash
gcloud config set project ikeuchi-data-sync

gcloud services enable iamcredentials.googleapis.com sts.googleapis.com
```

### 13.2 Workload Identity Pool の作成

```bash
export PROJECT_ID="ikeuchi-data-sync"
export PROJECT_NUM="957418534824"
export POOL_NAME="github-pool"
export PROVIDER_NAME="github-provider"

gcloud iam workload-identity-pools create "${POOL_NAME}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --display-name="GitHub Actions pool"
```

### 13.3 GitHub 用 Provider の作成

> 対象リポジトリを `masaakiuenoya-ike/review_observation` にしている例です。組織・リポジトリ名は環境に合わせて変更してください。  
> **main ブランチ限定**にするため、`attribute.ref` をマッピングし、`--attribute-condition` で `refs/heads/main` を縛る。これがないと同 repo の別ブランチからも WIF 認証できてしまう。

```bash
export REPO="masaakiuenoya-ike/review_observation"

# attribute.ref を追加し、condition で repo と main ブランチに限定
gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_NAME}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL_NAME}" \
  --display-name="GitHub OIDC provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="attribute.repository=='${REPO}' && attribute.ref=='refs/heads/main'" \
  --issuer-uri="https://token.actions.githubusercontent.com"
```

> tags のみ許可する場合は `attribute.ref=='refs/tags/.*'` などに変更可能。別ブランチも許可する場合は condition から `&& attribute.ref==...` を外す（非推奨）。

### 13.4 principal に GitHub リポジトリを紐付け

> 認証可能な「誰」は principalSet で紐付ける。**ブランチ制限（main 限定）は §13.3 の `--attribute-condition` で実現している**。ここではリポジトリ単位の紐付けのみ行う。

```bash
export REPO="masaakiuenoya-ike/review_observation"
export DEPLOY_SA="sa-review-observation-deploy@ikeuchi-data-sync.iam.gserviceaccount.com"

# リポジトリ単位で紐付け（main 限定は 13.3 の attribute-condition で担保）
gcloud iam service-accounts add-iam-policy-binding "${DEPLOY_SA}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUM}/locations/global/workloadIdentityPools/${POOL_NAME}/attribute.repository/${REPO}"
```

> 組織全体にしたい場合は `principalSet` を変更（例: `attribute.repository_owner/masaakiuenoya-ike`）。その場合も §13.3 の condition で ref 制限をかけることを推奨する。

### 13.5 GitHub であなたが渡すもの（Secrets 一覧）

**重要**: GitHub Secrets は **GCP 側の設定が終わっていないと登録できない**。  
`GCP_WIF_PROVIDER` と `GCP_WIF_SERVICE_ACCOUNT` の値は、§12・§13 で GCP に作成したリソースから得るため、**先に GCP を完了してから** GitHub に Secrets を登録する。

**作業順序（想定）**  
1. **GCP 側**: §12（デプロイ用SA作成・権限）→ §13.1〜13.4（WIF Pool / Provider 作成・principal 紐付け）を実施する。  
2. **GCP 側**: §3 で GCS バケット作成、§11 でスプレッドシート共有と ID を控える。  
3. **GitHub 側**: 上記で得た値を使って、リポジトリ **Settings → Secrets and variables → Actions** → **New repository secret** で以下を 1 件ずつ登録する。

GCP がまだの状態で main に push すると、deploy ジョブで Secrets 未設定により失敗する。その場合は GCP 設定 → Secrets 登録の順で対応する。

| Secret 名 | 必須 | 値の取り方・例（いずれも GCP 等の設定後に決まる） |
|-----------|------|------------------------------------------------|
| `GCP_WIF_PROVIDER` | 必須 | §13.2・13.3 で作成した WIF のプロバイダ文字列。<br>例: `projects/957418534824/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `GCP_WIF_SERVICE_ACCOUNT` | 必須 | §12.1 で作成したデプロイ用 SA のメール。<br>例: `sa-review-observation-deploy@ikeuchi-data-sync.iam.gserviceaccount.com` |
| `GCS_EXPORT_BUCKET` | 必須 | §3 で作成した CSV 出力用バケット名。 |
| `SHEET_ID` | 必須 | 書き込み先スプレッドシートの ID（URL の `/d/【ここ】/edit` の「ここ」）。§11 で共有したシートの ID。 |
| `GCP_PROJECT_ID` | 任意 | 未設定時は workflow 内で `ikeuchi-data-sync` を使用。 |

### 13.6 「Secret が設定できない」「デプロイが失敗する」場合の原因切り分け

本ドキュメントでは「GCP 設定 → GitHub Secrets 登録」の順序を書いている。それでも Secret を登録できない／デプロイが落ちる場合は、次のいずれかが典型原因である。

| 原因 | 内容・確認方法 |
|------|----------------|
| **WIF の provider / pool がまだない** | `GCP_WIF_PROVIDER` に入れる値が決まらない。§13.2・13.3 を実行し、作成した provider のリソース名を控えてから GitHub Secrets に登録する。 |
| **デプロイ用 SA 未作成 or workloadIdentityUser 未バインド** | WIF で認証できない。§12.1 で SA 作成、§12.2 で権限付与、§13.4 で `roles/iam.workloadIdentityUser` を principalSet にバインドしたか確認する。 |
| **runtime 用の gbp-oauth-json が未作成** | デプロイは成功するが、アプリ起動後に Secret Manager 参照で落ちる。§5.1 で Secret 作成・実行 SA に secretAccessor を付与する。 |
| **SHEET_ID / GCS_EXPORT_BUCKET が GitHub Secrets にない** | deploy.yml がこれらを必須で参照している。Settings → Secrets and variables → Actions で両方登録する。 |

---

## 14. （参考）旧「GitHub Actions WIF メモ」

deploy.yml および §12・§13 に統合済み。参照する場合は §12（デプロイ用SA権限）と §13（WIF 設定）を参照。

---

## 15. 既存月次データのインポート（参考）

**dim_store に存在する全店舗**を対象に、月次既存集計を **performance_monthly_snapshot** に投入する手順は以下を参照。

- **手順・タイミング・列対応**: [docs/既存月次データのインポート.md](../docs/既存月次データのインポート.md)
- **INSERT 用 SQL テンプレート**: [sql/020_import_historical_monthly_performance.sql](../sql/020_import_historical_monthly_performance.sql)

**実施タイミング**: places_provider_map に該当店舗を登録した直後。**store_code** は店舗マスタ `ikeuchi-ga4.stg_freee_prd.dim_store` の **store_id** を文字列にした値（[docs/店舗マスタ参照.md](../docs/店舗マスタ参照.md) 参照）。

---
