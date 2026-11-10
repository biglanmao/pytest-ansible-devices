"""插件命令行选项、pytest 配置项与 fixture 的集成测试。"""

from pathlib import Path

INVENTORY_CONTENT = """\
[web]
web1 ansible_connection=local

[all:vars]
site=lab
"""


def _write_inventory(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(INVENTORY_CONTENT)
    return path


def test_cli_options_are_registered(pytester):
    """``--device-inventory`` 应出现在 --help 中。"""
    result = pytester.runpytest_subprocess("--help")
    result.stdout.fnmatch_lines(["*--device-inventory*"])


def test_private_data_dir_option_is_removed(pytester):
    """``--device-private-data-dir`` 已取消，不应再出现在 --help 中。"""
    result = pytester.runpytest_subprocess("--help")
    assert "--device-private-data-dir" not in result.stdout.str()


def test_private_data_dir_fixture_is_removed(pytester):
    """``device_private_data_dir`` fixture 已删除，请求它应报 fixture 不存在。"""
    pytester.makepyfile(
        """
        def test_uses_removed_fixture(device_private_data_dir):
            pass
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(errors=1)
    assert "fixture 'device_private_data_dir' not found" in result.stdout.str()


def test_relative_paths_resolve_against_rootdir(tmp_path):
    """相对路径应以 pytest rootdir 为基准，而不是进程 CWD。"""
    from pytest_ansible_devices.fixture import _resolve_path

    rootdir = tmp_path / "project"
    rootdir.mkdir()

    assert _resolve_path("inventory.ini", rootdir) == (
        rootdir / "inventory.ini"
    ).resolve()
    assert _resolve_path("inventory", rootdir) == (rootdir / "inventory").resolve()


def test_default_inventory_dir_is_used(pytester):
    """未提供选项和配置时，使用 <rootdir>/etc/devices/inventory。"""
    inventory_dir = pytester.path / "etc" / "devices" / "inventory"
    _write_inventory(inventory_dir / "hosts.ini")

    pytester.makepyfile(
        f"""
        from pathlib import Path

        def test_default(device_inventory_path, device_inventory):
            assert device_inventory_path == Path({str(inventory_dir.resolve())!r})
            assert device_inventory_path.is_dir()
            assert "web1" in device_inventory.hosts
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


def test_missing_default_inventory_errors(pytester):
    """默认目录不存在时应报错，而不是静默 skip。"""
    expected = (pytester.path / "etc" / "devices" / "inventory").resolve()
    pytester.makepyfile(
        """
        def test_needs_inventory(device_inventory_path):
            assert device_inventory_path
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(errors=1)
    stdout = result.stdout.str()
    assert "清单源不存在" in stdout
    assert "插件默认值" in stdout
    assert str(expected) in stdout


def test_ini_config_is_used(pytester):
    """pytest 配置项 device_inventory 应生效。"""
    inventory = _write_inventory(pytester.path / "config" / "inventory.ini")
    pytester.makeini(
        """
        [pytest]
        device_inventory = config/inventory.ini
        """
    )

    pytester.makepyfile(
        f"""
        from pathlib import Path

        def test_ini(device_inventory_path):
            assert device_inventory_path == Path({str(inventory.resolve())!r})
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


def test_cli_overrides_ini_config(pytester):
    """命令行选项优先于 pytest 配置项。"""
    ini_inventory = _write_inventory(pytester.path / "config" / "ini.ini")
    cli_inventory = _write_inventory(pytester.path / "config" / "cli.ini")
    pytester.makeini(
        """
        [pytest]
        device_inventory = config/ini.ini
        """
    )

    pytester.makepyfile(
        f"""
        from pathlib import Path

        def test_cli_wins(device_inventory_path):
            assert device_inventory_path == Path({str(cli_inventory.resolve())!r})
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-inventory={cli_inventory}", "-q"
    )

    result.assert_outcomes(passed=1)


def test_inventory_path_fixture_returns_absolute_path(pytester, pytester_inventory):
    """``device_inventory_path`` 应返回命令行传入路径的绝对 ``Path``。"""
    pytester.makepyfile(
        f"""
        from pathlib import Path

        def test_option_values(device_inventory_path):
            assert device_inventory_path == Path({str(pytester_inventory)!r})
            assert device_inventory_path.is_absolute()
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-inventory={pytester_inventory}", "-q"
    )

    result.assert_outcomes(passed=1)


def test_directory_inventory_source_is_accepted(pytester):
    """``--device-inventory`` 传目录时应被接受，清单内主机可加载。"""
    inventory_dir = pytester.path / "inventory"
    _write_inventory(inventory_dir / "hosts.ini")
    (inventory_dir / "group_vars").mkdir()
    (inventory_dir / "group_vars" / "all.yml").write_text("site: lab\n")

    pytester.makepyfile(
        """
        def test_directory(device_inventory_path, device_inventory):
            assert device_inventory_path.is_dir()
            assert "web1" in device_inventory.hosts
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-inventory={inventory_dir}", "-q"
    )

    result.assert_outcomes(passed=1)


def test_empty_inventory_dir_reports_error(pytester):
    """清单目录为空时应报错并给出绝对路径。"""
    empty_dir = pytester.path / "empty"
    empty_dir.mkdir()

    pytester.makepyfile(
        """
        def test_needs_inventory(device_inventory_path):
            assert device_inventory_path
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-inventory={empty_dir}", "-q"
    )

    result.assert_outcomes(errors=1)
    stdout = result.stdout.str()
    assert "清单目录为空" in stdout
    assert str(empty_dir.resolve()) in stdout


def test_missing_inventory_file_reports_error(pytester):
    """传了 --device-inventory 但路径不存在时，应报错并给出绝对路径。"""
    missing = pytester.path / "missing.ini"
    pytester.makepyfile(
        """
        def test_needs_inventory(device_inventory_path):
            assert device_inventory_path
        """
    )

    result = pytester.runpytest_subprocess(f"--device-inventory={missing}", "-q")

    result.assert_outcomes(errors=1)
    stdout = result.stdout.str()
    assert "清单源不存在" in stdout
    assert "命令行 --device-inventory" in stdout
    assert str(missing.resolve()) in stdout


def test_device_inventory_loads_hosts_and_group_vars(pytester, pytester_inventory):
    """device_inventory 应加载主机、分组与 all:vars。"""
    pytester.makepyfile(
        """
        def test_inventory(device_inventory):
            assert sorted(device_inventory.hosts) == ["db1", "web1"]
            assert {"web", "db", "all", "ungrouped"} <= set(device_inventory.groups)
            assert device_inventory.groups["web"].get_vars() == {}
            assert device_inventory.groups["all"].get_vars()["site"] == "lab"
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-inventory={pytester_inventory}", "-q"
    )

    result.assert_outcomes(passed=1)


def test_directory_inventory_group_vars_reach_ansible(tmp_path):
    """目录清单的 group_vars 应被执行层加载（fixture 本身不加载）。"""
    import ansible_runner

    inventory_dir = tmp_path / "inventory"
    (inventory_dir / "group_vars").mkdir(parents=True)
    (inventory_dir / "hosts.ini").write_text(
        "[web]\nweb1 ansible_connection=local\n"
    )
    (inventory_dir / "group_vars" / "all.yml").write_text("site: from_group_vars\n")

    private_data_dir = tmp_path / "runner"
    private_data_dir.mkdir()

    result = ansible_runner.run(
        inventory=str(inventory_dir),
        private_data_dir=str(private_data_dir),
        host_pattern="web1",
        module="debug",
        module_args="var=site",
        quiet=True,
        suppress_env_files=True,
    )

    assert result.rc == 0 and result.status == "successful"
    payloads = [
        event["event_data"]["res"]
        for event in result.events
        if event.get("event") == "runner_on_ok"
    ]
    assert payloads[0]["site"] == "from_group_vars"
