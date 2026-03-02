"""GBP API 用 OAuth 2.0 アクセストークン取得。Secret Manager の refresh_token で取得。"""

from __future__ import annotations

import json
from typing import Any

import requests

try:
    from google.cloud import secretmanager
except ImportError:
    secretmanager = None


def _get_oauth_json_from_secret(secret_name: str, project_id: str) -> dict[str, Any]:
    if not secretmanager:
        raise RuntimeError("google-cloud-secret-manager is required")
    client = secretmanager.SecretManagerServiceClient()
    name = (
        secret_name
        if secret_name.startswith("projects/")
        else f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    )
    response = client.access_secret_version(request={"name": name})
    return json.loads(response.payload.data.decode("utf-8"))


def get_access_token(oauth_json: dict[str, Any]) -> str:
    """client_id, client_secret, refresh_token を含む dict から access_token を取得。"""
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": oauth_json["client_id"],
            "client_secret": oauth_json["client_secret"],
            "refresh_token": oauth_json["refresh_token"],
            "grant_type": "refresh_token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def get_gbp_access_token(secret_name: str, project_id: str) -> str:
    """Secret Manager から OAuth JSON を取得し、GBP 用 access_token を返す。"""
    oauth = _get_oauth_json_from_secret(secret_name, project_id)
    return get_access_token(oauth)
