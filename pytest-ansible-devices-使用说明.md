# pytest-ansible-devices 使用说明

> 适用版本：0.2.0
> 依赖：`pytest>=7`、`ansible-core>=2.16`、`ansible-runner>=2.4`

本插件只消除**重复配置**，不封装执行与结果：

- 提供 inventory 路径、受管运行目录等 fixture；
- 提供 `runner_context` 管理 `Runner` 生命周期；
- 提供 `run_directory`（不依赖 pytest）管理运行目录、manifest 与保留策略；
- 执行仍然直接调用 `ansible_runner.run`，结果仍然直接读 `runner.status / rc / events / stats`；
- 不提供设备管理器、连接池、结果对象、playbook 目录等额外抽象。

---

## 1. 安装与启用

```bash
pip install -e .          # 本地开发
# 或：pip install pytest-ansible-devices
```

插件通过 `pytest11` entry point 自动注册，**不需要**在 `conftest.py` 里写 `pytest_plugins`。

验证：

```bash
pytest --help | grep -A3 'ansible-runner'
```

---

## 2. 命令行选项

| 选项 / 配置项 | 说明 |
|---|---|
| `--device-inventory` | 清单源，**文件或目录**均可。相对路径以 pytest rootdir 为基准 |
| `device_inventory`（pytest 配置） | 同上，作为命令行选项的兜底 |
| `--device-run-dir` | 受管运行目录根。相对路径以 pytest rootdir 为基准；**不配置时不启用** |
| `device_run_dir`（pytest 配置） | 同上，作为命令行选项的兜底 |
| `--device-run-retention` | 受管目录保留策略：`failed`（默认）/ `all` / `none` |
| `device_run_retention`（pytest 配置） | 同上，默认 `failed` |
| `--device-verbosity` | Ansible 原生 verbosity 整数：`0` 摘要、`1` 增加 stdout/stderr、`2+` 任务参数与连接细节 |
| `device_verbosity`（pytest 配置） | 同上，不配置时保持 Ansible 原生行为 |

取值优先级：**命令行 > pytest 配置 > 不设置**。

插件**不提供内置默认目录**：未配置时直接报错，并提示两种配置方式。
目录形态要求存在且非空，否则报错并给出绝对路径与 rootdir。

```bash
pytest tests/ --device-inventory=tests/inventory.ini
pytest tests/ --device-inventory=/abs/path/inventory
```

`pytest.ini` / `pyproject.toml` 中配置：

```ini
[pytest]
device_inventory = etc/devices/inventory
```

> 使用 `pytest -c etc/pytest.toml` 时，pytest 的 **rootdir 是 `etc/`**，
> 相对路径以 `etc/` 为基准。此时应写 `device_inventory = devices/inventory`，
> 不要写成 `etc/devices/inventory`（会变成 `etc/etc/devices/inventory`）。

---

## 3. Fixtures

### `device_inventory_path`

session 级，返回**绝对 `Path`**。路径可以是文件，也可以是目录。

```python
def test_inventory_exists(device_inventory_path):
    assert device_inventory_path.exists()
    # 目录清单：group_vars/、host_vars/ 放在该目录内部
    assert device_inventory_path.is_dir() or device_inventory_path.is_file()
```

> `ansible-runner` 的 `inventory` 参数要求字符串，传给执行层时用 `str(device_inventory_path)`。
> fixture 已经做过 `expanduser()` 和 `resolve()`，用例里不需要再 `Path(...).resolve()`。

### `device_inventory`

session 级，返回 ansible-core 的 `InventoryManager`。适合按设备名断言、读取 inventory 内联变量；**不用于执行**。

> 注意：`InventoryManager` 只解析清单，**不会加载 `group_vars/` / `host_vars/`**；
> 这两类变量在 ansible-runner 执行时由 Ansible 加载。

```python
def test_device_exists(device_inventory):
    assert "web1" in device_inventory.hosts

    host = device_inventory.get_host("web1")
    assert host is not None
    assert host.vars.get("ansible_connection") in {"ssh", "local", None}
```

