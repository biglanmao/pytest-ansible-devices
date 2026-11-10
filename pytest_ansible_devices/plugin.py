"""pytest 插件入口 —— 在 pytest 框架下初始化 ansible-core / ansible-runner。

- ansible-runner 初始化：``pytest_configure`` 确保 ansible CLI 在 PATH。
- ansible-core 初始化：``ansible_inventory`` fixture（InventoryManager 加载清单）。
- 设备层：``device_manager`` fixture（清单驱动的设备管理器）。
- kw 层生命周期：``runner_context``。
"""

import os
import sys

import pytest

# 导入即注册 fixture（pytest 会收集插件模块上的 fixture 属性）。
from .fixture import device_inventory, device_inventory_path  # noqa: F401


def pytest_addoption(parser):
    group = parser.getgroup("ansible-runner")
    group.addoption(
        "--device-inventory",
        action="store",
        default=None,
        help="清单文件或目录（相对路径基于 pytest rootdir）",
    )
    parser.addini(
        "device_inventory",
        "清单文件或目录；相对路径基于 pytest rootdir；"
        "未配置时使用 <rootdir>/etc/devices/inventory",
        default="",
    )


def _ensure_ansible_path() -> None:
    """确保 ansible CLI 在 PATH（ansible-runner 通过子进程调用 ansible）。"""
    venv_bin = os.path.join(sys.prefix, "bin")
    if os.path.isdir(venv_bin):
        os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")


def pytest_configure(config):
    _ensure_ansible_path()
