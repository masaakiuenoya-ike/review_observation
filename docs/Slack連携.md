# Slack 連携（Webhook の方法）

review_observation は **Slack Incoming Webhooks** で次のタイミングで通知を送ります。

- **取込後（POST /）**: アラート・★1/★5 件数・評価アップ店舗のサマリ
- **日次（POST /daily-summary）**: 各店舗の評価・前日比（Scheduler で毎日 09:15 JST）

Webhook URL を設定しない場合は通知はスキップされ、エラーにはなりません。

---

## 1. Slack で Incoming Webhook を作る

### 「Create an app」でどちらを選ぶか

Slack の **Create an app** 画面で **「From scratch」** を選んでください。  
（Incoming Webhook だけ使う場合はマニフェスト不要で、画面から設定する方が簡単です。）

### 手順（From scratch の場合）

1. **From scratch** を選択する。
2. **App Name** を入力（例: `review_observation`）、**Pick a workspace** でワークスペースを選び **Create App** する。
3. 左メニュー **Incoming Webhooks** を開き、**Activate Incoming Webhooks** を **On** にする。
4. 同じページで **Add New Webhook to Workspace** をクリックし、**通知を送りたいチャンネル**（例: `#gbp-reviews`）を選んで **許可** する。
5. 表示された **Webhook URL** をコピーする。  
   形式: `https://hooks.slack.com/services/（チームID）/（ボットID）/（トークン）`（実際の値は Slack が表示する長い文字列です）

### 別の入口（Incoming Webhooks ページから）

