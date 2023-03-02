from dataclasses import dataclass
from typing import Iterable, Optional

from codesync import RepoAction, RepoState
from codesync.command import run_command
from codesync.config import Config
from codesync.git import git_clean, git_clone, git_fetch, git_pull, repo_head_branch
from codesync.worker_pool import WorkerPool


@dataclass
class RepoWorkerPoolJob:
    config: Config
    provider_name: str
    action: Optional[RepoAction]
    actions: Iterable[RepoAction]
    clean: bool
    default_branches: Iterable[str]
    exists_locally: bool
    full_name: str
    repo_clone_url: Optional[str]
    repo_name: str
    repo_path: str
    state: RepoState

    def execute(self):
        provider_name = self.provider_name
        full_name = self.full_name
        repo_name = self.repo_name
        state = self.state
        repo_path = self.repo_path
        repo_clone_url = self.repo_clone_url
        actions = self.actions
        action = self.action
        exists_locally = self.exists_locally
        clean = self.clean
        default_branches = self.default_branches
        print(f"{self.provider_name}/{full_name}: {state=!s} {action=!s} {clean=!s}")
        if action == "raise":
            raise Exception(
                f"{full_name} needs your attention",
                f"{provider_name=}",
                f"{full_name=}",
                f"{repo_name=}",
                f"{state=}",
                f"{repo_path=}",
                f"{repo_clone_url=}",
                f"{actions=}",
                f"{action=}",
            )
        elif action == "delete":
            if exists_locally:
                run_command(f"rm -rf {repo_path}")
        elif action == "clone":
            if repo_clone_url:
                git_clone(
                    config=self.config,
                    clone_url=repo_clone_url,
                    destination=repo_path,
                )
        elif action == "pull":
            branch = repo_head_branch(repo_path=repo_path)
            if branch and branch in default_branches:
                git_pull(config=self.config, repo_path=repo_path)
            elif branch is not None:
                git_fetch(config=self.config, repo_path=repo_path)
        else:
            # nop
            pass

        if clean:
            git_clean(repo_path=repo_path)


class RepoWorkerPool(WorkerPool):
    def push(self, job: RepoWorkerPoolJob) -> "RepoWorkerPool":
        super().push(job)
        return self

    def process(self, job: RepoWorkerPoolJob):
        job.execute()
