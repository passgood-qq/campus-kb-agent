"""数据库连接池与落库。池初始化失败时不抛异常，让服务仍能启动、/healthz 报出状态。"""
import logging

import psycopg2
from psycopg2 import pool

from app.config import get_settings

log = logging.getLogger("app.db")

_pool: pool.SimpleConnectionPool | None = None


def init_pool() -> None:
    global _pool
    s = get_settings()
    if not s.database_url:
        log.warning("未配置 DATABASE_URL，数据库功能不可用")
        return
    try:
        _pool = pool.SimpleConnectionPool(1, 5, dsn=s.database_url, connect_timeout=5)
        log.info("数据库连接池已建立")
    except psycopg2.Error as exc:
        log.error("数据库连接失败：%s", exc)
        _pool = None


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


def is_ready() -> bool:
    return _pool is not None


def save_query(
    question: str,
    answer: str,
    latency_ms: int,
    token_in: int,
    token_out: int,
    status: str = "ok",
) -> int:
    if _pool is None:
        raise RuntimeError("数据库连接池未初始化")
    conn = _pool.getconn()
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
        _pool.putconn(conn)