[Incoming Webhooks](https://api.slack.com/messaging/webhooks) のページから **「Add to Slack」** を押す方法もあります。その場合は上記の「Create an app」画面は経由せず、チャンネルを選ぶとすぐ Webhook URL が発行されます。

### App Credentials は不要です

**Client ID / Client Secret / Signing Secret**（App Credentials ページに表示されるもの）は、review_observation では **使いません**。通知送信には **Incoming Webhook URL** だけが必要です。GitHub Secrets や Cloud Run に登録するのも **Webhook URL のみ**で十分です。

- **誤って Credentials を共有・コミットした場合**: Slack の App Credentials ページで **Regenerate** を実行し、Client Secret と Signing Secret を再発行してください。旧い値は無効になります。

---

## 2. URL を Cloud Run に渡す（GitHub Secrets）

デプロイ時に Cloud Run の環境変数へ渡すため、**GitHub のリポジトリ**で次のように設定します。

1. リポジトリの **Settings** → **Secrets and variables** → **Actions** を開く。
2. **New repository secret** をクリック。
3. **Name**: `SLACK_WEBHOOK_URL`  
   **Secret**: コピーした Webhook URL（`https://hooks.slack.com/...`）をそのまま貼る。
4. **Add secret** で保存する。

次回の **main への push**（または手動の「Deploy to Cloud Run」ワークフロー実行）で、Cloud Run に `SLACK_WEBHOOK_URL` が渡り、取込後と日次サマリの両方でその URL に POST されます。

- 既にデプロイ済みの場合は、**main に空コミットで push** するか、**Actions タブから「Deploy to Cloud Run」を手動実行**すると、新しい Secret が反映されます。
- Secret を削除したり空にすると、次回デプロイ以降は Slack 通知は送られません（アプリは `SLACK_WEBHOOK_URL` が未設定なら送信をスキップします）。
- **デプロイが Secrets を渡しているか確認**: GitHub Actions の「Deploy to Cloud Run」実行ログで「Deploy to Cloud Run」ステップを開き、`SLACK_WEBHOOK_URL is set: yes` と出ていればリポジトリの Secret はジョブに渡っています。`no` の場合は Secret 名の typo や、フォークから実行している（Secrets は上流リポジトリにしかない）可能性があります。

---

## 3. 送信内容の概要

| タイミング | 内容 |
|------------|------|
| **取込後（POST /）** | 直近取込日のアラート一覧、★1/★5 件数、評価が上がった店舗。 |
| **日次（POST /daily-summary）** | 直近取込データに基づく各店舗の評価・前日比。Scheduler で毎日 09:15 JST に実行。 |

いずれも BQ の **v_latest_available_ratings** / **v_latest_available_alerts** を参照し、Slack Block Kit 形式でメッセージを組み立てて Webhook URL に **POST** しています。

---

## 4. トラブルシュート

- **通知が届かない**
  - **POST /daily-summary のレスポンス**を確認する。`{"message":"skipped (SLACK_WEBHOOK_URL not set)"}` の場合は **Webhook が Cloud Run に渡っていない**。GitHub Secrets に `SLACK_WEBHOOK_URL` を設定し、**再デプロイ**（push または Actions から手動実行）する。
  - GitHub Secrets に `SLACK_WEBHOOK_URL` が登録されているか確認する。
  - デプロイ後に Cloud Run の「リビジョン」→ 環境変数に `SLACK_WEBHOOK_URL` が存在するか確認する（値はマスクされます）。CLI では `gcloud run services describe review-observation --region=asia-northeast1 --format="yaml(spec.template.spec.containers[0].env)"` で名前の一覧を確認できる。
  - Cloud Run のログで `SLACK_WEBHOOK_URL not set` や `Slack daily summary failed` が出ていないか確認する。
  - Webhook 作成時に選んだ **チャンネル** と、通知を確認しているチャンネルが同じか確認する。
- **なぜ昨日は成功したのか（本質）**  
  - **理由 1（ウォーム）**: デプロイ直後に実行したため、**コンテナがまだ起動したまま**でコールドスタートがなかった。十数秒で 200 が返りやすい。
  - **理由 2（コマンドの違い）**: 200 を返すには**認証も通る**必要がある。Cloud Run はトークンの **audience（対象サービス URL）** を検証する。**`gcloud auth print-identity-token` に `--audiences="$URL"` を付けない**と Cloud Run がトークンを拒否し、**HTTP 000 や 403** になる。過去のドキュメントや deploy の「手動確認」メッセージには **--audiences が書かれていなかった**ため、そのコマンドをそのまま使うと今日は 000 になる。昨日、Scheduler の「ジョブを実行」や Console のテストで実行していた場合は、正しいトークンが付くので成功する。**手動で curl するときは必ず `TOKEN=$(gcloud auth print-identity-token --audiences="$URL")` を使う**（[infra/gcloud_commands.md §10.4c](../infra/gcloud_commands.md) 参照）。

- **「取込ジョブが動いているのに、なぜ 09:15 はコールドなのか」**  
  取込（`POST /`）は **2 時間おき・店舗直列**では **数分〜数十分以上**かかることもある。終了後、次の取込まで**最大約 2 時間**は別のリクエストが来ない時間帯がある。Cloud Run は無負荷が 15〜30 分続くとインスタンスを 0 にしやすいため、09:15 の daily-summary がコールドで当たり、起動に時間がかかって 000（クライアント側タイムアウト）になりやすい。**09:10 のウォームアップ（GET /health）**や **min-instances=1** の意味は変わらない。

- **GET /health・/daily-summary が 504（ログで hourly と同時刻）**  
  **Gunicorn のワーカーが 1 本**だと、長時間の **POST /（取込）** がそのワーカーを占有し、09:10 のウォームアップや 09:15 の日次が**キューで待ち続け** Cloud Run が **504** を返す。アプリは **Dockerfile で `--workers 2` 以上**にする（本リポジトリで恒久対応）。詳細は [infra/gcloud_commands.md §10.9](../infra/gcloud_commands.md) の表を参照。

- **手動で POST /daily-summary を叩いて HTTP: 000 になる場合（Cloud Shell からも同じとき）**
  - **000** は「サーバから 1 バイトも受け取れなかった」状態。
  - **対処 1: 認証（invoker ＋ トークン）とタイムアウト**  
    - **run.invoker**: 手動実行するユーザーに Cloud Run の呼び出し権限が必要。未付与だと 000/403 になりやすい。
    - **トークン**: 過去の成功例では手元で **`gcloud auth print-identity-token`（--audiences なし）** で 200。環境により `--audiences="$URL"` が必要な場合あり。000 なら `TOKEN=$(gcloud auth print-identity-token --audiences="$URL")` を試す。
    - **ポーリング**: 200 が返るまでリトライする `scripts/run_daily_summary_manual.sh` を推奨。curl の `--max-time` は 600（10 分）推奨。
    ```bash
    URL=$(gcloud run services describe review-observation --region=asia-northeast1 --format='value(status.url)')
    TOKEN=$(gcloud auth print-identity-token)
    curl -s -w "\nHTTP: %{http_code}\n" --max-time 600 -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' "$URL/daily-summary"
    ```
  - **対処 2: ログで「リクエストが届いているか」を確認（CLI）**  
    curl を実行した**直後**に、Cloud Run のログに **`POST /daily-summary started`** が出ているか確認する。出ていればリクエストはコンテナまで届いている（＝起動はできている）。出ていなければ、接続がコンテナに届く前に切れているか、コールドスタートがまだ完了していない。
    ```bash
    gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="review-observation"' \
      --project=ikeuchi-data-sync --limit=30 --format="table(timestamp,textPayload)" --freshness=10m
    ```
  - **対処 3: GET /health でウォームアップしてから POST（手動実行の標準手順）**  
    手動で本日分を送る場合は **必ず先に GET /health**（60〜120 秒タイムアウト）を実行し、続けて POST /daily-summary（600 秒）を叩く。コマンドは [infra/gcloud_commands.md §10.4c](../infra/gcloud_commands.md) の「手動で Slack 日次サマリを送る」を参照。
  - **対処 4: 常時 1 インスタンス（min-instances=1）**  
    コールドスタートをなくす。料金は増える。
    ```bash
    gcloud run services update review-observation --region=asia-northeast1 --min-instances=1
    ```
  - **恒久対策の選択肢**  
    - **推奨**: 毎日 **09:10** に **GET /health の Scheduler ジョブ**（`review-observation-daily-slack-warmup`）を追加する。09:15 の daily-slack がウォームで受けられる。作成手順は [infra/gcloud_commands.md §10.4c](../infra/gcloud_commands.md) を参照。  
    - **確実にしたい**: **min-instances=1**（対処 4）で常時 1 インスタンス維持。  
    - **手動実行時**: 必ず **ウォームアップ（GET /health）のあと** POST /daily-summary を実行し、curl は **--max-time 600** で叩く。
- **Webhook URL を変えたい**
  - GitHub Secrets の `SLACK_WEBHOOK_URL` を新しい URL に更新し、再度デプロイする。
