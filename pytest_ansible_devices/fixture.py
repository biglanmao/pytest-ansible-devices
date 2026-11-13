"""pytest fixtures：设备清单与受管运行目录。"""

from contextlib import contextmanager
import os
from pathlib import Path

import pytest
from _pytest.stash import StashKey

from .run_directory import (
    INDEX_FILE,
    RETENTION_POLICIES,
    new_session_id,
    run_directory,
    temporary_run_directory,
)


def _resolve_path(raw, rootdir: Path) -> Path:
    """把命令行/配置路径解析为绝对 ``Path``；相对路径以 pytest rootdir 为基准。"""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = rootdir / path
    return path.resolve()


def _inventory_source(config):
    """按 命令行 > pytest 配置 的顺序返回 ``(raw, 来源说明)``；都未配置时返回 None。"""
    cli = config.getoption("--device-inventory")
    if cli:
        return cli, "命令行 --device-inventory"

    ini = config.getini("device_inventory")
    if ini:
        return ini, "pytest 配置 device_inventory"

    return None, None


def _option_source(config, option: str, ini_name: str):
    """按 命令行 > pytest 配置 取值；都未配置时返回 ``(None, None)``。"""
    cli = config.getoption(option)
    if cli is not None and cli != "":
        return cli, f"命令行 {option}"

    ini = config.getini(ini_name)
    if ini is not None and str(ini).strip() != "":
        return ini, f"pytest 配置 {ini_name}"

    return None, None


def _mkdir_private(path: Path) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if existed:
        return
    try:
        path.chmod(0o700)
    except OSError:
        pass


_SESSION_ID_KEY: StashKey[str] = StashKey()


def _session_id(config) -> str:
    return config.stash.setdefault(_SESSION_ID_KEY, new_session_id())


def _worker_id(config) -> str | None:
    """当前 xdist worker 的 id（如 ``gw0``）；控制器或非 xdist 下返回 None。"""
    workerinput = getattr(config, "workerinput", None) or {}
    return workerinput.get("workerid") or os.environ.get("PYTEST_XDIST_WORKER")


def is_xdist_controller(config) -> bool:
    """当前进程是否是 xdist 控制器（负责分发、不执行用例）。

    判断依据与 xdist 自身一致：没有 ``workerinput``（不是 worker），
    且 ``dist`` 未关闭。xdist 未安装时该选项不存在，返回 False。
    """
    if _worker_id(config) is not None:
        return False
    return getattr(config.option, "dist", None) not in (None, "no")


def configure_session_log(config) -> str | None:
    """在 session 启动时固化 session id，并按需注入全局 ``ANSIBLE_LOG_PATH``。

    - session id 在这里首次生成，之后 ``device_session_dir`` 等夹具只读取，
      因此 ``private_data_dir`` 与全局日志落在同一个 ``<session-id>`` 下；
    - xdist 下每个 worker 独立一份日志：``<root>/<session-id>/<worker>/ansible.log``，
      避免多进程并发写同一个文件；
    - 控制器进程（``-n`` 下没有 workerinput）不跑用例，直接跳过；
    - 已存在的 ``ANSIBLE_LOG_PATH`` 优先，不覆盖调用方环境。
    """
    _session_id(config)  # 唯一生成点：后续一律读取同一个值

    if os.environ.get("ANSIBLE_LOG_PATH"):
        return None

    raw, _source = _option_source(config, "--device-log-dir", "device_log_dir")
    if raw is None:
        raw, _source = _option_source(config, "--device-run-dir", "device_run_dir")
    if raw is None:
        return None

    worker = _worker_id(config)
    if worker is None and is_xdist_controller(config):
        return None  # 控制器不跑用例；一旦设值会被 worker 继承而破坏隔离

    root = _resolve_path(raw, config.rootpath)
    if root.exists() and not root.is_dir():
        # 目录校验交给对应夹具，这里不抢先抛错打断整个 session。
        return None

    log_dir = root / _session_id(config)
    if worker is not None:
        log_dir = log_dir / worker
    try:
        _mkdir_private(log_dir)
    except OSError:
        return None  # 创建失败时保持原行为，由夹具侧给出明确报错

    log_path = log_dir / "ansible.log"
    os.environ["ANSIBLE_LOG_PATH"] = str(log_path)
    return str(log_path)


