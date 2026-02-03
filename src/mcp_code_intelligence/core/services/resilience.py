"""ResilienceManager implementation: circuit breaker + exponential backoff.

Implements the `ResilienceManager` protocol defined in
`src/mcp_code_intelligence/core/interfaces.py`.

Features:
- Circuit breaker with `failure_threshold` and `recovery_timeout`.
- Exponential backoff with jitter for retries.
- `_is_retriable` classification for database/search related exceptions.
- Detailed logging of retries and circuit state transitions.
"""
from __future__ import annotations

import asyncio
import time
import random
from typing import Any, Callable, Awaitable

from loguru import logger

from mcp_code_intelligence.core.interfaces import ResilienceManager
from mcp_code_intelligence.core.exceptions import (
    MCPCodeIntelligenceError,
    DatabaseError,
    RustPanicError,
    IndexCorruptionError,
)


class ServiceUnavailableError(MCPCodeIntelligenceError):
    """Raised when circuit breaker is open and service is unavailable."""


class SimpleResilienceManager(ResilienceManager):
    """Resilience manager with circuit breaker and exponential backoff.

    Parameters:
        failure_threshold: consecutive failures to open the circuit (default: 3)
        recovery_timeout: seconds to wait before allowing a trial after opening (default: 30)
        base_delay: base delay seconds for exponential backoff (default: 0.1)
        max_jitter: max jitter in seconds to add/subtract from backoff (default: 0.1)
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        base_delay: float = 0.1,
        max_jitter: float = 0.1,
    ) -> None:
        self.failure_threshold = int(failure_threshold)
        self.recovery_timeout = float(recovery_timeout)
        self.base_delay = float(base_delay)
        self.max_jitter = float(max_jitter)

        # Circuit state
        self._failure_count = 0
        self._state = "CLOSED"  # one of: CLOSED, OPEN, HALF_OPEN
        self._opened_at = 0.0
        self._lock = asyncio.Lock()

    def _open_circuit(self) -> None:
        self._state = "OPEN"
        self._opened_at = time.time()
        logger.warning(f"Circuit state: CLOSED -> OPEN (failure_count={self._failure_count})")

    def _close_circuit(self) -> None:
        prev = self._state
        self._state = "CLOSED"
        self._failure_count = 0
        self._opened_at = 0.0
        if prev != "CLOSED":
            logger.info(f"Circuit state: {prev} -> CLOSED")

    def _half_open(self) -> None:
        prev = self._state
        self._state = "HALF_OPEN"
        logger.info(f"Circuit state: {prev} -> HALF_OPEN (trial request allowed)")

    def _is_open(self) -> bool:
        if self._state != "OPEN":
            return False
        # If recovery timeout elapsed, move to HALF_OPEN and allow a trial
        if time.time() - self._opened_at >= self.recovery_timeout:
            self._half_open()
            return False
        return True

    def _is_retriable(self, exc: BaseException) -> bool:
        """Classify exceptions as retriable or fatal.

        Rules:
        - `RustPanicError` and `IndexCorruptionError` are fatal (not retriable).
        - Other `DatabaseError` instances are considered retriable.
        - Default to non-retriable.
        """
        if isinstance(exc, RustPanicError):
            return False
        if isinstance(exc, IndexCorruptionError):
            return False
        if isinstance(exc, DatabaseError):
            return True
        return False

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        max_retries: int = 3,
        jitter: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute an async function with retry/backoff and circuit-breaker.

        Raises `ServiceUnavailableError` immediately if circuit is OPEN.
        """
        if jitter is None:
            jitter = self.max_jitter

        async with self._lock:
            if self._is_open():
                logger.error("Request rejected: circuit breaker is OPEN")
                raise ServiceUnavailableError("Service unavailable (circuit open)")

        attempt = 0
        last_exc: BaseException | None = None

        while True:
            # If circuit opened while we waited for lock previously
            async with self._lock:
                if self._is_open():
                    logger.error("Request rejected at attempt %d: circuit OPEN", attempt)
                    raise ServiceUnavailableError("Service unavailable (circuit open)")

            try:
                result = await func(*args, **kwargs)

                # Success: reset failure counter and close circuit if needed
                async with self._lock:
                    self._close_circuit()

                if attempt > 0:
                    logger.info(f"Operation succeeded after {attempt} retries")
                return result

            except BaseException as e:  # noqa: B902 - deliberate broad catch for resilience wrapper
                last_exc = e

                # If exception is non-retriable, mark circuit if appropriate and re-raise
                retriable = self._is_retriable(e)
                logger.debug(f"Attempt {attempt+1} failed (retriable={retriable}): {e}")

                if not retriable:
                    # Fatal error: increase failure count and possibly open circuit
                    async with self._lock:
                        self._failure_count += 1
                        if self._failure_count >= self.failure_threshold:
                            self._open_circuit()
                    raise

                # Retriable error path
                attempt += 1
                async with self._lock:
                    self._failure_count += 1
                    if self._failure_count >= self.failure_threshold:
                        self._open_circuit()

                if attempt > max_retries:
                    logger.error(f"Operation failed after {attempt} attempts; giving up: {e}")
                    raise

                # Backoff with exponential policy and jitter
                backoff = self.base_delay * (2 ** (attempt - 1))
                jitter_val = random.uniform(-abs(jitter), abs(jitter))
                sleep_for = max(0.0, backoff + jitter_val)
                logger.warning(
                    f"Retrying operation in {sleep_for:.3f}s (attempt {attempt}/{max_retries})"
                )
                await asyncio.sleep(sleep_for)

                # If circuit became OPEN during sleeping, raise immediately
                async with self._lock:
                    if self._is_open():
                        logger.error("Circuit opened during backoff; rejecting further retries")
                        raise ServiceUnavailableError("Service unavailable (circuit open)")


__all__ = ["SimpleResilienceManager", "ServiceUnavailableError"]
