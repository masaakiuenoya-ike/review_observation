"""
BigQuery: places_provider_map 読込、ratings_daily_snapshot MERGE、reviews MERGE。
"""

from __future__ import annotations

from collections import defaultdict
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
    # 最大120秒でタイムアウト（ハング防止）
    return [dict(row) for row in job.result(timeout=120)]


def fetch_existing_review_ids_by_store(
    store_codes: list[str],
    provider: str,
) -> dict[str, set[str]]:
    """
    ingest 開始時点のスナップショット。各 store_code に既存の provider_review_id を集める。
    MERGE 直前の差分＝新規レビュー判定に使う。
    """
    if not store_codes:
        return {}
    client = get_client()
    ds = config.BQ_DATASET
    query = f"""
    SELECT store_code, provider_review_id
    FROM `{config.BQ_PROJECT}.{ds}.reviews`
    WHERE provider = @provider
      AND store_code IN UNNEST(@store_codes)
    """
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("provider", "STRING", provider),
                bigquery.ArrayQueryParameter("store_codes", "STRING", store_codes),
            ]
        ),
    )
    out: dict[str, set[str]] = defaultdict(set)
    for row in job.result(timeout=120):
        rid = (row["provider_review_id"] or "").strip()
        if rid:
            out[row["store_code"]].add(rid)
    return dict(out)


