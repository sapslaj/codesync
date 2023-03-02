import abc
import queue
import threading
from typing import Any

from codesync.config import DEFAULT_CONCURRENCY


class WorkerPool(abc.ABC):
    def __init__(self, size: int = DEFAULT_CONCURRENCY) -> None:
        self.queue = queue.Queue()
        self.threads = [threading.Thread(target=self._consumer, args=(self.queue,)) for _ in range(size)]
        self.started = False

    def start(self) -> "WorkerPool":
        if self.started:
            return self
        [thread.start() for thread in self.threads]
        self.started = True
        return self

    def finish(self) -> "WorkerPool":
        if not self.started:
            return self
        self.queue.put(None)
        self.started = False
        return self

    def wait(self) -> "WorkerPool":
        [thread.join() for thread in self.threads]
        return self

    def push(self, job: Any) -> "WorkerPool":
        self.queue.put(job)
        return self

    def _consumer(self, q: queue.Queue):
        while True:
            try:
                job = q.get(block=True, timeout=1)
            except queue.Empty:
                if self.started:
                    continue
                else:
                    break
            if job is None:
                break
            self.process(job)

    @abc.abstractmethod
    def process(self, job: Any):
        pass
