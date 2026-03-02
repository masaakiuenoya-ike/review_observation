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
| [docs/店舗マスタ参照.md](docs/店舗マスタ参照.md) | store_code の正: BigQuery **ikeuchi-ga4.stg_freee_prd.dim_store** の store_id（文字列） |
| [docs/GBPデータソース.md](docs/GBPデータソース.md) | 月次パフォーマンスの**現在のデータ**の出所: **tmp/Googleビジネスプロフィール集計.xlsx** の **GBPサマリー** シート |

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
7. **places_provider_map**: BigQuery の `mart_gbp.places_provider_map` に 1 店舗以上を手動で INSERT する。**store_code** は店舗マスタ `ikeuchi-ga4.stg_freee_prd.dim_store` の **store_id** を文字列にした値（[docs/店舗マスタ参照.md](docs/店舗マスタ参照.md) 参照）。
8. **既存月次データのインポート**（任意）: **dim_store に存在する全店舗**を対象に、**places_provider_map 登録直後**に [docs/既存月次データのインポート.md](docs/既存月次データのインポート.md) に従い `performance_monthly_snapshot` へ投入する。SQL: [sql/020_import_historical_monthly_performance.sql](sql/020_import_historical_monthly_performance.sql)（全店舗分は [scripts/gen_020_import_monthly.py](scripts/gen_020_import_monthly.py) で再生成可）。

---

## 今後実施すべき手順（チェックリスト）

初回セットアップ（上記 §1–8）のあと、次の順で進める。

| # | 項目 | 参照 |
|---|------|------|
| 1 | places_provider_map に **dim_store の全店舗**を登録（store_code = store_id の文字列） | 設計書 §3.1 / [docs/店舗マスタ参照.md](docs/店舗マスタ参照.md) |
| 2 | 既存月次データのインポート（全店舗を対象に 2023-07/08/09 を挿入。登録直後に実施） | [docs/既存月次データのインポート.md](docs/既存月次データのインポート.md) |
| 3 | Phase 2: GBP レビュー取得（OAuth → ratings_daily_snapshot / reviews の MERGE） | 設計書 §12 |
| 4 | Phase 2: スプレッドシート LATEST / ALERT の更新（アプリから全置換） | 設計書 §12 |
| 5 | Phase 2.5: performance_daily / monthly 取得＋MERGE、月次 Scheduler | 設計書 §12 |
| 6 | Phase 3: 並列化・リトライ・構造化ログ | 設計書 §12 |
| 7 | Phase 4: BQ Extract → GCS（CSV 出力） | 設計書 §12 |

※ Phase 5（CI/CD・Scheduler）はすでに導入済み。

---

## 次にやるべきこと（提案）

- **まだの場合**: **places_provider_map** に **dim_store の全店舗**を INSERT し、**スプレッドシート**を runtime SA に編集者で共有する。
- **上記の直後**: 既存月次データを入れる場合は、[docs/既存月次データのインポート.md](docs/既存月次データのインポート.md) の手順で `sql/020_import_historical_monthly_performance.sql` を実行（dim_store の全行が対象。店舗追加時は `scripts/gen_020_import_monthly.py` の STORE_IDS を更新して SQL を再生成）。
- **その次**: **Phase 2** の実装に進む。  
  - Secret Manager の OAuth は設定済みのため、**GBP API でレビュー取得** → **ratings_daily_snapshot / reviews へ MERGE** → **Sheets の LATEST / ALERT を更新** する処理を `src/main.py`（または別モジュール）に実装する。  
  - 設計書 §12 の Phase 2 → Phase 2.5 の順で進めると、レビュー・評価に続いて performance まで一連で扱える。

---

## 次のタスク一覧（優先順）

| 順 | タスク | 内容・参照 |
|----|--------|------------|
| **1** | **places_provider_map 登録** | dim_store の全 store_id を store_code として INSERT（provider='google', provider_place_id は GBP の location が分かれば設定）。未実施なら [docs/店舗マスタ参照.md](docs/店舗マスタ参照.md) と設計書 §3.1。 |
| **2** | **スプレッドシート共有** | 書き込み先シートを **sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com** に**編集者**で共有。未実施なら infra §11。 |
| **3** | **Phase 2: GBP レビュー取得** | OAuth で GBP API を呼び、`ratings_daily_snapshot` と `reviews` に MERGE。設計書 §12 Step 6–7。 |
| **4** | **Phase 2: Sheets 更新** | アプリから LATEST / ALERT タブを VIEW に基づき全置換。設計書 §12。 |
| **5** | **Phase 2.5: performance API** | performance_daily / monthly を GBP API で取得し MERGE。月次は毎月1日 09:00 JST の Scheduler と連携。設計書 §12 Step 8–9。 |
| **6** | **Phase 3: 安定化** | 並列化・リトライ・構造化ログ。設計書 §12 Step 10。 |
| **7** | **Phase 4: CSV 出力** | BQ Extract → GCS。設計書 §12 Step 11。 |

※ 既存月次データの xlsx からの upsert は実施済み（`scripts/import_gbp_monthly_from_xlsx.py`）。再投入時は同スクリプトを再実行可。

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
