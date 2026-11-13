"""数据库连接池与数据访问。

关键设计：
  1. 连接池懒加载 —— 启动时数据库不可用不该让服务永久残废
  2. 连接探活 + 自动重建 —— Neon 这类云库闲置会挂起，池里会留下死连接；
     不处理就会表现为「偶发写库失败」
  3. 混合检索 —— 向量召回 + 关键词召回，用 RRF 融合
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


# ---------------------------------------------------------------- 连接池

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


def _reset_pool() -> None:
    """丢弃整个池，下次调用时重建。云库挂起后旧连接全部失效，整体重建最省事。"""
    global _pool
    with _lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None
            log.warning("连接池已重置，将在下次请求时重建")


def is_ready() -> bool:
    return get_pool() is not None


def _acquire(p) -> psycopg2.extensions.connection:
    """取出一个确认可用的连接；死连接直接丢弃。"""
    conn = p.getconn()
    if conn.closed:
        p.putconn(conn, close=True)
        raise psycopg2.InterfaceError("连接已关闭")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.rollback()          # 结束探活事务，避免残留事务状态
        return conn
    except psycopg2.Error:
        p.putconn(conn, close=True)
        raise


def _call(fn, retries: int = 1):
    """执行一次数据访问；遇到连接类错误自动重建连接池并重试。"""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        p = get_pool()
        if p is None:
            raise RuntimeError("数据库不可用")
        conn = None
        try:
            conn = _acquire(p)
            return fn(conn)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
            last_exc = exc
            log.warning("数据库连接失效（第 %d 次尝试）：%s", attempt + 1, exc)
            if attempt >= retries:
                break
            _reset_pool()
        finally:
            if conn is not None:
                try:
                    p.putconn(conn)
                except Exception:
                    pass
    raise last_exc if last_exc else RuntimeError("数据库不可用")


# ---------------------------------------------------------------- 业务读写

def save_query(question, answer, latency_ms, token_in, token_out, status="ok") -> int:
    def _do(conn) -> int:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO queries
                       (question, answer, latency_ms, token_in, token_out, status)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (question, answer, latency_ms, token_in, token_out, status),
            )
            return cur.fetchone()[0]

    return _call(_do)


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
    def _do(conn) -> int:
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

    return _call(_do)


def replace_chunks(document_id: int, rows: list[dict]) -> int:
    def _do(conn) -> int:
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

    return _call(_do)


def _fetch_dicts(cur, rows_needed=None) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def search_chunks_hybrid(query_vector: str, terms: list[str], k: int = 5,
                         pool_size: int = 20) -> list[dict]:
    """向量 + 关键词两路召回，RRF 融合后取 top-k。"""

    def _do(conn) -> list[dict]:
        with conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT {_SELECT_COLS},
                           1 - (c.embedding <=> %s::vector) AS score
                     {_FROM_JOIN}
                     WHERE c.embedding IS NOT NULL
                     ORDER BY c.embedding <=> %s::vector
                     LIMIT %s""",
                (query_vector, query_vector, pool_size),
            )
            vec_rows = _fetch_dicts(cur)

            kw_rows: list[dict] = []
            if terms:
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
                    patterns + patterns + [pool_size],
                )
                kw_rows = _fetch_dicts(cur)

        fused: dict[int, dict] = {}
        sources: dict[int, set] = {}

        def _merge(rows, tag):
            for rank, r in enumerate(rows, start=1):
                cid = r["chunk_id"]
                if cid not in fused:
                    fused[cid] = dict(r)
                    fused[cid]["rrf"] = 0.0
                    sources[cid] = set()
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

    return _call(_do)


def counts() -> dict:
    def _do(conn) -> dict:
        with conn, conn.cursor() as cur:
            cur.execute(
                """SELECT (SELECT count(*) FROM documents),
                          (SELECT count(*) FROM chunks),
                          (SELECT count(*) FROM chunks WHERE embedding IS NOT NULL)"""
            )
            d, c, e = cur.fetchone()
            return {"documents": d, "chunks": c, "embedded": e}

    return _call(_do)
