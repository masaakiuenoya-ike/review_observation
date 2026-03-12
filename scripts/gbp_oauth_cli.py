#!/usr/bin/env python3
"""
GBP 用 OAuth を CLI で扱う統合スクリプト。

サブコマンド:
  get-refresh-token       … 初回のみ。ブラウザで同意後、refresh_token を表示する。
  get-access-token        … REFRESH_TOKEN から access_token を取得して表示する。
  fetch-locations         … access_token を取得して fetch_gbp_locations.py を実行する。
  request-quota-access   … クォータ 0 の場合に Basic API Access 申請フォームを開き、プロジェクト番号などを表示する。

前提:
  - get-refresh-token: CLIENT_ID, CLIENT_SECRET を環境変数に設定。GCP でリダイレクト URI に http://localhost:8080 を追加済みのこと。
  - get-access-token / fetch-locations: CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN を環境変数に設定。

使用例:
  export CLIENT_ID="xxx.apps.googleusercontent.com"
  export CLIENT_SECRET="GOCSPX-xxx"

  # 初回: refresh_token を取得
  python3 scripts/gbp_oauth_cli.py get-refresh-token
  # 表示された export REFRESH_TOKEN="..." を実行

  # locations 取得（dry-run）
  python3 scripts/gbp_oauth_cli.py fetch-locations --dry-run

  # access_token だけ欲しい場合
  python3 scripts/gbp_oauth_cli.py get-access-token
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
SCOPE = "https://www.googleapis.com/auth/business.manage"
REDIRECT_URI = "http://localhost:8080"
PORT = 8080
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _get_access_token_from_refresh(client_id: str, client_secret: str, refresh_token: str) -> str:
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if not r.ok:
        print(f"Token 取得に失敗しました: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    data = r.json()
    access = data.get("access_token")
    if not access:
        print("レスポンスに access_token が含まれていません。", file=sys.stderr)
        sys.exit(1)
    return access


def cmd_get_refresh_token() -> int:
    client_id = _env("CLIENT_ID")
    client_secret = _env("CLIENT_SECRET")
    if not client_id or not client_secret:
        print("CLIENT_ID と CLIENT_SECRET を環境変数に設定してください。", file=sys.stderr)
        return 1

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code"
        f"&scope={SCOPE}"
        "&access_type=offline"
        "&prompt=consent"
    )
    code_holder: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("/", "") and parsed.query:
                q = parse_qs(parsed.query)
                code_holder.extend(q.get("code", []))
            body = b"<html><body><p>Close this tab and return to the terminal.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    print("1) 次の URL をブラウザで開いて、アクセスを許可してください:")
    print(auth_url)
    print()
    print("2) 同意後、このターミナルに戻ってください。")
    print()

    server = HTTPServer(("", PORT), Handler)
    try:
        server.handle_request()
    except KeyboardInterrupt:
        pass
    server.server_close()

    if not code_holder:
        print(
            "認証コードを取得できませんでした。リダイレクト URI に http://localhost:8080 を追加済みか確認してください。",
            file=sys.stderr,
        )
        return 1

    code = code_holder[0]
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if not r.ok:
        print(f"Token 交換に失敗しました: {r.status_code} {r.text}", file=sys.stderr)
        return 1
    data = r.json()
    refresh = data.get("refresh_token")
    if not refresh:
        print(
            "レスポンスに refresh_token が含まれていません。prompt=consent で再試行してください。",
            file=sys.stderr,
        )
        return 1
    print("--- refresh_token（次のコマンドを実行して環境変数に設定）---")
    print(f'export REFRESH_TOKEN="{refresh}"')
    print("---")
    return 0


def cmd_get_access_token() -> int:
    client_id = _env("CLIENT_ID")
    client_secret = _env("CLIENT_SECRET")
    refresh_token = _env("REFRESH_TOKEN")
    if not all((client_id, client_secret, refresh_token)):
        print(
            "CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN を環境変数に設定してください。",
            file=sys.stderr,
        )
        return 1
    access = _get_access_token_from_refresh(client_id, client_secret, refresh_token)
    print("--- access_token（次のコマンドでスクリプトに渡せます）---")
    print(f'export ACCESS_TOKEN="{access}"')
    print("---")
    return 0


def cmd_fetch_locations(extra_args: list[str]) -> int:
    client_id = _env("CLIENT_ID")
    client_secret = _env("CLIENT_SECRET")
    refresh_token = _env("REFRESH_TOKEN")
    access_token = _env("ACCESS_TOKEN")

    if access_token and len(access_token) > 10:
        token = access_token
        print("Using ACCESS_TOKEN from environment")
    elif client_id and client_secret and refresh_token:
        token = _get_access_token_from_refresh(client_id, client_secret, refresh_token)
        print("Got access_token from REFRESH_TOKEN")
    else:
        print(
            "ACCESS_TOKEN を設定するか、CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN を設定してください。",
            file=sys.stderr,
        )
        return 1

    script = REPO_ROOT / "scripts" / "fetch_gbp_locations.py"
    cmd = [
        sys.executable,
        str(script),
        "--access-token",
        token,
        *extra_args,
    ]
    return subprocess.run(cmd, cwd=str(REPO_ROOT), env={**os.environ}).returncode


def cmd_request_quota_access() -> int:
    """クォータ申請フォームを開き、プロジェクト番号などを表示する。"""
    import webbrowser

    form_url = "https://support.google.com/business/contact/api_default"
    project_number = "957418534824"
    print("GBP API のクォータが 0 の場合、Basic API Access を申請してください。")
    print()
    print("申請フォーム:", form_url)
    print("フォームのドロップダウンで「Application for Basic API Access」を選択。")
    print()
    print("申請時に必要な情報:")
    print(f"  プロジェクト番号: {project_number}")
    print()
    try:
        webbrowser.open(form_url)
        print("ブラウザでフォームを開きました。")
    except Exception:
        print("上記 URL を手動で開いてください。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GBP OAuth CLI: refresh_token 取得 / access_token 取得 / locations 取得 / クォータ申請"
    )
    parser.add_argument(
        "command",
        choices=[
            "get-refresh-token",
            "get-access-token",
            "fetch-locations",
            "request-quota-access",
        ],
        help="get-refresh-token, get-access-token, fetch-locations, request-quota-access",
    )
    args, extra = parser.parse_known_args()

    if args.command == "get-refresh-token":
        return cmd_get_refresh_token()
    if args.command == "get-access-token":
        return cmd_get_access_token()
    if args.command == "fetch-locations":
        return cmd_fetch_locations(extra)
    if args.command == "request-quota-access":
        return cmd_request_quota_access()
    return 1


if __name__ == "__main__":
    sys.exit(main())
