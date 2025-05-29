import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, cast, override

import gitlab
from gitlab.v4.objects import GroupProject, Project

from codesync import RepoAction, RepoState
from codesync.config import DEFAULT_DEFAULT_BRANCH, DEFAULT_REPO_CLONE_SCHEME, Config
from codesync.provider import Provider
from codesync.provider_config.gitlab import GitLabProviderConfig
from codesync.repo.repo_worker_pool import RepoWorkerPool, RepoWorkerPoolJob
from codesync.repo.synced_repo import SyncedRepo
from codesync.worker_pool import WorkerPool


@dataclass
class GitLabRepoProcessorJob:
    config: Config
    group_name: str
    project_name: str
    state: RepoState
    repo_path: str
    push_function: Callable[[RepoWorkerPoolJob], Any]
    force_enable: bool = False
    project: Optional[GroupProject | Project] = None
    repo_clone_url: Optional[str] = None

    def org_config(self):
        return GitLabProviderConfig(config=self.config).group(self.group_name)

    def project_config(self):
        return self.org_config().project(self.project_name)

    def synced_repo(self) -> Optional[SyncedRepo]:
        project = self.project
        group_name = self.group_name
        project_name = self.project_name
        full_name = f"{group_name}/{project_name}"
        enabled = self.project_config().get("enabled")
        if not self.force_enable and enabled == False:
            print(f"{GitLabProvider.provider}/{full_name}: enabled=False")
            return
        state = self.state
        repo_path = self.repo_path
        repo_clone_url = self.repo_clone_url
        if project is not None and not repo_clone_url and self.state != "orphaned":
            repo_clone_url = {
                "https": project.http_url_to_repo,
                "ssh": project.ssh_url_to_repo,
            }.get(
                self.project_config().get(
                    "clone_scheme", default=DEFAULT_REPO_CLONE_SCHEME
                )
            )
        state = self.project_config().get("state", default=state)
        actions = self.project_actions_get(
            project_name=project_name,
            state=state,
        )
        default_branch = self.project_config().get("default_branch")
        default_branches = set(
            [default_branch]
            if default_branch
            else self.org_config().get(
                "default_branches", default=[DEFAULT_DEFAULT_BRANCH]
            )
        )
        return SyncedRepo(
            config=self.config,
            provider_name=GitLabProvider.provider,
            repo_name=project_name,
            actions=actions,
            state=state,
            default_branches=default_branches,
            repo_path=repo_path,
            repo_clone_url=repo_clone_url,
            full_name=full_name,
        )

    def project_actions_get(
        self,
        project_name: str,
        state: str,
        default: Optional[Iterable[RepoAction]] = None,
    ) -> list[RepoAction]:
        if default is None:
            default = []
        specific_project_actions = self.org_config().get(
            "projects", project_name, "actions", state
        )
        if specific_project_actions:
            return specific_project_actions
        return self.project_config().get("actions", state, default=default)


class GitLabRepoProcessorWorkerPool(WorkerPool):
    def push(self, job: GitLabRepoProcessorJob) -> "GitLabRepoProcessorWorkerPool":
        return cast(GitLabRepoProcessorWorkerPool, super().push(job))

    def process(self, job: GitLabRepoProcessorJob):
        synced_repo = job.synced_repo()
        if synced_repo:
            job.push_function(synced_repo.job())


