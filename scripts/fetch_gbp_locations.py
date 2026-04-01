#!/usr/bin/env python3
"""
GBP API で accounts と locations を取得し、
locationName と dim_store を突き合わせて places_provider_map の
provider_place_id および緯度経度を UPDATE する。
GBP の latlng が空の店舗は metadata.placeId + Maps Place Details、または住所の Geocoding で補完する（要 GOOGLE_MAPS_API_KEY）。
"""

from __future__ import annotations

import argparse
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


def _extract_lat_lng(loc: dict) -> tuple[float | None, float | None]:
    """GBP location の latlng（v4 / v1 想定）から緯度・経度を取り出す。"""
    ll = loc.get("latlng") or loc.get("latLng")
    if not isinstance(ll, dict):
        return None, None
    lat = ll.get("latitude")
    lng = ll.get("longitude")
    if lat is None or lng is None:
        return None, None
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None, None


def _location_id_from_resource_name(provider_place_id: str) -> str | None:
    """accounts/.../locations/{id} から locationId を抽出。"""
    if "/locations/" not in provider_place_id:
        return None
    return provider_place_id.split("/locations/")[-1].split("/")[0] or None


def _account_id_from_resource_name(provider_place_id: str) -> str | None:
    """accounts/{accountId}/locations/... から accountId を抽出。"""
    if not provider_place_id.startswith("accounts/"):
        return None
    parts = provider_place_id.split("/")
    if len(parts) < 2:
        return None
    return parts[1] or None


def _v1_get_location(
    access_token: str, path_suffix: str, read_mask: str
) -> dict | None:
    """Business Information v1 locations.get。成功時は JSON dict、失敗時は None。"""
    url = f"https://mybusinessbusinessinformation.googleapis.com/v1/{path_suffix}"
    r = _get_with_retry(
        url,
        {"Authorization": f"Bearer {access_token}"},
        {"readMask": read_mask},
        "locations.get(v1)",
    )
    if r.ok:
        try:
            return r.json()
        except Exception:
            return None
    return None


def _place_details_latlng(place_id: str, maps_api_key: str) -> tuple[float | None, float | None]:
    """Maps Places Details（legacy）で geometry/location を取得。"""
    if not place_id or not maps_api_key:
        return None, None
    r = requests.get(
        "https://maps.googleapis.com/maps/api/place/details/json",
        params={
            "place_id": place_id,
            "fields": "geometry/location",
            "key": maps_api_key,
        },
        timeout=30,
    )
    if not r.ok:
        return None, None
    try:
        data = r.json()
    except Exception:
        return None, None
    if data.get("status") not in ("OK",):
        return None, None
    loc = (data.get("result") or {}).get("geometry", {}).get("location") or {}
    try:
        lat, lng = loc.get("lat"), loc.get("lng")
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    except (TypeError, ValueError):
        pass
    return None, None


def _postal_address_to_geocode_query(addr: dict) -> str:
    """v1 PostalAddress を Geocoding 用の 1 行に近い文字列へ。"""
    parts: list[str] = []
    for line in addr.get("addressLines") or []:
        line = (line or "").strip()
        if line:
            parts.append(line)
    for key in ("postalCode", "locality", "administrativeArea"):
        v = (addr.get(key) or "").strip()
        if v:
            parts.append(v)
    rc = (addr.get("regionCode") or "").strip()
    if rc:
        parts.append(rc)
    return ", ".join(parts)


def _geocode_latlng(address_query: str, maps_api_key: str) -> tuple[float | None, float | None]:
    if not address_query.strip() or not maps_api_key:
        return None, None
    r = requests.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={
            "address": address_query,
            "key": maps_api_key,
            "region": "jp",
        },
        timeout=30,
    )
    if not r.ok:
        return None, None
    try:
        data = r.json()
    except Exception:
        return None, None
    if data.get("status") != "OK" or not data.get("results"):
        return None, None
    loc = (data["results"][0].get("geometry") or {}).get("location") or {}
    try:
        lat, lng = loc.get("lat"), loc.get("lng")
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    except (TypeError, ValueError):
        pass
    return None, None


def _metadata_place_id_v4(loc: dict) -> str | None:
    meta = loc.get("metadata") or {}
    pid = (meta.get("placeId") or "").strip()
    return pid or None


def _metadata_place_id_v1(loc: dict) -> str | None:
    meta = loc.get("metadata") or {}
    pid = (meta.get("placeId") or "").strip()
    return pid or None


