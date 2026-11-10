"""数据库连接池与数据访问。

关键设计：连接池懒加载。
启动时数据库不可用不应该让服务永久残废 —— 之后数据库起来了，下一次请求应能自动连上。
"""
import logging
import threading

import psycopg2
from psycopg2 import pool

from app.config import get_settings

log = logging.getLogger("app.db")

_pool: pool.SimpleConnectionPool | None = None
_lock = threading.Lock()


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
    """取连接池；之前失败过则在这里重试一次。"""
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


def save_query(
    question: str,
    answer: str,
    latency_ms: int,
    token_in: int,
    token_out: int,
    status: str = "ok",
) -> int:
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


def upsert_document(title: str, source_path: str, file_type: str, content_hash: str) -> int:
    """按 content_hash 去重：同一份文件重复灌库不会产生第二份文档。"""
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
    """整篇替换：先删旧片段再插新的，保证重复灌库不会残留脏数据。"""
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
                    (
                        document_id,
                        r["chunk_index"],
                        r["content"],
                        r.get("page_no"),
                        r.get("token_count"),
                        r["embedding"],
                    ),
                )
            cur.execute(
                "UPDATE documents SET status = 'indexed', updated_at = now() WHERE id = %s",
                (document_id,),
            )
            return len(rows)
    finally:
        p.putconn(conn)


def search_chunks(query_vector: str, k: int = 4) -> list[dict]:
    """按余弦相似度取 top-k 片段，带出文档标题和页码用于标注出处。"""
    p = get_pool()
    if p is None:
        raise RuntimeError("数据库不可用")
    conn = p.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """SELECT c.id            AS chunk_id,
                          c.document_id   AS document_id,
                          d.title         AS title,
                          c.chunk_index   AS chunk_index,
                          c.content       AS content,
                          c.page_no       AS page_no,
                          1 - (c.embedding <=> %s::vector) AS score
                     FROM chunks c
                     JOIN documents d ON d.id = c.document_id
                    WHERE c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s""",
                (query_vector, query_vector, k),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        p.putconn(conn)


def counts() -> dict:
    """给统计用：文档数、片段数、带向量的片段数。"""
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
