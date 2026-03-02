あなたはGCP/BigQuery/Cloud Run/Google Sheets/Google Business Profile APIのシニアアーキテクト兼ソフトウェアエンジニアです。
以下のGitHubリポジトリで実装し、workflow（CI/CD）を構築してCloud Runへデプロイできる状態まで作ってください：
https://github.com/masaakiuenoya-ike/review_observation

Apps Script(GAS)は使いません。BigQueryがSSOT、SheetsはLATEST/ALERTのみ更新です。

# 0. 目的 / 方針
- SSOTはBigQuery。履歴（全スナップショット）はBigQueryに保存する。
- スプレッドシートは閲覧UI用途。更新は LATEST/ALERT のみ（全置換）。
- 将来、Yahoo Map/Apple Map等のプロバイダを追加できるように、データモデルは provider 列で1本化する（テーブル分割しない）。
- store_code は既存のBigQuery店舗マスタを参照し、今回の監視データ側は store_code をキーに保持する（店舗名等はJOINで取得する）。
- 冪等性：同日・同店舗・同providerのスナップショットは上書き（MERGE）。
- まずはGoogle(GBP)のみ実装。Yahoo/Appleはスキーマ対応のみ先に入れてOK。
- デプロイはCloud Run。定期実行はCloud Scheduler（09:00 JSTでHTTP POST）。

# 0.1 リポジトリ前提（重要）
- 既に上記リポジトリをクローン済みとして、必要なファイルを作成・更新する。
- mainブランチへのpushでCIが走り、必要に応じてCloud Runへデプロイできるworkflowを追加する。
- Secrets/認証情報はGitHub Actions SecretsとGCP側（Secret Manager/IAM）で扱い、リポジトリに平文で置かない。

# 1. リポジトリ構成（作成）
- /src
  - main.py
  - gbp_client.py
  - bq_writer.py
  - sheets_writer.py
  - models.py
  - config.py
- /sql
  - 001_create_tables.sql
  - 002_create_views.sql
  - 010_merge_snapshot.sql
- /infra
  - gcloud_commands.md
  - scheduler_job.md（任意）
- /.github/workflows
  - ci.yml（lint/test）
  - deploy.yml（Cloud Runへデプロイ）
- requirements.txt
- pyproject.toml or setup.cfg（lint/format設定。ruff推奨、blackでも可）
- README.md
- Dockerfile（推奨：Cloud Runへ確実に同一ビルドを流すため）

# 2. 環境変数（Cloud Run）
必須：
- GCP_PROJECT
- BQ_DATASET
- BQ_LOCATION
- SHEET_ID
- SHEET_TAB_LATEST=LATEST
- SHEET_TAB_ALERT=ALERT
- PROVIDER=google
- TZ=Asia/Tokyo
- ALERT_LOW_RATING=4.2
- ALERT_DROP_RATING=-0.2
- ALERT_SURGE_REVIEWS=10
- MAX_WORKERS=5

認証（設計要件）：
- BigQuery/SheetsはCloud Runの実行サービスアカウントで実行。
- Sheetsは対象スプレッドシートをサービスアカウントに共有し書込み可能にする。
- GBPはOAuthが必要。少なくとも次のどちらかで動くようにする（後から差し替え可能な設計）：
  A) ドメインワイド委任（可能なら）
  B) OAuthクライアント + リフレッシュトークンをSecret Managerに保存して利用
- Secret Managerから取得する値は env にSECRET名を指定し、実体はGCPから読む。
  例：GBP_OAUTH_SECRET_NAME

# 0.2 解消した前提・設計の補足（疑問点の整理）
以下は本文に「前の設計」等で参照されていた曖昧点を、実装可能な形で確定した内容です。