### 受管运行目录（PAD-FR-21 / PAD-FR-22）

以下 fixture 按配置启用；未配置时为 `None`，不影响现有用例。

| fixture | 级别 | 说明 |
|---|---|---|
| `device_run_root` | session | 配置的受管根目录（绝对 `Path`） |
| `device_session_dir` | session | `<run-root>/<session-id>/`，本次 pytest session 的目录 |
| `device_verbosity` | session | 配置的 verbosity，未配置为 `None` |
| `device_run_retention` | session | 默认保留策略，未配置为 `failed` |
| `device_run_dir` | function | **工厂**：`with device_run_dir(label) as run:`，同一用例可创建多个 |

`device_run_dir` 返回的 `run` 是 `os.PathLike`，`str(run)` / `run.path` 都是本次 run 的
绝对目录，可直接作为 `private_data_dir`：

```python
import ansible_runner

def test_adhoc(device_inventory_path, device_run_dir):
    with device_run_dir("ssh-adhoc") as run:
        result = ansible_runner.run(
            private_data_dir=run,                 # 直接使用绝对路径
            inventory=str(device_inventory_path),
            host_pattern="vm_ubntu",
            module="command",
            module_args="hostname",
            envvars=run.envvars,                  # 可选：日志细分到 <run>/ansible.log
            verbosity=run.verbosity,              # 来自 --device-verbosity，或工厂参数覆盖
        )
        run.set_outcome(result)                   # 显式传入结果对象 / bool / "passed"
```

- 目录结构：`<run-root>/<session-id>/<label-slug>-<hash8>/<run_id>/`；
- `session-id` 是**进程级**的：xdist 下每个 worker 各自一份，所以 `-n 4` 会产生
  4 个 session 目录和 4 份 `index.jsonl`；收集全部 run 请扫 `<run-root>`
  （`find_run_dirs()`），不要只扫某一个 session 目录；
- 每个 run 目录写 `.pad-run.json` manifest，并在 `<session-dir>/index.jsonl` 追加索引；
- 默认 `ansible.log` 写在 `<run-root>/<session-id>/ansible.log`，一个 worker 进程一份；
- `run.log_path` / manifest 的 `log_path` 是 **per-run 日志路径**：只有传
  `envvars=run.envvars` 时才是实际日志；默认模式的日志在 session 目录下；
- 需要按 run 细分日志时传 `envvars=run.envvars`，日志改写到 `<run-dir>/ansible.log`，
  并随 run 目录一起被 `retention` 清理（成功 run 默认只保留 manifest）；
- 未配置 `--device-run-dir` 时既不启用受管目录，也不注入 `ANSIBLE_LOG_PATH`；
- `run.envvars` 只包含 `ANSIBLE_LOG_PATH`；需要其他变量时自行合并；
- `run.verbosity` 是调用 `ansible_runner.run(..., verbosity=...)` 的透传值，插件不解析日志；
- 未调用 `set_outcome` 时，由 `pytest_runtest_makereport` 按用例结果收尾；
- 未配置 `--device-run-dir` 时，工厂回退到 `mkdtemp`，退出即删除，行为与旧版一致。

保留策略：

| retention | 失败 run | 成功 run |
|---|---|---|
| `failed`（默认） | 保留 artifacts | 删除 artifacts，保留 manifest |
| `all` | 保留 | 保留 |
| `none` | 删除 artifacts，保留 manifest | 删除 artifacts，保留 manifest |

> “保留 manifest”意味着仍可通过 label / nodeid 反查到目录；普通脚本可直接使用
> `pytest_ansible_devices.find_run_dirs(root, label=...)`，无需 pytest。

清理时机：

- 用例结束时只**写决策**（manifest 的 `action` 与 `cleanup=pending`），不删文件；
- 真正删除在 `pytest_unconfigure` 执行，也就是所有报告（含 terminal summary、
  junitxml）产出之后；
