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
from .fixture import (  # noqa: F401
    ansible_inventory,
    device_inventory_path,
    device_private_data_dir,
)


def pytest_addoption(parser):
    group = parser.getgroup("ansible-runner")
    group.addoption(
        "--device-inventory",
        action="store",
        default=None,
        help="Ansible 清单文件路径（ansible-core InventoryManager 加载）",
    )
    group.addoption(
        "--device-private-data-dir",
        action="store",
        default=None,
        help="ansible-runner 工作目录；为空时每次执行使用临时目录",
    )


def _ensure_ansible_path() -> None:
    """确保 ansible CLI 在 PATH（ansible-runner 通过子进程调用 ansible）。"""
    venv_bin = os.path.join(sys.prefix, "bin")
    if os.path.isdir(venv_bin):
        os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")


def pytest_configure(config):
    _ensure_ansible_path()
