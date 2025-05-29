import argparse
import os
import signal
import sys
from typing import Type

from codesync.config import DEFAULT_CONCURRENCY, DEFAULT_SRC_DIR, Config
from codesync.path import path_glob
from codesync.provider import Provider
from codesync.provider.generic import GenericProvider
from codesync.provider.github import GitHubProvider
from codesync.provider.gitlab import GitLabProvider
from codesync.repo.repo_worker_pool import RepoWorkerPool


def exit_handler(exit_code: int):
    def handler(_sig, _frame):
        sys.exit(exit_code)

    return handler


def main():
    signal.signal(signal.SIGINT, exit_handler(1))
    signal.signal(signal.SIGTERM, exit_handler(1))

    parser = argparse.ArgumentParser()
    parser.add_argument("path", default=None, nargs="?")
    parser.add_argument("--concurrency", default=DEFAULT_CONCURRENCY, type=int)
    parser.add_argument("--config-file", default=None)
    args = parser.parse_args()

    config = Config()
    config.load_config_file(filepath=args.config_file)
    config.validate()
    codedir = os.path.expanduser(config.get("src_dir", default=DEFAULT_SRC_DIR))

    concurrency = args.concurrency
    if args.concurrency == DEFAULT_CONCURRENCY:
        concurrency = config.get("concurrency", default=DEFAULT_CONCURRENCY)
    print(f"Concurrency: {concurrency}{' (disabled)' if concurrency == 0 else ''}")
    repo_worker_pool = RepoWorkerPool(size=concurrency)

    with repo_worker_pool.context():
        if args.path:
            path_parts = [part for part in args.path.split(os.path.sep) if part]
            host_name = None
            if len(path_parts) == 0:
                raise Exception(f"Invalid path: {args.path}")
            host_name = path_parts[0]
            path = os.path.join(codedir, host_name)
            ProviderClass = provider_for_host(host_name=host_name)
            provider = ProviderClass(config=config, path=path, repo_worker_pool=repo_worker_pool)
            if len(path_parts) > 1:
                sub_path = os.path.sep.join(path_parts[1:])
                provider.sync_path(sub_path)
            else:
                provider.sync_all()
        else:
            for path, host_name in path_glob(f"{codedir}/*").items():
                ProviderClass = provider_for_host(host_name=host_name)
                provider = ProviderClass(config=config, path=path, repo_worker_pool=repo_worker_pool)
                provider.sync_all()

    if repo_worker_pool.errors:
        print("*" * 80)
        print(f"Errors: {len(repo_worker_pool.errors)}")
        for i, error in enumerate(repo_worker_pool.errors, 1):
            print(f"{i}:\t".ljust(75, "*"))
            print("Job: ", error.job)
            print("Exception: ", error.exc)
        sys.exit(1)


def provider_for_host(host_name: str) -> Type[Provider]:
    return {
        "gitlab.com": GitLabProvider,
        "github.com": GitHubProvider,
        "generic": GenericProvider,
    }.get(host_name, GenericProvider)


if __name__ == "__main__":
    main()
