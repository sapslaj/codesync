import os
from typing import Type

from codesync.config import DEFAULT_CONCURRENCY, DEFAULT_SRC_DIR, Config
from codesync.path import path_glob
from codesync.provider import Provider
from codesync.provider.generic import GenericProvider
from codesync.provider.github import GitHubProvider
from codesync.repo.repo_worker_pool import RepoWorkerPool


def main():
    config = Config()
    config.load_config_file()
    config.validate()
    codedir = os.path.expanduser(config.get("src_dir", default=DEFAULT_SRC_DIR))
    repo_worker_pool = RepoWorkerPool(size=config.get("concurrency", default=DEFAULT_CONCURRENCY))
    repo_worker_pool.start()
    for path, host_name in path_glob(f"{codedir}/*").items():
        ProviderClass: Type[Provider] = {
            "github.com": GitHubProvider,
            "generic": GenericProvider,
        }.get(host_name, GenericProvider)
        provider = ProviderClass(config=config, path=path, repo_worker_pool=repo_worker_pool)
        provider.sync()
    repo_worker_pool.finish().wait()


if __name__ == "__main__":
    main()
