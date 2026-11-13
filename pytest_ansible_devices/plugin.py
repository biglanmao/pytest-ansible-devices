"""pytest 插件入口 —— 在 pytest 框架下初始化 ansible-core / ansible-runner。

- ansible-runner 初始化：``pytest_configure`` 确保 ansible CLI 在 PATH。
- ansible-core 初始化：``ansible_inventory`` fixture（InventoryManager 加载清单）。
- 设备层：``device_manager`` fixture（清单驱动的设备管理器）。
- kw 层生命周期：``runner_context``。
"""

import argparse
import os
import sys

import pytest

# 导入即注册 fixture（pytest 会收集插件模块上的 fixture 属性）。
from .fixture import (  # noqa: F401
    cleanup_pending_runs,
    configure_session_log,
    device_inventory,
    device_inventory_path,
    device_run_dir,
    device_run_retention,
    device_run_root,
    device_runner_context,
    device_session_dir,
    device_verbosity,
    handle_test_report,
)
# 暴露给 pytestconfig.pluginmanager.get_plugin(...).runner_context
from .runner_context import runner_context  # noqa: F401
from .run_directory import RETENTION_POLICIES


def _non_negative_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"必须是整数: {value!r}")
    if number < 0:
        raise argparse.ArgumentTypeError(f"不能为负数: {number}")
    return number


def pytest_addoption(parser):
    group = parser.getgroup("ansible-runner")
    group.addoption(
        "--device-inventory",
        action="store",
        default=None,
        help="清单文件或目录（相对路径基于 pytest rootdir）",
    )
    group.addoption(
        "--device-run-dir",
        action="store",
        default=None,
        help="受管运行目录根（相对路径基于 pytest rootdir）；未配置时不启用",
    )
    group.addoption(
        "--device-run-retention",
        action="store",
        choices=RETENTION_POLICIES,
        default=None,
        help="受管运行目录保留策略，默认 failed",
    )
    group.addoption(
        "--device-verbosity",
        action="store",
        type=_non_negative_int,
        default=None,
        help="Ansible 原生 verbosity（0/1/2/...）；未配置时保持原生行为",
    )
    parser.addini(
        "device_inventory",
        "清单文件或目录；相对路径基于 pytest rootdir；"
        "未配置时必须通过命令行或本项提供",
        default="",
    )
    parser.addini(
        "device_run_dir",
        "受管运行目录根；相对路径基于 pytest rootdir；不配置时不启用",
        default="",
    )
    parser.addini(
        "device_run_retention",
        "受管运行目录保留策略：failed / all / none",
        default="failed",
    )
    parser.addini(
        "device_verbosity",
        "Ansible 原生 verbosity（整数）；不配置时保持原生行为",
        default="",
    )


def _ensure_ansible_path() -> None:
    """确保 ansible CLI 在 PATH（ansible-runner 通过子进程调用 ansible）。"""
    venv_bin = os.path.join(sys.prefix, "bin")
    if os.path.isdir(venv_bin):
        os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")


def pytest_configure(config):
    _ensure_ansible_path()


def pytest_sessionstart(session):
    """在用例执行前固化 session id，并注入全局 ANSIBLE_LOG_PATH。"""
    configure_session_log(session.config)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """报告全部产出后统一执行 retention 清理；失败只告警，不影响退出码。"""
    cleanup_pending_runs(config)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """用例级 outcome 由报告决定，defer 的运行目录在这里收尾。"""
    outcome = yield
    report = outcome.get_result()
    handle_test_report(item.config, item.nodeid, report)