- **テーブル定義の具体化**  
  「前の設計どおり」は本リポジトリに存在しないため、以下で定義する（#3 に反映）。
  - **places_provider_map**: store_code, provider, provider_place_id（GBPのPlace ID等）, is_active, created_at, updated_at。  
    provider_place_id でプロバイダAPIを呼び出す。パーティションはなし（小規模マスタ想定）。
  - **ratings_daily_snapshot**: snapshot_date, store_code, provider, rating_value, review_count, status, fetched_at, ingest_run_id。  
    PARTITION BY snapshot_date, CLUSTER BY store_code, provider。冪等MERGEのキーは snapshot_date + store_code + provider。
  - **reviews**: store_code, provider, provider_review_id（PK）, rating, review_text, review_created_at, ingested_at。  
    PARTITION BY DATE(ingested_at)、CLUSTER BY store_code, provider。重複排除は provider_review_id で MERGE/INSERT。
  - **raw_provider_payloads**: ingest_run_id, snapshot_date, store_code, provider, payload（JSON STRING）, created_at。  
    PARTITION BY snapshot_date, CLUSTER BY store_code, provider。デバッグ・監査用。

- **VIEW の閾値**  
  「まずはSQL固定でOK」に合わせ、v_rating_alerts では閾値を SQL 内にリテラルで記載する（4.2 / -0.2 / 10）。  
  将来、Cloud Run からパラメータ渡しや env 連携に変更する場合は VIEW をパラメータ化または別テーブル参照に変更可能。

- **ヘルスチェック**  
  deploy 後の確認用に、POST / とは別に **GET /health** を用意し、200 を返す。  
  deploy.yml のヘルスチェックは GET /health を呼ぶようにする。

- **SQL のデータセット名**  
  001/002/010 の SQL では **YOUR_DATASET** をプレースホルダとして使用。  
  適用時は手動置換または `sed "s/YOUR_DATASET/${BQ_DATASET}/g"` で BQ_DATASET に置換する。README の「SQL適用手順」に記載。

- **GBP（Google）取得元**  
  rating / review_count / レビュー明細は、**Google Business Profile API（GBP）** の **locations.reviews.list** で取得する。  
  レスポンスの `averageRating` / `totalReviewCount` および `reviews[]` を利用し、Place Details は使用しない。  
  認証は OAuth（B 案: リフレッシュトークンを Secret Manager に保存）をまずサポートし、A 案（ドメインワイド委任）は可能であれば後から差し替え可能なインターフェースにする。

- **LATEST の rating_count**  
  #6 の「LATEST列」の rating_count は、本文の「review_count」と同一（レビュー件数）とする。

## Google（GBP）取得元と認証方式の確定
- 取得元（Google）は **Google Business Profile API（GBP）** を正とする。
  - 目的が「全店舗のレビュー/評価の定点観測（自社管理店舗）」であるため。
  - Places API（Place Details）は本スコープでは使用しない（使用する場合はAPIキー運用となり認証・課金・取得項目が別設計になるため）。
- 認証方式は **OAuth 2.0（リフレッシュトークン）** を採用する。
  - リフレッシュトークン等の機密情報は Secret Manager に保存し、Cloud Run 実行時に取得する。
- places_provider_map の provider_place_id には、Googleの場合 **GBP location の resource name（locationリソース識別子）** を格納する。
  - 例：accounts/{accountId}/locations/{locationId}
  - これにより reviews/list 等のGBP API呼び出しでそのまま利用できる。

## しきい値の“正”
- ALERTしきい値は当面 **BigQuery VIEW のSQLリテラル固定** を正とする（4.2 / -0.2 / 10）。
- Cloud Run の環境変数に同名しきい値を残す場合は「将来の外部化用（現状はSQLが正）」とREADMEに明記する。

# 3. BigQuery スキーマ（選択肢1 provider列で1本化）
/sql/001_create_tables.sql に以下を作成（YOUR_DATASETは env BQ_DATASET に置換しやすく）。カラム・partition/cluster は 0.2 で確定した定義に従う：
- places_provider_map
- ratings_daily_snapshot
- reviews
- raw_provider_payloads

