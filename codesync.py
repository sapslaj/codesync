#!/usr/bin/env python3.10
import operator
import os
import re
from functools import reduce
from glob import glob
from os import PathLike
from typing import Any, Iterable, Literal, Optional

from github import Github
from github.Repository import Repository
from mergedeep import merge
import ruyaml

RepoAction = Literal["clone", "delete", "pull", "raise"]
RepoState = Literal["active", "archived", "orphaned"]

config = {
    "providers": {
        "github.com": {
            "orgs": {
                "_": {
                    "enabled": True,
                    "repos": {
                        "_": {
                            "enabled": True,
                            "actions": {
                                "active": ["pull"],
                                "archived": [],
                                "orphaned": [],
                            }
                        },
                    },
                },
            },
        },
    },
}


def config_get(*keys: Iterable[str], default: Any = None) -> Any:
    global config
    try:
        return reduce(operator.getitem, keys, config)
    except KeyError:
        return default


def run_command(cmd, dry_run=False):
    print(cmd)
    if not dry_run:
        os.system(cmd)


def path_glob(path: PathLike) -> dict[str, str]:
    return dict([(d, os.path.split(d)[-1]) for d in glob(path) if os.path.isdir(d)])


def git_clone(clone_url: str, destination: PathLike):
    run_command(f"git clone --recurse-submodules {clone_url} {destination}")


def git_fetch(repo_path: str):
    run_command(f"git -C {repo_path} fetch --prune --verbose")


def git_pull(repo_path: str):
    run_command(f"git -C {repo_path} pull --verbose --ff-only --autostash")


def repo_head_branch(repo_path: str) -> Optional[str]:
    with open(os.path.join(repo_path, ".git", "HEAD"), "r") as head_file:
        head = head_file.readline().strip()
    head_parse = re.search("^ref: refs/heads/(.*)$", head)
    if not head_parse:
        return
    return head_parse[1]


class Provider(object):
    provider = "_"

    def __init__(self, path: str) -> None:
        self.path = path

    def sync(self) -> None:
        pass

    def path_join(self, *paths: Iterable[PathLike]) -> PathLike:
        return os.path.join(self.path, *paths)

    def path_glob(self, path: PathLike) -> dict[str, str]:
        return path_glob(self.path_join(path))

    def config_get(self, *keys: Iterable[str], default: Any = None) -> Any:
        return config_get("providers", self.provider, *keys, default=default)


class GitHubProvider(Provider):
    provider = "github.com"

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.github = Github(self.config_get("auth", "token", default=os.environ.get("GITHUB_TOKEN")))

    def sync(self):
        for org_name in self.path_glob("*").values():
            if not self.org_config_get("enabled", org_name=org_name):
                continue
            current_repos = self.path_glob(f"{org_name}/*")
            repos = self._get_org_repos(org_name=org_name)
            for repo in repos:
                self._sync_repo(
                    org_name=org_name,
                    repo_name=repo.name,
                    state=("archived" if repo.archived else "active"),
                    repo_clone_url=repo.clone_url,
                )
            for repo_path, repo_name in current_repos.items():
                if repo_name in [r.name for r in repos]:
                    continue
                self._sync_repo(
                    org_name=org_name,
                    repo_name=repo_name,
                    state="orphaned",
                    repo_path=repo_path,
                )

    def _sync_repo(
        self,
        org_name: str,
        repo_name: str,
        state: RepoState,
        repo_path: str = None,
        repo_clone_url: str = None,
    ):
        enabled = self.repo_config_get("enabled", org_name=org_name, repo_name=repo_name)
        if not enabled:
            return
        if not repo_path:
            repo_path = self.path_join(org_name, repo_name)
        actions: list[RepoAction] = self.repo_config_get("actions", state, org_name=org_name, repo_name=repo_name) or []
        if os.path.exists(repo_path):
            action = self._repo_action_reduce(actions=actions, deletes=["clone"])
        else:
            action = self._repo_action_reduce(actions=actions, deletes=["delete", "pull"])
        print(f"{org_name}/{repo_name}: action={action}")
        match action:
            case "raise":
                raise Exception(
                    f"{org_name}/{repo_name} needs your attention",
                    f"org_name={org_name}",
                    f"repo_name={repo_name}",
                    f"state={state}",
                    f"repo_path={repo_path}",
                    f"repo_clone_url={repo_clone_url}",
                    f"actions={actions}",
                    f"action={action}",
                )
            case "delete":
                if os.path.exists(repo_path):
                    run_command(f"rm -rf {repo_path}")
            case "clone":
                if repo_clone_url:
                    git_clone(
                        clone_url=repo_clone_url,
                        destination=repo_path,
                    )
            case "pull":
                branch = repo_head_branch(repo_path=repo_path)
                if branch == "main":
                    git_pull(repo_path=repo_path)
                elif branch is not None:
                    git_fetch(repo_path=repo_path)

    def _repo_action_reduce(self, actions: Iterable[RepoAction] = [], deletes: list[RepoAction] = []) -> Optional[RepoAction]:
        return next(iter([action for action in actions if action not in deletes]), None)

    def _get_org_repos(self, org_name: str) -> Iterable[Repository]:
        user = self.github.get_user(org_name)
        if user.type == "Organization":
            org = self.github.get_organization(org_name)
            return org.get_repos()
        return user.get_repos()

    def org_config_get(self, *keys: Iterable[str], org_name: str, default: Any = None) -> Any:
        default = self.config_get("orgs", "_", *keys, default=default)
        return self.config_get("orgs", org_name, *keys, default=default)

    def repo_config_get(self, *keys: Iterable[str], org_name: str, repo_name: str, default: Any = None) -> Any:
        default = self.org_config_get("repos", "_", *keys, org_name=org_name, default=default)
        return self.org_config_get("repos", repo_name, *keys, org_name=org_name, default=default)


def main():
    global config
    config_filename = os.path.join(os.path.expanduser("~"), ".codesync.yaml")
    with open(config_filename, "r") as f:
        config = merge(config, ruyaml.safe_load(f))
    codedir = os.path.join(os.path.expanduser("~"), "code")
    for path, host_name in path_glob(f"{codedir}/*").items():
        _Provider: Provider = {
            "github.com": GitHubProvider,
        }.get(host_name, Provider)
        provider = _Provider(path=path)
        provider.sync()


if __name__ == "__main__":
    main()
