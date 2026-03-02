"""
review_observation Cloud Run エントリポイント（最小構成）。
GET /health, POST / を提供。本番処理は順次実装。
"""

import os
from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return "", 200


@app.route("/", methods=["POST"])
def run_ingest():
    # 最小応答（定点観測の実装は Phase 2 以降）
    return jsonify({"ok": True, "message": "ingest stub"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
