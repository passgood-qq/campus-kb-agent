"""D5 + D6：读文档 → 调模型 → 存库

D6 相比 D5 的改动：
  1. print 全部换成 logging（带时间戳、级别、耗时，可按 LOG_LEVEL 调）
  2. LLM / 数据库调用都加超时 + try/except，失败时给出明确的退出码
  3. latency 用 perf_counter 真实测量并写入 queries 表（原计划 D8 才补，提前了）
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("doc_pipeline")

LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
DOC_PATH = Path(os.getenv("DOC_PATH", "data/docs/what_is_rag.txt"))
QUESTION = "用三句话总结这篇文档的核心观点"

# 退出码：让脚本失败时能被 CI / 定时任务识别
EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG = 2
EXIT_DB = 3
EXIT_PIPELINE = 4


class PipelineError(Exception):
    """管线内的可预期失败（文档缺失、外部服务不可用等）。"""


def load_document(path: Path) -> str:
    if not path.exists():
        raise PipelineError(f"文档不存在：{path.resolve()}")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise PipelineError(f"文档内容为空：{path}")
    log.info("文档读取完成 path=%s chars=%d", path, len(content))
    return content


def upsert_document(cur, title: str, source_path: str, file_type: str, content_hash: str) -> int:
    cur.execute(
        """INSERT INTO documents (title, source_path, file_type, content_hash, status)
           VALUES (%s, %s, %s, %s, 'indexed')
           ON CONFLICT (content_hash) DO UPDATE
               SET status = 'indexed', updated_at = now()
           RETURNING id""",
        (title, source_path, file_type, content_hash),
    )
    doc_id = cur.fetchone()[0]
    log.info("文档已入库 doc_id=%s hash=%s", doc_id, content_hash[:8])
    return doc_id


def ask_llm(content: str) -> tuple[str, int, int, int]:
    if not os.getenv("LLM_API_KEY"):
        raise PipelineError("缺少 LLM_API_KEY，检查 .env")

    llm = OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        timeout=LLM_TIMEOUT,
        max_retries=1,
    )
    prompt = f"请根据以下文档内容回答问题：\n\n文档：\n{content}\n\n问题：{QUESTION}"

    started = time.perf_counter()
    try:
        resp = llm.chat.completions.create(
            model=os.getenv("LLM_MODEL"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
    except Exception as exc:  # SDK 各类异常统一收敛成自己的错误类型
        raise PipelineError(f"LLM 调用失败：{exc.__class__.__name__}: {exc}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)

    answer = (resp.choices[0].message.content or "").strip()
    if not answer:
        raise PipelineError("LLM 返回了空内容")
    log.info(
        "LLM 调用完成 latency=%dms token_in=%d token_out=%d",
        latency_ms, resp.usage.prompt_tokens, resp.usage.completion_tokens,
    )
    return answer, resp.usage.prompt_tokens, resp.usage.completion_tokens, latency_ms


def save_query(cur, question, answer, token_in, token_out, latency_ms, status="ok"):
    cur.execute(
        """INSERT INTO queries (question, answer, latency_ms, token_in, token_out, status)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (question, answer, latency_ms, token_in, token_out, status),
    )
    log.info("查询记录已写入 status=%s latency=%dms", status, latency_ms)


def main() -> int:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        log.error("缺少 DATABASE_URL，检查 .env")
        return EXIT_CONFIG
    if not os.getenv("LLM_API_KEY"):
        log.error("缺少 LLM_API_KEY，检查 .env")
        return EXIT_CONFIG

    try:
        content = load_document(DOC_PATH)
        content_hash = hashlib.md5(content.encode()).hexdigest()

        try:
            conn = psycopg2.connect(dsn, connect_timeout=5)
        except psycopg2.OperationalError as exc:
            log.error("数据库连接失败：%s", exc)
            return EXIT_DB

        try:
            with conn, conn.cursor() as cur:
                upsert_document(cur, "什么是RAG", str(DOC_PATH), "txt", content_hash)
                answer, tin, tout, latency = ask_llm(content)
                save_query(cur, QUESTION, answer, tin, tout, latency)
        finally:
            conn.close()

        log.info("管线执行完成")
        print(f"\n{answer}\n")
        return EXIT_OK

    except PipelineError as exc:
        log.error("管线中断：%s", exc)
        return EXIT_PIPELINE
    except Exception:
        log.exception("未预期的错误")
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
