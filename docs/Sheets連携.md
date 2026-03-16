# Sheets 連携（ダッシュボード用）

スプレッドシートでレビュー集計を可視化する方法は **2 通り** あります。

| 方式 | 説明 |
|------|------|
| **A. アプリが書き込む** | `POST /` 実行後に BQ の VIEW を読んで、LATEST / ALERT / サマリ タブを**上書き**する（§1 以降）。SHEET_ID と実行 SA の共有が必要。 |
| **B. スプレッドシートから BQ を参照** | **Connected Sheets** で BQ の VIEW を直接参照する。アプリの書き込みは不要。BQ に権限がある人なら誰でも設定可能。 |

BQ にすでにデータが入っている場合は **方式 B** がおすすめです（SHEET_ID 不要・権限は BQ のみ・更新は「データの更新」で反映）。

---

## 方式 B: スプレッドシートから BigQuery を直接参照する（Connected Sheets）

BQ の VIEW をスプレッドシートに「接続」し、同じスプレッドシート上でピボット・グラフ・フィルタが使えます。データの更新は手動またはスケジュールで行えます。

### プロジェクトとデータの所在（重要）

| 役割 | プロジェクト ID | 説明 |
|------|-----------------|------|
| **BigQuery のデータ**（VIEW・テーブル） | **ikeuchi-ga4** | レビューデータ・`mart_gbp` はここにある。Connected Sheets では **このプロジェクトを選ぶ**。 |
| Cloud Run / Scheduler / Secret | ikeuchi-data-sync | アプリの実行基盤。**BQ の mart_gbp はこのプロジェクトにはない**。 |

- **ikeuchi-data-sync** を選ぶと、データセット一覧に `mart_gbp` は出てきません（データは ikeuchi-ga4 側にあります）。
- プロジェクト一覧に **ikeuchi-ga4** が出てこない場合は、**接続に使っている Google アカウント**に ikeuchi-ga4 の BigQuery 閲覧権限が付与されていません。GCP のオーナー／管理者に「BigQuery データ閲覧者」などのロールを ikeuchi-ga4 で付与してもらってください。

### 手順（要約）

1. **Google スプレッドシート**を開く（新規でも既存でも可）。
2. メニュー **「データ」** → **「データ コネクタ」** → **「BigQuery に接続」**（または **「接続」** → **「BigQuery に接続」**。UI により文言が異なります）。
3. **プロジェクトを選択**: **`ikeuchi-ga4`**（レビューデータが入っている BQ プロジェクト。`ikeuchi-data-sync` ではない）。
4. **データセット**: `mart_gbp`。一覧に無い場合は上記「プロジェクトとデータの所在」を確認し、ikeuchi-ga4 を選んでいるか・権限があるかを見直す。
5. **テーブル or ビュー**（**推奨は下記「直近用」**）:
   - **v_latest_available_ratings** … **直近の取込日**の評価・レビュー数・前日比（取込が今日でなくても値が出る）
   - **v_latest_available_alerts** … 上記と同じ日付ベースのアラート
   - ※ v_latest_with_delta_ratings / v_rating_alerts は **「今日」の取込**があるときだけ行が返ります。今日まだ取込していないと 0 件になります。
