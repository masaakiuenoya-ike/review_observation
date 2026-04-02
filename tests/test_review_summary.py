"""review_summary の分岐テスト（Gemini / Slack はモック）。"""

from unittest import mock

from src import review_summary


def test_maybe_send_disabled():
    with mock.patch.object(review_summary.config, "REVIEW_SUMMARY_ENABLED", False):
        assert review_summary.maybe_send_after_ingest("2026-01-01", "run-1", []) == "disabled"


def test_maybe_send_no_new():
    with mock.patch.object(review_summary.config, "REVIEW_SUMMARY_ENABLED", True):
        assert review_summary.maybe_send_after_ingest("2026-01-01", "run-1", []) == "no_new_reviews"


def test_maybe_send_dry_run(monkeypatch):
    stores = [
        {
            "store_name": "テスト店",
            "reviews": [{"rating": 5.0, "review_text": "良い", "provider_review_id": "a"}],
        }
    ]
    monkeypatch.setattr(review_summary.config, "REVIEW_SUMMARY_ENABLED", True)
    monkeypatch.setattr(review_summary.config, "REVIEW_SUMMARY_SLACK_DRY_RUN", True)
    monkeypatch.setattr(review_summary.config, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(review_summary.config, "GEMINI_MODEL", "gemini-2.0-flash")

    with mock.patch(
        "src.review_summary._summarize_with_gemini", return_value="【ポジ】良い\n【ネガ】なし"
    ):
        out = review_summary.maybe_send_after_ingest("2026-01-01", "run-1", stores)
    assert out == "dry_run_logged"


def test_maybe_send_slack_post_failed(monkeypatch):
    stores = [
        {
            "store_name": "テスト店",
            "reviews": [{"rating": 5.0, "review_text": "良い", "provider_review_id": "c"}],
        }
    ]
    monkeypatch.setattr(review_summary.config, "REVIEW_SUMMARY_ENABLED", True)
    monkeypatch.setattr(review_summary.config, "REVIEW_SUMMARY_SLACK_DRY_RUN", False)
    monkeypatch.setattr(review_summary.config, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(review_summary.config, "SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

    class BadResp:
        ok = False
        status_code = 400
        text = "invalid_payload"

    with (
        mock.patch("src.review_summary._summarize_with_gemini", return_value="要約本文"),
        mock.patch("src.review_summary.requests.post", return_value=BadResp()),
    ):
        out = review_summary.maybe_send_after_ingest("2026-01-01", "run-1", stores)
    assert out == "slack_post_failed"


def test_maybe_send_no_gemini_key(monkeypatch):
    stores = [
        {
            "store_name": "テスト店",
            "reviews": [{"rating": 1.0, "review_text": "悪い", "provider_review_id": "b"}],
        }
    ]
    monkeypatch.setattr(review_summary.config, "REVIEW_SUMMARY_ENABLED", True)
    monkeypatch.setattr(review_summary.config, "GEMINI_API_KEY", "")

    assert (
        review_summary.maybe_send_after_ingest("2026-01-01", "run-1", stores)
        == "skipped_no_gemini_key"
    )
