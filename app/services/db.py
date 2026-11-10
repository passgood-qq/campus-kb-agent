"""数据库连接池与数据访问。

关键设计：
  1. 连接池懒加载 —— 启动时数据库不可用不该让服务永久残废
  2. 混合检索 —— 向量召回 + 关键词召回，用 RRF 融合
     纯向量对代码标识符（WHERE / unique_ptr / 3NF）不敏感，必须有关键词这一路兜底
"""
import logging
import threading

import psycopg2
from psycopg2 import pool

from app.config import get_settings

log = logging.getLogger("app.db")

_pool: pool.SimpleConnectionPool | None = None
_lock = threading.Lock()

RRF_K = 60  # RRF 常数，业界常用 60


def _build_pool() -> pool.SimpleConnectionPool | None:
    s = get_settings()
    if not s.database_url:
        log.warning("未配置 DATABASE_URL，数据库功能不可用")
        return None
    try:
        p = pool.SimpleConnectionPool(1, 5, dsn=s.database_url, connect_timeout=5)
        log.info("数据库连接池已建立")
        return p
    except psycopg2.Error as exc:
        log.error("数据库连接失败：%s", exc)
        return None


def init_pool() -> None:
    global _pool
    with _lock:
        if _pool is None:
            _pool = _build_pool()


def get_pool() -> pool.SimpleConnectionPool | None:
    global _pool
    if _pool is not None:
        return _pool
    with _lock:
        if _pool is None:
            _pool = _build_pool()
        return _pool


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None


def is_ready() -> bool:
    return get_pool() is not None


def save_query(question, answer, latency_ms, token_in, token_out, status="ok") -> int:
    p = get_pool()
    if p is None:
        raise RuntimeError("数据库不可用")
    conn = p.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO queries
                       (question, answer, latency_ms, token_in, token_out, status)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (question, answer, latency_ms, token_in, token_out, status),
            )
            return cur.fetchone()[0]
    finally:
        p.putconn(conn)


# ---------------------------------------------------------------- 文档与片段

_SELECT_COLS = """
    c.id            AS chunk_id,
    c.document_id   AS document_id,
    d.title         AS title,
    c.chunk_index   AS chunk_index,
    c.content       AS content,
    c.page_no       AS page_no
"""

_FROM_JOIN = """
      FROM chunks c
      JOIN documents d ON d.id = c.document_id
"""


def upsert_document(title, source_path, file_type, content_hash) -> int:
    p = get_pool()
    if p is None:
        raise RuntimeError("数据库不可用")
    conn = p.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO documents (title, source_path, file_type, content_hash, status)
                   VALUES (%s, %s, %s, %s, 'parsed')
                   ON CONFLICT (content_hash) DO UPDATE
                       SET title = EXCLUDED.title, updated_at = now()
                   RETURNING id""",
                (title, source_path, file_type, content_hash),
            )
            return cur.fetchone()[0]
    finally:
        p.putconn(conn)


def replace_chunks(document_id: int, rows: list[dict]) -> int:
    p = get_pool()
    if p is None:
        raise RuntimeError("数据库不可用")
    conn = p.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            for r in rows:
                cur.execute(
                    """INSERT INTO chunks
                           (document_id, chunk_index, content, page_no, token_count, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s::vector)""",
                    (document_id, r["chunk_index"], r["content"], r.get("page_no"),
                     r.get("token_count"), r["embedding"]),
                )
            cur.execute(
                "UPDATE documents SET status = 'indexed', updated_at = now() WHERE id = %s",
                (document_id,),
            )
            return len(rows)
    finally:
        p.putconn(conn)


def _fetch_dicts(cur, rows_needed=None) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _vector_search_with_score(cur, query_vector: str, limit: int) -> list[dict]:
    cur.execute(
        f"""SELECT {_SELECT_COLS},
                   1 - (c.embedding <=> %s::vector) AS score
             {_FROM_JOIN}
             WHERE c.embedding IS NOT NULL
             ORDER BY c.embedding <=> %s::vector
             LIMIT %s""",
        (query_vector, query_vector, limit),
    )
    return _fetch_dicts(cur)


def _keyword_search(cur, terms: list[str], limit: int) -> list[dict]:
    """把问题里的英文标识符拿出来做 ILIKE 匹配，命中越多排越前。"""
    if not terms:
        return []
    patterns = [f"%{t}%" for t in terms]
    hit_expr = " + ".join(["(CASE WHEN c.content ILIKE %s THEN 1 ELSE 0 END)"] * len(patterns))
    where_expr = " OR ".join(["c.content ILIKE %s"] * len(patterns))
    cur.execute(
        f"""SELECT {_SELECT_COLS},
                    0.0 AS score,
                    ({hit_expr}) AS kw_hits
             {_FROM_JOIN}
             WHERE ({where_expr})
             ORDER BY kw_hits DESC, length(c.content) ASC
             LIMIT %s""",
        patterns + patterns + [limit],
    )
    return _fetch_dicts(cur)


def search_chunks_hybrid(query_vector: str, terms: list[str], k: int = 5,
                         pool_size: int = 20) -> list[dict]:
    """向量 + 关键词两路召回，RRF 融合后取 top-k。"""
    p = get_pool()
    if p is None:
        raise RuntimeError("数据库不可用")
    conn = p.getconn()
    try:
        with conn, conn.cursor() as cur:
            vec_rows = _vector_search_with_score(cur, query_vector, pool_size)
            kw_rows = _keyword_search(cur, terms, pool_size)
    finally:
        p.putconn(conn)

    fused: dict[int, dict] = {}
    sources: dict[int, set] = {}

    def _merge(rows, tag):
        for rank, r in enumerate(rows, start=1):
            cid = r["chunk_id"]
            if cid not in fused:
                fused[cid] = dict(r)
                fused[cid]["rrf"] = 0.0
                sources[cid] = set()
            # 保留向量相似度用于展示（关键词那路没有真实相似度）
            if tag == "vector":
                fused[cid]["score"] = float(r.get("score") or 0.0)
            fused[cid]["rrf"] += 1.0 / (RRF_K + rank)
            sources[cid].add(tag)

    _merge(vec_rows, "vector")
    _merge(kw_rows, "keyword")

    ranked = sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)[:k]
    for r in ranked:
        tags = sources[r["chunk_id"]]
        r["retrieved_by"] = "both" if len(tags) == 2 else next(iter(tags))
        r["rrf"] = round(r["rrf"], 6)
        r.pop("kw_hits", None)
    log.info("混合检索 vector=%d keyword=%d 融合后=%d", len(vec_rows), len(kw_rows), len(ranked))
    return ranked


def counts() -> dict:
    p = get_pool()
    if p is None:
        raise RuntimeError("数据库不可用")
    conn = p.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """SELECT (SELECT count(*) FROM documents),
                          (SELECT count(*) FROM chunks),
                          (SELECT count(*) FROM chunks WHERE embedding IS NOT NULL)"""
            )
            d, c, e = cur.fetchone()
            return {"documents": d, "chunks": c, "embedded": e}
    finally:
        p.putconn(conn)