# 4. BigQuery VIEW（差分計算はBQ側）
/sql/002_create_views.sql に以下を作成：
- v_latest_with_delta（Asia/Tokyoで当日と前日をJOIN、delta算出）
- v_rating_alerts（閾値の正は 0.2 の「しきい値の"正"」に従う。SQL リテラルが正、env は将来用。まずは SQL 固定で OK）

# 5. 処理フロー（Cloud Run /src/main.py）
HTTP endpoint: POST /
- ingest_run_id = UUID
- snapshot_date = CURRENT_DATE("Asia/Tokyo")
- places_provider_map から provider='google' AND is_active=true を取得
- GBPからratingとreview_count取得、レビュー明細（新規分のみ）取得
- raw_provider_payloads 保存（endpointごと）
- ratings_daily_snapshot にMERGE（キー：snapshot_date, store_code, provider）
- reviews はprovider_review_idで重複排除INSERT（可能ならMERGE）
- BigQueryの v_latest_with_delta をSELECT→SheetsのLATEST全置換
- v_rating_alerts をSELECT→SheetsのALERT全置換
- summary JSONで返す（成功/失敗/実行ID）

エラー処理：
- 店舗単位で status='error' のスナップショットを残し、全体は200で返す（Scheduler停止回避）
- 例外はログに残す（構造化ログ）

並列化：
- ThreadPoolExecutorで並列化しつつMAX_WORKERSで制御
- 429/5xxは指数バックオフでリトライ（回数少なめ）

# 6. Sheets更新（/src/sheets_writer.py）
- batchUpdate/values.updateで全置換
- ヘッダ固定、2行目以降更新
- LATEST列：snapshot_date, store_code, provider, rating_value, rating_count, delta_rating, delta_review_count, fetched_at, status
- ALERT列：snapshot_date, store_code, provider, alert_type, rating_value, delta_rating, delta_review_count

# 7. workflow（CI/CD）を構築（重要）
## 7.1 CI（.github/workflows/ci.yml）
- Python 3.11（または3.10）で実行
- ruff（lint）、pytest（テスト）を実行
- main以外のPRでも動く
- 依存はpipでrequirements.txtからインストール

## 7.2 Deploy（.github/workflows/deploy.yml）
- トリガー：mainブランチへのpush（または tag v*）
- 認証：GitHub Actions → GCPは Workload Identity Federation（推奨）
  - サービスアカウント impersonation で gcloud/Artifact Registry/Cloud Run デプロイ
  - もしくは短期的にはGCP SAキーJSONをGitHub Secretsに置く方法も可（ただし最終的にはWIFへ移行しやすい設計）
- デプロイ方法：
  - Docker build → Artifact Registryへpush → gcloud run deploy
- Cloud Run service名、リージョンは env か workflow inputs で設定可能に
  例：SERVICE_NAME=review-observation, REGION=asia-northeast1
- デプロイ後に / をヘルスチェック（GETで200）※POSTは実行になるのでGET /health などを用意

## 7.3 追加の運用ファイル
- /infra/gcloud_commands.md に
  - Artifact Registry作成
  - Cloud Run service作成/更新
  - Scheduler作成（OIDCでRun呼び出し）
  - Secret Manager作成・権限付与
  - Sheets共有手順
  をコマンドで記載

# 8. README
- 事前準備（API有効化：BigQuery, Sheets, Cloud Run, Scheduler, Secret Manager, Artifact Registry）
- IAM（Cloud Run実行SA, Schedulerの呼び出し、Secret access）
- ローカル実行（adc or SAキー、環境変数）
- SQL適用手順
- GitHub Actionsでのデプロイ手順（WIF推奨、暫定キー方式も）
- トラブルシュート（429, auth, quota）

# 9. 実装の優先順位
1) SQL（テーブル＋VIEW）
2) Cloud Run最小実装（ダミーでsnapshot→view→sheets更新）
3) GBP API接続
4) reviews保存
5) 並列化・リトライ・エラーハンドリング

