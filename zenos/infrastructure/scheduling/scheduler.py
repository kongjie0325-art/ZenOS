"""Task scheduler with cron, interval, and one-shot trigger support."""

from __future__ import annotations

import asyncio
import enum
import heapq
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from zenos.infrastructure.scheduling.jobs import Job, JobPriority, JobStatus

logger = logging.getLogger(__name__)


class TriggerType(enum.Enum):
    """Supported trigger types for scheduled jobs."""

    CRON = "cron"
    INTERVAL = "interval"
    ONESHOT = "oneshot"


class SchedulerState(enum.Enum):
    """Internal scheduler lifecycle state."""

    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class TaskScheduler:
    """Asynchronous task scheduler supporting cron, interval, and one-shot jobs.

    Jobs are stored in a priority queue and dispatched by an internal event loop.
    The scheduler can be started, stopped, paused, and resumed at runtime.

    Example::

        scheduler = TaskScheduler()

        async def send_report():
            print("Report sent")

        job = scheduler.add_job(
            name="daily-report",
            func=send_report,
            trigger="cron",
            cron_expr="0 9 * * *",
        )
        await scheduler.start()
    """

    def __init__(self, max_concurrent: int = 10, tick_interval: float = 1.0) -> None:
        """Initialize the scheduler.

        Args:
            max_concurrent: Maximum number of jobs that may run simultaneously.
            tick_interval: How often (seconds) the scheduler checks for due jobs.
        """
        self._jobs: dict[str, Job] = {}
        self._queue: list[tuple[datetime, int, str]] = []  # (next_run, priority, job_id)
        self._state: SchedulerState = SchedulerState.STOPPED
        self._max_concurrent = max_concurrent
        self._tick_interval = tick_interval
        self._running_tasks: set[asyncio.Task[Any]] = set()
        self._loop_task: asyncio.Task[Any] | None = None
        self._semaphore = asyncio.Semaphore(max_concurrent)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def add_job(
        self,
        name: str,
        func: Callable[..., Any],
        trigger: str = "interval",
        *,
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        priority: JobPriority = JobPriority.NORMAL,
        max_retries: int = 3,
        cron_expr: str | None = None,
        interval_seconds: float | None = None,
        oneshot_at: datetime | None = None,
        next_run: datetime | None = None,
    ) -> Job:
        """Register a new job with the scheduler.

        Args:
            name: Human-readable job name.
            func: Async or sync callable to execute.
            trigger: One of ``'cron'``, ``'interval'``, or ``'oneshot'``.
            args: Positional arguments for the callable.
            kwargs: Keyword arguments for the callable.
            priority: Scheduling priority.
            max_retries: Maximum retry attempts on failure.
            cron_expr: Cron expression (required when trigger='cron').
            interval_seconds: Seconds between runs (required when trigger='interval').
            oneshot_at: Specific run time (required when trigger='oneshot').
            next_run: Override the computed next run time.

        Returns:
            The created ``Job`` instance.

        Raises:
            ValueError: If required trigger parameters are missing.
        """
        if trigger == "cron" and cron_expr is None:
            raise ValueError("cron_expr is required for cron triggers")
        if trigger == "interval" and interval_seconds is None:
            raise ValueError("interval_seconds is required for interval triggers")
        if trigger == "oneshot" and oneshot_at is None:
            raise ValueError("oneshot_at is required for oneshot triggers")

        job = Job(
            name=name,
            func=func,
            trigger=trigger,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
            max_retries=max_retries,
            cron_expr=cron_expr,
            interval_seconds=interval_seconds,
            oneshot_at=oneshot_at,
        )

        # Compute initial next_run
        job.next_run = next_run or self._compute_next_run(job)
        if job.next_run is None:
            raise ValueError(f"Could not determine next_run for trigger={trigger!r}")

        self._jobs[job.id] = job
        heapq.heappush(self._queue, (job.next_run, job.priority.value, job.id))
        logger.info("Added job %s (%s) with trigger=%s", job.name, job.id, trigger)
        return job

    def remove_job(self, job_id: str) -> Job:
        """Remove a job from the scheduler.

        Args:
            job_id: The unique identifier of the job to remove.

        Returns:
            The removed ``Job`` instance.

        Raises:
            KeyError: If ``job_id`` is not found.
        """
        if job_id not in self._jobs:
            raise KeyError(f"Job {job_id} not found")
        job = self._jobs.pop(job_id)
        job.status = JobStatus.CANCELLED
        # Lazy removal from heap — skipped entries are detected during dispatch.
        logger.info("Removed job %s (%s)", job.name, job.id)
        return job

    async def start(self) -> None:
        """Start the scheduler dispatch loop."""
        if self._state == SchedulerState.RUNNING:
            logger.warning("Scheduler is already running")
            return
        self._state = SchedulerState.RUNNING
        self._loop_task = asyncio.create_task(self._dispatch_loop())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler and cancel all running tasks."""
        self._state = SchedulerState.STOPPED
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        for task in list(self._running_tasks):
            task.cancel()
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)
        self._running_tasks.clear()
        logger.info("Scheduler stopped")

    def pause(self) -> None:
        """Pause scheduling. Already-running jobs continue to completion."""
        if self._state != SchedulerState.RUNNING:
            logger.warning("Cannot pause — scheduler is %s", self._state.value)
            return
        self._state = SchedulerState.PAUSED
        for job in self._jobs.values():
            if job.status == JobStatus.PENDING:
                job.status = JobStatus.PAUSED
        logger.info("Scheduler paused")

    def resume(self) -> None:
        """Resume a paused scheduler."""
        if self._state != SchedulerState.PAUSED:
            logger.warning("Cannot resume — scheduler is %s", self._state.value)
            return
        self._state = SchedulerState.RUNNING
        for job in self._jobs.values():
            if job.status == JobStatus.PAUSED:
                job.status = JobStatus.PENDING
        logger.info("Scheduler resumed")

    def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        trigger: str | None = None,
    ) -> list[Job]:
        """Return all registered jobs, optionally filtered.

        Args:
            status: Filter by job status.
            trigger: Filter by trigger type.

        Returns:
            A list of matching ``Job`` objects sorted by next run time.
        """
        jobs = list(self._jobs.values())
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        if trigger is not None:
            jobs = [j for j in jobs if j.trigger == trigger]
        jobs.sort(key=lambda j: (j.next_run or datetime.max, j.priority.value))
        return jobs

    def get_next_run(self) -> datetime | None:
        """Return the earliest ``next_run`` time across all active jobs.

        Returns:
            The soonest run time, or ``None`` if no jobs are scheduled.
        """
        active = [j for j in self._jobs.values() if j.is_active and j.next_run is not None]
        if not active:
            return None
        return min(j.next_run for j in active if j.next_run is not None)

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _compute_next_run(self, job: Job) -> datetime | None:
        """Calculate the next run time for a job based on its trigger."""
        now = datetime.utcnow()
        if job.trigger == "oneshot":
            return job.oneshot_at
        if job.trigger == "interval":
            ref = job.last_run or job.created_at
            return ref + timedelta(seconds=job.interval_seconds or 0)
        if job.trigger == "cron":
            return self._next_cron(job.cron_expr or "", now)
        return None

    @staticmethod
    def _next_cron(expr: str, now: datetime) -> datetime | None:
        """Parse a simplified cron expression and return the next future time.

        Supports ``*`` (any), single values, and comma-separated lists.
        Fields: minute hour day-of-month month day-of-week
        """
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {expr!r}")

        def _allowed(field: str, min_val: int, max_val: int) -> set[int]:
            if field == "*":
                return set(range(min_val, max_val + 1))
            values: set[int] = set()
            for token in field.split(","):
                values.add(int(token))
            return values

        minutes = _allowed(parts[0], 0, 59)
        hours = _allowed(parts[1], 0, 23)
        dom = _allowed(parts[2], 1, 31)
        months = _allowed(parts[3], 1, 12)
        dow = _allowed(parts[4], 0, 6)

        candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        # Brute-force walk forward at most 4 years
        limit = now + timedelta(days=366 * 4)
        while candidate <= limit:
            if (
                candidate.minute in minutes
                and candidate.hour in hours
                and candidate.day in dom
                and candidate.month in months
                and candidate.weekday() in dow
            ):
                return candidate
            candidate += timedelta(minutes=1)
        return None

    async def _dispatch_loop(self) -> None:
        """Main scheduling loop that dispatches due jobs."""
        while self._state != SchedulerState.STOPPED:
            try:
                if self._state == SchedulerState.RUNNING:
                    self._dispatch_due_jobs()
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unhandled error in dispatch loop")
                await asyncio.sleep(self._tick_interval)

    def _dispatch_due_jobs(self) -> None:
        """Check the priority queue and dispatch any jobs that are due."""
        now = datetime.utcnow()
        while self._queue:
            next_run, prio, job_id = self._queue[0]
            if job_id not in self._jobs:
                heapq.heappop(self._queue)
                continue
            if next_run > now:
                break
            heapq.heappop(self._queue)
            job = self._jobs[job_id]
            if not job.is_active:
                continue
            self._launch(job)

    def _launch(self, job: Job) -> None:
        """Launch a job execution in the background."""
        job.mark_running()
        task = asyncio.create_task(self._execute(job))
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)

    async def _execute(self, job: Job) -> None:
        """Execute a single job and handle retries / rescheduling."""
        async with self._semaphore:
            try:
                if asyncio.iscoroutinefunction(job.func):
                    result = await job.func(*job.args, **job.kwargs)
                else:
                    result = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: job.func(*job.args, **job.kwargs)
                    )
                job.mark_completed(result)
                logger.info("Job %s (%s) completed successfully", job.name, job.id)
            except Exception:
                logger.exception("Job %s (%s) failed", job.name, job.id)
                job.mark_failed(str(job.error) if job.error else "unknown error")

        # Reschedule recurring jobs
        if job.trigger in ("cron", "interval") and job.is_active:
            job.next_run = self._compute_next_run(job)
            if job.next_run:
                job.status = JobStatus.PENDING
                heapq.heappush(
                    self._queue, (job.next_run, job.priority.value, job.id)
                )
