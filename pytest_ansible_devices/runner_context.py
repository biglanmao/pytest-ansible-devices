"""runner 上下文管理器 —— kw 层直接使用 ansible-runner 的生命周期管理。

依据：整个 ansible-runner 面里，需要「开/关」管理的运行时状态对象只有 ``Runner`` 一个。
本模块只做一件事：创建 Runner → yield 给调用方 → 退出时清理临时目录。
"""

from contextlib import contextmanager
import shutil
import tempfile

from ansible_runner import Runner, RunnerConfig


@contextmanager
def runner_context(host=None, inventory=None, private_data_dir=None, **runner_kwargs):
    """创建 Runner → yield → 清理临时 private_data_dir。

    :param host: host_pattern（adhoc 目标，如 ``web`` / ``dev1`` / ``all``）
    :param inventory: inventory 源（文件路径，单一事实来源）
    :param private_data_dir: 显式指定则使用且不清理；None 则临时创建、退出时清理
    :param runner_kwargs: 其余透传给 ``RunnerConfig``（如 module / playbook 等）
    """
    owns_dir = private_data_dir is None
    pdd = private_data_dir or tempfile.mkdtemp(prefix="pad_runner_")
    try:
        config = RunnerConfig(
            private_data_dir=pdd,
            host_pattern=host,
            inventory=inventory,
            **runner_kwargs,
        )
        config.prepare()  # 构建 ansible 命令（否则 Runner.run 拿不到 command）
        runner = Runner(config)
        yield runner
    finally:
        if owns_dir:
            shutil.rmtree(pdd, ignore_errors=True)
