#!/usr/bin/env python3
"""
tmp/Googleビジネスプロフィール集計.xlsx の GBPサマリー シートを読み、
performance_monthly_snapshot に MERGE（upsert）する。
- B列は店舗ごとに5行結合。店舗名はブロック先頭行の B のみ。
- 指標: ユーザー→impressions, 電話→calls, ルート検索→direction_requests, WEBサイト→website_clicks
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# リポジトリルートをパスに追加
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# シートの店舗名 → dim_store.store_id（文字列で store_code）
# dim_store の store_name と一致するもの + シート独自表記のオーバーライド
SHEET_STORE_NAME_TO_STORE_ID: dict[str, str] = {
    "川越": "3547880",
    "平塚": "3547881",
    "越谷": "3547882",
    "江戸川": "3547883",
    "松戸": "3547884",
    "東村山": "3547886",
    "幕張": "3547885",
    "川崎丸子橋": "3547887",
    "町田": "3547888",
    "八王子": "3547890",
    "習志野": "3547889",
    "さいたま見沼": "3547891",  # dim_store は「見沼」
    "新座": "3547892",
    "前橋": "3547893",
    "摂津": "3547894",
    "箕面": "3547895",
    "藤沢": "3547896",
    "福岡志免": "3547900",  # dim_store は「志免」
    "相模原": "3547899",
    "浜松": "3547904",
    "羽村": "3564156",
    "岡山": "3609787",
    "青梅": "3547897",
    "札幌西野": "3628425",
    "八王子高倉": "3677756",
    "高崎": "3708278",
    "名古屋北": "3723588",
    "札幌清田": "3642024",
    "高槻": "3568919",
    "藤岡": "3729747",
}


def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _month_to_date_str(v) -> str | None:
    if v is None:
        return None
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)[:10]


def load_xlsx(path: Path) -> list[tuple[str, str, int | None, int | None, int | None, int | None]]:
    """(store_code, snapshot_month, impressions, calls, direction_requests, website_clicks) のリストを返す。"""
    try:
        import openpyxl
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
        import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["GBPサマリー"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if len(rows) < 3:
        return []

    header = rows[1]  # 2行目: 店舗, 指標, 月...
    months = [_month_to_date_str(header[i]) for i in range(3, len(header)) if header[i]]

    out: list[tuple[str, str, int | None, int | None, int | None, int | None]] = []
    i = 2  # データ開始は3行目 (0-based: 2)
    while i + 5 <= len(rows):
        store_name = rows[i][1]  # B列（ブロック先頭＝結合セルの値）
        if not store_name or not str(store_name).strip():
            i += 5
            continue
        store_name = str(store_name).strip()
        store_code = SHEET_STORE_NAME_TO_STORE_ID.get(store_name)
        if not store_code:
            i += 5
            continue
        # 5行: ユーザー, 電話, ルート検索, WEBサイト, 合計
        row_imp = rows[i]
        row_calls = rows[i + 1]
        row_dr = rows[i + 2]
        row_web = rows[i + 3]
        for mi, month_str in enumerate(months):
            if not month_str:
                continue
            col = 3 + mi
            imp = _to_int(row_imp[col]) if col < len(row_imp) else None
            calls = _to_int(row_calls[col]) if col < len(row_calls) else None
            dr = _to_int(row_dr[col]) if col < len(row_dr) else None
            web = _to_int(row_web[col]) if col < len(row_web) else None
            out.append((store_code, month_str, imp, calls, dr, web))
        i += 5

    return out


def build_merge_sql(rows: list, project: str, dataset: str) -> str:
    """MERGE（upsert）用の SQL を組み立てる。"""
    table = f"`{project}.{dataset}.performance_monthly_snapshot`"
    lines = [
        "-- MERGE (upsert) from tmp/Googleビジネスプロフィール集計.xlsx GBPサマリー",
        f"MERGE {table} AS T",
        "USING (",
        "  SELECT * FROM UNNEST([",
    ]
    values = []
    for store_code, snapshot_month, imp, calls, dr, web in rows:
        imp_s = "CAST(NULL AS INT64)" if imp is None else str(imp)
        calls_s = "CAST(NULL AS INT64)" if calls is None else str(calls)
        dr_s = "CAST(NULL AS INT64)" if dr is None else str(dr)
        web_s = "CAST(NULL AS INT64)" if web is None else str(web)
        values.append(
            f"    STRUCT(DATE('{snapshot_month}') AS snapshot_month, '{store_code}' AS store_code, "
            f"{imp_s} AS impressions, {calls_s} AS calls, {dr_s} AS direction_requests, {web_s} AS website_clicks)"
        )
    lines.append(",\n".join(values))
    (lines.append("  ]) AS row"),)
    (lines.append(") AS S"),)
    (
        lines.append(
            "ON T.snapshot_month = S.snapshot_month AND T.store_code = S.store_code AND T.provider = 'google'"
        ),
    )
    (lines.append("WHEN MATCHED THEN"),)
    (lines.append("  UPDATE SET"),)
    (lines.append("    impressions = S.impressions,"),)
    (lines.append("    calls = S.calls,"),)
    (lines.append("    direction_requests = S.direction_requests,"),)
    (lines.append("    website_clicks = S.website_clicks,"),)
    (lines.append("    fetched_at = CURRENT_TIMESTAMP(),"),)
    (lines.append("    ingest_run_id = 'import_xlsx',"),)
    (lines.append("    status = 'ok'"),)
    (lines.append("WHEN NOT MATCHED THEN"),)
    (
        lines.append(
            "  INSERT (snapshot_month, store_code, provider, provider_place_id, impressions, calls, direction_requests, website_clicks, fetched_at, ingest_run_id, status)"
        ),
    )
    (
        lines.append(
            "  VALUES (S.snapshot_month, S.store_code, 'google', NULL, S.impressions, S.calls, S.direction_requests, S.website_clicks, CURRENT_TIMESTAMP(), 'import_xlsx', 'ok')"
        ),
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GBPサマリー xlsx を performance_monthly_snapshot に MERGE"
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=REPO_ROOT / "tmp" / "Googleビジネスプロフィール集計.xlsx",
        help="xlsx パス",
    )
    parser.add_argument("--project", default="ikeuchi-ga4", help="BigQuery プロジェクト")
    parser.add_argument("--dataset", default="mart_gbp", help="BigQuery データセット")
    parser.add_argument("--dry-run", action="store_true", help="SQL を出力して実行しない")
    args = parser.parse_args()

    if not args.xlsx.exists():
        print(f"Error: {args.xlsx} がありません", file=sys.stderr)
        return 1

    rows = load_xlsx(args.xlsx)
    if not rows:
        print("Error: 読み取った行が0件です", file=sys.stderr)
        return 1

    print(f"読み取り: {len(rows)} 行（店舗×月）")
    sql = build_merge_sql(rows, args.project, args.dataset)

    if args.dry_run:
        print(sql)
        return 0

    sql_file = REPO_ROOT / "sql" / "030_merge_monthly_from_xlsx.sql"
    sql_file.write_text(sql, encoding="utf-8")
    print(f"SQL を書き出し: {sql_file}")

    with open(sql_file, "r", encoding="utf-8") as f:
        ret = subprocess.run(
            [
                "bq",
                "query",
                f"--project_id={args.project}",
                "--location=asia-northeast1",
                "--use_legacy_sql=false",
            ],
            stdin=f,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
    if ret.returncode != 0:
        print(ret.stderr, file=sys.stderr)
        return ret.returncode
    print("MERGE 完了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
