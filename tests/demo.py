"""demo：验证 清单 → 资源池 → 申请 → 执行 → 释放 的完整闭环。

Ansible 调用均为真实接口（InventoryManager + ansible-runner）。
运行：PATH 需包含 flytrap venv/bin（或由脚本内自动补充）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pytest_ansible_device import DeviceInventory, DevicePool, Demand  # noqa: E402


def main() -> None:
    inventory_file = str(Path(__file__).parent / "demo_inventory.ini")

    # 1. 清单（真实 InventoryManager）
    inventory = DeviceInventory(inventory_file)
    print("=== 1. 清单加载 ===")
    print("  hosts :", inventory.host_names())
    print("  groups:", inventory.group_names())
    print("  dev1 vars:", inventory.host_vars("dev1"))

    # 2. 一次性全部入池
    pool = DevicePool(inventory)
    print("\n=== 2. 一次性全部入池（对象引用，不连接） ===")
    for name, st in pool.status().items():
        print(f"  {name}: {st.value}")

    # 3. 按组申请 + 执行 + 释放
    print("\n=== 3. 按组申请 web（count=1）→ 执行 → 释放 ===")
    handles = pool.acquire(Demand(group="web", count=1))
    assert handles, "按组申请失败"
    h = handles[0]
    print(f"  获得句柄: {h.name}，池状态: {pool.status(h.name).value}")
    r = h.execute("echo hello_from_device")
    print(f"  执行 echo: success={r.success}, stdout={r.raw_output.strip()!r}")
    h.release()
    print(f"  释放后状态: {pool.status(h.name).value}")

    # 4. 按名称指定
    print("\n=== 4. 按名称申请 dev3 → 执行 hostname ===")
    handles = pool.acquire(Demand(name="dev3"))
    assert handles, "按名称申请失败"
    h = handles[0]
    r = h.execute("hostname")
    print(f"  执行 hostname: success={r.success}, stdout={r.raw_output.strip()!r}")
    h.release()

    # 5. 按元数据申请
    print("\n=== 5. 按元数据申请 os=CentOS7 ===")
    handles = pool.acquire(Demand(metadata={"os": "CentOS7"}))
    if handles:
        print(f"  获得: {handles[0].name}")
        handles[0].release()

    # 6. 申请数量不足 / 不存在 → 返回 None（FR-16 优雅降级）
    print("\n=== 6. 申请不存在的组（应返回 None） ===")
    print("  结果:", pool.acquire(Demand(group="nonexistent")))

    print("\n=== 闭环验证完成 ===")
    print("  最终池状态:", {n: s.value for n, s in pool.status().items()})


if __name__ == "__main__":
    main()