def _fetch_latlng_detail(
    access_token: str,
    provider_place_id: str,
    maps_api_key: str | None = None,
) -> tuple[float | None, float | None]:
    """
    リストで latlng が空の店舗を埋める。
    GBP は「ユーザー指定の latlng」のみ返すことが多いため、最後に metadata.placeId
    + Maps Place Details、または storefrontAddress + Geocoding を試す（要 GOOGLE_MAPS_API_KEY）。
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    loc_id = _location_id_from_resource_name(provider_place_id)
    account_id = _account_id_from_resource_name(provider_place_id)

    v1_paths: list[str] = []
    if loc_id and account_id:
        v1_paths.append(f"accounts/{account_id}/locations/{loc_id}")
    if loc_id:
        v1_paths.append(f"locations/{loc_id}")

    for path in v1_paths:
        body = _v1_get_location(access_token, path, "latlng")
        if body:
            lat, lng = _extract_lat_lng(body)
            if lat is not None and lng is not None:
                return lat, lng

    v4_url = f"https://mybusiness.googleapis.com/v4/{provider_place_id}"
    r = _get_with_retry(v4_url, headers, None, "locations.get(v4)")
    if r.ok:
        try:
            j = r.json()
        except Exception:
            j = {}
        lat, lng = _extract_lat_lng(j)
        if lat is not None and lng is not None:
            return lat, lng
        pid = _metadata_place_id_v4(j)
        if pid and maps_api_key:
            lat, lng = _place_details_latlng(pid, maps_api_key)
            if lat is not None and lng is not None:
                return lat, lng
        addr = j.get("address")
        if isinstance(addr, dict) and maps_api_key:
            q = _postal_address_to_geocode_query(addr)
            lat, lng = _geocode_latlng(q, maps_api_key)
            if lat is not None and lng is not None:
                return lat, lng

    for path in v1_paths:
        body = _v1_get_location(access_token, path, "metadata")
        if body:
            pid = _metadata_place_id_v1(body)
            if pid and maps_api_key:
                lat, lng = _place_details_latlng(pid, maps_api_key)
                if lat is not None and lng is not None:
                    return lat, lng

    if maps_api_key:
        for path in v1_paths:
            body = _v1_get_location(access_token, path, "storefrontAddress")
            if body:
                addr = body.get("storefrontAddress") or {}
                if isinstance(addr, dict):
                    q = _postal_address_to_geocode_query(addr)
                    lat, lng = _geocode_latlng(q, maps_api_key)
                    if lat is not None and lng is not None:
                        return lat, lng

    return None, None


def _format_bq_float(x: float) -> str:
    """BigQuery 数値リテラル用（科学記法を避けつつ過度に長くしない）。"""
    s = format(float(x), ".15g")
    if s in ("nan", "inf", "-inf"):
        raise ValueError(f"invalid coordinate for SQL: {s!r}")
    return s


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
    params: dict = {"pageSize": 100, "readMask": "name,title,storeCode,latlng"}
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
        params = {"pageSize": 100, "pageToken": token, "readMask": "name,title,storeCode,latlng"}
    return out


def _enrich_rows_latlng_via_get(
    access_token: str,
    rows: list[tuple[str, str, str, float | None, float | None]],
    maps_api_key: str | None,
) -> list[tuple[str, str, str, float | None, float | None]]:
    """各行で緯度経度が欠ける場合、GBP GET / Maps で埋める。"""
    out: list[tuple[str, str, str, float | None, float | None]] = []
    filled = 0
    for store_code, provider_place_id, location_name, lat, lng in rows:
        if lat is None or lng is None:
            lat2, lng2 = _fetch_latlng_detail(
                access_token, provider_place_id, maps_api_key
            )
            if lat2 is not None and lng2 is not None:
                lat, lng = lat2, lng2
                filled += 1
        out.append((store_code, provider_place_id, location_name, lat, lng))
    if filled:
        print(f"GET（GBP / Maps）で座標を補完した行: {filled}", file=sys.stderr)
    return out


def _rows_to_by_store(
    rows: list[tuple[str, str, str, float | None, float | None]],
) -> dict[str, tuple[str, str, float | None, float | None]]:
    """store_code -> (provider_place_id, location_name, lat, lng)"""
    d: dict[str, tuple[str, str, float | None, float | None]] = {}
    for store_code, provider_place_id, location_name, lat, lng in rows:
        d[store_code] = (provider_place_id, location_name, lat, lng)
    return d


def _merge_bq_google_missing_coords(
    access_token: str,
    by_store: dict[str, tuple[str, str, float | None, float | None]],
    bq_project: str,
    bq_dataset: str,
    bq_location: str,
    maps_api_key: str | None,
) -> int:
    """
    BQ 上で google かつ座標 NULL の行を対象に locations.get で座標を埋める。
    API リストに出てこない店舗コードもここで拾う。
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=bq_project, location=bq_location)
    table = f"`{bq_project}.{bq_dataset}.places_provider_map`"
    q = f"""
    SELECT store_code, provider_place_id
    FROM {table}
    WHERE provider = 'google'
      AND provider_place_id LIKE 'accounts/%'
      AND (latitude IS NULL OR longitude IS NULL)
    """
    filled = 0
    for row in client.query(q, location=bq_location).result():
        sc = row.store_code
        pid = row.provider_place_id
        _, locname, lat, lng = by_store.get(sc, (pid, "", None, None))
        if lat is not None and lng is not None:
            continue
        lat2, lng2 = _fetch_latlng_detail(access_token, pid, maps_api_key)
        if lat2 is None or lng2 is None:
            continue
        by_store[sc] = (pid, locname, lat2, lng2)
        filled += 1
    return filled


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
    parser.add_argument(
        "--dry-run", action="store_true", help="UPDATE せず一覧と SQL を出力するだけ"
    )
    parser.add_argument(
        "--no-update", action="store_true", help="UPDATE を実行しない（fetch と SQL 生成のみ）"
    )
    parser.add_argument(
        "--access-token",
        type=str,
        help="既に取得した ACCESS_TOKEN（未指定時は Secret Manager から取得）",
    )
    parser.add_argument(
        "--skip-bq-coords-backfill",
        action="store_true",
        help="BQ を読まず API から得た行だけを対象にする（欠損が残る場合あり）",
    )
    parser.add_argument(
        "--maps-api-key",
        type=str,
        default="",
        help="Google Maps API キー（Place Details / Geocoding）。未指定時は環境変数 GOOGLE_MAPS_API_KEY",
    )
    args = parser.parse_args()

    from src import config as app_config

    maps_api_key = (args.maps_api_key or "").strip() or (
        app_config.GOOGLE_MAPS_API_KEY or None
    )
    if not maps_api_key:
        print(
            "注意: GOOGLE_MAPS_API_KEY または --maps-api-key がありません。"
            "GBP が latlng を返さない店舗は座標が埋まりません（Place ID / 住所ジオコードを使う場合はキーが必要です）。",
            file=sys.stderr,
        )

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
                print(
                    f"  Account {aid}: 404 (locations なしまたは別 API のアカウントのためスキップ)",
                    file=sys.stderr,
                )
                continue
            raise

    # name = accounts/{accountId}/locations/{locationId}
    # locationName = 表示名
    # (store_code, provider_place_id, locationName, latitude?, longitude?)
    rows: list[tuple[str, str, str, float | None, float | None]] = []
    unmatched: list[str] = []
    for loc in all_locations:
        name = loc.get("name") or ""
        location_name = (loc.get("locationName") or "").strip()
        store_code = _match_store_code(location_name)
        lat, lng = _extract_lat_lng(loc)
        if store_code:
            rows.append((store_code, name, location_name, lat, lng))
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

    print("lists で欠けた座標を GBP / Maps で補完します...", file=sys.stderr)
    rows = _enrich_rows_latlng_via_get(token, rows, maps_api_key)
    by_store = _rows_to_by_store(rows)

    if not args.skip_bq_coords_backfill:
        try:
            n_bq = _merge_bq_google_missing_coords(
                token,
                by_store,
                app_config.BQ_PROJECT,
                app_config.BQ_DATASET,
                app_config.BQ_LOCATION,
                maps_api_key,
            )
            if n_bq:
                print(f"BQ 上の google 欠損行を locations.get で補完: {n_bq} 行", file=sys.stderr)
        except Exception as e:
            print(f"Warning: BQ 座標バックフィルをスキップ — {e}", file=sys.stderr)

    # SQL 生成（dict を store_code 順に）
    sql_lines = [
        "-- provider_place_id / latitude / longitude（latlng 取得時）を GBP API 結果で UPDATE",
        "BEGIN;",
    ]
    for store_code in sorted(by_store.keys()):
        provider_place_id, location_name, lat, lng = by_store[store_code]
        escaped = (provider_place_id or "").replace("'", "''")
        coord_sql = ""
        if lat is not None and lng is not None:
            try:
                coord_sql = (
                    f", latitude = {_format_bq_float(lat)}, "
                    f"longitude = {_format_bq_float(lng)}"
                )
            except ValueError:
                coord_sql = ""
        sql_lines.append(
            f"UPDATE `ikeuchi-ga4.mart_gbp.places_provider_map` "
            f"SET provider_place_id = '{escaped}'{coord_sql}, "
            f"updated_at = CURRENT_TIMESTAMP() "
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