- 清理失败只发 `RuntimeWarning` 并把 `cleanup` 记为 `failed`，**不会翻转用例结果**，
  现场保留；
- `manifest` 的 `cleanup` 字段取值：`skipped`（无需清理）/ `pending` / `done` / `failed`。

库层（不走 pytest）默认仍是“退出即清理”；需要同样的延迟语义时传
`run_directory(..., defer_cleanup=True)`，然后自行调用 `run.cleanup()`。

### 执行前校验设备名（可选）

Ansible 对不存在的 `host_pattern` 只打 warning，`rc` 仍可能是 0，用例会假通过。
执行前用 `device_inventory` 校验一次即可：

```python
def test_device(device_inventory):
    device = "web1"
    assert device in device_inventory.hosts, (
        f"设备不存在: {device}; 可用: {sorted(device_inventory.hosts)}"
    )
```

---

## 4. 执行示例

### 4.1 SSH ad-hoc

```python
import ansible_runner

DEVICE = "web1"


def test_ssh_adhoc(device_inventory_path, tmp_path):
    result = ansible_runner.run(
        inventory=str(device_inventory_path),
        private_data_dir=str(tmp_path),
        host_pattern=DEVICE,
        module="command",
        module_args="echo hello",
        quiet=True,
    )

    assert result.rc == 0 and result.status == "successful"
```

### 4.2 SSH playbook

playbook 目录由**用例自己指定**，插件不提供 `--device-playbook-dir`。

```python
def test_ssh_playbook(device_inventory_path, tmp_path):
    result = ansible_runner.run(
        inventory=str(device_inventory_path),
        private_data_dir=str(tmp_path),
        project_dir="/abs/path/to/playbooks",
        playbook="smoke.yml",
        extravars={"target_host": DEVICE},
        quiet=True,
    )

    assert result.rc == 0 and result.status == "successful"
```

### 4.3 串口 / 本地连接

连接方式由 inventory 或命令行显式指定，插件不自动判断。

```python
import json


def test_serial_adhoc(device_inventory_path, tmp_path):
    result = ansible_runner.run(
        inventory=str(device_inventory_path),
        private_data_dir=str(tmp_path),
        host_pattern=DEVICE,
        module="flytrap.tux.serial",
        module_args=json.dumps({"commands": ["ls -la"]}),
        cmdline="--connection local",
        quiet=True,
    )

    assert result.rc == 0 and result.status == "successful"
```

> `module_args` 目前必须是字符串；复杂参数用 `json.dumps(...)`。

### 4.4 串口 playbook

串口连接方式写在 playbook / inventory 里；插件只负责路径与生命周期。

```python
def test_serial_playbook(device_inventory_path, tmp_path):
    result = ansible_runner.run(
        inventory=str(device_inventory_path),
        private_data_dir=str(tmp_path),
        project_dir="/abs/path/to/playbooks",
        playbook="serial_smoke.yml",
        extravars={"target_host": DEVICE},
        quiet=True,
    )

    assert result.rc == 0 and result.status == "successful"
```

### 4.5 用 `runner_context` 管理生命周期

`runner_context` 是高级入口，与直接调用 `ansible_runner.run` 并存。三种获取方式等价。

**推荐：通过插件对象**

```python
def test_with_plugin(pytestconfig, device_inventory_path):
    plugin = pytestconfig.pluginmanager.get_plugin("pytest_ansible_devices")
    if plugin is None:
        pytest.fail("pytest_ansible_devices 插件未启用（检查 -p no:...）")

    with plugin.runner_context(
        host="web1",
        inventory=str(device_inventory_path),
        module="command",
        module_args="echo ok",
    ) as runner:
        runner.run()
        assert runner.status == "successful"
```

**或者：fixture 注入**

```python
def test_with_fixture(device_runner_context, device_inventory_path):
    with device_runner_context(
        host="web1",
        inventory=str(device_inventory_path),
        module="command",
        module_args="echo ok",
    ) as runner:
        runner.run()
        assert runner.status == "successful"
```

