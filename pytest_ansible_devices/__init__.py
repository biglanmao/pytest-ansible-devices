"""pytest-ansible-device —— 将 ansible-runner 集成到 pytest。

- 用例层：通过 ``ansible_runner_api`` fixture 使用 ansible-runner 关键接口。
- kw 层：直接 ``import ansible_runner`` + ``runner_context`` 管理 Runner 生命周期。
"""

from .runner_context import runner_context

__all__ = ["runner_context"]
