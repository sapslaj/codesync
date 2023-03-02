import abc
from typing import Any, Iterable, Optional, Tuple

from codesync.config import Config


class ProviderConfig(abc.ABC):
    def __init__(self, config: Config, **kwargs) -> None:
        self.config = config
        for k, v in kwargs.items():
            setattr(self, k, v)

    def extend(self, **kwargs) -> "ProviderConfig":
        return self.__class__(
            **{
                **self.__dict__,
                **kwargs,
            }
        )

    def get(self, *path: Iterable[str], keys: Optional[Iterable[str]] = None, default: Any = None) -> Any:
        if keys is None:
            keys = []
        parent_path, parent_keys = self._parent()
        return self.config.get(*parent_path, *path, keys=[*parent_keys, *keys], default=default)

    @abc.abstractmethod
    def _parent(self) -> Tuple[Iterable[str], Iterable[str]]:
        return [], []