**也可以：直接导入**

```python
from pytest_ansible_devices import runner_context
```

> - 插件被 `-p no:pytest_ansible_devices` 禁用时，插件代码不会加载，
>   `get_plugin(...)` 返回 `None`，只能由调用方判空并报错。
> - 使用 `pluginmanager.get_plugin()`，不要用旧别名 `getplugin()`。
> - 三种方式指向同一实现，行为一致。

清理规则：

- 不传 `private_data_dir`：临时目录，退出 `with` 时删除；
- 显式传 `private_data_dir`：退出后保留，便于事后排查。

---

## 5. 读取结果（不封装）

直接使用 ansible-runner 的原始属性：

| 属性 | 用途 |
|---|---|
| `result.status` | `"successful"` / `"failed"` 等 |
| `result.rc` | 进程返回码 |
| `result.stats` | play recap（ok / changed / failures 等） |
| `result.events` | 全部事件 |
| `result.config.artifact_dir` | 本次执行的 artifact 目录 |

### 5.1 取命令输出

```python
payloads = [
    event["event_data"]["res"]
    for event in result.events
    if event.get("event") == "runner_on_ok"
]

stdout = "\n".join(p.get("stdout", "") for p in payloads).strip()
```

### 5.2 取失败信息

```python
FAILED_EVENTS = {
    "runner_on_failed",
    "runner_on_unreachable",
    "runner_on_async_failed",
    "runner_on_timeout",
}

failed = next(
    (e for e in reversed(result.events) if e.get("event") in FAILED_EVENTS),
    None,
)

if failed is not None:
    data = failed.get("event_data", {})
    task = data.get("task")              # 失败任务名（ad-hoc 下是模块名）
    res = data.get("res", {})
    message = res.get("msg") or res.get("stderr")
    stderr = res.get("stderr")
```

### 5.3 判断整体成功

```python
ok = result.status == "successful" and result.rc == 0
```

---

## 6. 失败排查

断言失败时把关键信息一次性打出来，避免只看到 `rc` 不知道发生了什么：

```python
FAILED_EVENTS = {
    "runner_on_failed",
    "runner_on_unreachable",
    "runner_on_async_failed",
    "runner_on_timeout",
}


def failure_report(result) -> str:
    cfg = result.config
    failed = next(
        (e for e in reversed(result.events) if e.get("event") in FAILED_EVENTS),
        None,
    )
    data = (failed or {}).get("event_data", {})
    res = data.get("res", {})

    return "\n".join([
        f"device={cfg.host_pattern}",
        f"inventory={cfg.inventory}",
        f"playbook={cfg.playbook} module={cfg.module}",
        f"command={' '.join(cfg.command)}",
        f"artifact={cfg.artifact_dir}",
        f"status={result.status} rc={result.rc}",
        f"failed_task={data.get('task')}",
        f"error={res.get('msg') or res.get('stderr')}",
        f"stderr={res.get('stderr')}",
    ])
```

用法：

```python
assert result.rc == 0 and result.status == "successful", failure_report(result)
```

字段来源：

| 需要信息 | 来源 |
|---|---|
| 目标设备 | `result.config.host_pattern` |
| inventory 路径 | `result.config.inventory` |
| playbook / module | `result.config.playbook` / `result.config.module` |
| 实际命令行 | `result.config.command` |
| artifact 目录 | `result.config.artifact_dir` |
| 失败任务名 | `runner_on_failed` 等事件的 `event_data.task` |
| stderr / failed payload | 同一事件的 `event_data.res` |

### 常见错误定位

| 现象 | 先看哪里 |
|---|---|
| 设备不存在 | Ansible 只打 warning、`rc` 仍可能为 0；用 `device_inventory` 断言（见 §3） |
| playbook 不存在 | Ansible 报错文本；`failed_payload` / artifact 下的 stdout |
| collection 未找到 | 报错含 `couldn't resolve module/action`；检查 `ansible-galaxy collection list` |
| 串口打开失败 | `failed_payload["msg"]` / `failed_payload["stderr"]` |
| 模块参数错误 | `failed_payload["msg"]`；对照模块文档检查 `module_args` |

