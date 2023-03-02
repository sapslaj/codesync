#!/usr/bin/env python3
import json
import operator
import os
import re
import sys
from functools import reduce
from glob import glob
from typing import Any, Iterable, Literal, Optional, Type

import jsonschema
import more_itertools
import ruyaml
from github import Github
from github.Repository import Repository
from mergedeep import merge

if sys.version_info < (3, 9):
    # importlib.resources either doesn't exist or lacks the files()
    # function, so use the PyPI version:
    import importlib_resources
else:
    # importlib.resources has files(), so use that:
    import importlib.resources as importlib_resources

RepoAction = Literal["clone", "delete", "pull", "raise", "nop"]
RepoState = Literal["active", "archived", "orphaned"]
RepoCloneScheme = Literal["https", "ssh"]

VERSION = 0.7

DEFAULT_SRC_DIR = "~/src"
DEFAULT_DEFAULT_BRANCH = "main"  # lovely name
DEFAULT_REPO_CLONE_SCHEME: RepoCloneScheme = "https"

config = {
    "version": VERSION,
    "src_dir": DEFAULT_SRC_DIR,
    "git": {
        "clone": {"args": []},
        "fetch": {"args": []},
        "pull": {"args": []},
    },
    "providers": {
        "_": {
            "repos": {
                "_": {
                    "enabled": False,
                    "state": "active",
                    "default_branch": DEFAULT_DEFAULT_BRANCH,
                },
            },
        },
        "github.com": {
            "orgs": {
                "_": {
                    "enabled": True,
                    "default_branches": [DEFAULT_DEFAULT_BRANCH],
                    "repos": {
                        "_": {
                            "enabled": True,
                            "default_branch": DEFAULT_DEFAULT_BRANCH,
                            "clone_scheme": DEFAULT_REPO_CLONE_SCHEME,
                            "actions": {
                                "active": ["pull"],
                                "archived": [],
                                "orphaned": [],
                            },
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
        return reduce(operator.getitem, keys, config)  # type:ignore
    except (KeyError, TypeError):
        return default


def config_regex_get(*path: Iterable[str], keys: Iterable[str], default: Any = None) -> Any:
    global config
    key_groups = list(more_itertools.split_at(path, lambda k: k == "{}", 1))
    before_keys, after_keys = [], []
    if len(key_groups) == 1:
        before_keys = key_groups[0]
    elif len(key_groups) == 2:
        before_keys, after_keys = key_groups
    key, *child_keys = keys
    parent = config_get(*before_keys)
    if not isinstance(parent, dict):
        return default
    regex_keys = sorted([regex_key for regex_key in parent if regex_key.startswith("/")], key=len, reverse=True)
    for regex_key in regex_keys:
        if not isinstance(regex_key, str):
            continue
        parts = regex_key.split("/")
        flags = parts[-1]
        if flags:
            flags = f"(?{flags})"
        pattern = "/".join(parts[1:-1])
        if re.fullmatch(f"{flags}{pattern}", key):
            if child_keys:
                return config_regex_get(*before_keys, regex_key, *after_keys, keys=child_keys, default=default)
            else:
                return config_get(*before_keys, regex_key, *after_keys, default=default)
    return default


def config_validate():
    config_version = config["version"]
    print(f"Checking config (version {config_version}).")
    if config_version > VERSION:
        raise Exception(
            "codesync: fatal: configuration file version is higher than what this version of codesync can handle"
        )
    schema = json.loads(
        importlib_resources.files("codesync_schemas").joinpath(f"codesync-{config_version}.json").read_text()
    )
    jsonschema.validate(instance=config, schema=schema)
    print("Config is valid.")


def run_command(cmd, dry_run=False):
    print(cmd)
    if not dry_run:
        os.system(cmd)


def path_glob(path: str) -> dict[str, str]:
    return dict([(str(d), str(os.path.split(d)[-1])) for d in glob(path) if os.path.isdir(d)])


def git_clone(clone_url: str, destination: str):
    args = " ".join(config_get("git", "clone", "args", default=[]))
    run_command(f"git clone --recurse-submodules {clone_url} {destination} {args}")


def git_fetch(repo_path: str):
    args = " ".join(config_get("git", "fetch", "args", default=[]))
    run_command(f"git -C {repo_path} fetch {args}")


def git_pull(repo_path: str):
    args = " ".join(config_get("git", "pull", "args", default=[]))
    run_command(f"git -C {repo_path} pull {args}")


def git_clean(repo_path: str):
    run_command(
        f"git -C {repo_path} fetch -p "
        f"&& git -C {repo_path} for-each-ref --format '%(refname:short) %(upstream:track)' "
        "| awk '$2 == \"[gone]\" {print $1}' "
        f"| xargs -r git -C {repo_path} branch -D"
    )


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
        for repo_path, repo_name in self.path_glob("*").items():
            if not self._repo_config_get("enabled", repo_name=repo_name):
                continue
            state = self._repo_config_get("state", repo_name=repo_name, default="active")
            actions: list[RepoAction] = self._repo_config_get("actions", state, repo_name=repo_name) or []
            default_branch = self._repo_config_get(
                "default_branch", repo_name=repo_name, default=DEFAULT_DEFAULT_BRANCH
            )
            self.sync_repo(
                repo_name=repo_name,
                actions=actions,
                repo_path=repo_path,
                state=state,
                default_branches=set([default_branch]),
            )

    def path_join(self, *paths: Iterable[str]) -> str:
        return os.path.join(self.path, *paths)  # type: ignore

    def path_glob(self, path: str) -> dict[str, str]:
        return path_glob(self.path_join(path))

    def config_get(self, *keys: Iterable[str], default: Any = None) -> Any:
        return config_get("providers", self.provider, *keys, default=default)

    def config_regex_get(self, *path: Iterable[str], keys: Iterable[str], default: Any = None) -> Any:
        return config_regex_get("providers", self.provider, *path, keys=keys, default=default)

    def repo_action_reduce(
        self, actions: Optional[Iterable[RepoAction]] = None, deletes: Optional[Iterable[RepoAction]] = None
    ) -> Optional[RepoAction]:
        if actions is None:
            actions = []
        if deletes is None:
            deletes = []
        return next(iter([action for action in actions if action not in deletes]), None)  # type: ignore

    def sync_repo(
        self,
        repo_name: str,
        actions: list[RepoAction],
        state: RepoState,
        default_branches: set[str],
        repo_path: str,
        repo_clone_url: Optional[str] = None,
        full_name: Optional[str] = None,
    ):
        if not full_name:
            full_name = repo_name
        exists_locally = os.path.exists(repo_path)
        if exists_locally:
            action = self.repo_action_reduce(actions=actions, deletes=["clone"])
        else:
            action = self.repo_action_reduce(actions=actions, deletes=["delete", "pull"])
        clean = "clean" in actions and exists_locally
        print(f"{full_name}: {state=!s} {action=!s} {clean=!s}")

        if action == "raise":
            raise Exception(
                f"{full_name} needs your attention",
                f"provider={self.__class__.__name__}",
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
                    clone_url=repo_clone_url,
                    destination=repo_path,
                )
        elif action == "pull":
            branch = repo_head_branch(repo_path=repo_path)
            if branch in default_branches:
                git_pull(repo_path=repo_path)
            elif branch is not None:
                git_fetch(repo_path=repo_path)
        else:
            # nop
            pass

        if clean:
            git_clean(repo_path=repo_path)

    def _repo_config_get(self, *keys: Iterable[str], repo_name: str, default: Any = None) -> Any:
        default = self.config_get("repos", "_", *keys, default=default)
        default = self.config_regex_get("repos", "{}", *keys, keys=[repo_name], default=default)
        return self.config_get("repos", repo_name, *keys, default=default)

    def _repo_config_regex_get(
        self, *path: Iterable[str], keys: Iterable[str], repo_name: str, default: Any = None
    ) -> Any:
        default = self.config_regex_get("repos", "_", *path, keys=keys, default=default)
        default = self.config_regex_get("repos", "{}", *path, keys=[repo_name, *keys], default=default)
        return self.config_regex_get("repos", repo_name, *path, keys=keys, default=default)


class GitHubProvider(Provider):
    provider = "github.com"

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.github = Github(self.config_get("auth", "token", default=os.environ.get("GITHUB_TOKEN")))

    def sync(self):
        config_orgs: list[str] = [org for org in self.config_get("orgs").keys() if org != "_"]
        fs_orgs: list[str] = list(self.path_glob("*").values())
        for org_name in set(config_orgs + fs_orgs):
            if not self._org_config_get("enabled", org_name=org_name):
                continue
            repos = self._get_org_repos(org_name=org_name)
            for repo in repos:
                repo_clone_url = {
                    "https": repo.clone_url,
                    "ssh": repo.ssh_url,
                }.get(self._repo_config_get("clone_scheme", org_name=org_name, repo_name=repo.name), None)
                self._sync_repo(
                    org_name=org_name,
                    repo_name=repo.name,
                    state=("archived" if repo.archived else "active"),
                    repo_clone_url=repo_clone_url,
                    topics=repo.get_topics(),
                )
            current_repos = self.path_glob(f"{org_name}/*")
            remote_repo_names = [r.name for r in repos]
            for repo_path, repo_name in current_repos.items():
                if repo_name in remote_repo_names:
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
        topics: Optional[Iterable[str]] = None,
        repo_path: Optional[str] = None,
        repo_clone_url: Optional[str] = None,
    ):
        if topics is None:
            topics = []
        full_name = f"{org_name}/{repo_name}"
        enabled = self._repo_config_get("enabled", org_name=org_name, repo_name=repo_name)
        if not enabled:
            print(f"{full_name}: not enabled")
            return
        if not repo_path:
            repo_path = self.path_join(org_name, repo_name)
        state = self._repo_config_get("state", org_name=org_name, repo_name=repo_name, default=state)
        actions = self._repo_actions_get(org_name=org_name, repo_name=repo_name, state=state, topics=topics)
        default_branch = self._repo_config_get("default_branch", org_name=org_name, repo_name=repo_name)
        default_branches = (
            [default_branch]
            if default_branch
            else self._org_config_get("default_branches", org_name=org_name, default=[])
        )
        self.sync_repo(
            full_name=full_name,
            repo_name=repo_name,
            actions=actions,
            state=state,
            repo_path=repo_path,
            repo_clone_url=repo_clone_url,
            default_branches=set(default_branches),
        )

    def _get_org_repos(self, org_name: str) -> Iterable[Repository]:
        user = self.github.get_user(org_name)
        if user.type == "Organization":
            org = self.github.get_organization(org_name)
            return org.get_repos()
        # Gotta do this weird dance with users because GitHub's API doesn't
        # support getting all accessible repos for a user, only an org.
        public_repos = list(user.get_repos())
        private_repos = [repo for repo in self.github.get_user().get_repos() if repo.owner.login == org_name]
        return list(set(public_repos + private_repos))

    def _org_config_get(self, *keys: Iterable[str], org_name: str, default: Any = None) -> Any:
        default = self.config_get("orgs", "_", *keys, default=default)
        default = self.config_regex_get("orgs", "{}", *keys, keys=[org_name], default=default)
        return self.config_get("orgs", org_name, *keys, default=default)

    def _org_config_regex_get(
        self, *path: Iterable[str], keys: Iterable[str], org_name: str, default: Any = None
    ) -> Any:
        default = self.config_regex_get("orgs", "_", *path, keys=keys, default=default)
        default = self.config_regex_get("orgs", "{}", *path, keys=[org_name, *keys], default=default)
        return self.config_regex_get("orgs", org_name, *path, keys=keys, default=default)

    def _repo_config_get(self, *keys: Iterable[str], org_name: str, repo_name: str, default: Any = None) -> Any:
        default = super()._repo_config_get(*keys, repo_name=repo_name, default=default)
        default = self._org_config_get("repos", "_", *keys, org_name=org_name, default=default)
        default = self._org_config_regex_get(
            "repos", "{}", *keys, keys=[repo_name], org_name=org_name, default=default
        )
        return self._org_config_get("repos", repo_name, *keys, org_name=org_name, default=default)

    def _repo_config_regex_get(
        self,
        *path: Iterable[str],
        keys: Iterable[str],
        org_name: str,
        repo_name: str,
        default: Any = None,
    ) -> Any:
        default = super()._repo_config_regex_get(*path, keys=keys, repo_name=repo_name, default=default)
        default = self._org_config_regex_get("repos", "_", *path, keys=keys, org_name=org_name, default=default)
        default = self._org_config_regex_get(
            "repos", "{}", *path, keys=[repo_name, *keys], org_name=org_name, default=default
        )
        return self._org_config_regex_get("repos", repo_name, *path, keys=keys, org_name=org_name, default=default)

    def _topic_actions_get(
        self, org_name: str, topic: str, state: str, default: Optional[Iterable[RepoAction]] = None
    ) -> Iterable[RepoAction]:
        if default is None:
            default = []
        default = self._org_config_regex_get(
            "topics", "{}", "actions", state, keys=[topic], org_name=org_name, default=default
        )
        return self._org_config_get("topics", topic, "actions", state, org_name=org_name, default=default)

    def _repo_actions_get(
        self, org_name: str, repo_name: str, state: str, topics: Optional[Iterable[str]] = None
    ) -> list[RepoAction]:
        if topics is None:
            topics = []
        repo_actions = self._org_config_get("repos", repo_name, "actions", state, org_name=org_name, default=[])
        if repo_actions:
            return repo_actions
        topic_actions = list(
            set(
                more_itertools.collapse(
                    [self._topic_actions_get(org_name=org_name, topic=topic, state=state) for topic in topics]
                )
            )
        )
        if topic_actions:
            return topic_actions
        org_actions = self._org_config_get("repos", "_", "actions", state, org_name=org_name, default=[])
        if org_actions:
            return org_actions
        return super()._repo_config_get("actions", state, repo_name=repo_name, default=[])


def main():
    global config
    config_filename = os.path.join(os.path.expanduser("~"), ".codesync.yaml")
    if os.path.exists(config_filename):
        with open(config_filename, "r") as f:
            config = merge(config, ruyaml.safe_load(f))
    config_validate()
    codedir = os.path.expanduser(config.get("src_dir", DEFAULT_SRC_DIR))
    for path, host_name in path_glob(f"{codedir}/*").items():
        _Provider: Type[Provider] = {
            "github.com": GitHubProvider,
        }.get(host_name, Provider)
        provider = _Provider(path=path)
        provider.sync()


if __name__ == "__main__":
    main()
