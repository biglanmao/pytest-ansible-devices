import pytest

@pytest.fixture(scope="session")
def ansible_inventory(request):
    """ansible-core 初始化：InventoryManager 加载清单（进程内清单对象）。"""
    from ansible.inventory.manager import InventoryManager
    from ansible.parsing.dataloader import DataLoader

    inventory_file = request.config.getoption("--device-inventory")
    if not inventory_file:
        pytest.skip("未提供 --device-inventory，无法初始化 ansible-core 清单")
    loader = DataLoader()
    return InventoryManager(loader=loader, sources=[inventory_file])