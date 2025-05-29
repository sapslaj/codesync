from typing import Iterable, Optional, Tuple, cast

from codesync.provider_config import ProviderConfig


class GitLabProviderConfig(ProviderConfig):
    group_name: Optional[str] = None
    project_name: Optional[str] = None

    def group(self, group_name: str) -> "GitLabProviderConfig":
        return cast(GitLabProviderConfig, self.extend(group_name=group_name))

    def project(self, project_name: str) -> "GitLabProviderConfig":
        return cast(GitLabProviderConfig, self.extend(project_name=project_name))

    def _parent(self) -> Tuple[Iterable[str], Iterable[str]]:
        path = ["providers", "gitlab.com"]
        keys = []
        if not self.group_name:
            return path, keys
        path.extend(["groups", "{}"])
        keys.append(self.group_name)
        if self.project_name:
            path.extend(["projects", "{}"])
            keys.append(self.project_name)
        return path, keys
