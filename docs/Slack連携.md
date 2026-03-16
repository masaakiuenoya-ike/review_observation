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
  - GitHub Secrets に `SLACK_WEBHOOK_URL` が登録されているか確認する。
  - デプロイ後に Cloud Run の「リビジョン」→ 環境変数に `SLACK_WEBHOOK_URL` が設定されているか確認する（値はマスクされます）。
  - Cloud Run のログで `Slack notification failed` や `daily summary failed` が出ていないか確認する。
- **Webhook URL を変えたい**
  - GitHub Secrets の `SLACK_WEBHOOK_URL` を新しい URL に更新し、再度デプロイする。
