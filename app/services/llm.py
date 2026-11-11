"""LLM 调用封装：超时 + 指数退避重试 + 熔断。

异常分层：
  LLMError        —— 调用了但失败（下游有响应/超时）
  LLMUnavailable  —— 熔断打开，压根没调用
上游据此区分「降级」还是「报错」。
"""
import logging
import time

from openai import OpenAI

from app.config import get_settings
from app.services.resilience import BreakerState, CircuitBreaker

log = logging.getLogger("app.llm")


class LLMError(RuntimeError):
    """调用失败（超时、返回空、下游报错）。"""


class LLMUnavailable(RuntimeError):
    """熔断打开，本次请求没有真正调用模型。"""


_breaker = CircuitBreaker()


def get_breaker() -> CircuitBreaker:
    return _breaker


def configure_breaker(failure_threshold: int, recovery_seconds: float) -> None:
    """启动时按配置初始化熔断器。"""
    global _breaker
    _breaker = CircuitBreaker(
        failure_threshold=failure_threshold,
        recovery_seconds=recovery_seconds,
    )


def _call_once(client: OpenAI, model: str, prompt: str):
    return client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )


def _call_with_retry(client: OpenAI, model: str, prompt: str,
                     attempts: int, base_delay: float = 0.5, sleep=time.sleep):
    """指数退避重试：0.5s → 1s → 2s …

    只对可恢复错误重试。参数化 sleep 是为了测试不必真的等。
    """
    last_exc: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            return _call_once(client, model, prompt)
        except Exception as exc:  # SDK 各类异常统一在此重试
            last_exc = exc
            if i == attempts - 1:
                break
            delay = base_delay * (2 ** i)
            log.warning("LLM 调用失败（第 %d/%d 次）：%s，%.1fs 后重试",
                        i + 1, attempts, type(exc).__name__, delay)
            sleep(delay)
    raise LLMError(f"重试 {attempts} 次仍失败：{type(last_exc).__name__}: {last_exc}") from last_exc


def ask(question: str) -> tuple[str, int, int, int]:
    """返回 (answer, token_in, token_out, latency_ms)。"""
    s = get_settings()
    if not s.llm_api_key:
        raise LLMError("未配置 LLM_API_KEY")

    breaker = _breaker
    if not breaker.allow():
        log.error("LLM 熔断中（state=%s failures=%d），直接拒绝", breaker.state.value, breaker.failures)
        raise LLMUnavailable(f"LLM 服务熔断中（{breaker.state.value}）")

    client = OpenAI(
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        timeout=s.llm_timeout,
        max_retries=0,  # 重试由 _call_with_retry 显式控制，避免双重退避
    )

    started = time.perf_counter()
    try:
        resp = _call_with_retry(client, s.llm_model, question, s.llm_max_attempts)
    except LLMError:
        breaker.record_failure()
        raise
    latency_ms = int((time.perf_counter() - started) * 1000)

    answer = (resp.choices[0].message.content or "").strip()
    if not answer:
        breaker.record_failure()
        raise LLMError("LLM 返回了空内容")

    breaker.record_success()
    log.info("llm_ok latency=%dms token_in=%d token_out=%d state=%s",
             latency_ms, resp.usage.prompt_tokens, resp.usage.completion_tokens,
             breaker.state.value)
    return answer, resp.usage.prompt_tokens, resp.usage.completion_tokens, latency_ms
