"""熔断器。状态机：CLOSED → OPEN → HALF_OPEN → CLOSED。

为什么需要：
  LLM 服务挂掉时，如果每个请求都傻等 30 秒超时，线程池很快被占满，
  一个下游故障会放大成全站不可用。熔断的作用是"快速失败 + 定期试探"。
"""
import threading
import time
from enum import Enum


class BreakerState(str, Enum):
    CLOSED = "closed"        # 正常放行
    OPEN = "open"            # 直接拒绝，不再调用下游
    HALF_OPEN = "half_open"  # 冷却结束，放一个请求试探


class CircuitBreaker:
    """线程安全的最小熔断器。clock / sleep 可注入，方便测试不依赖真实时间。"""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
        clock=time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 查询
    @property
    def state(self) -> BreakerState:
        with self._lock:
            self._maybe_half_open()
            return self._state

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def _maybe_half_open(self) -> None:
        if self._state is BreakerState.OPEN:
            if self._clock() - self._opened_at >= self.recovery_seconds:
                self._state = BreakerState.HALF_OPEN

    def allow(self) -> bool:
        """是否放行这次请求。"""
        with self._lock:
            self._maybe_half_open()
            return self._state is not BreakerState.OPEN

    # ---------------------------------------------------------------- 打点
    def record_success(self) -> None:
        with self._lock:
            self._state = BreakerState.CLOSED
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            # 半开状态下失败一次就重新打开；闭合状态下达到阈值才打开
            if self._state is BreakerState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = BreakerState.OPEN
                self._opened_at = self._clock()

    def reset(self) -> None:
        with self._lock:
            self._state = BreakerState.CLOSED
            self._failures = 0
            self._opened_at = 0.0
