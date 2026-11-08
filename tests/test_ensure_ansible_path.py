"""``_ensure_ansible_path`` 的单元测试。"""

import os
import sys

from pytest_ansible_devices import plugin


def test_prepends_venv_bin_to_path(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin")

    plugin._ensure_ansible_path()

    assert os.environ["PATH"].split(os.pathsep)[0] == str(bin_dir)


def test_keeps_path_when_venv_bin_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin")

    plugin._ensure_ansible_path()

    assert os.environ["PATH"] == "/usr/bin"


def test_pytest_configure_calls_ensure(monkeypatch):
    called = []
    monkeypatch.setattr(plugin, "_ensure_ansible_path", lambda: called.append(True))

    plugin.pytest_configure(None)

    assert called == [True]