class _RunState:
    """记录当前测试创建的受管运行目录，供 makereport 阶段收尾。"""

    def __init__(self) -> None:
        self._runs: dict[str, list] = {}
        self._reports: dict[str, list] = {}

    def register(self, nodeid: str, run) -> None:
        self._runs.setdefault(nodeid, []).append(run)

    def record_report(self, nodeid: str, report) -> None:
        self._reports.setdefault(nodeid, []).append(report)

    def finalize_node(self, nodeid: str) -> None:
        runs = self._runs.pop(nodeid, [])
        reports = self._reports.pop(nodeid, [])

        if any(getattr(report, "failed", False) for report in reports):
            outcome = "failed"
        elif any(getattr(report, "skipped", False) for report in reports):
            outcome = "skipped"
        else:
            outcome = "passed"

        for run in runs:
            if not run.finalized:
                run.finalize(outcome)


_RUN_STATE_KEY: StashKey[_RunState] = StashKey()


def _run_state(config) -> _RunState:
    return config.stash.setdefault(_RUN_STATE_KEY, _RunState())


def handle_test_report(config, nodeid: str, report) -> None:
    """由 ``pytest_runtest_makereport`` 调用；teardown 阶段按用例结果收尾。"""
    state = config.stash.get(_RUN_STATE_KEY, None)
    if state is None:
        return
    state.record_report(nodeid, report)
    if report.when == "teardown":
        state.finalize_node(nodeid)


@pytest.fixture(scope="session")
def device_inventory_path(request):
    """清单源路径（文件或目录），返回绝对 ``Path``。"""
    config = request.config
    rootdir = config.rootpath
    raw, source = _inventory_source(config)
    if raw is None:
        pytest.fail(
            "未配置清单源。请任选一种方式指定：\n"
            "  - 命令行: pytest --device-inventory=<文件或目录>\n"
            "  - pytest 配置: [pytest] device_inventory = <文件或目录>\n"
            f"相对路径基于 rootdir: {rootdir}"
        )

    path = _resolve_path(raw, rootdir)

    if not path.exists():
        pytest.fail(
            f"清单源不存在: {path}"
            f"（来源: {source}；相对路径基于 rootdir: {rootdir}）"
        )
    if path.is_dir() and not any(path.iterdir()):
        pytest.fail(
            f"清单目录为空: {path}"
            f"（来源: {source}；相对路径基于 rootdir: {rootdir}）"
        )
    return path


@pytest.fixture(scope="session")
def device_inventory(device_inventory_path):
    """ansible-core 初始化：InventoryManager 加载清单（进程内清单对象）。"""
    from ansible.inventory.manager import InventoryManager
    from ansible.parsing.dataloader import DataLoader

    loader = DataLoader()
    # InventoryManager 要求 sources 为字符串（内部做 `',' in source` 判断）。
    return InventoryManager(loader=loader, sources=[str(device_inventory_path)])


@pytest.fixture(scope="session")
def device_runner_context():
    """提供与插件属性等价的 ``runner_context`` 上下文管理器。"""
    from .runner_context import runner_context

    return runner_context


# ---------------------------------------------------------------- PAD-FR-21
@pytest.fixture(scope="session")
def device_run_root(request):
    """``--device-run-dir`` / ``device_run_dir`` 指定的受管根目录。

    未配置时返回 ``None``，不改变现有行为。
    """
    config = request.config
    raw, source = _option_source(config, "--device-run-dir", "device_run_dir")
    if raw is None:
        return None

    root = _resolve_path(raw, config.rootpath)
    if root.exists() and not root.is_dir():
        pytest.fail(f"运行目录不是目录: {root}（来源: {source}）")
    try:
        _mkdir_private(root)
    except OSError as exc:
        pytest.fail(f"无法创建运行目录: {root}（来源: {source}）: {exc}")
    return root


@pytest.fixture(scope="session")
def device_log_root(request):
    """``--device-log-dir`` / ``device_log_dir`` 指定的独立日志根目录。

    未配置时返回 ``None``；此时日志仍放在 run 目录内（保持旧行为）。
    """
    config = request.config
    raw, source = _option_source(config, "--device-log-dir", "device_log_dir")
    if raw is None:
        return None

    root = _resolve_path(raw, config.rootpath)
    if root.exists() and not root.is_dir():
        pytest.fail(f"日志目录不是目录: {root}（来源: {source}）")
    try:
        _mkdir_private(root)
    except OSError as exc:
        pytest.fail(f"无法创建日志目录: {root}（来源: {source}）: {exc}")
    return root


