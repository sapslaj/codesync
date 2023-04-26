import json
import operator
import os
import re
import sys
from functools import reduce
from typing import Any, Iterable, Optional

if sys.version_info < (3, 9):
    import importlib_resources
else:
    import importlib.resources as importlib_resources

import jsonschema
import more_itertools
import ruyaml
from mergedeep import merge

from codesync import VERSION, RepoCloneScheme

DEFAULT_SRC_DIR = "~/src"
DEFAULT_DEFAULT_BRANCH = "main"  # lovely name
DEFAULT_REPO_CLONE_SCHEME: RepoCloneScheme = "https"
DEFAULT_CONCURRENCY = 4

default_config = {
    "version": VERSION,
    "src_dir": DEFAULT_SRC_DIR,
    "concurrency": DEFAULT_CONCURRENCY,
    "git": {
        "clone": {"args": []},
        "fetch": {"args": []},
        "pull": {"args": []},
    },
    "providers": {
        "generic": {
            "repos": {
                "/.*/": {
                    "enabled": False,
                    "state": "active",
                    "default_branch": DEFAULT_DEFAULT_BRANCH,
                },
            },
        },
        "github.com": {
            "orgs": {
                "/.*/": {
                    "enabled": True,
                    "default_branches": [DEFAULT_DEFAULT_BRANCH],
                    "repos": {
                        "/.*/": {
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


class Config:
    def __init__(self, config: Optional[dict] = None) -> None:
        if not config:
            config = default_config
        self.config = config

    def load_config_file(self, filepath: Optional[str] = None):
        if not filepath:
            filepath = os.path.join(os.path.expanduser("~"), ".codesync.yaml")
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                self.config = merge(self.config, ruyaml.safe_load(f))

    def validate(self) -> None:
        config_version = self.config["version"]
        print(f"Checking config (version {config_version}).")
        if config_version > VERSION:
            raise Exception(
                "codesync: fatal: configuration file version is higher than what this version of codesync can handle"
            )
        schema = json.loads(
            importlib_resources.files("codesync.schemas").joinpath(f"codesync-{config_version}.json").read_text()
        )
        jsonschema.validate(instance=self.config, schema=schema)
        print("Config is valid.")

    def get_raw(self, *path: Iterable[str], default: Any = None) -> Any:
        try:
            return reduce(operator.getitem, path, self.config)  # type:ignore
        except (KeyError, TypeError):
            return default

    def get(
        self,
        *path: Iterable[str],
        keys: Optional[Iterable[str]] = None,
        default: Any = None,
    ) -> Any:
        if not keys:
            return self.get_raw(*path, default=default)
        key_groups = list(more_itertools.split_at(path, lambda k: k == "{}", 1))
        before_keys, after_keys = [], []
        if len(key_groups) == 1:
            before_keys = key_groups[0]
        elif len(key_groups) == 2:
            before_keys, after_keys = key_groups
        key, *child_keys = keys
        parent = self.get_raw(*before_keys)
        if not isinstance(parent, dict):
            return default
        if key in parent:
            if child_keys:
                return self.get(*before_keys, key, *after_keys, keys=child_keys, default=default)
            else:
                return self.get_raw(*before_keys, key, *after_keys, default=default)
        regex_keys = sorted(
            [regex_key for regex_key in parent if regex_key.startswith("/")],
            key=len,
            reverse=True,
        )
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
                    return self.get(
                        *before_keys,
                        regex_key,
                        *after_keys,
                        keys=child_keys,
                        default=default,
                    )
                else:
                    return self.get_raw(*before_keys, regex_key, *after_keys, default=default)
        return default

    # def curry(
    #     self, *path: Iterable[str], keys: Iterable[str], default: Any = None
    # ) -> Callable[[Iterable[str], Iterable[str], Any]]:
    #     top_path = path
    #     top_keys = keys
    #     top_default = default

    #     def get(*path: Iterable[str], keys: Iterable[str], default: Any = top_default) -> Any:
    #         return self.get(*top_path, *path, keys=[*top_keys, *keys], default=default)

    #     return get
