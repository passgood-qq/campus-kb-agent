"""LLM 调用封装。异常统一收敛成 LLMError，便于上层决定返回 502 还是降级。"""
import logging
import time

from openai import OpenAI

from app.config import get_settings

log = logging.getLogger("app.llm")


class LLMError(RuntimeError):
    """LLM 不可用或返回异常。"""


def ask(question: str) -> tuple[str, int, int, int]:
    """返回 (answer, token_in, token_out, latency_ms)。"""
    s = get_settings()
    if not s.llm_api_key:
        raise LLMError("未配置 LLM_API_KEY")

    client = OpenAI(
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        timeout=s.llm_timeout,
        max_retries=1,
    )

    started = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=s.llm_model,
            messages=[{"role": "user", "content": question}],
            temperature=0.3,
        )
    except Exception as exc:  # SDK 的各类异常统一转换
        raise LLMError(f"LLM 调用失败：{type(exc).__name__}: {exc}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)

    answer = (resp.choices[0].message.content or "").strip()
    if not answer:
        raise LLMError("LLM 返回了空内容")

    log.info(
        "llm_ok latency=%dms token_in=%d token_out=%d",
        latency_ms, resp.usage.prompt_tokens, resp.usage.completion_tokens,
    )
    return answer, resp.usage.prompt_tokens, resp.usage.completion_tokens, latency_ms
