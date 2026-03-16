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

既存の **v_latest_with_delta_ratings** / **v_rating_alerts** は「**今日**（Asia/Tokyo）」の日付で絞っています。今日まだ取込（POST /）を実行していないと、これらの VIEW は **0 行**になり、シートに何も出ません。

**対処**: 直近の取込日を表示する **v_latest_available_ratings** と **v_latest_available_alerts** を BQ に作成し、Connected Sheets ではこちらを参照してください。

1. **VIEW を BQ に作成**: `sql/002b_views_latest_available.sql` を開き **YOUR_DATASET** を **mart_gbp** に置換し、[BigQuery コンソール](https://console.cloud.google.com/bigquery?project=ikeuchi-ga4) で **上から 2 つの CREATE OR REPLACE VIEW** を 1 文ずつ実行する。
2. スプレッドシートの接続で、参照先を **v_latest_available_ratings**（および **v_latest_available_alerts**）に変更し、「データの更新」を実行する。

---

## 1. 前提（方式 A: アプリが書き込む場合）

- BigQuery に **v_latest_with_delta_ratings** と **v_rating_alerts** の VIEW が作成済みであること（`sql/002_create_views.sql` を `mart_gbp` で適用）。
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

- **元データ**: BigQuery VIEW `v_latest_with_delta_ratings`（今日の ratings_daily_snapshot ＋ 前日比）。
- **列**: snapshot_date, store_code, provider, provider_place_id, rating_value, review_count, fetched_at, ingest_run_id, status, delta_rating, delta_review_count.

### ALERT タブ

- **元データ**: BigQuery VIEW `v_rating_alerts`（閾値でフィルタした行）。
- **列**: snapshot_date, store_code, provider, alert_type, rating_value, delta_rating, delta_review_count.
- **alert_type**: `low_rating`（評価 &lt; 4.2）, `rating_drop`（前日比 ≤ -0.2）, `review_surge`（レビュー増加 ≥ 10）。

閾値は VIEW 定義（`sql/002_create_views.sql` の v_rating_alerts）で変更できます。

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
