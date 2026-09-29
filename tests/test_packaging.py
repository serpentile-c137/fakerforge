"""Release metadata stays aligned with the installed package."""

from importlib.metadata import version

import fakerforge


def test_version_matches_installed_metadata() -> None:
    assert fakerforge.__version__ == version("fakerforge")
