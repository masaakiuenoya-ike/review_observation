"""
BigQuery VIEW（v_latest_with_delta_ratings / v_rating_alerts）を参照し、
Google Sheets の LATEST / ALERT タブを全置換する。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from . import config
from . import bq_ops


# LATEST タブの列（v_latest_with_delta_ratings の順）
LATEST_COLUMNS = [
    "snapshot_date",
    "store_code",
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

# ALERT タブの列（v_rating_alerts の順）
ALERT_COLUMNS = [
    "snapshot_date",
    "store_code",
    "provider",
    "alert_type",
    "rating_value",
    "delta_rating",
    "delta_review_count",
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


def _get_sheets_service():
    """Application Default Credentials で Sheets API クライアントを返す。"""
    from google.auth import default
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials, _ = default(scopes=scopes)
    return build("sheets", "v4", credentials=credentials)


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
    SHEET_ID が設定されていれば、v_latest_with_delta_ratings → LATEST タブ、
    v_rating_alerts → ALERT タブを全置換する。未設定なら何もしない。
    """
    if not config.SHEET_ID:
        return
    client = bq_ops.get_client()
    latest_rows = _fetch_view(client, "v_latest_with_delta_ratings", LATEST_COLUMNS)
    alert_rows = _fetch_view(client, "v_rating_alerts", ALERT_COLUMNS)
    _clear_and_update(config.SHEET_ID, config.SHEET_TAB_LATEST, latest_rows)
    _clear_and_update(config.SHEET_ID, config.SHEET_TAB_ALERT, alert_rows)
