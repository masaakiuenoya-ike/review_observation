# review_observation

Google Business Profile（GBP）のレビュー・評価を定点観測し、BigQuery を SSOT として保存するサービス。Cloud Run で稼働し、Cloud Scheduler から日次/月次で実行する。

- **SSOT**: BigQuery（ikeuchi-ga4 / mart_gbp）
- **閲覧用**: Google スプレッドシート（LATEST / ALERT タブを全置換）
- **デプロイ**: main への push で GitHub Actions が Docker ビルド → Artifact Registry → Cloud Run へ自動デプロイ

---

## ドキュメント

| ドキュメント | 内容 |
|--------------|------|
| [review_observation_SSOT設計書_20260302_rev2.md](review_observation_SSOT設計書_20260302_rev2.md) | データモデル・処理フロー・認証・実装順の確定版 |
| [infra/gcloud_commands.md](infra/gcloud_commands.md) | GCP の手順（BQ / GCS / SA / Secret Manager / WIF / Scheduler 等） |
| [docs/疑問点.md](docs/疑問点.md) | 設計書に基づく疑問点の整理・解消状況 |

---

## 前提・構成

- **実行基盤**: GCP プロジェクト `ikeuchi-data-sync`（Cloud Run, Artifact Registry, Secret Manager, Scheduler）
- **BigQuery**: プロジェクト `ikeuchi-ga4`、データセット `mart_gbp`（raw_gbp / stg_gbp / mart_gbp あり、アプリは mart_gbp を利用）
- **リージョン**: asia-northeast1
- **Cloud Run サービス名**: review-observation（認証必須、Scheduler は OIDC で呼び出し）

---

## 初回セットアップ（GCP 側）

1. [infra/gcloud_commands.md](infra/gcloud_commands.md) の **§0 前提** を確認し、§1 以降を順に実施する。
2. **BigQuery**: §2 でデータセット作成、§7 で `sql/001_create_tables.sql` と `sql/002_create_views.sql` を mart_gbp に適用（`YOUR_DATASET` → `mart_gbp` に置換）。
3. **デプロイ用 SA と WIF**: §12・§13 を実施し、**GitHub Secrets** に `GCP_WIF_PROVIDER` と `GCP_WIF_SERVICE_ACCOUNT` を登録する。
4. **GitHub Secrets** に以下も登録: `GCS_EXPORT_BUCKET`、`SHEET_ID`（必要なら `GCP_PROJECT_ID`）。
5. **Secret Manager**: §5.1 で `gbp-oauth-json` を作成し、実行 SA に secretAccessor を付与。OAuth JSON（client_id, client_secret, refresh_token）を `gcloud secrets versions add` で登録する。
6. **スプレッドシート**: 書き込み先シートを **sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com** に **編集者** で共有する。
7. **places_provider_map**: BigQuery の `mart_gbp.places_provider_map` に 1 店舗以上を手動で INSERT する（設計書・infra を参照）。

---

## デプロイ（main への push）

- **main** に push すると `.github/workflows/deploy.yml` が実行される。
- 流れ: **lint-test**（ruff + pytest）→ **build-push**（Docker → Artifact Registry）→ **deploy**（Cloud Run）→ **GET /health** で成功判定。
- 認証は **Workload Identity Federation（WIF）**。鍵 JSON は使わない。
- 必要な GitHub Secrets は [infra/gcloud_commands.md §13.5](infra/gcloud_commands.md) を参照。

---

## ローカル実行（任意）

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
export PORT=8080
python src/main.py
# GET http://localhost:8080/health
```

GCP の BigQuery / Sheets 等を使う場合は、`gcloud auth application-default login` で ADC を設定し、環境変数（BQ_PROJECT, BQ_DATASET, SHEET_ID 等）を設定する。

---

## リポジトリ構成

```
.github/workflows/   # CI（deploy.yml: lint → build → deploy）
infra/               # GCP 手順（gcloud_commands.md）
sql/                 # BigQuery DDL（001 テーブル, 002 VIEW）
src/                 # アプリ（main.py: /health, POST /）
tests/               # pytest（tests/ 配下）
Dockerfile           # Cloud Run 用
requirements.txt
pyproject.toml       # ruff / pytest 設定
```

---

## トラブルシュート

- **Secret が設定できない / デプロイが失敗する**: [infra/gcloud_commands.md §13.6](infra/gcloud_commands.md) の原因切り分けを参照。
- **WIF**: main ブランチからのみ認証可能（§13.3 の attribute-condition）。別ブランチでは deploy ジョブの認証が失敗する。
- **429 / 5xx**: GBP API のレート制限・障害。並列数（MAX_WORKERS）やリトライは実装側で調整。

---

## ライセンス・利用

社内利用を想定。詳細はプロジェクト方針に従う。