> `artifact` 目录：`runner_context` 的临时目录在退出时删除，需要保留时显式传
> `private_data_dir`，或在 `with` 块内读取。

---

## 7. 工作目录与清理策略

### 7.1 默认：pytest `tmp_path`

不配置受管目录时，工作目录仍完全由 pytest 控制：

| 需求 | 做法 |
|---|---|
| 每个测试独立目录 | 用例显式传 `private_data_dir=str(tmp_path)` |
| 固定位置排查 | 显式传一个固定目录，如 `private_data_dir=str(tmp_path / "runner")`（目录需先创建） |
| 固定 pytest 临时根目录 | `pytest --basetemp=build/pytest` |
| 保留失败现场 | `tmp_path_retention_policy = failed` |
| 成功后自动清理 | `tmp_path_retention_policy = none` |
| `runner_context` 临时目录 | 未显式传 `private_data_dir` 时，退出 `with` 立即删除 |

`pytest.ini` 示例：

```ini
[pytest]
tmp_path_retention_policy = failed
tmp_path_retention_count = 3
```

- `all`（默认）：保留最近 3 次 session 的所有目录；
- `failed`：只保留失败用例的目录；
- `none`：不保留，全部清理。

> 当前环境（pytest 9.2）已验证这些选项可用；项目声明 `pytest>=7`，
> 旧版本没有该 ini 选项时沿用默认保留策略。

### 7.2 可选：受管运行目录

需要 session 结束后仍保留日志、且让 kw 层与用例共用同一套目录时，配置：

```bash
pytest --device-run-dir=build/runs \
       --device-run-retention=failed --device-verbosity=1
```

或：

```ini
[pytest]
device_run_dir = build/runs
device_run_retention = failed
device_verbosity = 1
```

行为：

- `device_run_root` 是指定根目录；`device_session_dir` 自动追加 `<session-id>`；
- `device_run_dir(label)` 在 session 目录下创建 `<label-slug>-<hash8>/<run_id>/`；
- 默认 `ansible.log` 写在 `<run-root>/<session-id>/ansible.log`（每个 worker 进程一份）；
- 传 `envvars=run.envvars` 时日志改写到 `<run-dir>/ansible.log`，随 run 目录一起清理；
- `run.log_path` / `run.envvars["ANSIBLE_LOG_PATH"]` 指向 per-run 日志（仅在显式传入 `envvars` 时生效）；
- 失败 run 默认保留 artifacts，成功 run 只保留 manifest；
- **session 级日志不参与 `retention` 清理**，由调用方或 CI 负责保留与轮转；
- 显式传 `private_data_dir=` 的调用不受影响，插件不拦截 `ansible_runner.run`。

> 插件不提供 `--device-private-data-dir` 或 `device_private_data_dir` fixture：
> 运行时目录由用例显式持有。受管目录只是可选的“目录来源”，不是全局开关。

## 8. 常见坑

1. **不要把 `Path` 直接传给 `ansible_runner.run(inventory=...)`**
   ansible-runner 会在拼命令时抛 `TypeError`，需要 `str(device_inventory_path)`。
   `private_data_dir` 可以接受 `Path`，但统一用 `str(...)` 更省心。

2. **`module_args` 必须是字符串**
   复杂参数用 `json.dumps({"commands": ["ls -la"]})`。

3. **串口 ad-hoc 要显式 `cmdline="--connection local"`**
   插件不会替你猜连接方式，猜错比显式写一行更难排查。

4. **集合用 `ansible-galaxy install` 安装到 Ansible 默认路径**
   插件不提供 `--device-collections-path`，也不会设置 `ANSIBLE_COLLECTIONS_PATH`。

5. **playbook 目录由用例指定**
   插件没有 `--device-playbook-dir`，用 `project_dir=` 或 playbook 的绝对路径。

