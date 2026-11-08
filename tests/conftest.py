"""测试公共夹具。"""

import pytest

pytest_plugins = ["pytester"]

INVENTORY_CONTENT = """\
[web]
web1 ansible_connection=local

[db]
db1 ansible_connection=local

[all:vars]
site=lab
"""


def write_inventory(path):
    path.write_text(INVENTORY_CONTENT)
    return path


@pytest.fixture
def inventory_file(tmp_path):
    """直接用于 runner_context 的本地清单（无需 SSH）。"""
    return str(write_inventory(tmp_path / "inventory.ini"))


@pytest.fixture
def pytester_inventory(pytester):
    """pytester 沙箱内可用的清单文件。"""
    return str(write_inventory(pytester.path / "inventory.ini"))
