"""数据库连接池与落库。

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
