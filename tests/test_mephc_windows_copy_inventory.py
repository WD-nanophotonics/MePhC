from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "tools" / "mephc-runner"


def load_inventory():
    spec = importlib.util.spec_from_file_location(
        "mephc_windows_copy_inventory",
        SOURCE / "windows_copy_inventory.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_copy_scope_is_fixed():
    inventory = load_inventory()
    assert set(inventory.COPY_ROOTS) == {
        "AGENTRELAY",
        "CHATSEQUENCERUNNER",
        "MEPHC_WINDOWS",
        "RETIRED_MEPHC",
        "RETIRED_SQRLATT",
        "RETIRED_TRILATT",
        "RETIRED_MEPHC_WINDOWS",
    }
    assert inventory.COPY_ROOTS["MEPHC_WINDOWS"] == Path(
        "/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows"
    )


def test_secret_precedes_disposable_classification():
    inventory = load_inventory()
    assert inventory.base_classification(".venv/oauth-token.json") == "SECRET_OR_CREDENTIAL"
    assert inventory.base_classification(
        ".venv/Lib/site-packages/pygments/token.py"
    ) == "DISPOSABLE_GENERATED"
    assert inventory.base_classification(".venv/lib/cache.pyc") == "DISPOSABLE_GENERATED"
    assert inventory.base_classification("src/package.egg-info/PKG-INFO") == "DISPOSABLE_GENERATED"
    assert inventory.base_classification(".run/legacy.run.xml") == "DISPOSABLE_GENERATED"
    assert inventory.base_classification("source/module.py") is None


def test_streamed_hashes_bind_file_and_git_blob(tmp_path):
    inventory = load_inventory()
    path = tmp_path / "artifact"
    path.write_bytes(b"evidence\n")
    sha256, oid = inventory.sha256_and_blob_oid(path)
    assert sha256 == hashlib.sha256(b"evidence\n").hexdigest()
    assert oid == hashlib.sha1(b"blob 9\0evidence\n", usedforsecurity=False).hexdigest()


def test_inventory_source_has_no_delete_primitive():
    text = (SOURCE / "windows_copy_inventory.py").read_text(encoding="utf-8")
    assert 'print(create_inventory())' in text
    for token in ("unlink(", "rmtree(", "remove(", "git clean", "git reset"):
        assert token not in text
