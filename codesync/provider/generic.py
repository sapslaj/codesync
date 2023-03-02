from codesync import RepoAction
from codesync.config import DEFAULT_DEFAULT_BRANCH, Config
from codesync.provider import Provider
from codesync.provider_config.generic import GenericProviderConfig
from codesync.repo.repo_worker_pool import RepoWorkerPool
from codesync.repo.synced_repo import SyncedRepo


class GenericProvider(Provider):
    provider = "generic"

    def __init__(self, config: Config, path: str, repo_worker_pool: RepoWorkerPool) -> None:
        super().__init__(config=config, path=path, repo_worker_pool=repo_worker_pool)
        self.provider_config = GenericProviderConfig(config=config)

    def sync(self) -> None:
        for repo_path, repo_name in self.path_glob("*").items():
            repo_config = self.provider_config.repo(repo_name)
            if not repo_config.get("enabled"):
                print(f"{repo_path}: enabled=False")
                continue
            state = repo_config.get("state", default="active")
            actions: list[RepoAction] = repo_config.get("actions", state, default=[])
            default_branch = repo_config.get("default_branch", default=DEFAULT_DEFAULT_BRANCH)
            synced_repo = SyncedRepo(
                config=self.config,
                provider_name=self.provider,
                repo_name=repo_name,
                actions=actions,
                repo_path=repo_path,
                state=state,
                default_branches=set([default_branch]),
            )
            self.repo_worker_pool.push(synced_repo.job())
