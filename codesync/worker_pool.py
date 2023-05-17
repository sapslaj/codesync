import abc
import queue
import signal
import threading
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Optional

from codesync.config import DEFAULT_CONCURRENCY


@dataclass
class JobError:
    exc: Optional[BaseException]
    job: Any


class WorkerPool(abc.ABC):
    def __init__(self, size: int = DEFAULT_CONCURRENCY) -> None:
        self.exit = False
        self.size = size
        self.enable_concurrency = True
        if size == 0:
            self.enable_concurrency = False
        self.queue = queue.Queue()
        self.threads = [threading.Thread(target=self._consumer, args=(self.queue,)) for _ in range(self.size)]
        self.started = False
        self.errors: list[JobError] = []

    def start(self) -> "WorkerPool":
        if not self.enable_concurrency:
            return self
        if self.started:
            return self
        signal.signal(signal.SIGINT, self._exit_handler)
        signal.signal(signal.SIGTERM, self._exit_handler)
        [thread.start() for thread in self.threads]
        self.started = True
        return self

    def finish(self) -> "WorkerPool":
        if not self.enable_concurrency:
            return self
        if not self.started:
            return self
        self.queue.put(None)
        self.started = False
        return self

    def wait(self) -> "WorkerPool":
        if not self.enable_concurrency:
            return self
        [thread.join() for thread in self.threads]
        return self

    def push(self, job: Any) -> "WorkerPool":
        if not self.enable_concurrency:
            self.process(job=job)
            return self
        self.queue.put(job)
        return self

    @contextmanager
    def context(self):
        self.start()
        try:
            yield self
        except Exception:
            traceback.print_exc()
        finally:
            self.finish()
            self.wait()

    def _exit_handler(self, _sig, _frame):
        self.exit = True

    def _consumer(self, q: queue.Queue):
        while True:
            if self.exit:
                break
            try:
                job = q.get(block=True, timeout=1)
            except queue.Empty:
                if self.started:
                    continue
                else:
                    break
            if job is None:
                break
            try:
                self.process(job)
            except Exception as e:
                self.errors.append(JobError(exc=e, job=job))
                traceback.print_exc()

    @abc.abstractmethod
    def process(self, job: Any):
        pass
