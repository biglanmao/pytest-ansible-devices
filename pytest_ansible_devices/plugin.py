"""pytest 插件入口 —— 在 pytest 框架下初始化 ansible-core / ansible-runner。

- ansible-runner 初始化：``pytest_configure`` 确保 ansible CLI 在 PATH。
- ansible-core 初始化：``ansible_inventory`` fixture（InventoryManager 加载清单）。
- 上层使用：直接 ``import ansible_runner``（接口本就是公开的，无需再封装）。
- kw 层生命周期：``runner_context``。
"""

import os
import sys

import pytest


def pytest_addoption(parser):
    group = parser.getgroup("ansible-runner")
    group.addoption(
        "--device-inventory",
        action="store",
        default=None,
        help="Ansible 清单文件路径（ansible-core InventoryManager 加载）",
    )


def _ensure_ansible_path() -> None:
    """确保 ansible CLI 在 PATH（ansible-runner 通过子进程调用 ansible）。"""
    venv_bin = os.path.join(sys.prefix, "bin")
    if os.path.isdir(venv_bin):
        os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")


def pytest_configure(config):
    _ensure_ansible_path()



