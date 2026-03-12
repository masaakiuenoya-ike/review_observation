#!/usr/bin/env python3
"""
GBP 用 OAuth の refresh_token を取得するヘルパー。
localhost:8080 でリダイレクトを受け取り、認証コードを code に交換して refresh_token を表示する。

事前に GCP コンソールで OAuth クライアントに
「リダイレクト URI」として http://localhost:8080 を追加すること。

使い方:
  export CLIENT_ID="xxx.apps.googleusercontent.com"
  export CLIENT_SECRET="GOCSPX-xxx"
  python3 scripts/oauth_capture_code.py
  # 表示された URL をブラウザで開く → 同意 → リダイレクト後、ターミナルに refresh_token が表示される
"""

from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

SCOPE = "https://www.googleapis.com/auth/business.manage"
REDIRECT_URI = "http://localhost:8080"
PORT = 8080


def main() -> None:
    client_id = os.environ.get("CLIENT_ID", "").strip()
    client_secret = os.environ.get("CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("CLIENT_ID と CLIENT_SECRET を環境変数に設定してください。", file=sys.stderr)
        sys.exit(1)

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
            "認証コードを取得できませんでした。ブラウザで URL を開き、同意後に localhost:8080 にリダイレクトされたか確認してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    code = code_holder[0]
    r = requests.post(
        "https://oauth2.googleapis.com/token",
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
        sys.exit(1)
    data = r.json()
    refresh = data.get("refresh_token")
    if not refresh:
        print(
            "レスポンスに refresh_token が含まれていません。prompt=consent で再試行するか、既に同意済みの場合は一度アプリのアクセスを解除してから再度実行してください。",
            file=sys.stderr,
        )
        print("レスポンス:", data, file=sys.stderr)
        sys.exit(1)
    print("--- refresh_token (環境変数にコピーして使ってください) ---")
    print(refresh)
    print("---")
    print('export REFRESH_TOKEN="' + refresh + '"')
