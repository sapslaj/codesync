import os
import pathlib
import re
import subprocess
from typing import Iterable, Optional

from codesync.command import run_command
from codesync.config import Config


def _check_output(cmd: Iterable[str], *args, **kwargs):
    print(" ".join(cmd))
    return subprocess.check_output(args=cmd, *args, **kwargs)  # type: ignore


def git_clone(config: Config, clone_url: str, destination: str):
    pathlib.Path(destination).parent.mkdir(parents=True, exist_ok=True)
    args = " ".join(config.get("git", "clone", "args", default=[]))
    run_command(f"git clone --recurse-submodules {clone_url} {destination} {args}")


def git_fetch(config: Config, repo_path: str):
    args = " ".join(config.get("git", "fetch", "args", default=[]))
    run_command(f"git -C {repo_path} fetch {args}")


def git_pull(config: Config, repo_path: str):
    args = " ".join(config.get("git", "pull", "args", default=[]))
    run_command(f"git -C {repo_path} pull {args}")


def git_clean(repo_path: str):
    refs_out = _check_output(
        ["git", "-C", repo_path, "for-each-ref", "--format", "%(refname:short) %(upstream:track)"]
    )
    refs: list[str] = refs_out.decode("utf-8").strip().split("\n")
    for ref in refs:
        if ref.endswith("[gone]"):
            ref = ref.removesuffix("[gone]").strip()
            if repo_head_branch(repo_path) != ref:
                print(_check_output(["git", "-C", repo_path, "branch", "-D", ref]))


def repo_head_branch(repo_path: str) -> Optional[str]:
    with open(os.path.join(repo_path, ".git", "HEAD"), "r") as head_file:
        head = head_file.readline().strip()
    head_parse = re.search("^ref: refs/heads/(.*)$", head)
    if not head_parse:
        return
    return head_parse[1]
