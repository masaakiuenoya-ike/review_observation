"""
取込後に BQ のアラート VIEW と今回の★1/★5件数をまとめ、Slack Incoming Webhook へ通知する。
"""

from __future__ import annotations

from typing import Any

import requests

from . import config
from . import bq_ops


def _round1(val: Any) -> Any:
    """評価を小数点1桁に（2桁目で四捨五入）。None はそのまま。"""
    if val is None:
        return None
    try:
        return round(float(val), 1)
    except (TypeError, ValueError):
        return val


def _fetch_alerts(client: Any) -> list[dict[str, Any]]:
    """v_latest_available_alerts（直近取込日のアラート）を取得。"""
    ds = config.BQ_DATASET
    project = config.BQ_PROJECT
    q = f"""
    SELECT snapshot_date, store_code, store_name, alert_type, rating_value, delta_rating, delta_review_count
    FROM `{project}.{ds}.v_latest_available_alerts`
    ORDER BY store_code, alert_type
    """
    job = client.query(q)
    return [dict(r) for r in job.result(timeout=60)]


def _fetch_rating_up(client: Any) -> list[dict[str, Any]]:
    """★が上がった店舗（delta_rating >= 0.2）。直近取込日ベース。"""
    ds = config.BQ_DATASET
    project = config.BQ_PROJECT
    q = f"""
    SELECT snapshot_date, store_code, store_name, rating_value, delta_rating, delta_review_count
    FROM `{project}.{ds}.v_latest_available_ratings`
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
            store_code = r.get("store_code", "")
            store_name = r.get("store_name") or ""
            store_label = f"{store_name} ({store_code})" if store_name else store_code
            atype = r.get("alert_type", "")
            label = {
                "low_rating": "評価低い(<4.2)",
                "rating_drop": "★下がった",
                "review_surge": "レビュー急増",
            }.get(atype, atype)
            val = _round1(r.get("rating_value"))
            delta = _round1(r.get("delta_rating"))
            cnt = r.get("delta_review_count")
            lines.append(f"・{store_label}: {label} (評価={val}, Δ={delta}, レビューΔ={cnt})")
    else:
        lines.append("\nアラート: なし")

    # ★上がった
    if rating_ups:
        lines.append("\n*★が上がった*")
        for r in rating_ups:
            store_code = r.get("store_code", "")
            store_name = r.get("store_name") or ""
            store_label = f"{store_name} ({store_code})" if store_name else store_code
            delta = _round1(r.get("delta_rating"))
            lines.append(f"・{store_label}: Δ評価 +{delta}")
    else:
        lines.append("\n★が上がった: なし")

    # 今回の取込で★1/★5が増えた店舗
    star_relevant = [
        s for s in star_counts if (s.get("count_1star") or 0) > 0 or (s.get("count_5star") or 0) > 0
    ]
    if star_relevant:
        lines.append("\n*今回の取込で★1/★5が含まれた店舗*")
        for s in star_relevant:
            store_code = s.get("store_code", "")
            store_name = s.get("store_name") or ""
            store_label = f"{store_name} ({store_code})" if store_name else store_code
            c1 = s.get("count_1star") or 0
            c5 = s.get("count_5star") or 0
            parts = []
            if c1 > 0:
                parts.append(f"★1: {c1}件")
            if c5 > 0:
                parts.append(f"★5: {c5}件")
            lines.append(f"・{store_label}: {', '.join(parts)}")
    else:
        lines.append("\n今回の取込で★1/★5: 該当なし")

    text = "\n".join(lines)
    return {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ],
    }


def _fetch_all_ratings_for_daily(client: Any) -> list[dict[str, Any]]:
    """日次サマリ用: 全店舗の評価・前日比を取得。"""
    ds = config.BQ_DATASET
    project = config.BQ_PROJECT
    q = f"""
    SELECT snapshot_date, store_code, store_name, rating_value, review_count, delta_rating, delta_review_count
    FROM `{project}.{ds}.v_latest_available_ratings`
    WHERE status = 'ok'
    ORDER BY store_code
    """
    job = client.query(q)
    return [dict(r) for r in job.result(timeout=90)]


def _store_label(r: dict) -> str:
    """店舗表示用ラベル（store_code は出力しない。店舗名のみ）。"""
    store_name = (r.get("store_name") or "").strip()
    return store_name if store_name else "（店舗名なし）"


def _delta_category(r: dict) -> str:
    """delta_rating で UP / DOWN / same を判定。"""
    delta = r.get("delta_rating")
    if delta is None:
        return "same"
    try:
        d = float(delta)
        if d > 0:
            return "up"
        if d < 0:
            return "down"
    except (TypeError, ValueError):
        pass
    return "same"


def _format_daily_summary_blocks(
    snapshot_date: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """日次サマリ: 評価UP/DOWN/変化無と、店舗別評価（評価高い順・順位付き）を1ブロックにまとめる。評価は小数点1桁で四捨五入。DB変更不要で rows の delta_rating で分類。"""
    lines = [f"*GBP 日次サマリ*（{snapshot_date}）", ""]

    # 評価UP / 評価DOWN / 評価変化無（delta_rating で分類）
    up_list = [r for r in rows if _delta_category(r) == "up"]
    down_list = [r for r in rows if _delta_category(r) == "down"]
    same_list = [r for r in rows if _delta_category(r) == "same"]

    lines.append("*評価UP*")
    if up_list:
        for r in up_list:
            name = _store_label(r)
            delta = _round1(r.get("delta_rating"))
            current = _round1(r.get("rating_value"))
            prev = None
            if current is not None and delta is not None:
                try:
                    prev = round(float(current) - float(delta), 1)
                except (TypeError, ValueError):
                    pass
            up_str = f"+{delta}" if delta is not None else "-"
            cur_str = str(current) if current is not None else "-"
            prev_str = str(prev) if prev is not None else "-"
            lines.append(
                f"{name}: 上がり幅 {up_str}, 現状のGBP評価 {cur_str}, 以前のGBP評価 {prev_str}"
            )
    else:
        lines.append("（なし）")
    lines.append("")
    lines.append("*評価DOWN*")
    if down_list:
        for r in down_list:
            lines.append(_store_label(r))
    else:
        lines.append("（なし）")
    lines.append("")
    lines.append("*評価変化無*")
    if same_list:
        for r in same_list:
            lines.append(_store_label(r))
    else:
        lines.append("（なし）")
    lines.append("")

    # 店舗別評価: 評価の高い順にソートし順位をつける
    def _rating_sort_key(r: dict) -> tuple:
        val = r.get("rating_value")
        if val is None:
            return (-1.0, r.get("store_code", ""))
        try:
            return (-float(val), r.get("store_code", ""))
        except (TypeError, ValueError):
            return (-1.0, r.get("store_code", ""))

    sorted_rows = sorted(rows, key=_rating_sort_key)
    lines.append("*店舗別評価*")
    for i, r in enumerate(sorted_rows, start=1):
        label = _store_label(r)
        rating = _round1(r.get("rating_value"))
        delta = _round1(r.get("delta_rating"))
        rev = r.get("review_count")
        rev_delta = r.get("delta_review_count")
        delta_str = f" (前日比 {delta:+.1f})" if delta is not None else ""
        rev_str = (
            f", レビュー {rev}件 (Δ{rev_delta})"
            if rev is not None and rev_delta is not None
            else ""
        )
        rating_display = rating if rating is not None else "-"
        lines.append(f"{i}位: {label}: GBP評価 {rating_display}{delta_str}{rev_str}")
    text = "\n".join(lines)
    # Slack section は 3000 文字上限。超えたら前半で切る（通常は店舗数で超えない）
    if len(text) > 2900:
        text = text[:2897] + "\n…（省略）"
    return {
        "text": "GBP 日次サマリ",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


def send_daily_summary() -> None:
    """
    1日1回用: BQ の v_latest_available_ratings を全件取得し、
    各店舗の評価・前日比を Slack に送る。取込は行わない。
    SLACK_WEBHOOK_URL が未設定の場合は何もしない。
    """
    if not config.SLACK_WEBHOOK_URL:
        return
    try:
        client = bq_ops.get_client()
        rows = _fetch_all_ratings_for_daily(client)
        if not rows:
            payload = {
                "text": "GBP 日次サマリ（データなし）",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*GBP 日次サマリ*\n直近取込データがありません。",
                        },
                    }
                ],
            }
        else:
            snapshot_date = str(rows[0].get("snapshot_date", "")) if rows else ""
            payload = _format_daily_summary_blocks(snapshot_date, rows)
        r = requests.post(config.SLACK_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        import sys

        print(f"[review_observation] Slack daily summary failed: {e}", file=sys.stderr)


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
        payload = _format_slack_blocks(snapshot_date, alerts, rating_ups, star_counts_per_store)
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
