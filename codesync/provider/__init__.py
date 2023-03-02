import abc
import os
from typing import Iterable

from codesync.config import Config
from codesync.path import path_glob
from codesync.repo.repo_worker_pool import RepoWorkerPool


class Provider(abc.ABC):
    def __init__(self, config: Config, path: str, repo_worker_pool: RepoWorkerPool) -> None:
        self.config = config
        self.path = path
        self.repo_worker_pool = repo_worker_pool

    def path_join(self, *paths: Iterable[str]) -> str:
        return os.path.join(self.path, *paths)  # type: ignore

    def path_glob(self, path: str) -> dict[str, str]:
        return path_glob(self.path_join(path))

    @abc.abstractmethod
    def sync(self) -> None:
        pass
