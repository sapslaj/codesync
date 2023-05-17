import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, cast

import more_itertools
from github import Github, UnknownObjectException
from github.Repository import Repository

from codesync import RepoAction, RepoState
from codesync.config import DEFAULT_REPO_CLONE_SCHEME, Config
from codesync.provider import Provider
from codesync.provider_config.github import GitHubProviderConfig
from codesync.repo.repo_worker_pool import RepoWorkerPool, RepoWorkerPoolJob
from codesync.repo.synced_repo import SyncedRepo
from codesync.worker_pool import WorkerPool


@dataclass
class GitHubRepoProcessorJob:
    config: Config
    org_name: str
    repo_name: str
    state: RepoState
    repo_path: str
    push_function: Callable[[RepoWorkerPoolJob], Any]
    topics: Optional[Iterable[str]] = None
    repo: Optional[Repository] = None
    repo_clone_url: Optional[str] = None

    def org_config(self):
        return GitHubProviderConfig(config=self.config).org(self.org_name)

    def repo_config(self):
        return self.org_config().repo(self.repo_name)

    def synced_repo(self) -> Optional[SyncedRepo]:
        repo = self.repo
        org_name = self.org_name
        repo_name = self.repo_name
        full_name = f"{org_name}/{repo_name}"
        enabled = self.repo_config().get("enabled")
        if not enabled:
            print(f"{GitHubProvider.provider}/{full_name}: enabled=False")
            return
        state = self.state
        topics = self.topics
        if not topics:
            if repo:
                topics = repo.get_topics()
            else:
                topics = []
        repo_path = self.repo_path
        repo_clone_url = self.repo_clone_url
        if repo is not None and not repo_clone_url and self.state != "orphaned":
            repo_clone_url = {
                "https": repo.clone_url,
                "ssh": repo.ssh_url,
            }.get(self.repo_config().get("clone_scheme", default=DEFAULT_REPO_CLONE_SCHEME))
        state = self.repo_config().get("state", default=state)
        actions = self.repo_actions_get(repo_name=repo_name, state=state, topics=topics)
        default_branch = self.repo_config().get("default_branch")
        default_branches = set(
            [default_branch] if default_branch else self.org_config().get("default_branches", default=[])
        )
        return SyncedRepo(
            config=self.config,
            provider_name=GitHubProvider.provider,
            repo_name=repo_name,
            actions=actions,
            state=state,
            default_branches=default_branches,
            repo_path=repo_path,
            repo_clone_url=repo_clone_url,
            full_name=full_name,
        )

    def repo_actions_get(
        self,
        repo_name: str,
        state: str,
        topics: Optional[Iterable[str]] = None,
        default: Optional[Iterable[RepoAction]] = None,
    ) -> list[RepoAction]:
        if default is None:
            default = []
        if topics is None:
            topics = []
        specific_repo_actions = self.org_config().get("repos", repo_name, "actions", state)
        if specific_repo_actions:
            return specific_repo_actions
        topic_actions = [
            a
            for a in set(
                more_itertools.collapse([self.org_config().topic(topic).get("actions", state) for topic in topics])
            )
            if a is not None
        ]
        if topic_actions:
            return topic_actions
        return self.repo_config().get("actions", state, default=default)


class GitHubRepoProcessorWorkerPool(WorkerPool):
    def push(self, job: GitHubRepoProcessorJob) -> "GitHubRepoProcessorWorkerPool":
        return cast(GitHubRepoProcessorWorkerPool, super().push(job))

    def process(self, job: GitHubRepoProcessorJob):
        synced_repo = job.synced_repo()
        if synced_repo:
            job.push_function(synced_repo.job())


