"""
取込後に BQ のアラート VIEW と今回の★1/★5件数をまとめ、Slack Incoming Webhook へ通知する。
"""

from __future__ import annotations

from typing import Any

import requests

from . import config
from . import bq_ops


def _fetch_alerts(client: Any) -> list[dict[str, Any]]:
    """v_rating_alerts（今日）を取得。"""
    ds = config.BQ_DATASET
    project = config.BQ_PROJECT
    q = f"""
    SELECT snapshot_date, store_code, alert_type, rating_value, delta_rating, delta_review_count
    FROM `{project}.{ds}.v_rating_alerts`
    ORDER BY store_code, alert_type
    """
    job = client.query(q)
    return [dict(r) for r in job.result(timeout=60)]


def _fetch_rating_up(client: Any) -> list[dict[str, Any]]:
    """★が上がった店舗（delta_rating >= 0.2）。"""
    ds = config.BQ_DATASET
    project = config.BQ_PROJECT
    q = f"""
    SELECT snapshot_date, store_code, rating_value, delta_rating, delta_review_count
    FROM `{project}.{ds}.v_latest_with_delta_ratings`
    WHERE delta_rating >= 0.2
    ORDER BY store_code
    """
    job = client.query(q)
    return [dict(r) for r in job.result(timeout=60)]


def _format_slack_blocks(
    snapshot_date: str,
    alerts: list[dict],
    rating_ups: list[dict],
    star_counts: list[dict],
) -> dict[str, Any]:
    """Slack Block Kit の blocks を組み立て（通知内容が空でもヘッダーは出す）。"""
    lines: list[str] = []
    lines.append(f"*GBP レビュー取込サマリ*（{snapshot_date}）")

    # ★下がった / 評価低い / レビュー急増
    if alerts:
        lines.append("\n*アラート*")
        for r in alerts:
            store = r.get("store_code", "")
            atype = r.get("alert_type", "")
            label = {"low_rating": "評価低い(<4.2)", "rating_drop": "★下がった", "review_surge": "レビュー急増"}.get(atype, atype)
            val = r.get("rating_value")
            delta = r.get("delta_rating")
            cnt = r.get("delta_review_count")
            lines.append(f"・店舗 {store}: {label} (評価={val}, Δ={delta}, レビューΔ={cnt})")
    else:
        lines.append("\nアラート: なし")

    # ★上がった
    if rating_ups:
        lines.append("\n*★が上がった*")
        for r in rating_ups:
            store = r.get("store_code", "")
            delta = r.get("delta_rating")
            lines.append(f"・店舗 {store}: Δ評価 +{delta}")
    else:
        lines.append("\n★が上がった: なし")

    # 今回の取込で★1/★5が増えた店舗
    star_relevant = [s for s in star_counts if (s.get("count_1star") or 0) > 0 or (s.get("count_5star") or 0) > 0]
    if star_relevant:
        lines.append("\n*今回の取込で★1/★5が含まれた店舗*")
        for s in star_relevant:
            store = s.get("store_code", "")
            c1 = s.get("count_1star") or 0
            c5 = s.get("count_5star") or 0
            parts = []
            if c1 > 0:
                parts.append(f"★1: {c1}件")
            if c5 > 0:
                parts.append(f"★5: {c5}件")
            lines.append(f"・店舗 {store}: {', '.join(parts)}")
    else:
        lines.append("\n今回の取込で★1/★5: 該当なし")

    text = "\n".join(lines)
    return {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ],
    }


def send_slack_notification(
    snapshot_date: str,
    star_counts_per_store: list[dict[str, Any]],
) -> None:
    """
    SLACK_WEBHOOK_URL が設定されていれば、BQ のアラート・★上がった・今回の★1/★5を取得し、
    Slack に通知する。未設定または失敗時は何もしない（例外は出さない）。
    """
    if not config.SLACK_WEBHOOK_URL:
        return
    try:
        client = bq_ops.get_client()
        alerts = _fetch_alerts(client)
        rating_ups = _fetch_rating_up(client)
        payload = _format_slack_blocks(
            snapshot_date, alerts, rating_ups, star_counts_per_store
        )
        payload["text"] = "GBP レビュー取込サマリ"  # 通知オフ時のプレーンテキスト
        r = requests.post(
            config.SLACK_WEBHOOK_URL,
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        import sys
        print(f"[review_observation] Slack notification failed: {e}", file=sys.stderr)
