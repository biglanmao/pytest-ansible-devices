"""受管运行目录 —— 不依赖 pytest 的运行目录创建、索引与清理。

设计依据：PAD-FR-21 / PAD-FR-22。

- ``run_directory`` 是核心上下文管理器，普通脚本 / CLI 可直接使用；
- 目录结构为 ``<root>/<label-slug>-<hash8>/<run_id>/``；
- 每个 run 目录写 manifest（同时作为删除标记），并在 root 下追加 JSONL 索引；
- 退出时由调用方显式设置 outcome，按 retention 决定保留或清理；
- 只清理带 manifest 标记的目录，不跟随符号链接，不删除 root 本身。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
import uuid

RUN_MARKER = ".pad-run.json"
INDEX_FILE = "index.jsonl"
LOG_FILENAME = "ansible.log"
MARKER_KIND = "pytest-ansible-devices/run-directory"

RETENTION_POLICIES = ("failed", "all", "none")

_PASS_OUTCOMES = {
    "passed",
    "pass",
    "ok",
    "success",
    "successful",
    "true",
}
_FAIL_OUTCOMES = {
    "failed",
    "fail",
    "failure",
    "error",
    "errored",
    "unreachable",
    "timeout",
    "false",
    "crashed",
}

_UNSET = object()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_session_id() -> str:
    """生成可排序的 session 目录名（时间 + pid + 随机后缀）。"""
    return (
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-"
        f"{os.getpid()}-{uuid.uuid4().hex[:6]}"
    )


def _slugify(label: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(label or "run")).strip("-._")
    slug = slug[:60].rstrip("-._")
    return slug or "run"


def _label_hash(label: str) -> str:
    return hashlib.sha256(str(label).encode("utf-8")).hexdigest()[:8]


def normalize_outcome(outcome: Any) -> str | None:
    """把 bool / 字符串 / 带 ok/status/rc 的结果对象归一化为 passed/failed。

    无法识别的字符串原样返回（小写），由保留策略按“非 passed 即失败”处理。
    """
    if outcome is None:
        return None

    if isinstance(outcome, bool):
        return "passed" if outcome else "failed"

    if isinstance(outcome, str):
        text = outcome.strip().lower()
        if text in _PASS_OUTCOMES:
            return "passed"
        if text in _FAIL_OUTCOMES:
            return "failed"
        return text

    # kw 层 Result 常见形态：ok / status / rc。
    ok = getattr(outcome, "ok", None)
    if isinstance(ok, bool):
        return "passed" if ok else "failed"

    status = getattr(outcome, "status", None)
    if isinstance(status, str):
        text = status.strip().lower()
        return "passed" if text in _PASS_OUTCOMES else "failed"

    rc = getattr(outcome, "rc", None)
    if isinstance(rc, int) and not isinstance(rc, bool):
        return "passed" if rc == 0 else "failed"

    return normalize_outcome(str(outcome))


def _validate_retention(retention: str) -> str:
    if retention not in RETENTION_POLICIES:
        allowed = ", ".join(RETENTION_POLICIES)
        raise ValueError(f"retention 必须是 {allowed} 之一，实际为: {retention!r}")
    return retention


def _validate_verbosity(verbosity: int | None) -> int | None:
    if verbosity is None:
        return None
    if isinstance(verbosity, bool) or not isinstance(verbosity, int):
        raise ValueError(f"verbosity 必须是整数或 None，实际为: {verbosity!r}")
    if verbosity < 0:
        raise ValueError(f"verbosity 不能为负数，实际为: {verbosity}")
    return verbosity


def _mkdir_private(path: Path) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if existed:
        # 只收紧本次创建的目录；不擅自修改用户已有目录（例如 /tmp）的权限。
        return
    try:
        path.chmod(0o700)
    except OSError:
        # 某些文件系统不支持 chmod；目录已创建，继续。
        pass


class RunDirectory(os.PathLike):
    """一次运行的受管目录。

    ``os.fspath(run)`` / ``str(run)`` 返回绝对路径，可直接作为
    ``private_data_dir`` 传给 ``ansible_runner.run``。
    """

    def __init__(
        self,
        path: Path,
        *,
        root: Path,
        label: str,
        run_id: str,
        retention: str,
        verbosity: int | None = None,
        log_filename: str = LOG_FILENAME,
        nodeid: str | None = None,
        index_path: Path | None = None,
        defer: bool = False,
    ) -> None:
        self.path = Path(path)
        self.root = Path(root)
        self.label = str(label)
        self.run_id = run_id
        self.retention = _validate_retention(retention)
        self.verbosity = _validate_verbosity(verbosity)
        self.log_filename = log_filename
        self.nodeid = nodeid
        self.index_path = Path(index_path) if index_path is not None else None
        self.defer = defer

        self.started_at = _utcnow()
        self._outcome: str | None = None
        self._finalized = False
        self._final_action: str | None = None
        self._manifest_path = self.path / RUN_MARKER

    # ------------------------------------------------------------------ path
    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:
        return (
            f"RunDirectory({str(self.path)!r}, label={self.label!r}, "
            f"retention={self.retention!r}, outcome={self.outcome!r})"
        )

    @property
    def outcome(self) -> str | None:
        return self._outcome

    @property
    def finalized(self) -> bool:
        return self._finalized

    @property
    def final_action(self) -> str | None:
        return self._final_action

    @property
    def log_path(self) -> Path:
        return self.path / self.log_filename

    @property
    def artifact_dir(self) -> Path:
        return self.path / "artifacts"

    @property
    def envvars(self) -> dict[str, str]:
        """runner 需要的环境变量：本 run 的 ``ANSIBLE_LOG_PATH``。"""
        return {"ANSIBLE_LOG_PATH": str(self.log_path)}

    @property
    def manifest(self) -> dict[str, Any]:
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # --------------------------------------------------------------- outcome
    def set_outcome(self, outcome: Any) -> "RunDirectory":
        """显式设置本 run 的 outcome（可传 bool / 字符串 / 结果对象）。"""
        self._outcome = normalize_outcome(outcome)
        return self

    # --------------------------------------------------------------- manifest
    def _write_manifest(self, status: str, action: str | None = None) -> None:
        data = {
            "kind": MARKER_KIND,
            "label": self.label,
            "nodeid": self.nodeid,
            "run_id": self.run_id,
            "artifact_dir": str(self.artifact_dir),
            "path": str(self.path),
            "root": str(self.root),
            "retention": self.retention,
            "verbosity": self.verbosity,
            "started_at": self.started_at,
            "status": status,
            "action": action,
            "outcome": self._outcome,
            "updated_at": _utcnow(),
        }

        tmp = self._manifest_path.with_name(f"{RUN_MARKER}.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp, self._manifest_path)

    def _append_index(self, event: str, action: str | None = None) -> None:
        if self.index_path is None:
            return
        record = {
            "event": event,
            "label": self.label,
            "nodeid": self.nodeid,
            "run_id": self.run_id,
            "path": str(self.path),
            "artifact_dir": str(self.artifact_dir),
            "retention": self.retention,
            "outcome": self._outcome,
            "action": action,
            "timestamp": _utcnow(),
        }
        try:
            with self.index_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.index_path.chmod(0o600)
        except OSError:
            # 索引失败不应阻断运行；manifest 仍可反查。
            pass

    # ---------------------------------------------------------------- cleanup
    def _decide_action(self, outcome: str | None) -> str:
        if self.retention == "all":
            return "keep"
        if self.retention == "none":
            return "delete"
        # failed：只有明确成功的 run 才清理，未知状态按失败保留。
        return "delete" if outcome == "passed" else "keep"

    def _check_delete_allowed(self) -> None:
        manifest = self._manifest_path
        if self.path.is_symlink():
            raise RuntimeError(f"拒绝删除：run 目录是符号链接 {self.path}")
        if manifest.is_symlink() or not manifest.is_file():
            raise RuntimeError(f"拒绝删除：缺少运行目录标记 {manifest}")
        data = self.manifest
        if data.get("kind") != MARKER_KIND:
            raise RuntimeError(f"拒绝删除：标记文件格式不匹配 {manifest}")

        resolved_root = self.root.resolve()
        resolved_path = self.path.resolve()
        if resolved_path == resolved_root:
            raise RuntimeError(f"拒绝删除：不能删除 root 本身 {resolved_path}")
        if not resolved_path.is_relative_to(resolved_root):
            raise RuntimeError(
                f"拒绝删除：目录不在 root 下 {resolved_path}（root={resolved_root}）"
            )

    def _delete_children(self) -> None:
        """只删除 run 目录内容，保留 manifest；不跟随符号链接。"""
        self._check_delete_allowed()
        for entry in os.scandir(self.path):
            if entry.name == RUN_MARKER:
                continue
            if entry.is_symlink():
                os.unlink(entry.path)
            elif entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)

    def finalize(self, outcome: Any = _UNSET) -> str:
        """写入 manifest（先），再按 retention 清理（后）。返回 keep/delete。"""
        if self._finalized:
            return self._final_action or "keep"

        if outcome is not _UNSET and outcome is not None:
            self.set_outcome(outcome)

        if self._outcome is None:
            self._outcome = "unknown"

        action = self._decide_action(self._outcome)
        # 顺序要求：先写 manifest / 索引，后删除。
        self._write_manifest(self._outcome, action)
        self._append_index("finished", action)
        if action == "delete":
            self._delete_children()

        self._finalized = True
        self._final_action = action
        return action

    # ------------------------------------------------------------ context mgr
    def __enter__(self) -> "RunDirectory":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._finalized:
            return False

        if exc_type is not None:
            self.set_outcome("failed")
        elif self._outcome is None and self.defer:
            # 用例级 outcome 由 pytest_runtest_makereport 决定。
            self._write_manifest("pending", "pending")
            return False

        self.finalize()
        return False


@contextmanager
def run_directory(
    root: str | os.PathLike[str],
    label: str,
    retention: str = "failed",
    *,
    outcome: Any = None,
    verbosity: int | None = None,
    log_filename: str = LOG_FILENAME,
    nodeid: str | None = None,
    index_path: str | os.PathLike[str] | None = None,
    defer: bool = False,
):
    """在 ``root`` 下创建 ``<label-slug>-<hash8>/<run_id>/`` 并管理其生命周期。

    :param root: 受管根目录（必填；不存在时创建）
    :param label: 操作名 / pytest nodeid，用于目录名与 manifest
    :param retention: ``failed`` / ``all`` / ``none``，默认 ``failed``
    :param outcome: 显式 outcome；也可在上下文内调用 ``set_outcome``
    :param verbosity: Ansible 原生 verbosity 整数（0/1/2/...），仅携带不解析
    :param log_filename: ``ANSIBLE_LOG_PATH`` 的文件名，默认 ``ansible.log``
    :param nodeid: 关联的 pytest nodeid（可选，写入 manifest）
    :param index_path: 索引文件路径，默认 ``<root>/index.jsonl``
    :param defer: 未显式设置 outcome 时保留 pending，交给外部收尾
    """
    _validate_retention(retention)
    _validate_verbosity(verbosity)

    root_path = Path(root).expanduser().resolve()
    if root_path.exists() and not root_path.is_dir():
        raise NotADirectoryError(f"运行目录 root 不是目录: {root_path}")
    _mkdir_private(root_path)

    label = str(label or "run")
    label_dir = root_path / f"{_slugify(label)}-{_label_hash(label)}"
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid.uuid4().hex[:8]}"
    run_path = label_dir / run_id
    _mkdir_private(label_dir)
    _mkdir_private(run_path)

    if index_path is None:
        resolved_index = root_path / INDEX_FILE
    else:
        resolved_index = Path(index_path).expanduser()
        if not resolved_index.is_absolute():
            resolved_index = root_path / resolved_index
        resolved_index.parent.mkdir(parents=True, exist_ok=True)

    run = RunDirectory(
        run_path,
        root=root_path,
        label=label,
        run_id=run_id,
        retention=retention,
        verbosity=verbosity,
        log_filename=log_filename,
        nodeid=nodeid,
        index_path=resolved_index,
        defer=defer,
    )
    run._write_manifest("started")
    run._append_index("created")

    failed = False
    try:
        yield run
    except BaseException:
        failed = True
        run.set_outcome("failed")
        raise
    finally:
        if not run.finalized:
            if not failed and outcome is not None:
                value = outcome() if callable(outcome) else outcome
                run.set_outcome(value)
            if run.defer and run.outcome is None and not failed:
                # 交给 pytest_runtest_makereport 或外部显式 finalize。
                run._write_manifest("pending", "pending")
            else:
                run.finalize()


@contextmanager
def temporary_run_directory(
    label: str = "run",
    retention: str = "failed",
    *,
    outcome: Any = None,
    verbosity: int | None = None,
    log_filename: str = LOG_FILENAME,
    defer: bool = False,
):
    """未启用受管目录时的 mkdtemp 回退：退出后删除整个临时 root。"""
    root = Path(tempfile.mkdtemp(prefix="pad_run_"))
    try:
        with run_directory(
            root,
            label,
            retention=retention,
            outcome=outcome,
            verbosity=verbosity,
            log_filename=log_filename,
            defer=defer,
        ) as run:
            yield run
    finally:
        shutil.rmtree(root, ignore_errors=True)


def find_run_dirs(
    root: str | os.PathLike[str],
    *,
    label: str | None = None,
    nodeid: str | None = None,
) -> list[RunDirectory]:
    """按 manifest 反查运行目录；不跟随符号链接。"""
    root_path = Path(root)
    found: list[RunDirectory] = []
    if not root_path.is_dir():
        return found

    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        if RUN_MARKER not in filenames:
            continue
        path = Path(dirpath)
        try:
            data = json.loads((path / RUN_MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("kind") != MARKER_KIND:
            continue
        if label is not None and data.get("label") != label:
            continue
        if nodeid is not None and data.get("nodeid") != nodeid:
            continue

        found.append(
            RunDirectory(
                path,
                root=root_path,
                label=data.get("label", ""),
                run_id=data.get("run_id", ""),
                retention=data.get("retention", "failed"),
                verbosity=data.get("verbosity"),
                nodeid=data.get("nodeid"),
                index_path=None,
            )
        )

    found.sort(key=lambda run: str(run.path))
    return found
