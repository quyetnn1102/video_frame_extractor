"""
Background jobs for the slow work: downloading a video, then extracting frames or rendering a short.

A request starts a job and returns at once; the page polls the job for its stage and progress,
and can cancel it. Jobs live in memory only (one process: deploy.py runs a single worker), so a
restart forgets them. The files a finished job produced stay on disk and are listed as before.
"""
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from logger import app_logger

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED = 'queued', 'running', 'succeeded', 'failed', 'cancelled'
FINISHED_STATES = frozenset({SUCCEEDED, FAILED, CANCELLED})

KEEP_FINISHED_SECONDS = 3600   # finished jobs stay visible for an hour
MAX_KEPT_JOBS = 50             # and never more than this many in memory
MAX_UNFINISHED_JOBS = 10       # running or waiting; more are refused (429)
UNEXPECTED_ERROR = 'Something went wrong while working on this. See the application log.'
STARTING_MESSAGE = 'Starting'
WAITING_MESSAGE = 'Waiting for another job to finish'


class JobCancelled(Exception):
    """Raised inside a job's work when the user cancels it; the work stops and cleans up."""


class JobFailed(Exception):
    """An expected failure with a message that is safe to show (no paths, no exception text)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Job:
    id: str
    kind: str
    stages: Sequence[str]
    state: str = QUEUED
    stage: Optional[str] = None
    progress: Optional[float] = None   # 0..1 within the current stage; None when unknown
    message: str = 'Waiting to start'
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    subject: Optional[str] = None  # the file the job works on (a short's name), if any

    def to_dict(self) -> Dict[str, Any]:
        """What the browser sees."""
        end = self.finished or time.time()
        return {
            'id': self.id,
            'kind': self.kind,
            'state': self.state,
            'stage': self.stage,
            'stage_index': self.stages.index(self.stage) + 1 if self.stage in self.stages else 0,
            'stage_count': len(self.stages),
            'progress': None if self.progress is None else round(self.progress, 3),
            'message': self.message,
            'result': self.result,
            'error': self.error,
            'created': datetime.fromtimestamp(self.created, timezone.utc).isoformat(),
            'elapsed_seconds': round(end - (self.started or self.created), 1),
            'subject': self.subject,
        }


class JobReporter:
    """Handed to a job's work function: reports what is happening and stops it when cancelled."""

    def __init__(self, registry: 'JobRegistry', job: Job):
        self._registry = registry
        self._job = job

    def stage(self, name: str, message: str) -> None:
        self.check_cancelled()
        self._registry.update(self._job, stage=name, message=message, progress=None)

    def progress(self, fraction: Optional[float]) -> None:
        """Also the cancellation point: call it often from loops and download hooks."""
        self.check_cancelled()
        if fraction is not None:
            fraction = min(1.0, max(0.0, float(fraction)))
        self._registry.update(self._job, progress=fraction)

    def check_cancelled(self) -> None:
        if self._job.cancel_requested.is_set():
            raise JobCancelled()


class NullReporter:
    """For the synchronous API routes: same calls, nothing reported, never cancelled."""

    def stage(self, name: str, message: str) -> None:
        pass

    def progress(self, fraction: Optional[float]) -> None:
        pass

    def check_cancelled(self) -> None:
        pass


class JobQueueFull(Exception):
    """Too many jobs are already waiting or running; the request should be refused (429)."""


