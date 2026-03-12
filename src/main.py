"""
review_observation Cloud Run エントリポイント。
GET /health, POST / で定点観測実行（GBP レビュー取得 → BQ MERGE）。
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify

# 初回 POST で import がブロックしないよう起動時に読み込む
from . import config
from . import bq_ops
from . import gbp_oauth
from . import gbp_reviews
from . import sheets_writer

app = Flask(__name__)

# Asia/Tokyo の「今日」を snapshot_date に使用
TZ = ZoneInfo("Asia/Tokyo")


@app.route("/health", methods=["GET"])
def health():
    return "", 200


@app.route("/", methods=["POST"])
def run_ingest():
    """定点観測: places_provider_map 読込 → GBP reviews.list → ratings_daily_snapshot / reviews MERGE。"""
    print("[review_observation] POST / started", flush=True)
    ingest_run_id = str(uuid.uuid4())
    # 日本時間で日付を確定（Scheduler が 09:00 JST ならその「日」）
    snapshot_date = datetime.now(TZ).date()

    print("[review_observation] loading places_provider_map...", flush=True)
    places = bq_ops.load_places_provider_map(
        provider="google", is_active=True, require_place_id=True
    )
    print(f"[review_observation] loaded {len(places)} places", flush=True)
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

    print("[review_observation] getting access_token...", flush=True)
    try:
        access_token = gbp_oauth.get_gbp_access_token(
            config.GBP_OAUTH_SECRET_NAME, config.GCP_PROJECT
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "ingest_run_id": ingest_run_id}), 500

    print("[review_observation] fetching reviews for each place...", flush=True)
    rating_rows: list[dict] = []
    errors = 0

    def _fetch_and_merge(
        *,
        access_token: str,
        place: dict,
        store_code: str,
        provider_place_id: str,
        ingest_run_id: str,
        rating_rows: list[dict],
    ) -> None:
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

    for i, place in enumerate(places, 1):
        store_code = place["store_code"]
        provider_place_id = (place.get("provider_place_id") or "").strip()
        if not provider_place_id:
            continue
        print(f"[review_observation] place {i}/{len(places)} store_code={store_code}...", flush=True)
        try:
            _fetch_and_merge(
                access_token=access_token,
                place=place,
                store_code=store_code,
                provider_place_id=provider_place_id,
                ingest_run_id=ingest_run_id,
                rating_rows=rating_rows,
            )
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                print("[review_observation] 401 (token expired?), refreshing access_token and retrying once...", flush=True, file=sys.stderr)
                try:
                    access_token = gbp_oauth.get_gbp_access_token(
                        config.GBP_OAUTH_SECRET_NAME, config.GCP_PROJECT
                    )
                    _fetch_and_merge(
                        access_token=access_token,
                        place=place,
                        store_code=store_code,
                        provider_place_id=provider_place_id,
                        ingest_run_id=ingest_run_id,
                        rating_rows=rating_rows,
                    )
                except Exception as retry_e:
                    errors += 1
                    if errors == 1:
                        import traceback
                        print(f"[review_observation] 店舗 {store_code} リトライ後もエラー: {retry_e}", file=sys.stderr)
                        traceback.print_exc(file=sys.stderr)
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
                    continue
            else:
                errors += 1
                if errors == 1:
                    import traceback
                    print(f"[review_observation] 店舗 {store_code} でエラー（代表）: {e}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
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
                continue
        except Exception as e:
            errors += 1
            # デバッグ用: 先頭1件だけ stderr に出力（同じエラーが31件続くため）
            if errors == 1:
                import traceback
                print(f"[review_observation] 店舗 {store_code} でエラー（代表）: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
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

    sheets_updated = False
    if config.SHEET_ID:
        try:
            sheets_writer.write_latest_and_alerts()
            sheets_updated = True
            print("[review_observation] Sheets LATEST/ALERT updated", flush=True)
        except Exception as e:
            print(f"[review_observation] Sheets update failed: {e}", file=sys.stderr)

    return jsonify(
        {
            "ok": True,
            "ingest_run_id": ingest_run_id,
            "snapshot_date": snapshot_date.isoformat(),
            "processed": len(rating_rows),
            "errors": errors,
            "sheets_updated": sheets_updated,
        }
    ), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
