"""pytest fixtures：清单、工作目录与设备管理器。"""

import pytest

from .device import AnsibleDeviceManager


@pytest.fixture(scope="session")
def device_inventory_path(request):
    """``--device-inventory`` 指定的清单文件路径。"""
    path = request.config.getoption("--device-inventory")
    if not path:
        pytest.skip("未提供 --device-inventory，无法初始化清单")
    return path


@pytest.fixture(scope="session")
def ansible_inventory(device_inventory_path):
    """ansible-core 初始化：InventoryManager 加载清单（进程内清单对象）。"""
    from ansible.inventory.manager import InventoryManager
    from ansible.parsing.dataloader import DataLoader

    loader = DataLoader()
    return InventoryManager(loader=loader, sources=[device_inventory_path])


@pytest.fixture(scope="session")
def device_private_data_dir(request):
    """``--device-private-data-dir`` 指定的 ansible-runner 工作目录。"""
    return request.config.getoption("--device-private-data-dir")