"""
review_observation Cloud Run エントリポイント。
GET /health, POST / で定点観測実行（GBP レビュー取得 → BQ MERGE）。
"""

from __future__ import annotations

import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
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
from . import slack_notify

app = Flask(__name__)

# Asia/Tokyo の「今日」を snapshot_date に使用
TZ = ZoneInfo("Asia/Tokyo")


@app.route("/health", methods=["GET"])
def health():
    return "", 200


@app.route("/sheets-update", methods=["POST"])
def run_sheets_update():
    """
    BQ の v_latest_available_ratings / v_latest_available_alerts を読んで
    Sheets の LATEST / ALERT / サマリ のみ更新する。取込は行わない。
    store_name を反映したいときや、取込がタイムアウトしてシートが更新されていないときに実行する。
    """
    print("[review_observation] POST /sheets-update started", flush=True)
    if not config.SHEET_ID:
        return jsonify({"ok": False, "error": "SHEET_ID not set"}), 400
    try:
        sheets_writer.write_latest_and_alerts()
        print("[review_observation] Sheets LATEST/ALERT/サマリ updated", flush=True)
    except Exception as e:
        print(f"[review_observation] sheets-update failed: {e}", file=sys.stderr)
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "message": "sheets updated"}), 200


# daily-summary の最大実行時間（秒）。これを超えたら 503 を返してクライアントがハングしないようにする。
DAILY_SUMMARY_TIMEOUT_SEC = 150