6. 「接続」または「インポート」で、シートに BQ の結果が表示される。
7. 必要に応じて **「データの更新」**（手動）や **更新スケジュール** を設定（[ヘルプ: データの更新](https://support.google.com/docs/answer/9703214)）。

### 注意

- Connected Sheets を使う **ユーザー**が、**ikeuchi-ga4** の BigQuery に対する **閲覧権限**（例: BigQuery データ閲覧者）を持っている必要があります。
- アプリで **SHEET_ID を設定していない**場合は、取込処理は BQ への MERGE のみ行い、Sheets への書き込みはスキップされます。方式 B のみ使う場合は SHEET_ID は不要です。

### 接続したのに値が表示されないとき

- **方式 A（アプリが書き込む）**: アプリは **v_latest_available_ratings** / **v_latest_available_alerts** を参照するため、直近 1 回でも取込が成功していれば値が出る。0 件の場合は (1) 上記 VIEW が BQ に存在するか（`sql/002b_views_latest_available.sql` を mart_gbp で適用）、(2) `ratings_daily_snapshot` に 1 日分以上のデータがあるかを確認する。
- **方式 B（Connected Sheets）**: 参照先が **v_latest_available_ratings** / **v_latest_available_alerts** になっているか確認し、「データの更新」を実行する。

### store_name がスプレッドシートに出力されないとき（方式 A）

**原因**: BigQuery の **v_latest_available_ratings** / **v_latest_available_alerts** が、**store_name 列を含む定義**で作成されていない（古い VIEW のまま、または VIEW が未作成）。

**対処**:

1. **VIEW を再作成する**（`ikeuchi-ga4.mart_gbp` で実行）:
   - `sql/002b_views_latest_available.sql` を開き、**YOUR_DATASET** を **mart_gbp** に置換する。
   - BigQuery コンソールまたは `bq query --project_id=ikeuchi-ga4 --location=asia-northeast1 --use_legacy_sql=false` で、**上から 2 つの CREATE OR REPLACE VIEW** を 1 文ずつ実行する。
   - これで `v_latest_available_ratings` と `v_latest_available_alerts` に **store_name**（＝ `places_provider_map.display_name`）が含まれる。
2. **取込を 1 回実行**してシートを再書き込みする（Scheduler の手動実行または翌時実行で反映）。

**補足**: `places_provider_map` の **display_name** が空の店舗は、store_name が空文字で出力される。店舗名を出したい場合は `sql/040_insert_places_provider_map.sql` や UPDATE で display_name を設定する。

**取込がタイムアウトしてシートが更新されない場合**: 取込（POST /）が 30 分で切れると、Sheets 更新まで到達せず store_name も出ない。そのときは **POST /sheets-update** を 1 回呼ぶと、取込なしで BQ の直近データから LATEST / ALERT / サマリ（store_name 含む）だけを書き直せる。手動実行は [infra/gcloud_commands.md §10.5b](../infra/gcloud_commands.md) の curl または Scheduler ジョブ `review-observation-sheets-update` で行える。

### 全件表示されない・「500件しか表示されない」と表示されるとき（方式 B）

**原因**: Connected Sheets で BQ データを「抽出」（Extract）して表示する場合、**取得行数**の初期値や上限が 500 行になっていることがあります（接続作成時のプレビューや設定による）。

**対処**（全件表示したい場合）:

1. スプレッドシートで、該当する **BigQuery 接続** を開く（右サイドバー「データ コネクタ」や、シート左下の接続名をクリック）。
2. **「データの取得」** または **「抽出」** の設定で、**行数**（Number of rows / 取得する行数）を確認する。
3. 500 より大きい値に変更する。最大は **500,000 行**（データ 10 MB 以下かつ 500 万セル以下という制限あり）。UI によっては一覧に 100,000 までしか出ない場合がありますが、**入力欄に直接「100000」や「500000」と入力**すると設定できることがあります。
4. **「適用」** または **「データの更新」** で再取得する。

- 参照: [Analyze & refresh BigQuery data in Google Sheets (Connected Sheets)](https://support.google.com/docs/answer/9703214) — "Pull data into an extract" で最大 500k 行と記載。
- **方式 A**（アプリが LATEST / ALERT タブに書き込む）の場合は、アプリが BQ の VIEW の**全行**を取得してから書き込むため、行数制限はアプリ側にはありません（店舗数＝数十行程度）。「500 件」と出るのは Connected Sheets で BQ を直接参照しているときの設定です。

### LATEST / ALERT に値が入っていない（方式 A）

**主な原因**:

1. **SHEET_ID が Cloud Run に渡っていない**  
   デプロイ時に GitHub Secrets の **SHEET_ID** が未設定または空だと、Cloud Run の環境変数に SHEET_ID が入らず、アプリは Sheets を更新しません（取込は成功してもシートは空のまま）。  
   **対処**: GitHub リポジトリの **Settings → Secrets and variables → Actions** で **SHEET_ID** を追加する（値はスプレッドシート URL の `https://docs.google.com/spreadsheets/d/<ここがID>/edit` の部分）。保存後、**main に push するか「Deploy to Cloud Run」ワークフローを手動実行**して再デプロイする。
2. **スプレッドシートが Cloud Run の SA と共有されていない**  
   **対処**: スプレッドシートの「共有」に **sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com** を **編集者** で追加する（[§3 実行 SA への共有](#3-実行-sa-への共有) 参照）。
3. **タブ名が一致していない**  
   デフォルトは **LATEST**・**ALERT**・**サマリ**（半角）。別名の場合は環境変数 `SHEET_TAB_LATEST` / `SHEET_TAB_ALERT` / `SHEET_TAB_SUMMARY` で合わせる。

**確認**: Cloud Run のログで `[review_observation] Sheets skip: SHEET_ID not set` が出ていれば 1、Sheets API の 403 などが出ていれば 2 を疑う。設定後は **POST /sheets-update** を 1 回実行すると即時反映される（[infra §10.5b](../infra/gcloud_commands.md)）。

4. **GCP プロジェクトで Google Sheets API が有効になっていない**  
   Cloud Run を動かしているプロジェクト（**ikeuchi-data-sync**）で **Google Sheets API** を有効にしてください。未有効だと `SERVICE_DISABLED` / 500 になります。  
   **対処**: [Google Sheets API 有効化](https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=957418534824) を開き「有効にする」をクリック。有効化から数分かかることがあります。

5. **BigQuery の VIEW が 0 件**  
   アプリは **ikeuchi-ga4.mart_gbp** の `v_latest_available_ratings` / `v_latest_available_alerts` を参照します。Cloud Run の実行 SA（`sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com`）に **ikeuchi-ga4 の BigQuery データ閲覧権限**（例: プロジェクトまたはデータセットの `roles/bigquery.dataViewer`）がないとクエリが失敗します。権限はあるが **ratings_daily_snapshot にデータが 1 件もない**場合も VIEW は 0 件になり、LATEST/ALERT にはヘッダー行だけ書かれます。  
   **確認**: 取込または **POST /sheets-update** 実行後、Cloud Run ログに `Sheets: LATEST=N rows, ALERT=M rows (from BQ)` と出ます。N が 1（ヘッダーのみ）なら VIEW が 0 件です。BigQuery コンソールで `SELECT COUNT(*) FROM \`ikeuchi-ga4.mart_gbp.ratings_daily_snapshot\`` を実行 SA と同じ権限で試すか、先に 1 回 **POST /**（取込）を成功させてから **POST /sheets-update** を試してください。

※ 原因 4 の「Sheets API が未有効」のときは、有効化後に **POST /sheets-update** を再実行すれば LATEST/ALERT に書き込まれます。

### reviews テーブルが「500件のプレビューのみ」と表示されるとき

**原因**: BigQuery コンソールの**テーブルプレビュー**は、デフォルトで **500 行**までしか表示しません。テーブル本体のデータは全件保存されているため、**500 件で打ち切られているわけではありません**。

**確認**: 全件数は次のクエリで確認できる。  
`SELECT COUNT(*) FROM \`ikeuchi-ga4.mart_gbp.reviews\``  
全行を参照したい場合は、上記のような **クエリを実行**するか、Connected Sheets で reviews を参照している場合は「取得行数」を 500 より大きく設定する（[全件表示されない・500件](#全件表示されない500件しか表示されないと表示されるとき方式-b) 参照）。

---

## 1. 前提（方式 A: アプリが書き込む場合）

- BigQuery に **v_latest_available_ratings** と **v_latest_available_alerts** の VIEW が作成済みであること（`sql/002b_views_latest_available.sql` を YOUR_DATASET → mart_gbp に置換して適用。あわせて `sql/002_create_views.sql` で v_latest_with_delta_ratings 等も作成可）。
- アプリは **直近の取込日** を表示する上記 VIEW を参照するため、当日の取込がなくてもシートに値が出る。
- Cloud Run の実行サービスアカウント（`sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com`）で Sheets API にアクセスするため、**スプレッドシートをこの SA に共有**する必要があります。

---

## 2. スプレッドシートの準備（方式 A の場合）

1. 新規または既存の Google スプレッドシートを開く。
2. **LATEST**・**ALERT**・**サマリ** の 3 つのシート（タブ）を用意する。  
   - 既存タブ名を変えたい場合は、環境変数 `SHEET_TAB_LATEST` / `SHEET_TAB_ALERT` / `SHEET_TAB_SUMMARY` で指定可能（デフォルトは `LATEST` / `ALERT` / `サマリ`）。
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
| SHEET_TAB_SUMMARY | サマリ用のタブ名 | 任意（既定: サマリ） |

- **SHEET_ID** が空または未設定のときは、Sheets 更新はスキップされ、取込処理のみ実行されます。
- ローカル実行時は `export SHEET_ID=...` で設定。Cloud Run では deploy.yml が `secrets.SHEET_ID` を注入します。

---

## 5. 出力内容

### LATEST タブ

- **元データ**: BigQuery VIEW `v_latest_available_ratings`（直近の取込日の ratings_daily_snapshot ＋ 前日比）。当日の取込がなくても値が出る。
- **列**: snapshot_date, store_code, provider, provider_place_id, rating_value, review_count, fetched_at, ingest_run_id, status, delta_rating, delta_review_count.

### ALERT タブ

- **元データ**: BigQuery VIEW `v_latest_available_alerts`（閾値でフィルタした行。直近取込日ベース）。
- **列**: snapshot_date, store_code, store_name, provider, alert_type, rating_value, delta_rating, delta_review_count.
- **alert_type** の種類と条件:
  - **low_rating**: 現在の評価が **4.2 未満**（前日データ不要）
  - **rating_drop**: 前日比が **-0.2 以下**（＝評価が 0.2 以上下がった）
  - **review_surge**: 前日比レビュー数が **+10 以上**

閾値は VIEW 定義（`sql/002b_views_latest_available.sql` の v_latest_available_alerts）で変更できます。

#### なぜ low_rating だけ出るのか（前日データがないとき）

**直近の取込日が 1 日分しかない**（前日の `ratings_daily_snapshot` が無い）場合、**delta_rating** と **delta_review_count** は NULL になります（今日 − 昨日 を計算するため、昨日が無いと NULL）。

- **low_rating** は「今の評価 &lt; 4.2」だけを見るため、**前日が無くても**該当店舗は出ます。
- **rating_drop** は「delta_rating ≤ -0.2」なので、delta_rating が NULL の行は条件に含まれません（SQL で NULL との比較は TRUE にならない）。
- **review_surge** も「delta_review_count ≥ 10」のため、NULL の行は出ません。

そのため、**取込を始めたばかりで 1 日分のデータしかないときは、ALERT には low_rating だけ**が並び、delta_rating・delta_review_count は空になります。**2 日分以上の取込が溜まると**、rating_drop や review_surge も条件を満たした店舗だけ出るようになります。

### サマリタブ

- **内容**: 更新日・店舗数・平均評価・総レビュー数、およびアラート種別ごとの件数。
- **用途**: 一覧で KPI を確認し、グラフの見出しやレポート用に使う。

---

## 6. スプレッドシートで可視化する

LATEST とサマリのデータを使って、シート上でグラフや条件付き書式を設定できます。

### 6.1 グラフの作成

1. **店舗別の評価（★）**: LATEST タブで **store_code**（B列）と **rating_value**（E列）を選択 → **挿入** → **グラフ** → **縦棒グラフ**。店舗ごとの評価が比較できる。
2. **店舗別のレビュー数**: 同様に **store_code**（B列）と **review_count**（F列）を選択して縦棒グラフを作成。
3. **前日比（評価）**: **store_code**（B列）と **delta_rating**（J列）を選択 → 縦棒グラフ（プラス・マイナスが一目で分かる）。
4. **サマリの数値だけ表示**: サマリタブはそのままダッシュボードの「見出し」として表示し、必要に応じてセルを大きくしたりフォントを変更する。

### 6.2 条件付き書式（例）

- **LATEST** の **rating_value** 列: 4.2 未満を赤、4.5 以上を緑など、色ルールを設定すると低評価店舗が目立つ。
- **delta_rating** 列: 0 未満を赤、0.2 以上を緑にすると「★が下がった／上がった」が分かりやすい。

### 6.3 注意

- アプリは **データの上書きのみ** 行います。グラフや条件付き書式は **手動で 1 回設定** すると、以降の更新でもデータ範囲が同じであればそのまま維持されます（タブ全体をクリアしてから書き込むため、グラフのデータ範囲が「LATEST!B2:E32」のように固定範囲の場合は、行数が増減すると要再調整）。

---

## 7. 動作確認

1. `SHEET_ID` を設定して `POST /` を実行（手動 curl または Scheduler）。
2. レスポンスの `"sheets_updated": true` で Sheets 更新が成功したことを確認。
3. スプレッドシートの LATEST / ALERT / サマリ タブに、上記の列・集計でデータが入っていることを確認。

Sheets 更新で例外が発生した場合は、取込は 200 のまま完了し、`sheets_updated` は `false` になります。ログに `[review_observation] Sheets update failed: ...` とスタックトレースが出力されます。

---

## 値が入らないときの確認（トラブルシューティング）

1. **SHEET_ID が設定されているか**
   - ローカル: `echo $SHEET_ID` で値が出るか確認。未設定なら `export SHEET_ID=スプレッドシートのID`（URL の `https://docs.google.com/spreadsheets/d/` と `/edit` のあいだ）。
   - Cloud Run: GitHub Secrets に `SHEET_ID` を登録し、デプロイ後に Cloud Run の「変数とシークレット」で `SHEET_ID` が渡っているか確認。
   - 未設定のときはログに `Sheets skip: SHEET_ID not set` と出ます。

2. **実行サービスアカウント（SA）を共有しているか**
   - スプレッドシートの「共有」に **編集者** で次のメールを追加しているか確認:  
     `sa-review-observation-run@ikeuchi-data-sync.iam.gserviceaccount.com`
   - 共有していないと 403 などで `Sheets update failed` になります。

3. **レスポンスの `sheets_updated`**
   - POST / の JSON で `"sheets_updated": true` なら書き込みは成功しています。`false` のときは上記 1・2 またはタブ名の誤りを確認。

4. **タブは自動作成される**
   - LATEST / ALERT / サマリ のいずれかが無い場合、アプリが自動作成してから書き込みます。手動でタブを作る必要はありません（既存タブ名を変えている場合は環境変数 `SHEET_TAB_*` を合わせてください）。
