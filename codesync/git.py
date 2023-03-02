import os
import re
from typing import Optional

from codesync.command import run_command
from codesync.config import Config


def git_clone(config: Config, clone_url: str, destination: str):
    args = " ".join(config.get("git", "clone", "args", default=[]))
    run_command(f"git clone --recurse-submodules {clone_url} {destination} {args}")


def git_fetch(config: Config, repo_path: str):
    args = " ".join(config.get("git", "fetch", "args", default=[]))
    run_command(f"git -C {repo_path} fetch {args}")


def git_pull(config: Config, repo_path: str):
    args = " ".join(config.get("git", "pull", "args", default=[]))
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
