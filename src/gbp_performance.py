"""
Google Business Profile Performance API（日次メトリクス）の取得とパース。

公式: locations.fetchMultiDailyMetricsTimeSeries
https://developers.google.com/my-business/reference/performance/rest/v1/locations/fetchMultiDailyMetricsTimeSeries

リクエスト仕様（GET・body 空）:
  - 必須クエリ dailyMetrics[] … 取得する日次指標
  - 必須クエリ dailyRange … 期間（REST の DailyRange に相当。start_date / end_date は両端とも含む inclusive）
    https://developers.google.com/my-business/reference/performance/rest/v1/DailyRange
  - gRPC Transcoding ではクエリ例のとおり dailyRange.start_date.year 等のフラット形式を使う

返却は常に「日付ごとの値」の時系列のみ。月次集計を返す別パラメータはこのメソッドにはない。
"""

from __future__ import annotations

import sys
import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import requests

from . import gbp_reviews

PERF_BASE = "https://businessprofileperformance.googleapis.com/v1"

# fetchMultiDailyMetricsTimeSeries でまとめて取る指標
DEFAULT_PERF_METRICS: list[str] = [
    "CALL_CLICKS",
    "WEBSITE_CLICKS",
    "BUSINESS_DIRECTION_REQUESTS",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
]

_IMPRESSION_METRICS = frozenset(
    {
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    }
)

_REQUEST_TIMEOUT_SEC = 60


def location_numeric_id(provider_place_id: str) -> str:
    s = (provider_place_id or "").strip()
    if "/locations/" not in s:
        raise ValueError(f"provider_place_id に /locations/ がありません: {s!r}")
    return s.split("/locations/")[-1].split("/")[0].strip()


def build_fetch_multi_params(
    metrics: list[str],
    start: date,
    end: date,
) -> list[tuple[str, str]]:
    """
    dailyRange の開始日・終了日を API 仕様どおりクエリに展開する（両端 inclusive）。
    """
    pairs: list[tuple[str, str]] = []
    for m in metrics:
        pairs.append(("dailyMetrics", m))
    pairs.extend(
        [
            ("dailyRange.start_date.year", str(start.year)),
            ("dailyRange.start_date.month", str(start.month)),
            ("dailyRange.start_date.day", str(start.day)),
            ("dailyRange.end_date.year", str(end.year)),
            ("dailyRange.end_date.month", str(end.month)),
            ("dailyRange.end_date.day", str(end.day)),
        ]
    )
    return pairs


def fetch_multi_daily_metrics(
    access_token: str,
    location_numeric_id: str,
    start: date,
    end: date,
    *,
    metrics: list[str] | None = None,
    max_429_retries: int = 3,
) -> dict[str, Any]:
    """
    fetchMultiDailyMetricsTimeSeries を 1 回呼ぶ。期間は [start, end]（inclusive）を dailyRange に渡す。
    成功時は JSON dict、失敗時は例外。429 のときは最大 max_429_retries 回まで約 65 秒待って再試行する。
    """
    gbp_reviews._ensure_dns_mybusiness_resolved()
    mlist = metrics if metrics is not None else DEFAULT_PERF_METRICS
    url = f"{PERF_BASE}/locations/{location_numeric_id}:fetchMultiDailyMetricsTimeSeries"
    params = build_fetch_multi_params(mlist, start, end)
    headers = {"Authorization": f"Bearer {access_token}"}

    attempt = 0
    while True:
        result_holder: list[requests.Response | None] = [None]
        exc_holder: list[BaseException | None] = [None]

        def _do_get() -> None:
            try:
                result_holder[0] = requests.get(
                    url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT_SEC
                )
            except BaseException as e:
                exc_holder[0] = e

        t = threading.Thread(target=_do_get, daemon=True)
        t.start()
        t.join(timeout=_REQUEST_TIMEOUT_SEC + 5)
        if t.is_alive():
            raise TimeoutError(f"Performance API GET did not complete in {_REQUEST_TIMEOUT_SEC}s")
        if exc_holder[0]:
            raise exc_holder[0]
        r = result_holder[0]
        assert r is not None
        if r.status_code == 429 and attempt < max_429_retries:
            attempt += 1
            print(
                f"[gbp_performance] 429 rate limit, sleep 65s retry {attempt}/{max_429_retries}",
                file=sys.stderr,
            )
            time.sleep(65)
            continue
        if not r.ok:
            try:
                body = r.json()
                err = body.get("error", {}).get("message", r.text[:500])
            except Exception:
                err = r.text[:500]
            print(f"[gbp_performance] {r.status_code} {url}: {err}", file=sys.stderr)
            r.raise_for_status()
        return r.json()


def _dated_value_to_date(d: dict[str, Any]) -> date | None:
    if not d:
        return None
    y = d.get("year")
    mo = d.get("month")
    if y is None or mo is None:
        return None
    day = d.get("day")
    if day is None:
        return None
    try:
        return date(int(y), int(mo), int(day))
    except (TypeError, ValueError):
        return None


def parse_performance_daily_totals(body: dict[str, Any]) -> dict[date, dict[str, int]]:
    """
    API レスポンスを日付ごとの集計に変換。
    impressions = 4 種の BUSINESS_IMPRESSIONS_* の合算。
    value 省略は 0（Google の仕様）。
    """
    acc: dict[date, dict[str, int]] = defaultdict(
        lambda: {
            "impressions": 0,
            "calls": 0,
            "direction_requests": 0,
            "website_clicks": 0,
        }
    )
    for block in body.get("multiDailyMetricTimeSeries") or []:
        for series in block.get("dailyMetricTimeSeries") or []:
            metric = series.get("dailyMetric") or ""
            ts = series.get("timeSeries") or {}
            for dv in ts.get("datedValues") or []:
                day = _dated_value_to_date(dv.get("date") or {})
                if day is None:
                    continue
                raw = dv.get("value")
                val = int(raw) if raw is not None and str(raw).strip() != "" else 0
                row = acc[day]
                if metric in _IMPRESSION_METRICS:
                    row["impressions"] += val
                elif metric == "CALL_CLICKS":
                    row["calls"] += val
                elif metric == "BUSINESS_DIRECTION_REQUESTS":
                    row["direction_requests"] += val
                elif metric == "WEBSITE_CLICKS":
                    row["website_clicks"] += val
    return dict(acc)


def month_date_range(year_month: str) -> tuple[date, date]:
    """'YYYY-MM' → その月の初日・末日（含む）。"""
    parts = year_month.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"year-month は YYYY-MM 形式: {year_month!r}")
    y, m = int(parts[0]), int(parts[1])
    start = date(y, m, 1)
    if m == 12:
        end = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(y, m + 1, 1) - timedelta(days=1)
    return start, end
