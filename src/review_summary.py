"""
取込で検出した「新規」レビューのみを Gemini で店舗別に要約し、Slack に送る。
要約は BigQuery に保存しない。
"""

from __future__ import annotations

import json
import sys
from typing import Any

import requests

from . import config

_MAX_TEXT_PER_REVIEW = 1200
_MAX_REVIEWS_PER_STORE = 40


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _build_prompt_payload(
    stores: list[dict[str, Any]],
) -> str:
    """Gemini に渡す JSON 文字列（店舗名・星・コメントのみ）。"""
    slim: list[dict[str, Any]] = []
    for s in stores:
        name = (s.get("store_name") or "").strip() or "（店舗名なし）"
        revs_in = s.get("reviews") or []
        revs_out: list[dict[str, Any]] = []
        for r in revs_in[:_MAX_REVIEWS_PER_STORE]:
            revs_out.append(
                {
                    "rating": r.get("rating"),
                    "text": _truncate(str(r.get("review_text") or ""), _MAX_TEXT_PER_REVIEW),
                }
            )
        if revs_out:
            slim.append({"store_name": name, "reviews": revs_out})
    return json.dumps({"stores": slim}, ensure_ascii=False)


def _summarize_with_gemini(payload_json: str) -> str | None:
    """Gemini は REST（requests）のみ。pip の依存解決を増やさない。"""
    if not config.GEMINI_API_KEY:
        return None
    model_id = config.GEMINI_MODEL.strip()
    if model_id.startswith("models/"):
        model_id = model_id.replace("models/", "", 1)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    prompt = f"""あなたは日本のローカルビジネスのレビュー分析担当です。
以下の JSON は、今回の取込で「新規」と判定されたレビューだけを店舗別にまとめたものです。

ルール:
- 出力は日本語のみ。
- 店舗ごとに見出しとして店舗名を書く（先頭に「■」など）。
- その直下に「【ポジティブ】」「【ネガティブ】」の2ブロック。該当がなければ「（なし）」。
- 各ブロックは箇条書き、最大3項目、1項目は60文字以内を目安。
- 個人名・ニックネームは伏せる（「利用者」等）。
- 憶測は書かず、コメントの内容に基づく。

JSON:
{payload_json}
"""
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192},
    }
    try:
        r = requests.post(
            url,
            params={"key": config.GEMINI_API_KEY},
            json=body,
            timeout=120,
        )
    except requests.RequestException as e:
        print(f"[review_summary] Gemini request error: {e}", file=sys.stderr)
        return None
    try:
        data = r.json()
    except Exception:
        print(f"[review_summary] Gemini invalid JSON: {r.text[:500]}", file=sys.stderr)
        return None
    if not r.ok:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        msg = err.get("message", r.text[:500])
        print(f"[review_summary] Gemini HTTP {r.status_code}: {msg}", file=sys.stderr)
        return None
    try:
        candidates = data.get("candidates") or []
        if not candidates:
            fb = data.get("promptFeedback") if isinstance(data, dict) else None
            print(
                f"[review_summary] Gemini no candidates (promptFeedback={fb})",
                file=sys.stderr,
            )
            return None
        cand0 = candidates[0] if isinstance(candidates[0], dict) else {}
        fr = cand0.get("finishReason")
        parts = (cand0.get("content") or {}).get("parts") or []
        chunks = [p.get("text", "") for p in parts if isinstance(p, dict)]
        text = "\n".join(chunks).strip()
    except (IndexError, KeyError, TypeError):
        print(
            f"[review_summary] Gemini unexpected response: {str(data)[:500]}",
            file=sys.stderr,
        )
        return None
    if not text:
        fb = data.get("promptFeedback") if isinstance(data, dict) else None
        print(
            f"[review_summary] Gemini empty text finishReason={fr} promptFeedback={fb}",
            file=sys.stderr,
        )
        return None
    if fr and fr not in ("STOP", "MAX_TOKENS"):
        print(
            f"[review_summary] Gemini note: finishReason={fr} (text was returned anyway)",
            file=sys.stderr,
        )
    return text


def _slack_webhook_url() -> str:
    return (config.REVIEW_SUMMARY_SLACK_WEBHOOK_URL or config.SLACK_WEBHOOK_URL or "").strip()


def _post_slack_markdown(title: str, body: str) -> bool:
    """Slack Incoming Webhook。text は一部 mrkdwn が効く。全チャンク成功で True。"""
    url = _slack_webhook_url()
    if config.REVIEW_SUMMARY_SLACK_DRY_RUN:
        print(
            f"[review_summary] REVIEW_SUMMARY_SLACK_DRY_RUN=1 — Slack には POST しません\n"
            f"--- {title} ---\n{body}\n--- end ---",
            flush=True,
        )
        return True
    if not url:
        print(
            "[review_summary] Webhook URL がありません（REVIEW_SUMMARY_SLACK_WEBHOOK_URL または SLACK_WEBHOOK_URL）",
            file=sys.stderr,
        )
        return False
    # 4000 文字超は分割（安全マージン）
    chunk_size = 3500
    parts: list[str] = []
    if len(body) <= chunk_size:
        parts.append(body)
    else:
        for i in range(0, len(body), chunk_size):
            parts.append(body[i : i + chunk_size])
    for i, part in enumerate(parts):
        suffix = f" ({i + 1}/{len(parts)})" if len(parts) > 1 else ""
        text = f"*{title}*{suffix}\n\n{part}"
        r = requests.post(url, json={"text": text}, timeout=60)
        if not r.ok:
            print(
                f"[review_summary] Slack POST failed: {r.status_code} {r.text[:300]}",
                file=sys.stderr,
            )
            return False
    return True


def maybe_send_after_ingest(
    snapshot_date: str,
    ingest_run_id: str,
    stores_with_new_reviews: list[dict[str, Any]],
) -> str:
    """
    stores_with_new_reviews: 各要素は store_name, reviews（gbp_reviews 形式の dict リスト）
    戻り値: 処理結果ラベル（ログ・JSON 応答用）
    """
    if not config.REVIEW_SUMMARY_ENABLED:
        return "disabled"
    if not stores_with_new_reviews:
        return "no_new_reviews"
    # 実際にレビュー行がある店舗だけ
    nonempty = [s for s in stores_with_new_reviews if s.get("reviews")]
    if not nonempty:
        return "no_new_reviews"

    payload_json = _build_prompt_payload(nonempty)
    summary = _summarize_with_gemini(payload_json)
    if not summary:
        if not config.GEMINI_API_KEY:
            print(
                "[review_summary] GEMINI_API_KEY が未設定のためスキップ",
                file=sys.stderr,
            )
            return "skipped_no_gemini_key"
        return "skipped_gemini_failed"

    title = f"新規レビュー要約（{snapshot_date}）"
    meta = f"ingest_run_id: `{ingest_run_id}`"
    body = f"{meta}\n\n{summary}"
    slack_ok = _post_slack_markdown(title, body)
    if config.REVIEW_SUMMARY_SLACK_DRY_RUN:
        return "dry_run_logged"
    if not _slack_webhook_url():
        return "summarized_no_webhook"
    if not slack_ok:
        return "slack_post_failed"
    return "sent"