class GitHubProvider(Provider):
    provider = "github.com"

    def __init__(self, config: Config, path: str, repo_worker_pool: RepoWorkerPool) -> None:
        super().__init__(config=config, path=path, repo_worker_pool=repo_worker_pool)
        self.provider_config = GitHubProviderConfig(config=config)
        self.github = Github(self.provider_config.get("auth", "token", default=os.environ.get("GITHUB_TOKEN")))
        self.repo_processor_worker_pool = GitHubRepoProcessorWorkerPool(size=repo_worker_pool.size)

    def get_org_repos(self, org_name: str) -> Iterable[Repository]:
        user = self.github.get_user(org_name)
        if user.type == "Organization":
            org = self.github.get_organization(org_name)
            return org.get_repos()
        # Gotta do this weird dance with users because GitHub's API doesn't
        # support getting all accessible repos for a user, only an org.
        public_repos = list(user.get_repos())
        private_repos = [repo for repo in self.github.get_user().get_repos() if repo.owner.login == org_name]
        return list(set(public_repos + private_repos))

    def get_org_repo(self, org_name: str, repo_name: str) -> Repository:
        return self.github.get_repo(f"{org_name}/{repo_name}")

    def sync_all(self):
        config_orgs: list[str] = [org for org in self.provider_config.get("orgs", default={}).keys() if org != "_"]
        fs_orgs: list[str] = list(self.path_glob("*").values())
        with self.repo_processor_worker_pool.context():
            for org_name in set(config_orgs + fs_orgs):
                if org_name.startswith("/"):
                    # skip regex names
                    continue
                org_enabled = self.provider_config.org(org_name).get("enabled")
                if org_enabled is False:
                    print(f"{self.provider}/{org_name}: enabled=False")
                    continue
                jobs = self.org_repo_processor_jobs(org_name=org_name, remote=(org_enabled is True))
                for job in jobs:
                    self.repo_processor_worker_pool.push(job)

    def sync_path(self, path: str):
        path_parts = path.split("/")
        org_name = None
        repo_name = None
        if len(path_parts) == 1:
            org_name = path_parts[0]
        elif len(path_parts) == 2:
            org_name, repo_name = path_parts
        else:
            raise Exception(f"invalid path: {path}")

        org_enabled = self.provider_config.org(org_name).get("enabled")
        if org_enabled is False:
            print(f"[WARN] {self.provider}/{org_name} is disabled via config")

        with self.repo_processor_worker_pool.context():
            if repo_name:
                repo = None
                try:
                    repo = self.get_org_repo(org_name=org_name, repo_name=repo_name)
                    state = "archived" if repo.archived else "active"
                except UnknownObjectException:
                    state = "orphaned"
                repo_path = self.path_join(org_name, repo_name)
                self.repo_processor_worker_pool.push(
                    GitHubRepoProcessorJob(
                        config=self.config,
                        push_function=self.repo_worker_pool.push,
                        repo=repo,
                        org_name=org_name,
                        repo_name=repo_name,
                        state=state,
                        repo_path=repo_path,
                    )
                )
            else:
                jobs = self.org_repo_processor_jobs(org_name=org_name, remote=(org_enabled is True))
                for job in jobs:
                    self.repo_processor_worker_pool.push(job)

    def org_repo_processor_jobs(
        self, org_name: str, remote: bool = True, local: bool = True
    ) -> Iterable[GitHubRepoProcessorJob]:
        jobs: list[GitHubRepoProcessorJob] = []
        remote_repo_names = []
        if remote:
            repos = self.get_org_repos(org_name=org_name)
            for repo in repos:
                state = "archived" if repo.archived else "active"
                repo_path = self.path_join(org_name, repo.name)
                jobs.append(
                    GitHubRepoProcessorJob(
                        config=self.config,
                        push_function=self.repo_worker_pool.push,
                        repo=repo,
                        org_name=org_name,
                        repo_name=repo.name,
                        state=state,
                        repo_path=repo_path,
                    )
                )
            remote_repo_names = [r.name for r in repos]
        if local:
            current_repos = self.path_glob(f"{org_name}/*")
            for repo_path, repo_name in current_repos.items():
                if repo_name in remote_repo_names:
                    continue
                try:
                    repo = self.get_org_repo(org_name=org_name, repo_name=repo_name)
                    state = "archived" if repo.archived else "active"
                except UnknownObjectException:
                    state = "orphaned"
                jobs.append(
                    GitHubRepoProcessorJob(
                        config=self.config,
                        push_function=self.repo_worker_pool.push,
                        org_name=org_name,
                        repo_name=repo_name,
                        state=state,
                        repo_path=repo_path,
                    )
                )
        return jobs
