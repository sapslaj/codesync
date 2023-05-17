from typing import cast

import pytest

from codesync import RepoAction
from codesync.config import Config
from codesync.repo.synced_repo import SyncedRepo


class TestSyncedRepo:
    class TestRepoActionReduce:
        @pytest.mark.parametrize(
            ("actions", "deletes", "expected_action"),
            [
                ([], [], None),
                (["pull", "clone"], ["pull"], "clone"),
                (["pull", "clone"], ["clone"], "pull"),
                (["clean", "pull", "clone"], ["clean", "clone"], "pull"),
            ],
        )
        def test_returns_correct_action(
            self, actions: list[RepoAction], deletes: list[RepoAction], expected_action: RepoAction
        ):
            config = Config()
            repo = SyncedRepo(
                config=config,
                provider_name="test",
                repo_name="test",
                actions=actions,
                state="active",
                default_branches=set(),
                repo_path="test",
            )
            assert repo.repo_action_reduce(actions=actions, deletes=deletes) == expected_action
