#!/usr/bin/env python3
"""
Business Profile Performance API の fetchMultiDailyMetricsTimeSeries が
1 店舗で通るかを切り分ける。

前提:
  - Secret Manager の gbp-oauth-json（refresh_token）が読める ADC
  - OAuth に https://www.googleapis.com/auth/business.manage が含まれること
  - GCP で Business Profile Performance API が有効
  - locationId は「unobfuscated」。通常は accounts/.../locations/{この数値} の末尾

例:
  python scripts/test_gbp_performance_fetch.py --store-code 3568922
  python scripts/test_gbp_performance_fetch.py --location-id 13356364523439956955
  python scripts/test_gbp_performance_fetch.py --print-curl   # トークンは YOUR_TOKEN

公式:
  https://developers.google.com/my-business/reference/performance/rest/v1/locations/fetchMultiDailyMetricsTimeSeries

OAuth メモ（重要）:
  - 正しいスコープは **https://www.googleapis.com/auth/business.manage**（[スコープ一覧](https://developers.google.com/identity/protocols/oauth2/scopes) の Google Business Profile API）。
  - **OAuth 2.0 Playground** にこのスコープを入れると、
    「legacy API … scope name is invalid」系のエラーになりやすい。**Playground では取得しないこと。**
  - 自プロジェクトの **OAuth クライアント**で同意する。例: リポジトリの
      python3 scripts/gbp_oauth_cli.py get-refresh-token
    （CLIENT_ID / CLIENT_SECRET を自前のものに。同意画面に business.manage を追加済みであること）
  - 既存の refresh_token が **狭いスコープのまま**の場合は、再同意（prompt=consent）で
    **business.manage 付きのトークン**を取り直す。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src import gbp_performance  # noqa: E402

DEFAULT_METRICS = gbp_performance.DEFAULT_PERF_METRICS


def _print_curl(location_id: str, metrics: list[str], start: date, end: date) -> None:
    q = gbp_performance.build_fetch_multi_params(metrics, start, end)
    qs = "&".join(
        f"{requests.utils.quote(k, safe='')}={requests.utils.quote(v, safe='')}" for k, v in q
    )
    url = f"{gbp_performance.PERF_BASE}/locations/{location_id}:fetchMultiDailyMetricsTimeSeries?{qs}"
    print("--- curl 例（YOUR_TOKEN を差し替え） ---", flush=True)
    print(
        f"curl -sS -H 'Authorization: Bearer YOUR_TOKEN' '{url}' | python3 -m json.tool",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="GBP Performance API 1 店舗疎通テスト")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--store-code", help="places_provider_map の store_code（BQ から place_id 解決）"
    )
    g.add_argument("--location-id", help="Performance API 用 locations/{id} の id（数値文字列）")
    parser.add_argument(
        "--lag-days",
        type=int,
        default=3,
        help="終端日を今日から何日前にするか（日次指標の確定ラグ想定。既定 3）",
    )
    parser.add_argument(
        "--range-days",
        type=int,
        default=14,
        help="取得日数（終端からさかのぼる。既定 14）",
    )
    parser.add_argument(
        "--print-curl",
        action="store_true",
        help="HTTP リクエストは送らず curl 1 行だけ表示して終了",
    )
    args = parser.parse_args()

    from src import bq_ops, config, gbp_oauth

    if args.store_code:
        places = bq_ops.load_places_provider_map(
            provider="google", is_active=True, require_place_id=True
        )
        row = next((p for p in places if p["store_code"] == args.store_code), None)
        if not row:
            print(f"store_code={args.store_code} が map に無いか place_id 空", file=sys.stderr)
            return 1
        pid = (row.get("provider_place_id") or "").strip()
        title = (row.get("display_name") or "").strip()
        print(f"store_code={args.store_code} display_name={title!r}", flush=True)
        print(f"provider_place_id={pid}", flush=True)
        try:
            location_id = gbp_performance.location_numeric_id(pid)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
    else:
        location_id = (args.location_id or "").strip()
        if not location_id.isdigit():
            print("--location-id は数値の listing id を想定", file=sys.stderr)
            return 1

    print(f"Performance API location_id={location_id}", flush=True)

    end = date.today() - timedelta(days=max(0, args.lag_days))
    start = end - timedelta(days=max(1, args.range_days))
    print(
        f"dailyRange: {start.isoformat()} .. {end.isoformat()} (inclusive 想定は API 仕様に従う)",
        flush=True,
    )

    if args.print_curl:
        _print_curl(location_id, DEFAULT_METRICS, start, end)
        return 0

    token = gbp_oauth.get_gbp_access_token(config.GBP_OAUTH_SECRET_NAME, config.GCP_PROJECT)
    url = f"{gbp_performance.PERF_BASE}/locations/{location_id}:fetchMultiDailyMetricsTimeSeries"
    params = gbp_performance.build_fetch_multi_params(DEFAULT_METRICS, start, end)

    print(f"GET {url}", flush=True)
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=60,
    )
    print(f"HTTP {r.status_code}", flush=True)
    try:
        body = r.json()
    except Exception:
        print(r.text[:2000], flush=True)
        return 2

    if not r.ok:
        print(json.dumps(body, ensure_ascii=False, indent=2), flush=True)
        return 3

    print(json.dumps(body, ensure_ascii=False, indent=2), flush=True)

    series = body.get("multiDailyMetricTimeSeries") or []
    if not series:
        print(
            "\n注意: multiDailyMetricTimeSeries が空。locationId の形式・スコープ・日付レンジ・API 有効化を確認。",
            file=sys.stderr,
        )
        return 4

    print("\n--- 要約（各メトリクスのデータ点数） ---", flush=True)
    for block in series:
        for item in block.get("dailyMetricTimeSeries") or []:
            metric = item.get("dailyMetric")
            ts = item.get("timeSeries") or {}
            pts = ts.get("datedValues") or []
            print(f"  {metric}: {len(pts)} points", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
