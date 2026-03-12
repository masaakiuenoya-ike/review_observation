#!/usr/bin/env python3
"""
GBP API で accounts と locations を取得し、
locationName と dim_store を突き合わせて places_provider_map の provider_place_id を UPDATE する。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# GBP locationName（例: 池内自動車 習志野店）から store_code を決めるための対応表。
# キーは「店舗名の一部」（locationName に含まれる文字列）。値は dim_store の store_id（文字列）。
LOCATION_NAME_TO_STORE_CODE: dict[str, str] = {
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
    "見沼": "3547891",
    "さいたま見沼": "3547891",
    "新座": "3547892",
    "前橋": "3547893",
    "摂津": "3547894",
    "箕面": "3547895",
    "藤沢": "3547896",
    "志免": "3547900",
    "福岡志免": "3547900",
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
    "四日市": "3800875",
    "立川": "3802118",
    "栃木": "3802119",
    "入間": "3825904",
    "大垣": "3754805",
    "天理": "3745137",
    "盛岡": "3779233",
    "姫路": "3669685",
    "本庄": "3718953",
    "宝塚": "3719415",
    "垂水": "3600761",
    "泉南": "3609812",
    "長岡京": "3568912",
    "茨木": "3568922",
}


def _match_store_code(location_name: str) -> str | None:
    """locationName から store_code を推定。最長一致でキーを探す。"""
    if not location_name:
        return None
    # 長いキーから試す（例: さいたま見沼 > 見沼）
    for key in sorted(LOCATION_NAME_TO_STORE_CODE.keys(), key=len, reverse=True):
        if key in location_name:
            return LOCATION_NAME_TO_STORE_CODE[key]
    return None


def _check_response(r: requests.Response, context: str) -> None:
    """4xx/5xx のときレスポンス本文を stderr に出力してから raise_for_status。"""
    if not r.ok:
        try:
            body = r.text
            if body:
                print(f"API Error ({context}): {r.status_code} - {body[:500]}", file=sys.stderr)
        except Exception:
            pass
        r.raise_for_status()


def _get_with_retry(
    url: str,
    headers: dict,
    params: dict | None,
    context: str,
    max_retries: int = 3,
    wait_seconds: int = 65,
) -> requests.Response:
    """429 のとき wait_seconds 待ってリトライする。"""
    import time
    r = None
    for attempt in range(max_retries):
        r = requests.get(url, headers=headers, params=params or {}, timeout=30)
        if r.status_code == 429 and attempt < max_retries - 1:
            print(
                f"Rate limit (429). Waiting {wait_seconds}s before retry {attempt + 2}/{max_retries}...",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
            continue
        return r
    assert r is not None
    return r


def fetch_accounts(access_token: str) -> list[str]:
    """accountId のリストを返す。"""
    url = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
    headers = {"Authorization": f"Bearer {access_token}"}
    r = _get_with_retry(url, headers, None, "accounts.list")
    _check_response(r, "accounts.list")
    data = r.json()
    account_ids = []
    for acc in data.get("accounts", []):
        name = acc.get("name", "")
        if name.startswith("accounts/"):
            aid = name.replace("accounts/", "").split("/")[0]
            if aid:
                account_ids.append(aid)
    return account_ids


def _fetch_locations_v4(access_token: str, account_id: str) -> list[dict]:
    """My Business API v4 で locations を取得。"""
    base = "https://mybusiness.googleapis.com/v4"
    url = f"{base}/accounts/{account_id}/locations"
    params: dict = {"pageSize": 100}
    out = []
    while True:
        r = _get_with_retry(
            url,
            {"Authorization": f"Bearer {access_token}"},
            params,
            "locations.list(v4)",
        )
        if r.status_code == 404:
            raise requests.exceptions.HTTPError("404", response=r)
        _check_response(r, "locations.list(v4)")
        data = r.json()
        out.extend(data.get("locations", []))
        token = data.get("nextPageToken")
        if not token:
            break
        params = {"pageSize": 100, "pageToken": token}
    return out


def _fetch_locations_v1(access_token: str, account_id: str) -> list[dict]:
    """Business Information API v1 で locations を取得。v4 が 404 のときのフォールバック。"""
    base = "https://mybusinessbusinessinformation.googleapis.com/v1"
    url = f"{base}/accounts/{account_id}/locations"
    params: dict = {"pageSize": 100, "readMask": "name,title,storeCode"}
    out = []
    while True:
        r = _get_with_retry(
            url,
            {"Authorization": f"Bearer {access_token}"},
            params,
            "locations.list(v1)",
        )
        if r.status_code == 403:
            try:
                err = r.json()
                msg = (err.get("error") or {}).get("message") or r.text
                if "mybusinessbusinessinformation" in msg.lower() or "has not been used" in msg:
                    print(
                        "\nBusiness Information API が無効です。GCP コンソールで有効にしてください:",
                        file=sys.stderr,
                    )
                    print(
                        "  https://console.developers.google.com/apis/api/mybusinessbusinessinformation.googleapis.com/overview",
                        file=sys.stderr,
                    )
                    print(
                        "  gcloud: gcloud services enable mybusinessbusinessinformation.googleapis.com --project=PROJECT_ID",
                        file=sys.stderr,
                    )
            except Exception:
                pass
        _check_response(r, "locations.list(v1)")
        data = r.json()
        for loc in data.get("locations", []):
            loc = dict(loc)
            # v1 の name は "locations/{locationId}" 形式のため、accounts/.../locations/... に正規化
            name = loc.get("name") or ""
            if name.startswith("locations/") and not name.startswith("accounts/"):
                loc["name"] = f"accounts/{account_id}/{name}"
            # 既存ロジックは locationName を参照するので、v1 の title を locationName として扱う
            if "locationName" not in loc:
                loc["locationName"] = (loc.get("title") or "").strip()
            out.append(loc)
        token = data.get("nextPageToken")
        if not token:
            break
        params = {"pageSize": 100, "pageToken": token, "readMask": "name,title,storeCode"}
    return out


def fetch_locations(access_token: str, account_id: str) -> list[dict]:
    """指定アカウントの全 location を返す。v4 を試し、404 なら v1 にフォールバック。"""
    try:
        return _fetch_locations_v4(access_token, account_id)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return _fetch_locations_v1(access_token, account_id)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="GBP locations 取得 → places_provider_map UPDATE")
    parser.add_argument("--dry-run", action="store_true", help="UPDATE せず一覧と SQL を出力するだけ")
    parser.add_argument("--no-update", action="store_true", help="UPDATE を実行しない（fetch と SQL 生成のみ）")
    parser.add_argument("--access-token", type=str, help="既に取得した ACCESS_TOKEN（未指定時は Secret Manager から取得）")
    args = parser.parse_args()

    import os

    if args.access_token:
        token = args.access_token.strip()
        print("Using ACCESS_TOKEN from --access-token")
    else:
        from src.config import GBP_OAUTH_SECRET_NAME, GCP_PROJECT
        from src import gbp_oauth

        print("Getting access token from Secret Manager...")
        token = gbp_oauth.get_gbp_access_token(GBP_OAUTH_SECRET_NAME, GCP_PROJECT)
    print("Fetching accounts...")
    account_ids = fetch_accounts(token)
    if not account_ids:
        print("No accounts found.", file=sys.stderr)
        return 1
    print(f"Accounts: {account_ids}")

    all_locations: list[dict] = []
    for aid in account_ids:
        try:
            locs = fetch_locations(token, aid)
            print(f"  Account {aid}: {len(locs)} locations")
            for loc in locs:
                loc["_account_id"] = aid
            all_locations.extend(locs)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                print(f"  Account {aid}: 404 (locations なしまたは別 API のアカウントのためスキップ)", file=sys.stderr)
                continue
            raise

    # name = accounts/{accountId}/locations/{locationId}
    # locationName = 表示名
    rows: list[tuple[str, str, str]] = []  # (store_code, provider_place_id, locationName)
    unmatched: list[str] = []
    for loc in all_locations:
        name = loc.get("name") or ""
        location_name = (loc.get("locationName") or "").strip()
        store_code = _match_store_code(location_name)
        if store_code:
            rows.append((store_code, name, location_name))
        else:
            unmatched.append(f"  {name}  locationName={location_name!r}")

    print(f"\nMatched: {len(rows)}  Unmatched: {len(unmatched)}")
    if unmatched:
        print("Unmatched locations (manual mapping needed):")
        for u in unmatched[:30]:
            print(u)
        if len(unmatched) > 30:
            print(f"  ... and {len(unmatched) - 30} more")

    if not rows:
        print("No rows to update.", file=sys.stderr)
        return 1

    # SQL 生成
    sql_lines = [
        "-- provider_place_id を GBP API 取得結果で UPDATE",
        "BEGIN;",
    ]
    for store_code, provider_place_id, location_name in sorted(rows, key=lambda x: x[0]):
        escaped = provider_place_id.replace("'", "''")
        sql_lines.append(
            f"UPDATE `ikeuchi-ga4.mart_gbp.places_provider_map` "
            f"SET provider_place_id = '{escaped}', updated_at = CURRENT_TIMESTAMP() "
            f"WHERE store_code = '{store_code}' AND provider = 'google';"
        )
    sql_lines.append("COMMIT;")
    sql = "\n".join(sql_lines)

    out_sql = REPO_ROOT / "sql" / "050_update_provider_place_id_from_gbp.sql"
    out_sql.write_text(sql, encoding="utf-8")
    print(f"\nWrote {out_sql}")

    if args.dry_run or args.no_update:
        print("\n--- Generated SQL (first 20 lines) ---")
        print("\n".join(sql_lines[:20]))
        if len(sql_lines) > 20:
            print("...")
        return 0

    # BQ で実行（BEGIN/COMMIT は BQ では別の扱いなので、1 文ずつ実行するか、または BEGIN/COMMIT を外す）
    from google.cloud import bigquery
    from src import config

    client = bigquery.Client(project=config.BQ_PROJECT, location=config.BQ_LOCATION)
    for line in sql_lines:
        line = line.strip()
        if not line or line.startswith("--") or line in ("BEGIN;", "COMMIT;"):
            continue
        client.query(line).result()
        print(f"  Ran: {line[:60]}...")
    print("Done.")
    return 0


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        print(
            "Warning: Python 3.10+ is recommended. Python 3.9 may raise importlib.metadata errors.",
            file=sys.stderr,
        )
    sys.exit(main())
