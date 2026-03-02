"""
BigQuery: places_provider_map 読込、ratings_daily_snapshot MERGE、reviews MERGE。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from google.cloud import bigquery

from . import config


def get_client() -> bigquery.Client:
    return bigquery.Client(project=config.BQ_PROJECT, location=config.BQ_LOCATION)


def load_places_provider_map(
    *,
    provider: str = "google",
    is_active: bool = True,
    require_place_id: bool = True,
) -> list[dict[str, Any]]:
    """places_provider_map を読む。require_place_id=True のとき provider_place_id が空でない行のみ。"""
    client = get_client()
    ds = config.BQ_DATASET
    cond = "provider = @provider AND is_active = @is_active"
    if require_place_id:
        cond += " AND COALESCE(TRIM(provider_place_id), '') != ''"
    query = f"""
        SELECT store_code, provider, provider_place_id, display_name
        FROM `{config.BQ_PROJECT}.{ds}.places_provider_map`
        WHERE {cond}
        ORDER BY store_code
    """
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("provider", "STRING", provider),
                bigquery.ScalarQueryParameter("is_active", "BOOL", is_active),
            ]
        ),
    )
    return [dict(row) for row in job.result()]


def merge_ratings_daily_snapshot(
    snapshot_date: date,
    ingest_run_id: str,
    rows: list[dict[str, Any]],
) -> None:
    """ratings_daily_snapshot に MERGE（snapshot_date + store_code + provider）。"""
    if not rows:
        return
    client = get_client()
    ds = config.BQ_DATASET
    table = f"{config.BQ_PROJECT}.{ds}.ratings_daily_snapshot"
    # 1 行ずつ MERGE（簡易実装。まとめて UNNEST でも可）
    for r in rows:
        sql = f"""
        MERGE `{table}` AS T
        USING (SELECT
            @snapshot_date AS snapshot_date,
            @store_code AS store_code,
            @provider AS provider,
            @provider_place_id AS provider_place_id,
            @rating_value AS rating_value,
            @review_count AS review_count,
            @ingest_run_id AS ingest_run_id,
            @status AS status
        ) AS S
        ON T.snapshot_date = S.snapshot_date AND T.store_code = S.store_code AND T.provider = S.provider
        WHEN MATCHED THEN UPDATE SET
            provider_place_id = S.provider_place_id,
            rating_value = S.rating_value,
            review_count = S.review_count,
            fetched_at = CURRENT_TIMESTAMP(),
            ingest_run_id = S.ingest_run_id,
            status = S.status
        WHEN NOT MATCHED THEN INSERT (
            snapshot_date, store_code, provider, provider_place_id,
            rating_value, review_count, fetched_at, ingest_run_id, status
        ) VALUES (
            S.snapshot_date, S.store_code, S.provider, S.provider_place_id,
            S.rating_value, S.review_count, CURRENT_TIMESTAMP(), S.ingest_run_id, S.status
        )
        """
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(
                        "snapshot_date", "DATE", snapshot_date.isoformat()
                    ),
                    bigquery.ScalarQueryParameter("store_code", "STRING", r["store_code"]),
                    bigquery.ScalarQueryParameter("provider", "STRING", r["provider"]),
                    bigquery.ScalarQueryParameter(
                        "provider_place_id", "STRING", r.get("provider_place_id") or ""
                    ),
                    bigquery.ScalarQueryParameter("rating_value", "FLOAT64", r.get("rating_value")),
                    bigquery.ScalarQueryParameter(
                        "review_count", "INT64", r.get("review_count", 0)
                    ),
                    bigquery.ScalarQueryParameter("ingest_run_id", "STRING", ingest_run_id),
                    bigquery.ScalarQueryParameter("status", "STRING", r.get("status", "ok")),
                ]
            ),
        )
        job.result()


def merge_reviews(
    store_code: str,
    provider: str,
    provider_place_id: str,
    reviews: list[dict[str, Any]],
    ingest_run_id: str,
) -> None:
    """reviews に MERGE（store_code + provider + provider_review_id）。"""
    if not reviews:
        return
    client = get_client()
    ds = config.BQ_DATASET
    table = f"{config.BQ_PROJECT}.{ds}.reviews"
    # 簡易: 1 件ずつ MERGE（大量の場合は UNNEST で一括推奨）
    for rev in reviews:
        rid = rev.get("provider_review_id") or ""
        if not rid:
            continue
        sql = f"""
        MERGE `{table}` AS T
        USING (SELECT
            @store_code AS store_code,
            @provider AS provider,
            @provider_place_id AS provider_place_id,
            @provider_review_id AS provider_review_id,
            @rating AS rating,
            @review_text AS review_text,
            @review_created_at AS review_created_at,
            @review_updated_at AS review_updated_at,
            @reviewer_display_name AS reviewer_display_name,
            @ingest_run_id AS ingest_run_id
        ) AS S
        ON T.store_code = S.store_code AND T.provider = S.provider AND T.provider_review_id = S.provider_review_id
        WHEN MATCHED THEN UPDATE SET
            rating = S.rating,
            review_text = S.review_text,
            review_created_at = S.review_created_at,
            review_updated_at = S.review_updated_at,
            reviewer_display_name = S.reviewer_display_name,
            ingested_at = CURRENT_TIMESTAMP(),
            ingest_run_id = S.ingest_run_id
        WHEN NOT MATCHED THEN INSERT (
            store_code, provider, provider_place_id, provider_review_id,
            rating, review_text, review_created_at, review_updated_at, reviewer_display_name,
            ingested_at, ingest_run_id
        ) VALUES (
            S.store_code, S.provider, S.provider_place_id, S.provider_review_id,
            S.rating, S.review_text, S.review_created_at, S.review_updated_at, S.reviewer_display_name,
            CURRENT_TIMESTAMP(), S.ingest_run_id
        )
        """
        params = [
            bigquery.ScalarQueryParameter("store_code", "STRING", store_code),
            bigquery.ScalarQueryParameter("provider", "STRING", provider),
            bigquery.ScalarQueryParameter("provider_place_id", "STRING", provider_place_id),
            bigquery.ScalarQueryParameter("provider_review_id", "STRING", rid),
            bigquery.ScalarQueryParameter("rating", "FLOAT64", rev.get("rating")),
            bigquery.ScalarQueryParameter(
                "review_text", "STRING", (rev.get("review_text") or "")[: 2**16 - 1]
            ),
            bigquery.ScalarQueryParameter(
                "review_created_at", "TIMESTAMP", rev.get("review_created_at")
            ),
            bigquery.ScalarQueryParameter(
                "review_updated_at", "TIMESTAMP", rev.get("review_updated_at")
            ),
            bigquery.ScalarQueryParameter(
                "reviewer_display_name", "STRING", rev.get("reviewer_display_name")
            ),
            bigquery.ScalarQueryParameter("ingest_run_id", "STRING", ingest_run_id),
        ]
        job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
        job.result()