@app.route("/daily-summary", methods=["POST"])
def run_daily_summary():
    """
    1日1回用: 取込は行わず、BQ の直近取込データを元に各店舗の評価・前日比を Slack に送る。
    Cloud Scheduler で毎日 1 回（例: 9:00 JST）呼ぶ想定。
    全体を DAILY_SUMMARY_TIMEOUT_SEC で打ち切り、必ず HTTP レスポンスを返す。
    """
    print("[review_observation] POST /daily-summary started", flush=True)
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(slack_notify.send_daily_summary)
        try:
            future.result(timeout=DAILY_SUMMARY_TIMEOUT_SEC)
        except FuturesTimeoutError:
            print("[review_observation] daily-summary timed out", file=sys.stderr)
            return (
                jsonify({"ok": False, "error": "daily summary timed out"}),
                503,
            )
        except Exception as e:
            print(f"[review_observation] daily-summary failed: {e}", file=sys.stderr)
            return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "message": "daily summary sent"}), 200


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

    places_with_id = [
        (p, (p.get("provider_place_id") or "").strip())
        for p in places
        if (p.get("provider_place_id") or "").strip()
    ]
    if not places_with_id:
        return jsonify(
            {
                "ok": True,
                "ingest_run_id": ingest_run_id,
                "snapshot_date": snapshot_date.isoformat(),
                "processed": 0,
                "errors": 0,
                "message": "no places with provider_place_id",
            }
        ), 200

    def _process_one(place: dict, provider_place_id: str, tok: str) -> tuple[dict, dict]:
        """1 店舗を取得・MERGE し、(rating_row, star_count_dict) を返す。401 のときは HTTPError をそのまま上げる。"""
        store_code = place["store_code"]
        avg_rating, total_count, reviews = gbp_reviews.fetch_reviews_for_location(
            tok, provider_place_id
        )
        store_name = place.get("display_name") or ""
        bq_ops.merge_reviews(
            store_code=store_code,
            provider=place["provider"],
            provider_place_id=provider_place_id,
            reviews=reviews,
            ingest_run_id=ingest_run_id,
            store_name=store_name,
        )
        count_1 = sum(1 for r in reviews if r.get("rating") == 1.0)
        count_5 = sum(1 for r in reviews if r.get("rating") == 5.0)
        rating_row = {
            "store_code": store_code,
            "store_name": store_name,
            "provider": place["provider"],
            "provider_place_id": provider_place_id,
            "rating_value": avg_rating,
            "review_count": total_count,
            "status": "ok",
        }
        star_count = {
            "store_code": store_code,
            "store_name": place.get("display_name") or "",
            "count_1star": count_1,
            "count_5star": count_5,
        }
        return (rating_row, star_count)

    results_by_store: dict[str, tuple[dict, dict]] = {}
    errors = 0
    need_401_retry: list[tuple[dict, str]] = []

    print(
        f"[review_observation] fetching reviews for {len(places_with_id)} places (max_workers={config.MAX_WORKERS})...",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_one, place, provider_place_id, access_token): (
                place,
                provider_place_id,
            )
            for place, provider_place_id in places_with_id
        }
        for future in as_completed(futures):
            place, provider_place_id = futures[future]
            store_code = place["store_code"]
            try:
                r_row, s_count = future.result()
                results_by_store[store_code] = (r_row, s_count)
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 401:
                    need_401_retry.append((place, provider_place_id))
                else:
                    errors += 1
                    if errors == 1:
                        import traceback

                        print(
                            f"[review_observation] 店舗 {store_code} でエラー（代表）: {e}",
                            file=sys.stderr,
                        )
                        traceback.print_exc(file=sys.stderr)
                    results_by_store[store_code] = (
                        {
                            "store_code": store_code,
                            "provider": place["provider"],
                            "provider_place_id": provider_place_id,
                            "rating_value": None,
                            "review_count": None,
                            "status": "error",
                        },
                        {
                            "store_code": store_code,
                            "store_name": place.get("display_name") or "",
                            "count_1star": 0,
                            "count_5star": 0,
                        },
                    )
            except Exception as e:
                errors += 1
                if errors == 1:
                    import traceback

                    print(
                        f"[review_observation] 店舗 {store_code} でエラー（代表）: {e}",
                        file=sys.stderr,
                    )
                    traceback.print_exc(file=sys.stderr)
                results_by_store[store_code] = (
                    {
                        "store_code": store_code,
                        "provider": place["provider"],
                        "provider_place_id": provider_place_id,
                        "rating_value": None,
                        "review_count": None,
                        "status": "error",
                    },
                    {
                        "store_code": store_code,
                        "store_name": place.get("display_name") or "",
                        "count_1star": 0,
                        "count_5star": 0,
                    },
                )

    if need_401_retry:
        print(
            "[review_observation] 401 (token expired?), refreshing and retrying failed stores...",
            flush=True,
            file=sys.stderr,
        )
        try:
            access_token = gbp_oauth.get_gbp_access_token(
                config.GBP_OAUTH_SECRET_NAME, config.GCP_PROJECT
            )
            for place, provider_place_id in need_401_retry:
                store_code = place["store_code"]
                try:
                    r_row, s_count = _process_one(place, provider_place_id, access_token)
                    results_by_store[store_code] = (r_row, s_count)
                except Exception as retry_e:
                    errors += 1
                    if errors == 1:
                        import traceback

                        print(
                            f"[review_observation] 店舗 {store_code} リトライ後エラー: {retry_e}",
                            file=sys.stderr,
                        )
                        traceback.print_exc(file=sys.stderr)
                    results_by_store[store_code] = (
                        {
                            "store_code": store_code,
                            "provider": place["provider"],
                            "provider_place_id": provider_place_id,
                            "rating_value": None,
                            "review_count": None,
                            "status": "error",
                        },
                        {
                            "store_code": store_code,
                            "store_name": place.get("display_name") or "",
                            "count_1star": 0,
                            "count_5star": 0,
                        },
                    )
        except Exception as e:
            print(f"[review_observation] token refresh failed: {e}", file=sys.stderr)
            for place, provider_place_id in need_401_retry:
                store_code = place["store_code"]
                if store_code not in results_by_store:
                    errors += 1
                    results_by_store[store_code] = (
                        {
                            "store_code": store_code,
                            "provider": place["provider"],
                            "provider_place_id": provider_place_id,
                            "rating_value": None,
                            "review_count": None,
                            "status": "error",
                        },
                        {
                            "store_code": store_code,
                            "store_name": place.get("display_name") or "",
                            "count_1star": 0,
                            "count_5star": 0,
                        },
                    )

    # 元の places 順で rating_rows / star_counts_per_store を並べる
    store_order = [p["store_code"] for p in places if (p.get("provider_place_id") or "").strip()]
    rating_rows = []
    star_counts_per_store = []
    for store_code in store_order:
        if store_code in results_by_store:
            r_row, s_count = results_by_store[store_code]
            rating_rows.append(r_row)
            star_counts_per_store.append(s_count)

    try:
        bq_ops.merge_ratings_daily_snapshot(snapshot_date, ingest_run_id, rating_rows)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "ingest_run_id": ingest_run_id}), 500

    sheets_updated = False
    if config.SHEET_ID:
        try:
            sheets_writer.write_latest_and_alerts()
            sheets_updated = True
            print("[review_observation] Sheets LATEST/ALERT/サマリ updated", flush=True)
        except Exception as e:
            print(
                f"[review_observation] Sheets update failed: {e}",
                file=sys.stderr,
                flush=True,
            )
            import traceback

            traceback.print_exc(file=sys.stderr)

    if config.SLACK_WEBHOOK_URL:
        try:
            slack_notify.send_slack_notification(snapshot_date.isoformat(), star_counts_per_store)
        except Exception as e:
            print(f"[review_observation] Slack notification failed: {e}", file=sys.stderr)

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
