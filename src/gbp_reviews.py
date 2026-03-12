"""
GBP API (My Business v4) で reviews.list を呼ぶ。
GET https://mybusiness.googleapis.com/v4/{parent}/reviews
※ reviews は v4 のみ（v1 に代替なし）。requests の timeout は DNS に効かないためスレッドでラップ。
"""

from __future__ import annotations

import socket
import sys
import threading
from typing import Any
from urllib.parse import urlparse

import requests

# 1 店舗あたりの最大待ち時間（秒）。requests の timeout は DNS に効かないためスレッドで強制。
# connect 4s + read 6s より少し長めに設定。
_REQUEST_TIMEOUT_SEC = 11
_DNS_RESOLVE_TIMEOUT_SEC = 3

STAR_MAP = {
    "ONE": 1.0,
    "TWO": 2.0,
    "THREE": 3.0,
    "FOUR": 4.0,
    "FIVE": 5.0,
}


def _rating_from_star(star_rating: str) -> float | None:
    if not star_rating:
        return None
    return STAR_MAP.get(star_rating.upper())


def fetch_reviews_for_location(
    access_token: str,
    parent: str,
    *,
    page_size: int = 50,
    order_by: str = "updateTime desc",
) -> tuple[float | None, int, list[dict[str, Any]]]:
    """
    parent = accounts/{accountId}/locations/{locationId} 形式。
    Returns (average_rating, total_review_count, list of review rows for our schema).
    """
    base = "https://mybusiness.googleapis.com/v4"
    url = f"{base}/{parent}/reviews"
    host = urlparse(url).hostname or "mybusiness.googleapis.com"
    # DNS は requests の timeout 対象外のため、先に短いタイムアウトで解決を試みる
    dns_ok: list[bool] = [False]

    def _resolve() -> None:
        try:
            socket.getaddrinfo(host, 443, socket.AF_INET)
            dns_ok[0] = True
        except Exception:
            pass

    t_dns = threading.Thread(target=_resolve, daemon=True)
    t_dns.start()
    t_dns.join(timeout=_DNS_RESOLVE_TIMEOUT_SEC)
    if not dns_ok[0]:
        print(
            f"[gbp_reviews] DNS resolution for {host} timed out ({_DNS_RESOLVE_TIMEOUT_SEC}s)",
            file=sys.stderr,
        )
        raise TimeoutError(
            f"DNS resolution for {host} did not complete in {_DNS_RESOLVE_TIMEOUT_SEC}s"
        )

    headers = {"Authorization": f"Bearer {access_token}"}
    params: dict[str, str | int] = {"pageSize": page_size, "orderBy": order_by}
    all_reviews: list[dict[str, Any]] = []
    total_count = 0
    avg_rating: float | None = None

    while True:
        print(f"[gbp_reviews] GET {url[:80]}...", flush=True, file=sys.stderr)
        result_holder: list[requests.Response | None] = [None]
        exc_holder: list[BaseException | None] = [None]

        def _do_get() -> None:
            try:
                result_holder[0] = requests.get(url, headers=headers, params=params, timeout=(4, 6))
            except BaseException as e:
                exc_holder[0] = e

        t = threading.Thread(target=_do_get, daemon=True)
        t.start()
        t.join(timeout=_REQUEST_TIMEOUT_SEC)
        if t.is_alive():
            print(
                f"[gbp_reviews] 応答が {_REQUEST_TIMEOUT_SEC}s 以内に返りませんでした",
                file=sys.stderr,
            )
            raise TimeoutError(f"GET {url[:60]}... did not complete in {_REQUEST_TIMEOUT_SEC}s")
        if exc_holder[0]:
            if isinstance(exc_holder[0], requests.exceptions.Timeout):
                print(f"[gbp_reviews] Timeout: {exc_holder[0]}", file=sys.stderr)
            elif isinstance(exc_holder[0], requests.exceptions.RequestException):
                print(f"[gbp_reviews] RequestException: {exc_holder[0]}", file=sys.stderr)
            raise exc_holder[0]
        r = result_holder[0]
        assert r is not None
        if not r.ok:
            try:
                body = r.json()
                err_msg = body.get("error", {}).get("message", r.text[:500])
                print(f"[gbp_reviews] {r.status_code} {url}: {err_msg}", file=sys.stderr)
            except Exception:
                print(f"[gbp_reviews] {r.status_code} {url}: {r.text[:500]}", file=sys.stderr)
            r.raise_for_status()
        data = r.json()
        total_count = data.get("totalReviewCount", 0)
        avg_rating = data.get("averageRating")
        if avg_rating is not None:
            avg_rating = float(avg_rating)
        reviews = data.get("reviews") or []
        for rev in reviews:
            reviewer = rev.get("reviewer") or {}
            all_reviews.append(
                {
                    "provider_review_id": rev.get("reviewId") or "",
                    "rating": _rating_from_star(rev.get("starRating", "")),
                    "review_text": rev.get("comment") or "",
                    "review_created_at": rev.get("createTime"),
                    "review_updated_at": rev.get("updateTime"),
                    "reviewer_display_name": reviewer.get("displayName")
                    if not reviewer.get("isAnonymous")
                    else None,
                }
            )
        next_token = data.get("nextPageToken")
        if not next_token:
            break
        params = {"pageSize": page_size, "orderBy": order_by, "pageToken": next_token}

    return (avg_rating, total_count, all_reviews)
