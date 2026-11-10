"""``runner_context`` 生命周期与真实 ansible-runner 执行测试。"""

from pathlib import Path

import pytest

from pytest_ansible_devices.runner_context import runner_context


def _ok_events(runner):
    return [e for e in runner.events if e.get("event") == "runner_on_ok"]


def test_yields_prepared_runner(inventory_file):
    """进入上下文时 Runner 已就绪，命令已构建。"""
    with runner_context(
        host="web1", inventory=inventory_file, module="ping"
    ) as runner:
        assert runner.status == "unstarted"
        assert runner.config.command[:2] == ["ansible", "-i"]
        assert runner.config.command[-3:] == ["-m", "ping", "web1"]

    assert Path(runner.config.private_data_dir).is_dir() is False


def test_temporary_private_data_dir_is_cleaned(inventory_file):
    """未显式指定工作目录时，退出上下文应删除临时目录。"""
    with runner_context(
        host="web1", inventory=inventory_file, module="ping"
    ) as runner:
        private_data_dir = Path(runner.config.private_data_dir)
        assert private_data_dir.is_dir()

    assert not private_data_dir.exists()


def test_temporary_private_data_dir_is_cleaned_on_exception(inventory_file):
    """上下文内抛异常时仍应清理临时目录。"""
    with pytest.raises(RuntimeError, match="boom"):
        with runner_context(
            host="web1", inventory=inventory_file, module="ping"
        ) as runner:
            private_data_dir = Path(runner.config.private_data_dir)
            raise RuntimeError("boom")

    assert not private_data_dir.exists()


def test_explicit_private_data_dir_is_preserved(inventory_file, tmp_path):
    """显式指定的工作目录退出后应保留。"""
    private_data_dir = tmp_path / "runner"
    private_data_dir.mkdir()

    with runner_context(
        host="web1",
        inventory=inventory_file,
        private_data_dir=str(private_data_dir),
        module="ping",
    ) as runner:
        assert Path(runner.config.private_data_dir) == private_data_dir

    assert private_data_dir.is_dir()


def test_runs_adhoc_command(inventory_file):
    """真实执行 ad-hoc 命令并读取结果。"""
    with runner_context(
        host="web1",
        inventory=inventory_file,
        module="command",
        module_args="echo hello_from_test",
    ) as runner:
        runner.run()
        assert runner.status == "successful"
        assert runner.rc == 0
        events = _ok_events(runner)

    assert events
    assert events[0]["event_data"]["res"]["stdout"] == "hello_from_test"


def test_runs_playbook(inventory_file, tmp_path):
    """真实执行 playbook。"""
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        """\
---
- name: test playbook
  hosts: web1
  gather_facts: false
  tasks:
    - name: echo
      command: echo playbook_ok
      register: result
    - name: show
      debug:
        var: result.stdout
"""
    )

    with runner_context(inventory=inventory_file, playbook=str(playbook)) as runner:
        runner.run()
        assert runner.status == "successful"
        assert runner.rc == 0
        stdout_values = [
            e["event_data"]["res"].get("stdout") for e in _ok_events(runner)
        ]

    assert "playbook_ok" in stdout_values


def test_device_runner_context_fixture(device_runner_context, inventory_file):
    """``device_runner_context`` fixture 应与模块函数行为一致。"""
    with device_runner_context(
        host="web1", inventory=inventory_file, module="ping"
    ) as runner:
        runner.run()
        assert runner.status == "successful"
