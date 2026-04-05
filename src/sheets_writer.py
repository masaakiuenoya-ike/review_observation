"""
BigQuery VIEW を参照し Google Sheets を更新する。
  - v_latest_available_ratings → LATEST
  - v_latest_available_alerts → ALERT
  - 集計 → サマリ
  - v_latest_available_performance_monthly → Google_Monthly_Performance タブ（環境変数で変更可）
直近の取込日で表示するため、当日の取込がなくても値が出る。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from . import config
from . import bq_ops


# LATEST タブの列（v_latest_available_ratings の順）
LATEST_COLUMNS = [
    "snapshot_date",
    "store_code",
    "store_name",
    "provider",
    "provider_place_id",
    "rating_value",
    "review_count",
    "fetched_at",
    "ingest_run_id",
    "status",
    "delta_rating",
    "delta_review_count",
]

# ALERT タブの列（v_latest_available_alerts の順）
ALERT_COLUMNS = [
    "snapshot_date",
    "store_code",
    "store_name",
    "provider",
    "alert_type",
    "rating_value",
    "delta_rating",
    "delta_review_count",
]

# 月次パフォーマンス（v_latest_available_performance_monthly の列順）
PERFORMANCE_MONTHLY_COLUMNS = [
    "snapshot_date",
    "store_code",
    "store_name",
    "provider",
    "provider_place_id",
    "impressions",
    "calls",
    "direction_requests",
    "website_clicks",
    "fetched_at",
    "ingest_run_id",
    "status",
    "delta_impressions",
    "delta_calls",
    "delta_direction_requests",
    "delta_website_clicks",
]


def _cell_value(val: Any) -> str | float | int | None:
    """BQ の値をシート用に変換（日付は ISO 文字列）。"""
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return val


def _rows_from_bq_result(columns: list[str], rows: list[dict[str, Any]]) -> list[list[Any]]:
    """BQ の Row のイテレータを、ヘッダー＋データ行の list[list] に変換。"""
    out: list[list[Any]] = [columns]
    for row in rows:
        out.append([_cell_value(row.get(c)) for c in columns])
    return out


def _fetch_view(client: Any, view_name: str, columns: list[str]) -> list[list[Any]]:
    """BQ の VIEW を 1 件ずつ読んで、シート用の list[list] を返す。"""
    ds = config.BQ_DATASET
    project = config.BQ_PROJECT
    query = f"SELECT {', '.join(columns)} FROM `{project}.{ds}.{view_name}` ORDER BY store_code, provider"
    job = client.query(query)
    rows = [dict(r) for r in job.result(timeout=120)]
    return _rows_from_bq_result(columns, rows)


def _fetch_summary_rows(client: Any) -> list[list[Any]]:
    """サマリタブ用: 全体集計とアラート内訳を BQ から取得し、行のリストで返す。"""
    ds = config.BQ_DATASET
    project = config.BQ_PROJECT
    # 全体サマリ（直近取込日の v_latest_available_ratings から）
    q_summary = f"""
    SELECT
      MAX(snapshot_date) AS snapshot_date,
      COUNT(*) AS store_count,
      ROUND(AVG(rating_value), 2) AS avg_rating,
      SUM(review_count) AS total_reviews
    FROM `{project}.{ds}.v_latest_available_ratings`
    WHERE status = 'ok'
    """
    job = client.query(q_summary)
    summary_row = next(iter(job.result(timeout=60)), None)
    # アラート内訳
    q_alerts = f"""
    SELECT alert_type, COUNT(*) AS cnt
    FROM `{project}.{ds}.v_latest_available_alerts`
    GROUP BY alert_type
    ORDER BY alert_type
    """
    job_alerts = client.query(q_alerts)
    alert_rows = [dict(r) for r in job_alerts.result(timeout=60)]
    # サマリタブの行構成
    out: list[list[Any]] = []
    out.append(["更新日", "店舗数", "平均評価", "総レビュー数"])
    if summary_row:
        out.append(
            [
                _cell_value(summary_row.get("snapshot_date")),
                summary_row.get("store_count"),
                summary_row.get("avg_rating"),
                summary_row.get("total_reviews"),
            ]
        )
    else:
        out.append(["", 0, "", 0])
    out.append([])
    out.append(["アラート種別", "件数"])
    for r in alert_rows:
        out.append([r.get("alert_type", ""), r.get("cnt", 0)])
    if not alert_rows:
        out.append(["（なし）", 0])
    return out


def _get_sheets_service():
    """Application Default Credentials で Sheets API クライアントを返す。"""
    from google.auth import default
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials, _ = default(scopes=scopes)
    return build("sheets", "v4", credentials=credentials)


def _ensure_tabs_exist(service: Any, sheet_id: str) -> None:
    """LATEST / ALERT / サマリ / 月次パフォーマンス タブが無ければ作成する。"""
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=sheet_id, fields="sheets(properties(title))")
        .execute()
    )
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    required = {
        config.SHEET_TAB_LATEST,
        config.SHEET_TAB_ALERT,
        config.SHEET_TAB_SUMMARY,
        config.SHEET_TAB_PERFORMANCE_MONTHLY,
    }
    missing = required - existing
    if not missing:
        return
    requests = [{"addSheet": {"properties": {"title": title}}} for title in sorted(missing)]
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": requests},
    ).execute()


def _clear_and_update(sheet_id: str, tab_name: str, rows: list[list[Any]]) -> None:
    """指定タブをクリアし、rows（ヘッダー含む）で上書き。"""
    if not rows:
        return
    service = _get_sheets_service()
    # 範囲: タブ名のみで「そのシート全体」を指す。行数で絞ってもよい。
    range_name = f"'{tab_name}'!A1"
    body = {"values": rows}
    # まず範囲を広めにクリア（最大 1000 行想定）
    clear_range = f"'{tab_name}'!A1:Z1000"
    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id,
        range=clear_range,
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_name,
        valueInputOption="USER_ENTERED",
        body=body,
    ).execute()


def write_latest_and_alerts() -> None:
    """
    SHEET_ID が設定されていれば、v_latest_available_ratings → LATEST、
    v_latest_available_alerts → ALERT、集計 → サマリ、
    v_latest_available_performance_monthly → SHEET_TAB_PERFORMANCE_MONTHLY タブを全置換する。
    未設定なら何もしない。直近の取込日で表示するため、当日の取込がなくても値が出る。
    必要なタブが無い場合は自動作成する。
    """
    import sys

    if not config.SHEET_ID:
        print(
            "[review_observation] Sheets skip: SHEET_ID not set",
            file=sys.stderr,
            flush=True,
        )
        return
    service = _get_sheets_service()
    _ensure_tabs_exist(service, config.SHEET_ID)
    client = bq_ops.get_client()
    latest_rows = _fetch_view(client, "v_latest_available_ratings", LATEST_COLUMNS)
    alert_rows = _fetch_view(client, "v_latest_available_alerts", ALERT_COLUMNS)
    perf_rows = _fetch_view(
        client,
        "v_latest_available_performance_monthly",
        PERFORMANCE_MONTHLY_COLUMNS,
    )
    summary_rows = _fetch_summary_rows(client)
    # 件数ログ（ヘッダー1行含む。0件なら VIEW が空か BQ 権限の可能性）
    n_latest = len(latest_rows)
    n_alert = len(alert_rows)
    n_perf = len(perf_rows)
    print(
        f"[review_observation] Sheets: LATEST={n_latest} rows, ALERT={n_alert} rows, "
        f"{config.SHEET_TAB_PERFORMANCE_MONTHLY}={n_perf} rows (from BQ)",
        flush=True,
    )
    if n_latest <= 1:
        print(
            "[review_observation] Sheets: v_latest_available_ratings returned no data rows; check BQ VIEW and ratings_daily_snapshot",
            file=sys.stderr,
            flush=True,
        )
    if n_perf <= 1:
        print(
            "[review_observation] Sheets: v_latest_available_performance_monthly returned no data rows; "
            "run scripts/sync_gbp_performance_to_bq.py and ensure sql/002 VIEW exists",
            file=sys.stderr,
            flush=True,
        )
    _clear_and_update(config.SHEET_ID, config.SHEET_TAB_LATEST, latest_rows)
    _clear_and_update(config.SHEET_ID, config.SHEET_TAB_ALERT, alert_rows)
    _clear_and_update(config.SHEET_ID, config.SHEET_TAB_SUMMARY, summary_rows)
    _clear_and_update(config.SHEET_ID, config.SHEET_TAB_PERFORMANCE_MONTHLY, perf_rows)
