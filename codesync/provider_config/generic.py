from typing import Iterable, Optional, Tuple, cast

from codesync.provider_config import ProviderConfig


class GenericProviderConfig(ProviderConfig):
    repo_name: Optional[str]

    def repo(self, repo_name: str) -> "GenericProviderConfig":
        return cast(GenericProviderConfig, self.extend(repo_name=repo_name))

    def _parent(self) -> Tuple[Iterable[str], Iterable[str]]:
        path = ["providers", "generic"]
        keys = []
        if self.repo_name:
            path.extend(["repos", "{}"])
            keys.append(self.repo_name)
        return path, keys
