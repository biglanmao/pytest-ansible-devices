"""pytest fixtures：清单、工作目录与设备管理器。"""

from pathlib import Path

import pytest


def _resolve_path(raw: str, rootdir: Path) -> Path:
    """把命令行路径解析为绝对 ``Path``；相对路径以 pytest rootdir 为基准。"""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = rootdir / path
    return path.resolve()


@pytest.fixture(scope="session")
def device_inventory_path(request):
    """``--device-inventory`` 指定的清单文件路径（绝对 ``Path``）。"""
    raw = request.config.getoption("--device-inventory")
    if not raw:
        pytest.skip("未提供 --device-inventory，无法初始化清单")

    rootdir = request.config.rootpath
    path = _resolve_path(raw, rootdir)
    if not path.is_file():
        pytest.fail(
            f"--device-inventory 指向的清单文件不存在: {path}"
            f"（相对路径基于 rootdir: {rootdir}）"
        )
    return path


@pytest.fixture(scope="session")
def device_inventory(device_inventory_path):
    """ansible-core 初始化：InventoryManager 加载清单（进程内清单对象）。"""
    from ansible.inventory.manager import InventoryManager
    from ansible.parsing.dataloader import DataLoader

    loader = DataLoader()
    # InventoryManager 要求 sources 为字符串（内部做 `',' in source` 判断）。
    return InventoryManager(loader=loader, sources=[str(device_inventory_path)])


@pytest.fixture
def device_private_data_dir(tmp_path, request):
    """ansible-runner 工作目录（绝对 ``Path``）。

    未提供 ``--device-private-data-dir`` 时使用当前测试的 ``tmp_path``，
    保证每个测试有独立目录且自动清理。
    """
    raw = request.config.getoption("--device-private-data-dir")
    if not raw:
        return tmp_path
    return _resolve_path(raw, request.config.rootpath)
