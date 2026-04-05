#!/usr/bin/env python3
"""
BigQuery 上の performance_daily_snapshot / performance_monthly_snapshot の取込状況を確認する。

  python3 scripts/verify_performance_ingest.py
  python3 scripts/verify_performance_ingest.py --ingest-run-id efafdbcc-2ace-48eb-a6b1-22584ae360a1

前提: gcloud auth application-default login 済み、BQ_PROJECT / BQ_DATASET が正しいこと。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from google.cloud import bigquery  # noqa: E402

from src import config  # noqa: E402


def _latest_ingest_run_id(client: bigquery.Client, proj: str, ds: str) -> str | None:
    sql = f"""
    SELECT ingest_run_id
    FROM `{proj}.{ds}.performance_monthly_snapshot`
    WHERE ingest_run_id IS NOT NULL AND TRIM(ingest_run_id) != ''
    GROUP BY ingest_run_id
    ORDER BY MAX(fetched_at) DESC
    LIMIT 1
    """
    rows = list(client.query(sql).result(timeout=60))
    if not rows:
        return None
    return rows[0]["ingest_run_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description="performance 取込の BQ 検証")
    parser.add_argument(
        "--ingest-run-id",
        help="省略時は performance_monthly_snapshot で最も新しい ingest_run_id",
    )
    args = parser.parse_args()

    client = bigquery.Client(project=config.BQ_PROJECT, location=config.BQ_LOCATION)
    proj, ds = config.BQ_PROJECT, config.BQ_DATASET

    rid = (args.ingest_run_id or "").strip() or _latest_ingest_run_id(client, proj, ds)
    if not rid:
        print("ingest_run_id が取得できません（テーブルが空の可能性）", file=sys.stderr)
        return 1

    print(f"ingest_run_id={rid}\n", flush=True)

    job_cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("rid", "STRING", rid)]
    )

    blocks = [
        (
            "行数・取込時刻",
            f"""
            SELECT 'monthly' AS tbl, COUNT(*) AS n, MIN(fetched_at) AS min_f, MAX(fetched_at) AS max_f
            FROM `{proj}.{ds}.performance_monthly_snapshot`
            WHERE ingest_run_id = @rid
            UNION ALL
            SELECT 'daily', COUNT(*), MIN(fetched_at), MAX(fetched_at)
            FROM `{proj}.{ds}.performance_daily_snapshot`
            WHERE ingest_run_id = @rid
            """,
        ),
        (
            "月次: 指標列が SQL NULL の行数（0=欠損なし）・値>0 の行数・合計",
            f"""
            SELECT
              COUNTIF(status = 'ok') AS ok_rows,
              COUNTIF(status != 'ok') AS error_rows,
              COUNTIF(impressions IS NULL) AS cnt_rows_impressions_is_null,
              COUNTIF(calls IS NULL) AS cnt_rows_calls_is_null,
              COUNTIF(direction_requests IS NULL) AS cnt_rows_direction_is_null,
              COUNTIF(website_clicks IS NULL) AS cnt_rows_website_clicks_is_null,
              COUNTIF(impressions > 0) AS rows_pos_impressions,
              COUNTIF(calls > 0) AS rows_pos_calls,
              COUNTIF(direction_requests > 0) AS rows_pos_direction,
              COUNTIF(website_clicks > 0) AS rows_pos_web,
              SUM(impressions) AS sum_impressions,
              SUM(calls) AS sum_calls,
              SUM(direction_requests) AS sum_direction,
              SUM(website_clicks) AS sum_web
            FROM `{proj}.{ds}.performance_monthly_snapshot`
            WHERE ingest_run_id = @rid
            """,
        ),
        (
            "日次: 件数・日付範囲・impressions が SQL NULL の行数",
            f"""
            SELECT
              COUNT(*) AS n,
              COUNTIF(status = 'ok') AS ok_rows,
              COUNTIF(impressions IS NULL) AS cnt_rows_impressions_is_null,
              MIN(snapshot_date) AS d0,
              MAX(snapshot_date) AS d1
            FROM `{proj}.{ds}.performance_daily_snapshot`
            WHERE ingest_run_id = @rid
            """,
        ),
        (
            "月次サンプル（インプレッション上位5店舗）",
            f"""
            SELECT store_code, snapshot_month, impressions, calls, direction_requests, website_clicks, status
            FROM `{proj}.{ds}.performance_monthly_snapshot`
            WHERE ingest_run_id = @rid AND status = 'ok'
            ORDER BY impressions DESC
            LIMIT 5
            """,
        ),
        (
            "テーブル全体の最新 snapshot_month（VIEW 用）",
            f"""
            SELECT MAX(snapshot_month) AS latest_month, COUNT(*) AS row_count
            FROM `{proj}.{ds}.performance_monthly_snapshot`
            """,
        ),
    ]

    for title, sql in blocks:
        print("===", title, "===")
        cfg = job_cfg if "@rid" in sql else None
        job = client.query(sql, job_config=cfg)
        for row in job.result(timeout=120):
            print(dict(row))
        print()

    print(
        "【読み方】cnt_rows_*_is_null は「その列が BigQuery の NULL である行数」。"
        "すべて 0 なら欠損なく取り込めています（0 という数値と NULL は別です）。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
