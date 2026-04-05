#!/usr/bin/env python3
"""
全店舗の GBP Performance（fetchMultiDailyMetricsTimeSeries）を BigQuery に取り込む。

- performance_daily_snapshot: 指定期間の各日 × 各店舗（データが無い日は 0）
- performance_monthly_snapshot: 期間と重なる各暦月ごとに日次の合算（スプレッドシートは
  v_latest_available_performance_monthly などと接続可能）

API は月次専用の From/To はなく、必須の dailyRange（開始日・終了日・両端 inclusive）で
日次時系列だけを返す。運用は **日次・月次ともオン（既定）** を想定し、店舗あたり
**1 回**の dailyRange（全体の start..end）で取得し、日次テーブルへは日ごと、月次テーブルへは
暦月ごとの合算を書き込む。--no-daily / --no-monthly で片方だけにすることも可能。

期間（終端は必ず min(指定終端, 今日JST - lag_days) にクリップ）:
  既定 … 日本時間の「実行時の年月」の 1 日〜末日（月初は lag で当月が空になりがちなので、
    引数なしのときだけ自動で「前月」に切り替える）
  --year-month YYYY-MM … その月
  --from-date / --to-date YYYY-MM-DD … 任意レンジ（両方必須）

例:
  python3 scripts/sync_gbp_performance_to_bq.py
  python3 scripts/sync_gbp_performance_to_bq.py --year-month 2026-03 --lag-days 3
  python3 scripts/sync_gbp_performance_to_bq.py --from-date 2026-02-01 --to-date 2026-03-31 --no-daily
  python3 scripts/sync_gbp_performance_to_bq.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

JST = ZoneInfo("Asia/Tokyo")


def _today_jst() -> date:
    return datetime.now(JST).date()


def _prev_month_ym(d: date) -> str:
    """d がある月の直前の暦月を YYYY-MM で返す。"""
    if d.month == 1:
        y, m = d.year - 1, 12
    else:
        y, m = d.year, d.month - 1
    return f"{y}-{m:02d}"


def _parse_iso_date(s: str) -> date:
    parts = s.strip().split("-")
    if len(parts) != 3:
        raise ValueError(f"日付は YYYY-MM-DD: {s!r}")
    y, mo, d = int(parts[0]), int(parts[1]), int(parts[2])
    return date(y, mo, d)


def _iter_month_starts(lo: date, hi: date):
    cur = date(lo.year, lo.month, 1)
    end_m = date(hi.year, hi.month, 1)
    while cur <= end_m:
        yield cur
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)


def _month_end(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1) - timedelta(days=1)
    return date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)


def _clip_range_end(req_start: date, req_end: date, lag_days: int) -> tuple[date, date]:
    cap = _today_jst() - timedelta(days=max(0, lag_days))
    eff_end = min(req_end, cap)
    return req_start, eff_end


def _daterange_inclusive(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def _sum_daily_segment(
    by_day: dict,
    seg_lo: date,
    seg_hi: date,
    z: dict[str, int],
) -> dict[str, int]:
    tot = {k: 0 for k in z}
    for d in _daterange_inclusive(seg_lo, seg_hi):
        m = by_day.get(d, z)
        for k in z:
            tot[k] += m[k]
    return tot


def main() -> int:
    parser = argparse.ArgumentParser(description="GBP Performance → BigQuery 全店舗同期")
    parser.add_argument(
        "--year-month",
        metavar="YYYY-MM",
        help="集計対象の暦月（未指定時は JST の当月）",
    )
    parser.add_argument("--from-date", metavar="YYYY-MM-DD", help="開始日（--to-date と併用）")
    parser.add_argument("--to-date", metavar="YYYY-MM-DD", help="終了日（--to-date と併用）")
    parser.add_argument(
        "--lag-days",
        type=int,
        default=3,
        help="終端を今日(JST)から何日前までに制限するか（日次指標の遅延想定。既定 3）",
    )
    parser.add_argument(
        "--daily",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="日次テーブルへ書き込む（既定: オン。運用は --daily --monthly の両方を推奨）",
    )
    parser.add_argument(
        "--monthly",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="月次テーブルへ書き込む（既定: オン。店舗あたり API は日次の有無に関わらず 1 回）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="BigQuery へは書かず件数だけ表示",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=0.2,
        help="店舗間の待機秒（既定 0.2）",
    )
    args = parser.parse_args()

    if not args.daily and not args.monthly:
        print("--daily と --monthly のどちらか一方以上が必要です", file=sys.stderr)
        return 1

    if (args.from_date or args.to_date) and (args.from_date is None or args.to_date is None):
        print("--from-date と --to-date は両方指定してください", file=sys.stderr)
        return 1
    if args.year_month and (args.from_date or args.to_date):
        print("--year-month と --from-date/--to-date は併用できません", file=sys.stderr)
        return 1

    from src import gbp_performance

    explicit_range = bool(args.from_date or args.year_month)

    if args.from_date and args.to_date:
        req_start = _parse_iso_date(args.from_date)
        req_end = _parse_iso_date(args.to_date)
    elif args.year_month:
        try:
            req_start, req_end = gbp_performance.month_date_range(args.year_month)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
    else:
        t = _today_jst()
        req_start, req_end = gbp_performance.month_date_range(f"{t.year}-{t.month:02d}")

    start, end = _clip_range_end(req_start, req_end, args.lag_days)
    if start > end and not explicit_range:
        prev = _prev_month_ym(_today_jst())
        req_start, req_end = gbp_performance.month_date_range(prev)
        start, end = _clip_range_end(req_start, req_end, args.lag_days)
        print(
            f"注意: 当月は lag_days={args.lag_days} によりまだ有効な終端日がありません。"
            f"前月 {prev} に切り替えます → 実効 {start}..{end}",
            flush=True,
        )
    if start > end:
        print(
            f"有効期間が空です: 希望 {req_start}..{req_end}, lag={args.lag_days} → {start}..{end}",
            file=sys.stderr,
        )
        if explicit_range:
            print(
                "ヒント: --lag-days を小さくするか、終了日を調整してください。",
                file=sys.stderr,
            )
        return 1

    print(
        f"期間: {start.isoformat()} .. {end.isoformat()} (JST 今日={_today_jst()}, lag_days={args.lag_days})",
        flush=True,
    )
    print(f"daily={args.daily} monthly={args.monthly} dry_run={args.dry_run}", flush=True)

    from src import bq_ops, config, gbp_oauth

    places = bq_ops.load_places_provider_map(
        provider="google", is_active=True, require_place_id=True
    )
    if not places:
        print("places_provider_map に該当行がありません", file=sys.stderr)
        return 1

    token = gbp_oauth.get_gbp_access_token(config.GBP_OAUTH_SECRET_NAME, config.GCP_PROJECT)
    ingest_run_id = str(uuid.uuid4())
    print(f"ingest_run_id={ingest_run_id} stores={len(places)}", flush=True)

    month_starts = list(_iter_month_starts(start, end))

    daily_rows: list[dict] = []
    monthly_rows: list[dict] = []

    z = {"impressions": 0, "calls": 0, "direction_requests": 0, "website_clicks": 0}

    for i, row in enumerate(places):
        store_code = row["store_code"]
        provider = row["provider"]
        pid = (row.get("provider_place_id") or "").strip()
        try:
            nid = gbp_performance.location_numeric_id(pid)
        except ValueError as e:
            print(f"[skip] {store_code}: {e}", file=sys.stderr)
            if args.monthly:
                for ms in month_starts:
                    monthly_rows.append(
                        {
                            "snapshot_month": ms,
                            "store_code": store_code,
                            "provider": provider,
                            "provider_place_id": pid,
                            **z,
                            "status": "error",
                            "error_code": "bad_place_id",
                            "error_message": str(e)[:1024],
                        }
                    )
            continue

        if args.daily or args.monthly:
            try:
                body = gbp_performance.fetch_multi_daily_metrics(token, nid, start, end)
                by_day = gbp_performance.parse_performance_daily_totals(body)
            except Exception as e:
                print(f"[error] {store_code}: {e}", file=sys.stderr)
                if args.monthly:
                    msg = str(e)[:1024]
                    for ms in month_starts:
                        monthly_rows.append(
                            {
                                "snapshot_month": ms,
                                "store_code": store_code,
                                "provider": provider,
                                "provider_place_id": pid,
                                **z,
                                "status": "error",
                                "error_code": "fetch_failed",
                                "error_message": msg,
                            }
                        )
                continue

            if args.daily:
                for d in _daterange_inclusive(start, end):
                    m = by_day.get(d, z)
                    daily_rows.append(
                        {
                            "snapshot_date": d,
                            "store_code": store_code,
                            "provider": provider,
                            "provider_place_id": pid,
                            "impressions": m["impressions"],
                            "calls": m["calls"],
                            "direction_requests": m["direction_requests"],
                            "website_clicks": m["website_clicks"],
                            "status": "ok",
                        }
                    )

            if args.monthly:
                for ms in month_starts:
                    seg_lo = max(start, ms)
                    seg_hi = min(end, _month_end(ms))
                    if seg_lo > seg_hi:
                        continue
                    tot = _sum_daily_segment(by_day, seg_lo, seg_hi, z)
                    monthly_rows.append(
                        {
                            "snapshot_month": ms,
                            "store_code": store_code,
                            "provider": provider,
                            "provider_place_id": pid,
                            **tot,
                            "status": "ok",
                        }
                    )

        if args.sleep_sec > 0 and i + 1 < len(places):
            time.sleep(args.sleep_sec)

    print(
        f"集計: daily_rows={len(daily_rows)} monthly_rows={len(monthly_rows)}",
        flush=True,
    )

    if args.dry_run:
        return 0

    if args.daily and daily_rows:
        bq_ops.merge_performance_daily_snapshot(ingest_run_id, daily_rows)
    if args.monthly and monthly_rows:
        bq_ops.merge_performance_monthly_snapshot(ingest_run_id, monthly_rows)

    print("BigQuery MERGE 完了", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
