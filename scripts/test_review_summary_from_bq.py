#!/usr/bin/env python3
"""
BigQuery の reviews から指定した店舗・日時帯の口コミを読み、本番と同じプロンプトで要約（Vertex または API キー）を試す。

前提:
  - 環境変数は本番と同様（REVIEW_SUMMARY_USE_VERTEX_AI, VERTEX_AI_*, GEMINI_API_KEY, GEMINI_MODEL など）
  - Vertex: `gcloud auth application-default login`（またはサービスアカウント）
  - BQ: `BQ_PROJECT`, `BQ_DATASET`（既定: ikeuchi-ga4 / mart_gbp）

本番の取込は「その実行で初めて BQ に入ったレビュー」だけを要約するが、
**既に BQ にある行もこのスクリプトで要約できる**（Vertex / API キーは本番と同じ env）。

例（高崎店・2026/4/2。細かい窓で 0 件なら JST 丸一日を取る）:
  python scripts/test_review_summary_from_bq.py \\
    --store-code 3708278 --jst-date 2026-04-02 --full-day --dry-run

要約だけ出す（標準出力）:
  python scripts/test_review_summary_from_bq.py \\
    --store-code 3708278 --jst-date 2026-04-02 --full-day

要約を Slack にも送る（SLACK_WEBHOOK_URL または REVIEW_SUMMARY_SLACK_WEBHOOK_URL が必要）:
  python scripts/test_review_summary_from_bq.py \\
    --store-code 3708278 --jst-date 2026-04-02 --full-day --send-slack

行が取れないときは review_id を直接指定（クォート内は BQ の全文。ドキュメントの「…」をコマンドに入れない）:
  python scripts/test_review_summary_from_bq.py \\
    --store-code 3708278 --provider-review-id '<provider_review_idの全文>'

トラブルシュート:
  - unrecognized arguments: ...  → シェルに「...」と打っている。省略記号なので削除し、ID 全文かオプションだけにする。
  - RefreshError: gcloud auth application-default login を再実行。
  - python3.11 が無い: brew install python@3.12 のあと
      $(brew --prefix python@3.12)/bin/python3.12 -m venv .venv
      source .venv/bin/activate && pip install -r requirements.txt
    （python3 が 3.10 以上なら python3 -m venv .venv でも可）
  - importlib.metadata / packages_distributions: 古い Python（例: 3.9）＋ gcloud で出ることがある。上記の新しめの venv で実行。
  - RefreshError (ADC): `gcloud auth application-default login` するか、
      export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"
    でユーザー認証トークンを渡す（ローカル・Vertex/BQ 短期用）。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _load_config():
    # 環境を読み直す前に import しない（テストで差し替えやすい）
    from src import config

    return config


def _bq_client_optional_token(project: str, location: str):
    """ADC が無いとき GOOGLE_OAUTH_ACCESS_TOKEN で BQ（gcloud auth print-access-token）。"""
    tok = (os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN") or "").strip()
    if tok:
        from google.oauth2.credentials import Credentials

        creds = Credentials(token=tok)
        return bigquery.Client(project=project, location=location, credentials=creds)
    return bigquery.Client(project=project, location=location)


def _utc_ts_to_jst_str(ts) -> str:
    if ts is None:
        return "(なし)"
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    return ts.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M JST")


def _diagnose_empty_window(
    client: bigquery.Client,
    *,
    project: str,
    dataset: str,
    store_code: str,
    jst_date: str,
) -> None:
    """日時窓で 0 件のとき、その JST 日の reviews の有無と JOIN を stderr に出す。"""
    d = date.fromisoformat(jst_date)
    q_rev = f"""
    SELECT
      COUNT(*) AS n,
      MIN(TIMESTAMP(review_created_at)) AS tmin,
      MAX(TIMESTAMP(review_created_at)) AS tmax
    FROM `{project}.{dataset}.reviews`
    WHERE store_code = @sc
      AND provider = 'google'
      AND DATE(TIMESTAMP(review_created_at), 'Asia/Tokyo') = @d
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("sc", "STRING", store_code),
            bigquery.ScalarQueryParameter("d", "DATE", d),
        ]
    )
    rev_row = list(client.query(q_rev, job_config=job_config).result(timeout=120))
    if not rev_row:
        return
    r0 = rev_row[0]
    n = int(r0["n"] or 0)
    if n == 0:
        print(
            f"ヒント: store_code={store_code} で、JST {jst_date} の reviews は 0 件です。",
            file=sys.stderr,
        )
        q_any = f"""
        SELECT
          COUNT(*) AS total,
          MIN(TIMESTAMP(review_created_at)) AS tmin,
          MAX(TIMESTAMP(review_created_at)) AS tmax
        FROM `{project}.{dataset}.reviews`
        WHERE store_code = @sc AND provider = 'google'
        """
        jc_any = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("sc", "STRING", store_code)]
        )
        any_rows = list(client.query(q_any, job_config=jc_any).result(timeout=120))
        if any_rows:
            a0 = any_rows[0]
            tot = int(a0["total"] or 0)
            if tot == 0:
                print(
                    "  → この store_code の Google 口コミは BQ の reviews に 1 件もありません。"
                    " is_active・取り込みジョブの対象店かを確認してください。",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  → 同一店舗の全期間では {tot} 件あり、"
                    f"最古～最新（JST）: {_utc_ts_to_jst_str(a0['tmin'])} ～ {_utc_ts_to_jst_str(a0['tmax'])}",
                    file=sys.stderr,
                )
                print(
                    "  → GBP にその日のコメント付き口コミがあっても BQ に無い場合は、"
                    "まだ merge されていない・年の取り違え（2025/2026）・別店の可能性があります。",
                    file=sys.stderr,
                )
        return
    print(
        f"ヒント: JST {jst_date} には reviews に {n} 件あります。"
        f" 時刻（UTC 保存値の JST 表示）: {_utc_ts_to_jst_str(r0['tmin'])} ～ {_utc_ts_to_jst_str(r0['tmax'])}",
        file=sys.stderr,
    )
    q_join = f"""
    SELECT COUNT(*) AS n
    FROM `{project}.{dataset}.reviews` AS r
    INNER JOIN `{project}.{dataset}.places_provider_map` AS m
      ON m.store_code = r.store_code AND m.provider = r.provider
    WHERE r.store_code = @sc
      AND r.provider = 'google'
      AND DATE(TIMESTAMP(r.review_created_at), 'Asia/Tokyo') = @d
    """
    j_row = list(client.query(q_join, job_config=job_config).result(timeout=120))
    jn = int(j_row[0]["n"] or 0) if j_row else 0
    if jn == 0:
        print(
            "ヒント: reviews にはあるが places_provider_map と INNER JOIN できていません（map の store_code / provider を確認）。",
            file=sys.stderr,
        )
    else:
        print(
            "  → --full-day または --jst-start/--jst-end を広げるとヒットする可能性があります。",
            file=sys.stderr,
        )


