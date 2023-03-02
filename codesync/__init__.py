from typing import Literal

RepoAction = Literal["clone", "delete", "pull", "raise", "nop"]
RepoState = Literal["active", "archived", "orphaned"]
RepoCloneScheme = Literal["https", "ssh"]

VERSION = 0.8
