# review_observation Cloud Run（最小構成）
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
ENV PYTHONPATH=/app
# Cloud Run は PORT を設定する
ENV PORT=8080
EXPOSE 8080

# --workers: 1 のとき、長時間の POST /（取込）が唯一のワーカーを占有し、
#   同時に届く GET /health（ウォームアップ）や POST /daily-summary がキューで待ち続け 504 になる。
#   2 以上にして取込と軽いエンドポイントを並行処理する（Cloud Run のリクエストタイムアウト 3600s に合わせる）。
# --timeout: ワーカーが応答しない秒数。取込が 1 時間かかる場合があるため 3600。
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "3600", "src.main:app"]
