"""Mirror accepted operational records without awaiting durable storage on requests.

The bounded queue belongs to one process: host termination, saturation or write
failures may permanently lose history even when Redis acceptance succeeded.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextvars import Context, copy_context

from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.telemetry import emit


class BackgroundWriter:
    """Bounded, process-local best-effort work; never a durable delivery queue."""

    def __init__(self, capacity: int = 256) -> None:
        """Allocate pending-work capacity; the active operation is outside the queue."""
        self.queue: asyncio.Queue[tuple[str, str, Callable[[], Awaitable[object]], Context]] = (
            asyncio.Queue(maxsize=capacity)
        )
        self.task: asyncio.Task[None] | None = None
        self.closed = False

    def submit(
        self, collection: str, record_id: str, operation: Callable[[], Awaitable[object]]
    ) -> None:
        """Enqueue a deferred async operation without waiting for its completion.

        Closed/full queues log and drop the operation. Capture the submitting
        tracing context so later dependency telemetry remains request-correlated.
        There is no retry or acknowledgment of durable delivery to the caller.
        """
        if self.closed or self.queue.full():
            emit(
                "background_write_dropped",
                level=logging.WARNING,
                collection=collection,
                record_id=record_id,
                reason="closed" if self.closed else "queue_full",
            )
            rate_metrics.background_write(collection, "dropped")
            return
        self.queue.put_nowait((collection, record_id, operation, copy_context()))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())
            self.task.add_done_callback(self._completed)

    async def _run(self) -> None:
        """Drain serially, restoring each submitter's context for its operation."""
        while not self.queue.empty():
            collection, record_id, operation, context = self.queue.get_nowait()
            try:
                await asyncio.create_task(
                    self._execute(collection, record_id, operation), context=context
                )
            finally:
                self.queue.task_done()

    @staticmethod
    async def _execute(
        collection: str, record_id: str, operation: Callable[[], Awaitable[object]]
    ) -> None:
        """Log any job failure and continue, so one bad job never strands the queue.

        Cancellation still propagates; failed jobs are not retried.
        """
        try:
            await operation()
        except Exception as error:
            emit(
                "background_write_failed",
                level=logging.WARNING,
                collection=collection,
                record_id=record_id,
                error_type=type(error).__name__,
            )
            rate_metrics.background_write(collection, "failed")
        else:
            emit("background_write_completed", collection=collection, record_id=record_id)
            rate_metrics.background_write(collection, "completed")

    @staticmethod
    def _completed(task: asyncio.Task[None]) -> None:
        """Observe unexpected worker exceptions rather than leaving them unreported."""
        if not task.cancelled() and (error := task.exception()) is not None:
            emit(
                "background_worker_failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )

    async def flush(self) -> None:
        """Wait for the current worker; caller cancellation does not cancel its writes."""
        if self.task is not None:
            await asyncio.shield(self.task)

    async def close(self) -> None:
        """Reject new submissions and allow at most two seconds for the worker.

        Timeout cancels the worker and logs unfinished work; this is a bounded
        shutdown courtesy, not a guarantee that accepted records reach Table.
        """
        self.closed = True
        if self.task is None:
            return
        try:
            await asyncio.wait_for(self.task, timeout=2)
        except TimeoutError:
            emit(
                "background_writes_abandoned",
                level=logging.WARNING,
                pending=self.queue.qsize() + 1,
            )
