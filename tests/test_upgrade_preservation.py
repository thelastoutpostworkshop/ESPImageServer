from pathlib import Path
import runpy
import shutil

import pytest

PROJECT = Path(__file__).resolve().parents[1]
support = runpy.run_path(str(PROJECT / "ci/upgrade_support.py"))


def test_old_backend_data_is_loaded_by_new_version(tmp_path):
    installed = tmp_path / "Installed app"
    shutil.copytree(PROJECT / "src", installed / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    shutil.copy2(PROJECT / "pyproject.toml", installed / "pyproject.toml")
    user = tmp_path / "User data"
    support["set_backend_version"](installed, "0.0.1")
    support["storage_probe"](installed, user, "save", "0.0.1")
    saved = support["snapshot"](user)
    # The synthetic next version uses the same schema; this deliberately does
    # not claim testing of historical migrations or older released code.
    support["set_backend_version"](installed, "0.0.2")
    support["assert_preserved"](user, saved)
    support["storage_probe"](installed, user, "restart", "0.0.2")
    # Prove the preservation guard detects deletion, not merely successful boot.
    model = next(user.rglob("storage-probe.txt"))
    model.unlink()
    with pytest.raises(AssertionError, match="user data"):
        support["assert_preserved"](user, saved)