class JobRegistry:
    """
    Runs jobs on a few daemon threads. Daemon threads matter: stopping the app (Ctrl+C, a service
    stop) must not wait for an hour-long render. A job cut off that way leaves its partial files
    in the working folders, which are emptied when the app starts (app_enhanced.run_startup_cleanup).
    """

    def __init__(self, max_workers: int, max_unfinished: int = MAX_UNFINISHED_JOBS):
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}
        self._on_cancel_while_queued: Dict[str, Callable[[], None]] = {}
        self._max_workers = max_workers
        self._max_unfinished = max_unfinished
        self._queue: 'queue.Queue[Optional[Tuple[Job, Callable]]]' = queue.Queue()
        for number in range(max_workers):
            threading.Thread(target=self._worker, name=f'job-{number + 1}', daemon=True).start()

    def submit(self, kind: str, stages: Sequence[str],
               work: Callable[[JobReporter], Dict[str, Any]],
               on_cancel_while_queued: Optional[Callable[[], None]] = None,
               subject: Optional[str] = None) -> Job:
        """
        Queues `work`; it returns the job's result or raises JobFailed / JobCancelled.
        `on_cancel_while_queued` runs when the job is cancelled before it started (the work, which
        would normally record the outcome, then never runs). Raises JobQueueFull.
        """
        job = Job(id=uuid.uuid4().hex, kind=kind, stages=tuple(stages), subject=subject)
        with self._lock:
            self._prune()
            unfinished = sum(1 for other in self._jobs.values() if other.state not in FINISHED_STATES)
            if unfinished >= self._max_unfinished:
                raise JobQueueFull()
            job.message = WAITING_MESSAGE if unfinished >= self._max_workers else STARTING_MESSAGE
            self._jobs[job.id] = job
            if on_cancel_while_queued:
                self._on_cancel_while_queued[job.id] = on_cancel_while_queued
        self._queue.put((job, work))
        return job

    def active_subjects(self) -> Set[str]:
        """The files that queued or running jobs work on."""
        with self._lock:
            return {job.subject for job in self._jobs.values()
                    if job.subject and job.state not in FINISHED_STATES}

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> List[Job]:
        """Newest first."""
        with self._lock:
            self._prune()
            return sorted(self._jobs.values(), key=lambda job: job.created, reverse=True)

    def snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        """The job as the browser sees it, read in one go (never half of an update)."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def snapshots(self) -> List[Dict[str, Any]]:
        """Every job as the browser sees it, newest first."""
        with self._lock:
            self._prune()
            return [job.to_dict() for job in sorted(self._jobs.values(), key=lambda job: job.created, reverse=True)]

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Asks a job to stop and returns its snapshot (None when unknown). A queued job stops at
        once; a running one at its next progress report.
        """
        on_cancel = None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.state not in FINISHED_STATES:
                job.cancel_requested.set()
                if job.state == QUEUED:
                    self._finish(job, CANCELLED, message='Cancelled')
                    on_cancel = self._on_cancel_while_queued.pop(job.id, None)
                else:
                    job.message = 'Cancelling...'
            result = job.to_dict()
        if on_cancel:
            on_cancel()  # outside the lock: it writes to the database
        return result

    def update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(job, name, value)

    def shutdown(self) -> None:
        """Stops the workers once their current job ends (used by tests)."""
        for _ in range(self._max_workers):
            self._queue.put(None)

    # -- internals ----------------------------------------------------------------

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            self._run(*item)

    def _run(self, job: Job, work: Callable[[JobReporter], Dict[str, Any]]) -> None:
        with self._lock:
            self._on_cancel_while_queued.pop(job.id, None)
            if job.state != QUEUED:  # cancelled while it waited for a free worker
                return
            job.state, job.started, job.message = RUNNING, time.time(), 'Starting'
        try:
            result = work(JobReporter(self, job))
        except JobCancelled:
            self._finish_locked(job, CANCELLED, message='Cancelled')
        except JobFailed as failure:
            self._finish_locked(job, FAILED, message='Failed', error=failure.message)
        except Exception as error:
            app_logger.exception(f"Job {job.id[:8]} crashed", kind=job.kind, error_type=type(error).__name__)
            self._finish_locked(job, FAILED, message='Failed', error=UNEXPECTED_ERROR)
        else:
            self._finish_locked(job, SUCCEEDED, message='Done', result=result, progress=1.0)

    def _finish_locked(self, job: Job, state: str, **changes: Any) -> None:
        with self._lock:
            self._finish(job, state, **changes)

    @staticmethod
    def _finish(job: Job, state: str, **changes: Any) -> None:
        for name, value in changes.items():
            setattr(job, name, value)
        job.state, job.finished = state, time.time()

    def _prune(self) -> None:
        """Forgets old finished jobs. Call with the lock held."""
        now = time.time()
        expired = [job_id for job_id, job in self._jobs.items()
                   if job.state in FINISHED_STATES and now - (job.finished or now) > KEEP_FINISHED_SECONDS]
        for job_id in expired:
            del self._jobs[job_id]
        finished = sorted((job for job in self._jobs.values() if job.state in FINISHED_STATES),
                          key=lambda job: job.created)
        while len(self._jobs) >= MAX_KEPT_JOBS and finished:
            del self._jobs[finished.pop(0).id]
