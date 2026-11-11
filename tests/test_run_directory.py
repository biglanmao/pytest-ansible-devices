"""``run_directory`` 核心行为（不依赖 pytest 运行环境）。"""

import json
import os
import stat
from pathlib import Path

import pytest

from pytest_ansible_devices.run_directory import (
    INDEX_FILE,
    RUN_MARKER,
    find_run_dirs,
    normalize_outcome,
    run_directory,
    temporary_run_directory,
)


def _artifact(run):
    artifact = run.artifact_dir
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "stdout").write_text("hello", encoding="utf-8")
    return artifact


def test_layout_manifest_and_env(tmp_path):
    root = tmp_path / "runs"

    with run_directory(root, "tests/test_x.py::test_a", retention="failed") as run:
        assert run.path.is_absolute()
        assert run.path.is_relative_to(root.resolve())
        assert run.path.parent.name.startswith("tests-test_x.py-test_a-")
        assert run.path.name.startswith("20")

        manifest = json.loads((run.path / RUN_MARKER).read_text(encoding="utf-8"))
        assert manifest["kind"] == "pytest-ansible-devices/run-directory"
        assert manifest["label"] == "tests/test_x.py::test_a"
        assert manifest["run_id"] == run.run_id
        assert manifest["artifact_dir"] == str(run.artifact_dir)
        assert manifest["started_at"]
        assert manifest["status"] == "started"

        assert run.envvars == {"ANSIBLE_LOG_PATH": str(run.path / "ansible.log")}
        assert stat.S_IMODE(run.path.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    ("retention", "outcome", "kept"),
    [
        ("failed", "failed", True),
        ("failed", "passed", False),
        ("all", "failed", True),
        ("all", "passed", True),
        ("none", "failed", False),
        ("none", "passed", False),
    ],
)
def test_retention_policies(tmp_path, retention, outcome, kept):
    with run_directory(tmp_path / "runs", "op", retention=retention) as run:
        artifact = _artifact(run)
        run.set_outcome(outcome)

    assert (run.path / RUN_MARKER).is_file()
    assert artifact.exists() is kept
    manifest = json.loads((run.path / RUN_MARKER).read_text(encoding="utf-8"))
    assert manifest["outcome"] == outcome
    assert manifest["action"] == ("keep" if kept else "delete")


def test_exception_marks_failed_and_keeps_artifacts(tmp_path):
    with pytest.raises(RuntimeError, match="boom"):
        with run_directory(tmp_path / "runs", "op") as run:
            artifact = _artifact(run)
            raise RuntimeError("boom")

    assert artifact.exists()
    manifest = json.loads((run.path / RUN_MARKER).read_text(encoding="utf-8"))
    assert manifest["outcome"] == "failed"
    assert manifest["action"] == "keep"


def test_deferred_outcome(tmp_path):
    with run_directory(tmp_path / "runs", "op", defer=True) as run:
        artifact = _artifact(run)

    # 退出时 outcome 未知，交给外部收尾；此时不删除。
    assert run.finalized is False
    assert artifact.exists()
    manifest = json.loads((run.path / RUN_MARKER).read_text(encoding="utf-8"))
    assert manifest["status"] == "pending"

    run.finalize("passed")
    assert run.finalized is True
    assert not artifact.exists()
    assert (run.path / RUN_MARKER).is_file()


def test_unknown_outcome_is_kept_by_failed_policy(tmp_path):
    with run_directory(tmp_path / "runs", "op") as run:
        artifact = _artifact(run)

    assert artifact.exists()
    manifest = json.loads((run.path / RUN_MARKER).read_text(encoding="utf-8"))
    assert manifest["outcome"] == "unknown"
    assert manifest["action"] == "keep"


def test_outcome_object_and_bool_are_normalized():
    class Result:
        def __init__(self, rc):
            self.rc = rc

    assert normalize_outcome(True) == "passed"
    assert normalize_outcome(False) == "failed"
    assert normalize_outcome("successful") == "passed"
    assert normalize_outcome("unreachable") == "failed"
    assert normalize_outcome(Result(0)) == "passed"
    assert normalize_outcome(Result(2)) == "failed"


def test_index_and_find_run_dirs(tmp_path):
    root = tmp_path / "runs"

    with run_directory(root, "op-a", nodeid="test_x.py::test_a") as run_a:
        run_a.set_outcome("failed")
    with run_directory(root, "op-b", nodeid="test_x.py::test_b") as run_b:
        run_b.set_outcome("passed")

    index_lines = (root / INDEX_FILE).read_text(encoding="utf-8").splitlines()
    assert len(index_lines) == 4
    events = [json.loads(line)["event"] for line in index_lines]
    assert events == ["created", "finished", "created", "finished"]

    assert [run.path for run in find_run_dirs(root, label="op-a")] == [run_a.path]
    assert [run.path for run in find_run_dirs(root, nodeid="test_x.py::test_b")] == [
        run_b.path
    ]
    assert len(find_run_dirs(root)) == 2


def test_symlinks_are_removed_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")

    with run_directory(tmp_path / "runs", "op") as run:
        link = run.path / "outside-link"
        link.symlink_to(outside, target_is_directory=True)
        run.set_outcome("passed")

    assert not link.exists()
    assert (outside / "keep.txt").is_file()


def test_delete_requires_marker(tmp_path):
    with run_directory(tmp_path / "runs", "op") as run:
        (run.path / "artifacts").mkdir()
        (run.path / RUN_MARKER).unlink()
        with pytest.raises(RuntimeError, match="拒绝删除"):
            run._delete_children()

    assert (run.path / "artifacts").exists()


def test_does_not_delete_root(tmp_path):
    root = tmp_path / "runs"
    with run_directory(root, "op") as run:
        run.set_outcome("passed")

    assert root.is_dir()
    assert run.path.is_dir()


def test_temporary_run_directory_is_removed(tmp_path):
    with temporary_run_directory("op") as run:
        path = run.path
        assert path.is_dir()

    assert not path.exists()
    assert not path.parent.parent.exists()


def test_invalid_retention_and_verbosity(tmp_path):
    with pytest.raises(ValueError, match="retention"):
        with run_directory(tmp_path, "op", retention="sometimes"):
            pass

    with pytest.raises(ValueError, match="verbosity"):
        with run_directory(tmp_path, "op", verbosity=-1):
            pass
