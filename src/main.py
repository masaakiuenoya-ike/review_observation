"""
review_observation Cloud Run エントリポイント。
GET /health, POST / で定点観測実行（GBP レビュー取得 → BQ MERGE）。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify

app = Flask(__name__)

# Asia/Tokyo の「今日」を snapshot_date に使用
TZ = ZoneInfo("Asia/Tokyo")


@app.route("/health", methods=["GET"])
def health():
    return "", 200


@app.route("/", methods=["POST"])
def run_ingest():
    """定点観測: places_provider_map 読込 → GBP reviews.list → ratings_daily_snapshot / reviews MERGE。"""
    ingest_run_id = str(uuid.uuid4())
    # 日本時間で日付を確定（Scheduler が 09:00 JST ならその「日」）
    snapshot_date = datetime.now(TZ).date()

    try:
        from . import config
        from . import bq_ops
        from . import gbp_oauth
        from . import gbp_reviews
    except ImportError as e:
        return jsonify({"ok": False, "error": str(e), "ingest_run_id": ingest_run_id}), 500

    places = bq_ops.load_places_provider_map(
        provider="google", is_active=True, require_place_id=True
    )
    if not places:
        return jsonify(
            {
                "ok": True,
                "ingest_run_id": ingest_run_id,
                "snapshot_date": snapshot_date.isoformat(),
                "message": "no places with provider_place_id (GBP location) configured",
                "processed": 0,
                "errors": 0,
            }
        ), 200

    try:
        access_token = gbp_oauth.get_gbp_access_token(
            config.GBP_OAUTH_SECRET_NAME, config.GCP_PROJECT
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "ingest_run_id": ingest_run_id}), 500

    rating_rows: list[dict] = []
    errors = 0

    for place in places:
        store_code = place["store_code"]
        provider_place_id = (place.get("provider_place_id") or "").strip()
        if not provider_place_id:
            continue
        try:
            avg_rating, total_count, reviews = gbp_reviews.fetch_reviews_for_location(
                access_token, provider_place_id
            )
            rating_rows.append(
                {
                    "store_code": store_code,
                    "provider": place["provider"],
                    "provider_place_id": provider_place_id,
                    "rating_value": avg_rating,
                    "review_count": total_count,
                    "status": "ok",
                }
            )
            bq_ops.merge_reviews(
                store_code=store_code,
                provider=place["provider"],
                provider_place_id=provider_place_id,
                reviews=reviews,
                ingest_run_id=ingest_run_id,
            )
        except Exception:
            errors += 1
            rating_rows.append(
                {
                    "store_code": store_code,
                    "provider": place["provider"],
                    "provider_place_id": provider_place_id,
                    "rating_value": None,
                    "review_count": None,
                    "status": "error",
                }
            )
            # 店舗単位で status='error' を記録。全体は 200 を返す
            continue

    try:
        bq_ops.merge_ratings_daily_snapshot(snapshot_date, ingest_run_id, rating_rows)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "ingest_run_id": ingest_run_id}), 500

    return jsonify(
        {
            "ok": True,
            "ingest_run_id": ingest_run_id,
            "snapshot_date": snapshot_date.isoformat(),
            "processed": len(rating_rows),
            "errors": errors,
        }
    ), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