def _fetch_rows(
    client: bigquery.Client,
    *,
    project: str,
    dataset: str,
    store_code: str,
    provider_review_id: str | None,
    jst_date: str,
    jst_start: str,
    jst_end: str,
    full_day: bool,
) -> tuple[str, list[dict]]:
    """戻り値: (店舗表示名, gbp 形式の review dict リスト)。"""
    if provider_review_id:
        q = f"""
        SELECT m.display_name AS store_name,
               r.provider_review_id, r.rating, r.review_text,
               r.review_created_at
        FROM `{project}.{dataset}.reviews` AS r
        JOIN `{project}.{dataset}.places_provider_map` AS m
          ON m.store_code = r.store_code AND m.provider = r.provider
        WHERE r.store_code = @store_code
          AND r.provider = 'google'
          AND r.provider_review_id = @rid
        """
        params = [
            bigquery.ScalarQueryParameter("store_code", "STRING", store_code),
            bigquery.ScalarQueryParameter("rid", "STRING", provider_review_id),
        ]
    else:
        q = f"""
        SELECT m.display_name AS store_name,
               r.provider_review_id, r.rating, r.review_text,
               r.review_created_at
        FROM `{project}.{dataset}.reviews` AS r
        JOIN `{project}.{dataset}.places_provider_map` AS m
          ON m.store_code = r.store_code AND m.provider = r.provider
        WHERE r.store_code = @store_code
          AND r.provider = 'google'
          AND TIMESTAMP(r.review_created_at) >= TIMESTAMP(@start_ts)
          AND TIMESTAMP(r.review_created_at) < TIMESTAMP(@end_ts)
        ORDER BY r.review_created_at
        """
        tz = ZoneInfo("Asia/Tokyo")
        if full_day:
            start_dt = datetime.fromisoformat(f"{jst_date}T00:00:00").replace(tzinfo=tz)
            end_dt = start_dt + timedelta(days=1)
        else:
            start_dt = datetime.fromisoformat(f"{jst_date}T{jst_start}:00").replace(tzinfo=tz)
            end_dt = datetime.fromisoformat(f"{jst_date}T{jst_end}:00").replace(tzinfo=tz)
        params = [
            bigquery.ScalarQueryParameter("store_code", "STRING", store_code),
            bigquery.ScalarQueryParameter("start_ts", "TIMESTAMP", start_dt),
            bigquery.ScalarQueryParameter("end_ts", "TIMESTAMP", end_dt),
        ]
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(client.query(q, job_config=job_config).result(timeout=120))
    if not rows:
        return "", []
    name = (rows[0]["store_name"] or "").strip() or "（店舗名なし）"
    revs = []
    for row in rows:
        revs.append(
            {
                "provider_review_id": (row["provider_review_id"] or "").strip(),
                "rating": float(row["rating"]) if row["rating"] is not None else None,
                "review_text": row["review_text"] or "",
            }
        )
    return name, revs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BQ の口コミを 1 件束ねて要約 API を試す",
        epilog=(
            "注意: ドキュメントの「…」や ... は省略の意味であり、コマンドラインにそのまま入れないでください。"
            " --provider-review-id には BigQuery の ID をスペースなしで全文指定します。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--store-code", default="3708278", help="dim_store / store_code（既定: 高崎）"
    )
    parser.add_argument("--jst-date", default="2026-04-02", help="JST の日付 YYYY-MM-DD")
    parser.add_argument(
        "--jst-start", default="20:35", help="JST 開始時刻 HH:MM（日付は --jst-date）"
    )
    parser.add_argument(
        "--jst-end", default="20:50", help="JST 終了時刻 HH:MM（排他的。--full-day 時は無視）"
    )
    parser.add_argument(
        "--full-day",
        action="store_true",
        help="--jst-date の JST 丸一日（00:00〜翌00:00）を対象にする（細い窓で 0 件のとき用）",
    )
    parser.add_argument(
        "--provider-review-id",
        default="",
        help="指定時は日時帯ではなくこの reviewId のみ取得",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Gemini/Vertex は呼ばず、BQ 結果と JSON ペイロードだけ表示",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="要約に渡すユーザープロンプト全文を表示",
    )
    parser.add_argument(
        "--send-slack",
        action="store_true",
        help="要約成功後に本番と同じ Incoming Webhook で Slack に POST する",
    )
    parser.add_argument(
        "--snapshot-date",
        default="",
        help="Slack 見出し用の日付 YYYY-MM-DD（省略時は今日 JST）",
    )
    parser.add_argument(
        "--ingest-run-id",
        default="bq_manual",
        help="Slack 本文先頭の ingest_run_id 表示（既定: bq_manual）",
    )
    args = parser.parse_args()

    config = _load_config()
    project = config.BQ_PROJECT
    dataset = config.BQ_DATASET
    client = _bq_client_optional_token(project, config.BQ_LOCATION)

    rid = (args.provider_review_id or "").strip() or None
    store_name, reviews = _fetch_rows(
        client,
        project=project,
        dataset=dataset,
        store_code=args.store_code,
        provider_review_id=rid,
        jst_date=args.jst_date,
        jst_start=args.jst_start,
        jst_end=args.jst_end,
        full_day=args.full_day,
    )
    if not reviews:
        print(
            "該当行がありません。review_created_at が JST の想定とずれている可能性があります。\n"
            "  --full-day（JST 丸一日）を試すか、--jst-start / --jst-end を広げる、"
            "または --provider-review-id で BQ の ID を直接指定してください。",
            file=sys.stderr,
        )
        if not rid:
            _diagnose_empty_window(
                client,
                project=project,
                dataset=dataset,
                store_code=args.store_code,
                jst_date=args.jst_date,
            )
        return 1

    stores = [{"store_name": store_name, "reviews": reviews}]
    print(
        f"store_code={args.store_code} store_name={store_name} reviews={len(reviews)}", flush=True
    )
    for r in reviews:
        rid_disp = r["provider_review_id"] or ""
        rid_short = (rid_disp[:24] + "…") if len(rid_disp) > 24 else rid_disp
        print(
            f"  id={rid_short} rating={r['rating']} text_len={len((r.get('review_text') or ''))}",
            flush=True,
        )

    if reviews and all(not (x.get("review_text") or "").strip() for x in reviews):
        print(
            "注意: 本文（review_text）がすべて空です。"
            "Google の星のみレビューは API 上 comment がなく、BQ にも空のまま入ります。"
            "要約プロンプトに渡るのは rating のみです。",
            file=sys.stderr,
        )

    from src import review_summary

    payload_json = review_summary._build_prompt_payload(stores)
    if args.dry_run:
        print("--- payload JSON ---", flush=True)
        print(payload_json, flush=True)
        return 0

    if args.print_prompt:
        print("--- user prompt ---", flush=True)
        print(review_summary._review_summary_user_prompt(payload_json), flush=True)

    # 本番と同じ経路（Vertex または API キー）
    summary = review_summary._summarize_review_text(payload_json)
    if not summary:
        print("(要約に失敗しました。stderr の [review_summary] ログを確認)", file=sys.stderr)
        return 2

    print("--- 要約 ---", flush=True)
    print(summary, flush=True)

    if args.send_slack:
        tz = ZoneInfo("Asia/Tokyo")
        snap = (args.snapshot_date or "").strip()
        if not snap:
            snap = datetime.now(tz).strftime("%Y-%m-%d")
        title = f"新規レビュー要約（{snap}・BQ参照）"
        meta = f"ingest_run_id: `{args.ingest_run_id}`"
        body = f"{meta}\n\n{summary}"
        url = review_summary._slack_webhook_url()
        if not url:
            print(
                "SLACK_WEBHOOK_URL または REVIEW_SUMMARY_SLACK_WEBHOOK_URL が未設定のため "
                "--send-slack できません。",
                file=sys.stderr,
            )
            return 3
        if review_summary._post_slack_markdown(title, body):
            print("--- Slack POST 済 ---", flush=True)
            return 0
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
