from typing import Iterable, Optional, Tuple, cast

from codesync.provider_config import ProviderConfig


class GitHubProviderConfig(ProviderConfig):
    org_name: Optional[str] = None
    repo_name: Optional[str] = None
    topic_name: Optional[str] = None

    def org(self, org_name: str) -> "GitHubProviderConfig":
        return cast(GitHubProviderConfig, self.extend(org_name=org_name))

    def topic(self, topic_name: str) -> "GitHubProviderConfig":
        return cast(GitHubProviderConfig, self.extend(topic_name=topic_name))

    def repo(self, repo_name: str) -> "GitHubProviderConfig":
        return cast(GitHubProviderConfig, self.extend(repo_name=repo_name))

    def _parent(self) -> Tuple[Iterable[str], Iterable[str]]:
        path = ["providers", "github.com"]
        keys = []
        if not self.org_name:
            return path, keys
        path.extend(["orgs", "{}"])
        keys.append(self.org_name)
        if self.topic_name:
            path.extend(["topics", "{}"])
            keys.append(self.topic_name)
            return path, keys
        if self.repo_name:
            path.extend(["repos", "{}"])
            keys.append(self.repo_name)
        return path, keys
