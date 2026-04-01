# Slack 通知の設定

## 方針: 通知は 1 日 1 回

- **Slack には 1 日 1 回だけ**送る（毎日 09:15 JST の **日次サマリ** のみ）。
- 取込（POST /）のたびに送っていた **取込サマリ** は送らない。

## 現在の Scheduler と通知の関係

| ジョブ名 | スケジュール | 呼び出し | Slack 通知 |
|----------|--------------|----------|------------|
| review-observation-hourly | 毎時 0 分 | POST / | **送らない**（取込のみ） |
| review-observation-daily | 毎日 09:00 | POST / | **送らない**（取込のみ） |
| review-observation-sheets-update | 毎日 09:10 | POST /sheets-update | なし |
| review-observation-daily-slack-warmup | 毎日 09:10 | GET /health | なし（09:15 用ウォームアップ） |
| **review-observation-daily-slack** | **毎日 09:15** | **POST /daily-summary** | **1 日 1 回ここだけ** |

- 取込（POST /）は hourly や daily で実行されるが、**完了時の Slack 送信は行わない**（main.py で send_slack_notification を呼ばない）。
- 日次サマリ（評価UP/DOWN/変化無・店舗別評価の順位付き）は **daily-slack** が **1 日 1 回** POST /daily-summary を叩くことで送られる。

## 運用の流れ（例）

1. 毎時: **hourly** が POST / で取込 → BQ・Sheets 更新（Slack は送らない）
2. 毎日 09:00: **daily** が POST / で取込（Slack は送らない）
3. 毎日 09:10: **sheets-update** でシートのみ更新。**daily-slack-warmup** で GET /health を実行し 09:15 用にウォームアップ。
4. 毎日 09:15: **daily-slack** が POST /daily-summary → **Slack に 1 回だけ通知**

## 設定の確認コマンド

```bash
gcloud scheduler jobs list --project=ikeuchi-data-sync --location=asia-northeast1 \
  --format="table(name.basename(),schedule,state)" --filter="name:review-observation"
```