6. **运行时目录用 `tmp_path` 或受管目录**
   用例里可传 `private_data_dir=str(tmp_path)`；需要跨 session 保留日志时用 §7.2
   的 `device_run_dir` 工厂。两者都不要在插件外另造全局目录开关。

7. **不要在用例里临时写 inventory 模拟设备**
   设备信息只来自 `--device-inventory`，否则等于维护第二套设备真相。

8. **`runner_context` 退出会删除临时目录**
   需要的事件、结果、artifact 路径都要在 `with` 块内读取完。

9. **用 `-c` 指定配置文件时，rootdir 会变**
   `pytest -c etc/pytest.toml` 的 rootdir 是 `etc/`，`device_inventory` 的相对路径
   以 `etc/` 为基准；写错会出现 `etc/etc/...`。

10. **目录清单的 `group_vars/` 必须放在目录内部**
    `-i .../inventory` 时只认 `.../inventory/group_vars/`，同级的 `group_vars/` 不生效。

11. **受管运行目录的 outcome 要显式**
    在 `with device_run_dir(...)` 里执行完 ansible 后调用 `run.set_outcome(result)`；
    不调用时由 pytest 的用例结果决定，`retention=failed` 下未知结果按失败保留。

12. **`ANSIBLE_LOG_PATH` 由使用方合并**
    `run.envvars` 只提供日志路径；还需要其他环境变量时自行 `{**run.envvars, ...}`。

13. **日志的清理边界**
    默认的 session 级日志写在 `<session-dir>/ansible.log`，插件**从不删除**，由调用方或 CI 负责；
    传 `envvars=run.envvars` 的 per-run 日志位于 run 目录内，会随 `retention` 清理一同删除。
    清理本身延迟到 session 结束（`pytest_unconfigure`）执行，失败只告警、不影响用例结果。

14. **收集 run 不要只扫一个 session 目录**
    xdist 下每个 worker 有自己的 `session-id`，一次 `-n 4` 就是 4 个 session 目录。
    用 `find_run_dirs(<run-root>)` 递归扫 manifest；另外 manifest 里的
    `log_path` / `artifact_dir` 可能已被 `retention` 删掉（成功 run 只留 manifest），
    读文件前先看 `outcome` / `action`。

---

## 9. 兼容性说明

### 0.2.0（日志模型收敛，破坏性）

- 删除 `--device-log-dir` 选项与 `device_log_dir` 配置项；
- 删除 `device_log_env`、`device_log_root` fixture；
- 删除 `run_directory(log_root=...)` / `temporary_run_directory(log_root=...)` 参数；
- 默认日志改为 `<run-root>/<session-id>/ansible.log`，移除 `gwN` 子目录；
- 迁移：需要独立日志目录时，直接在用例里传
  `envvars={"ANSIBLE_LOG_PATH": "<自定义路径>"}`；需要按 run 细分时用
  `envvars=run.envvars`。

### 更早的变更

- fixture 返回值已统一为绝对 `Path`（旧版本是字符串）：
  - `str(device_inventory_path)`、`Path(device_inventory_path)` 都可用；
  - 直接做字符串拼接的代码需要显式 `str(...)`。
- **破坏性变更（PAD-FR-16）**：`--device-private-data-dir` 选项与
  `device_private_data_dir` fixture 已删除。
  - 迁移：用例改用 pytest 的 `tmp_path`，传 `private_data_dir=str(tmp_path)`；
  - 需要固定目录时在用例内显式传 `private_data_dir=...`；
  - 不要再依赖任何全局工作目录开关。
- **行为变更（PAD-FR-19）**：`--device-inventory` 现在接受文件或目录，
  并新增 pytest 配置项 `device_inventory`。
  - **不提供内置默认目录**；未配置、路径不存在、目录为空都会报错（以前是 `skip`）；
  - 只跑非设备用例时不受影响；请求了 inventory fixture 的用例必须先显式配置清单源。