def merge_ratings_daily_snapshot(
    snapshot_date: date,
    ingest_run_id: str,
    rows: list[dict[str, Any]],
) -> None:
    """ratings_daily_snapshot に MERGE（snapshot_date + store_code + provider）。一括 UNNEST で 1 クエリ。"""
    if not rows:
        return
    client = get_client()
    ds = config.BQ_DATASET
    table = f"{config.BQ_PROJECT}.{ds}.ratings_daily_snapshot"
    store_codes = [r["store_code"] for r in rows]
    store_names = [r.get("store_name") or "" for r in rows]
    providers = [r["provider"] for r in rows]
    place_ids = [r.get("provider_place_id") or "" for r in rows]
    rating_values = [r.get("rating_value") for r in rows]
    review_counts = [r.get("review_count", 0) for r in rows]
    statuses = [r.get("status", "ok") for r in rows]
    sql = f"""
    MERGE `{table}` AS T
    USING (
        SELECT
            @snapshot_date AS snapshot_date,
            s.store_code AS store_code,
            s.store_name AS store_name,
            s.provider AS provider,
            s.provider_place_id AS provider_place_id,
            s.rating_value AS rating_value,
            s.review_count AS review_count,
            @ingest_run_id AS ingest_run_id,
            s.status AS status
        FROM (
            SELECT sc AS store_code, sn AS store_name, p AS provider, pid AS provider_place_id,
                   rv AS rating_value, rc AS review_count, st AS status
            FROM UNNEST(@store_codes) AS sc WITH OFFSET o
            JOIN UNNEST(@store_names) AS sn WITH OFFSET o0 ON o = o0
            JOIN UNNEST(@providers) AS p WITH OFFSET o2 ON o = o2
            JOIN UNNEST(@place_ids) AS pid WITH OFFSET o3 ON o = o3
            JOIN UNNEST(@rating_values) AS rv WITH OFFSET o4 ON o = o4
            JOIN UNNEST(@review_counts) AS rc WITH OFFSET o5 ON o = o5
            JOIN UNNEST(@statuses) AS st WITH OFFSET o6 ON o = o6
        ) AS s
    ) AS S
    ON T.snapshot_date = S.snapshot_date AND T.store_code = S.store_code AND T.provider = S.provider
    WHEN MATCHED THEN UPDATE SET
        store_name = S.store_name,
        provider_place_id = S.provider_place_id,
        rating_value = S.rating_value,
        review_count = S.review_count,
        fetched_at = CURRENT_TIMESTAMP(),
        ingest_run_id = S.ingest_run_id,
        status = S.status
    WHEN NOT MATCHED THEN INSERT (
        snapshot_date, store_code, store_name, provider, provider_place_id,
        rating_value, review_count, fetched_at, ingest_run_id, status
    ) VALUES (
        S.snapshot_date, S.store_code, S.store_name, S.provider, S.provider_place_id,
        S.rating_value, S.review_count, CURRENT_TIMESTAMP(), S.ingest_run_id, S.status
    )
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("snapshot_date", "DATE", snapshot_date.isoformat()),
            bigquery.ScalarQueryParameter("ingest_run_id", "STRING", ingest_run_id),
            bigquery.ArrayQueryParameter("store_codes", "STRING", store_codes),
            bigquery.ArrayQueryParameter("store_names", "STRING", store_names),
            bigquery.ArrayQueryParameter("providers", "STRING", providers),
            bigquery.ArrayQueryParameter("place_ids", "STRING", place_ids),
            bigquery.ArrayQueryParameter("rating_values", "FLOAT64", rating_values),
            bigquery.ArrayQueryParameter("review_counts", "INT64", review_counts),
            bigquery.ArrayQueryParameter("statuses", "STRING", statuses),
        ]
    )
    job = client.query(sql, job_config=job_config)
    job.result(timeout=120)


# 1 店舗あたりのレビューを何件ずつまとめて MERGE するか（BQ パラメータ上限を避ける）
_REVIEW_BATCH_SIZE = 80


def merge_reviews(
    store_code: str,
    provider: str,
    provider_place_id: str,
    reviews: list[dict[str, Any]],
    ingest_run_id: str,
    store_name: str = "",
) -> None:
    """reviews に MERGE（store_code + provider + provider_review_id）。store_name も書き込む。"""
    valid = [r for r in reviews if r.get("provider_review_id")]
    if not valid:
        return
    client = get_client()
    ds = config.BQ_DATASET
    table = f"{config.BQ_PROJECT}.{ds}.reviews"
    total = len(valid)
    if total > 10:
        import sys

        print(
            f"[bq_ops] merge_reviews store={store_code} merging {total} reviews (batch)...",
            file=sys.stderr,
        )
    for offset in range(0, total, _REVIEW_BATCH_SIZE):
        batch = valid[offset : offset + _REVIEW_BATCH_SIZE]
        ids = [r.get("provider_review_id", "") for r in batch]
        ratings = [r.get("rating") for r in batch]
        texts = [(r.get("review_text") or "")[: 2**16 - 1] for r in batch]
        created = [r.get("review_created_at") for r in batch]
        updated = [r.get("review_updated_at") for r in batch]
        names = [r.get("reviewer_display_name") or "" for r in batch]
        sql = f"""
        MERGE `{table}` AS T
        USING (
            SELECT
                @store_code AS store_code,
                @store_name AS store_name,
                @provider AS provider,
                @provider_place_id AS provider_place_id,
                i.rid AS provider_review_id,
                i.r AS rating,
                i.rt AS review_text,
                i.rc AS review_created_at,
                i.ru AS review_updated_at,
                i.rn AS reviewer_display_name,
                @ingest_run_id AS ingest_run_id
            FROM (
                SELECT rid, r, rt, rc, ru, rn FROM
                UNNEST(@ids) AS rid WITH OFFSET pos
                JOIN UNNEST(@ratings) AS r WITH OFFSET pos2 ON pos = pos2
                JOIN UNNEST(@texts) AS rt WITH OFFSET pos3 ON pos = pos3
                JOIN UNNEST(@created) AS rc WITH OFFSET pos4 ON pos = pos4
                JOIN UNNEST(@updated) AS ru WITH OFFSET pos5 ON pos = pos5
                JOIN UNNEST(@names) AS rn WITH OFFSET pos6 ON pos = pos6
            ) AS i
        ) AS S
        ON T.store_code = S.store_code AND T.provider = S.provider AND T.provider_review_id = S.provider_review_id
        WHEN MATCHED THEN UPDATE SET
            store_name = S.store_name,
            rating = S.rating,
            review_text = S.review_text,
            review_created_at = S.review_created_at,
            review_updated_at = S.review_updated_at,
            reviewer_display_name = S.reviewer_display_name,
            ingested_at = CURRENT_TIMESTAMP(),
            ingest_run_id = S.ingest_run_id
        WHEN NOT MATCHED THEN INSERT (
            store_code, store_name, provider, provider_place_id, provider_review_id,
            rating, review_text, review_created_at, review_updated_at, reviewer_display_name,
            ingested_at, ingest_run_id
        ) VALUES (
            S.store_code, S.store_name, S.provider, S.provider_place_id, S.provider_review_id,
            S.rating, S.review_text, S.review_created_at, S.review_updated_at, S.reviewer_display_name,
            CURRENT_TIMESTAMP(), S.ingest_run_id
        )
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("store_code", "STRING", store_code),
                bigquery.ScalarQueryParameter("store_name", "STRING", store_name),
                bigquery.ScalarQueryParameter("provider", "STRING", provider),
                bigquery.ScalarQueryParameter("provider_place_id", "STRING", provider_place_id),
                bigquery.ScalarQueryParameter("ingest_run_id", "STRING", ingest_run_id),
                bigquery.ArrayQueryParameter("ids", "STRING", ids),
                bigquery.ArrayQueryParameter("ratings", "FLOAT64", ratings),
                bigquery.ArrayQueryParameter("texts", "STRING", texts),
                bigquery.ArrayQueryParameter("created", "TIMESTAMP", created),
                bigquery.ArrayQueryParameter("updated", "TIMESTAMP", updated),
                bigquery.ArrayQueryParameter("names", "STRING", names),
            ]
        )
        job = client.query(sql, job_config=job_config)
        try:
            job.result(timeout=120)
        except Exception as e:
            import sys

            print(
                f"[bq_ops] merge_reviews store={store_code} batch failed: {e}",
                file=sys.stderr,
            )
            raise
        if total > 10 and (offset + len(batch)) % 50 == 0:
            import sys

            print(
                f"[bq_ops] merge_reviews store={store_code} progress {offset + len(batch)}/{total}",
                file=sys.stderr,
            )
