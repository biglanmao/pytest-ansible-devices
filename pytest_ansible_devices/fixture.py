"""pytest fixtures：设备清单。"""

from pathlib import Path

import pytest


def _resolve_path(raw, rootdir: Path) -> Path:
    """把命令行/配置路径解析为绝对 ``Path``；相对路径以 pytest rootdir 为基准。"""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = rootdir / path
    return path.resolve()


def _inventory_source(config):
    """按 命令行 > pytest 配置 的顺序返回 ``(raw, 来源说明)``；都未配置时返回 None。"""
    cli = config.getoption("--device-inventory")
    if cli:
        return cli, "命令行 --device-inventory"

    ini = config.getini("device_inventory")
    if ini:
        return ini, "pytest 配置 device_inventory"

    return None, None


@pytest.fixture(scope="session")
def device_inventory_path(request):
    """清单源路径（文件或目录），返回绝对 ``Path``。"""
    config = request.config
    rootdir = config.rootpath
    raw, source = _inventory_source(config)
    if raw is None:
        pytest.fail(
            "未配置清单源。请任选一种方式指定：\n"
            "  - 命令行: pytest --device-inventory=<文件或目录>\n"
            "  - pytest 配置: [pytest] device_inventory = <文件或目录>\n"
            f"相对路径基于 rootdir: {rootdir}"
        )

    path = _resolve_path(raw, rootdir)

    if not path.exists():
        pytest.fail(
            f"清单源不存在: {path}"
            f"（来源: {source}；相对路径基于 rootdir: {rootdir}）"
        )
    if path.is_dir() and not any(path.iterdir()):
        pytest.fail(
            f"清单目录为空: {path}"
            f"（来源: {source}；相对路径基于 rootdir: {rootdir}）"
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
