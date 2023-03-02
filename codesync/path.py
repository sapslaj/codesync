import os
from glob import glob


def path_glob(path: str) -> dict[str, str]:
    return dict([(str(d), str(os.path.split(d)[-1])) for d in glob(path) if os.path.isdir(d)])
