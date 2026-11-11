"""pytest-ansible-device —— 将 ansible-runner 集成到 pytest。

- 用例层：通过 fixture 使用 ansible-runner 关键接口。
- kw 层：直接 ``import ansible_runner`` + ``runner_context`` 管理 Runner 生命周期。
- 运行目录：``run_directory`` 不依赖 pytest，可在普通脚本 / CLI 中独立使用。
"""

from .run_directory import (
    RunDirectory,
    find_run_dirs,
    run_directory,
    temporary_run_directory,
)
from .runner_context import runner_context

__all__ = [
    "RunDirectory",
    "find_run_dirs",
    "run_directory",
    "runner_context",
    "temporary_run_directory",
]