class GitLabProvider(Provider):
    provider = "gitlab.com"

    def __init__(
        self, config: Config, path: str, repo_worker_pool: RepoWorkerPool
    ) -> None:
        super().__init__(config=config, path=path, repo_worker_pool=repo_worker_pool)
        self.provider_config = GitLabProviderConfig(config=config)
        self.gitlab = gitlab.Gitlab(
            private_token=self.provider_config.get(
                "auth", "token", default=os.environ.get("GITLAB_TOKEN")
            )
        )
        self.gitlab.auth()
        self.repo_processor_worker_pool = GitLabRepoProcessorWorkerPool(
            size=repo_worker_pool.size
        )

    def get_group_projects(self, group_name: str) -> Iterable[GroupProject]:
        return self.gitlab.groups.get(group_name).list(iterable=True)

    def get_group_project(self, group_name: str, project_name: str) -> Project:
        return self.gitlab.projects.get(f"{group_name}/{project_name}")

    def get_local_subgroup_names(self, top: str | None = None) -> set[str]:
        subgroups: set[str] = set()

        def load_potential_subgroups(dir: str):
            subdirs = [
                subdir
                for subdir in os.listdir(dir)
                if os.path.isdir(os.path.join(dir, subdir))
            ]
            if ".git" in subdirs:
                return
            group_name = dir.removeprefix(self.path)
            if group_name:
                subgroups.add(group_name.removeprefix("/"))
            for subdir in subdirs:
                load_potential_subgroups(f"{dir}/{subdir}")

        if top:
            load_potential_subgroups(f"{self.path}/{top}")
        else:
            load_potential_subgroups(self.path)

        return subgroups

    @override
    def sync_all(self):
        config_groups: set[str] = set(
            group
            for group in self.provider_config.get("groups", default={}).keys()
            if group != "_"
        )
        fs_groups: set[str] = self.get_local_subgroup_names()

        with self.repo_processor_worker_pool.context():
            for group_name in set(list(config_groups) + list(fs_groups)):
                if group_name.startswith("/"):
                    # skip regex names
                    continue
                org_enabled = self.provider_config.group(group_name).get("enabled")
                if org_enabled is False:
                    print(f"{self.provider}/{group_name}: enabled=False")
                    continue
                jobs = self.group_project_repo_processor_jobs(
                    group_name=group_name,
                    remote=(org_enabled is True),
                )
                for job in jobs:
                    self.repo_processor_worker_pool.push(job)

    @override
    def sync_path(self, path: str):
        group_name: str | None = None
        project_name: str | None = None
        project_name = path.split("/")[-1]
        try:
            self.gitlab.groups.get(path)
            group_name = path
            project_name = None
        except gitlab.GitlabGetError:
            path_parts = path.split("/")
            project_name = path_parts[-1]
            group_name = "/".join(path_parts[:-1])

        org_enabled = self.provider_config.group(group_name).get("enabled")
        if org_enabled is False:
            print(f"[WARN] {self.provider}/{group_name} is disabled via config")

        with self.repo_processor_worker_pool.context():
            if project_name:
                project: Project | None = None
                try:
                    project = self.get_group_project(
                        group_name=group_name, project_name=project_name
                    )
                    state = "archived" if project.archived else "active"
                except gitlab.GitlabGetError:
                    state = "orphaned"

                repo_path = self.path_join(group_name, project_name)
                self.repo_processor_worker_pool.push(
                    GitLabRepoProcessorJob(
                        config=self.config,
                        push_function=self.repo_worker_pool.push,
                        project=project,
                        group_name=group_name,
                        project_name=project_name,
                        state=state,
                        repo_path=repo_path,
                        force_enable=True,
                    )
                )
            else:
                jobs = self.group_project_repo_processor_jobs(
                    group_name=group_name, remote=(org_enabled is True)
                )
                for job in jobs:
                    self.repo_processor_worker_pool.push(job)

    def group_project_repo_processor_jobs(
        self,
        group_name: str,
        remote: bool = True,
        local: bool = True,
    ) -> Iterable[GitLabRepoProcessorJob]:
        jobs: list[GitLabRepoProcessorJob] = []
        remote_project_names = []
        if remote:
            projects = self.get_group_projects(group_name=group_name)
            for project in projects:
                state = "archived" if project.archived else "active"
                repo_path = self.path_join(project.path_with_namespace)
                jobs.append(
                    GitLabRepoProcessorJob(
                        config=self.config,
                        push_function=self.repo_worker_pool.push,
                        project=project,
                        group_name=group_name,
                        project_name=project.name,
                        state=state,
                        repo_path=repo_path,
                    )
                )
            remote_project_names = [r.path_with_namespace for r in projects]
        if local:
            current_repos: dict[str, str] = {}
            for path, name in self.path_glob(f"{group_name}/*").items():
                if ".git" not in os.listdir(path):
                    continue
                current_repos[path] = name
            for repo_path, project_name in current_repos.items():
                if project_name in remote_project_names:
                    continue
                try:
                    project = self.get_group_project(
                        group_name=group_name, project_name=project_name
                    )
                    state = "archived" if project.archived else "active"
                except gitlab.GitlabGetError:
                    state = "orphaned"
                self.config
                jobs.append(
                    GitLabRepoProcessorJob(
                        config=self.config,
                        push_function=self.repo_worker_pool.push,
                        group_name=group_name,
                        project_name=project_name,
                        state=state,
                        repo_path=repo_path,
                    )
                )
        return jobs
