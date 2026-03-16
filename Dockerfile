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

# --timeout: 31店舗の取込は数分かかることがあるため 600 秒（Cloud Run のリクエストタイムアウトも 600 以上にすること）
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "600", "src.main:app"]
