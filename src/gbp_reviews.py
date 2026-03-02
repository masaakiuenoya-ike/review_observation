"""
GBP API (My Business v4) で reviews.list を呼び、評価・レビュー一覧を取得する。
GET https://mybusiness.googleapis.com/v4/{parent}/reviews
"""

from __future__ import annotations

from typing import Any

import requests

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
    headers = {"Authorization": f"Bearer {access_token}"}
    params: dict[str, str | int] = {"pageSize": page_size, "orderBy": order_by}
    all_reviews: list[dict[str, Any]] = []
    total_count = 0
    avg_rating: float | None = None

    while True:
        r = requests.get(url, headers=headers, params=params, timeout=30)
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
