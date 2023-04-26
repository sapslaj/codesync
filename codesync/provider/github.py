import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, cast

import more_itertools
from github import Github
from github.Repository import Repository

from codesync import RepoAction, RepoState
from codesync.config import Config
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
            }.get(self.repo_config().get("clone_scheme"))
        full_name = f"{org_name}/{repo_name}"
        enabled = self.repo_config().get("enabled")
        if not enabled:
            print(f"{GitHubProvider.provider}/{full_name}: enabled=False")
            return
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
        default=Optional[Iterable[RepoAction]],
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
        self.repo_processor_worker_pool = GitHubRepoProcessorWorkerPool(config.get("concurrency"))

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

    def sync(self):
        config_orgs: list[str] = [org for org in self.provider_config.get("orgs", default={}).keys() if org != "_"]
        fs_orgs: list[str] = list(self.path_glob("*").values())
        self.repo_processor_worker_pool.start()
        for org_name in set(config_orgs + fs_orgs):
            if org_name.startswith("/"):
                # skip regex names
                continue
            if not self.provider_config.org(org_name).get("enabled"):
                print(f"{self.provider}/{org_name}: enabled=False")
                continue
            repos = self.get_org_repos(org_name=org_name)
            for repo in repos:
                state = "archived" if repo.archived else "active"
                repo_path = self.path_join(org_name, repo.name)
                self.repo_processor_worker_pool.push(
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
            current_repos = self.path_glob(f"{org_name}/*")
            remote_repo_names = [r.name for r in repos]
            for repo_path, repo_name in current_repos.items():
                if repo_name in remote_repo_names:
                    continue
                self.repo_processor_worker_pool.push(
                    GitHubRepoProcessorJob(
                        config=self.config,
                        push_function=self.repo_worker_pool.push,
                        org_name=org_name,
                        repo_name=repo_name,
                        state="orphaned",
                        repo_path=repo_path,
                    )
                )
        self.repo_processor_worker_pool.finish().wait()