@pytest.fixture(scope="session")
def device_session_dir(request, device_run_root):
    """本次 session 的运行目录：``<run-root>/<session-id>/``。"""
    if device_run_root is None:
        return None
    session_dir = device_run_root / _session_id(request.config)
    _mkdir_private(session_dir)
    return session_dir


@pytest.fixture(scope="session")
def device_run_retention(request):
    """受管运行目录的默认保留策略：failed / all / none。"""
    raw, source = _option_source(
        request.config, "--device-run-retention", "device_run_retention"
    )
    if raw is None:
        raw = "failed"
    if raw not in RETENTION_POLICIES:
        allowed = ", ".join(RETENTION_POLICIES)
        pytest.fail(f"retention 必须是 {allowed} 之一（来源: {source}），实际为: {raw!r}")
    return raw


@pytest.fixture(scope="session")
def device_verbosity(request):
    """Ansible 原生 verbosity（0/1/2/...）；未配置时返回 None。"""
    raw, source = _option_source(
        request.config, "--device-verbosity", "device_verbosity"
    )
    if raw is None:
        return None
    try:
        verbosity = int(raw)
    except (TypeError, ValueError):
        pytest.fail(f"verbosity 必须是整数（来源: {source}），实际为: {raw!r}")
    if verbosity < 0:
        pytest.fail(f"verbosity 不能为负数（来源: {source}），实际为: {verbosity}")
    return verbosity


@pytest.fixture(scope="session")
def device_log_env(request, device_session_dir, device_log_root):
    """session 级 ``ANSIBLE_LOG_PATH``；未配置目录时为空字典。

    配置了 ``--device-log-dir`` 时日志完全独立于运行目录；
    否则沿用旧的 ``<session-dir>/ansible.log``。
    """
    if device_log_root is not None:
        log_dir = device_log_root / _session_id(request.config)
    else:
        log_dir = device_session_dir

    if log_dir is None:
        return {}
    _mkdir_private(log_dir)
    return {"ANSIBLE_LOG_PATH": str(log_dir / "ansible.log")}


# ---------------------------------------------------------------- PAD-FR-22
@contextmanager
def _registered(manager, state: _RunState, nodeid: str):
    with manager as run:
        state.register(nodeid, run)
        yield run


@pytest.fixture
def device_run_dir(
    request,
    device_session_dir,
    device_run_retention,
    device_verbosity,
    device_log_root,
):
    """返回运行目录工厂，可在同一用例内创建多个 run 目录。

    用法::

        def test_x(device_run_dir):
            with device_run_dir("ssh-adhoc") as run:
                ansible_runner.run(private_data_dir=run, envvars=run.envvars)
                run.set_outcome(result)

    未配置 ``--device-run-dir`` 时回退到 mkdtemp，退出即删除，行为与旧版一致。
    """
    config = request.config
    nodeid = request.node.nodeid
    state = _run_state(config)
    default_retention = device_run_retention
    default_verbosity = device_verbosity
    session_id = _session_id(config)
    default_log_root = (
        None if device_log_root is None else device_log_root / session_id
    )

    def factory(
        label=None,
        *,
        retention=None,
        outcome=None,
        verbosity=None,
        root=None,
        log_root=None,
    ):
        run_label = nodeid if not label else str(label)
        selected_retention = retention or default_retention
        if selected_retention not in RETENTION_POLICIES:
            allowed = ", ".join(RETENTION_POLICIES)
            raise ValueError(
                f"retention 必须是 {allowed} 之一，实际为: {selected_retention!r}"
            )
        selected_verbosity = default_verbosity if verbosity is None else verbosity

        if root is not None:
            target_root = _resolve_path(root, config.rootpath)
        else:
            target_root = device_session_dir

        if log_root is not None:
            selected_log_root = _resolve_path(log_root, config.rootpath)
        else:
            selected_log_root = default_log_root

        if target_root is None:
            manager = temporary_run_directory(
                run_label,
                retention=selected_retention,
                outcome=outcome,
                verbosity=selected_verbosity,
                log_root=selected_log_root,
                defer=False,
            )
        else:
            manager = run_directory(
                target_root,
                run_label,
                retention=selected_retention,
                outcome=outcome,
                verbosity=selected_verbosity,
                log_root=selected_log_root,
                nodeid=nodeid,
                index_path=target_root / INDEX_FILE,
                defer=True,
            )

        return _registered(manager, state, nodeid)

    return factory