上記を満たす、動く最小システムとして実装してください。
まずはコード一式、SQL、workflow（ci/deploy）、infra手順、READMEを生成してください。

---
# 13. 追加：GBPパフォーマンス指標（ユーザ数/電話/ルート/Web）の日次・月次取得

## 13.1 方針（SSOT更新）
- 既存の「レビュー/評価（ratings_daily_snapshot / reviews）」とは別に、GBPのパフォーマンス指標を **日次・月次** で取得し、BigQueryに履歴保存する。
- 「ユーザ数」は厳密なユニークユーザーではなく、GBP側で提供される **表示回数（impressions / views）** をSSOT上の“ユーザ数相当”として扱う（指標名は実装でGBPの正式メトリクス名に合わせる）。
- 電話/ルート/Webサイトは「行動数（calls / direction requests / website clicks）」として保持する。

## 13.2 追加テーブル（SSOT）

### 13.2.1 performance_daily_snapshot（新規）
- 目的：日次パフォーマンス（閲覧・アクション）を店舗×日で蓄積

**カラム**
- snapshot_date（DATE, Asia/Tokyo日付）※PARTITION
- store_code（STRING）
- provider（STRING）※当面 'google'
- provider_place_id（STRING）※GBP location resource name
- impressions（INT64）※ユーザ数相当（表示回数）
- calls（INT64）※電話
- direction_requests（INT64）※ルート検索（経路）
- website_clicks（INT64）※Webサイト
- fetched_at（TIMESTAMP）
- ingest_run_id（STRING）
- status（STRING：ok/error）
- error_code（STRING, NULL可）
- error_message（STRING, NULL可）

**PARTITION / CLUSTER**
- PARTITION BY snapshot_date
- CLUSTER BY store_code, provider

**冪等キー**
- snapshot_date + store_code + provider

### 13.2.2 performance_monthly_snapshot（新規）
- 目的：月次パフォーマンスを店舗×月で蓄積（期間集計）

**カラム**
- snapshot_month（DATE：月初日を採用）※PARTITION
- store_code（STRING）
- provider（STRING）※当面 'google'
- provider_place_id（STRING）
- impressions（INT64）
- calls（INT64）
- direction_requests（INT64）
- website_clicks（INT64）
- fetched_at（TIMESTAMP）
- ingest_run_id（STRING）
- status（STRING：ok/error）
- error_code（STRING, NULL可）
- error_message（STRING, NULL可）

**PARTITION / CLUSTER**
- PARTITION BY snapshot_month
- CLUSTER BY store_code, provider

**冪等キー**
- snapshot_month + store_code + provider

## 13.3 取得頻度（バッチ）
- 日次：毎日 09:00 JST（既存スケジュールに同梱して実行）
- 月次：毎月 1日 09:00 JST（Schedulerを追加、または日次ジョブ内で「月初のみ」実行）

## 13.4 Sheets出力（当面の方針）
- 既存方針どおり Sheets は LATEST/ALERT のみ更新。
- LATESTに「当日分の impressions/calls/direction_requests/website_clicks」を追加するかは運用要件が固まり次第（初期はBQのみでOK）。

## 13.5 CSV出力（追加要件の拡張）
- 10章のCSV出力に、以下を追加：
  - performance_daily_snapshot（当日分）→ GCSへCSV
  - performance_monthly_snapshot（当月分 or 前月分）→ GCSへCSV

---
# 14. 実装順（追加分の反映）

## Phase 2.5：GBPパフォーマンス連携（追加）
- performance_daily_snapshot / performance_monthly_snapshot のDDLを追加（sql/001_create_tables.sql）
- GBPパフォーマンスAPI（またはreportInsights相当）から日次・月次指標を取得し、MERGEで格納
- 既存のCSV出力に performance_* を追加
