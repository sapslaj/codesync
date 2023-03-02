import os
from dataclasses import dataclass
from typing import Iterable, Optional

from codesync import RepoAction, RepoState
from codesync.config import Config
from codesync.repo.repo_worker_pool import RepoWorkerPoolJob


@dataclass
class SyncedRepo:
    config: Config
    provider_name: str
    repo_name: str
    actions: list[RepoAction]
    state: RepoState
    default_branches: set[str]
    repo_path: str
    repo_clone_url: Optional[str] = None
    full_name: Optional[str] = None

    def job(self) -> RepoWorkerPoolJob:
        if not self.full_name:
            self.full_name = self.repo_name
        exists_locally = os.path.exists(self.repo_path)
        if exists_locally:
            action = self.repo_action_reduce(actions=self.actions, deletes=["clone"])
        else:
            action = self.repo_action_reduce(actions=self.actions, deletes=["delete", "pull"])
        clean = "clean" in self.actions and exists_locally
        return RepoWorkerPoolJob(
            config=self.config,
            provider_name=self.provider_name,
            action=action,
            actions=self.actions,
            clean=clean,
            default_branches=self.default_branches,
            exists_locally=exists_locally,
            full_name=self.full_name,
            repo_clone_url=self.repo_clone_url,
            repo_name=self.repo_name,
            repo_path=self.repo_path,
            state=self.state,
        )

    def repo_action_reduce(
        self, actions: Optional[Iterable[RepoAction]] = None, deletes: Optional[Iterable[RepoAction]] = None
    ) -> Optional[RepoAction]:
        if actions is None:
            actions = []
        if deletes is None:
            deletes = []
        return next(iter([action for action in actions if action not in deletes]), None)  # type: ignore
