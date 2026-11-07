"""验证 ansible-core / ansible-runner 在 pytest 下的初始化，及上层直接 import 使用。"""

from pathlib import Path

INVENTORY = str(Path(__file__).parent.parent / "demo_inventory.ini")


def test_ansible_inventory_initialized(ansible_inventory):
    """ansible-core 初始化：InventoryManager 已加载清单。"""
    hosts = [h.name for h in ansible_inventory.hosts.values()]
    assert "dev1" in hosts
    assert "web" in ansible_inventory.groups


def test_ansible_runner_run_direct_import():
    """上层直接 import ansible_runner 使用（无需封装 fixture）。"""
    import ansible_runner

    r = ansible_runner.run(host_pattern="localhost", module="ping")
    assert r.status == "successful"
    assert r.rc == 0


def test_ansible_runner_get_inventory_direct_import():
    """上层直接 import ansible_runner 查询清单。"""
    import ansible_runner

    resp, err = ansible_runner.get_inventory(
        action="list", inventories=[INVENTORY], response_format="json"
    )
    assert err == ""
    assert isinstance(resp, dict)


def test_runner_context():
    """kw 层：runner_context 管理 Runner 生命周期。"""
    from pytest_ansible_device.runner_context import runner_context

    with runner_context(host="localhost", inventory=INVENTORY) as runner:
        assert runner is not None
        assert runner.config is not None
        assert runner.status == "unstarted"
