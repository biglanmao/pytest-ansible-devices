"""插件命令行选项与 fixture 注册的集成测试。"""


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


def test_inventory_path_fixture_skips_without_option(pytester):
    """未提供 --device-inventory 时，依赖它的用例应跳过而不是报错。"""
    pytester.makepyfile(
        """
        def test_needs_inventory(device_inventory_path):
            assert device_inventory_path
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(skipped=1)


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


def test_relative_paths_resolve_against_rootdir(tmp_path):
    """相对路径应以 pytest rootdir 为基准，而不是进程 CWD。"""
    from pytest_ansible_devices.fixture import _resolve_path

    rootdir = tmp_path / "project"
    rootdir.mkdir()

    assert _resolve_path("inventory.ini", rootdir) == (
        rootdir / "inventory.ini"
    ).resolve()
    assert _resolve_path("playbooks", rootdir) == (rootdir / "playbooks").resolve()


def test_missing_inventory_file_reports_error(pytester):
    """传了 --device-inventory 但文件不存在时，应报错并给出绝对路径。"""
    missing = pytester.path / "missing.ini"
    pytester.makepyfile(
        """
        def test_needs_inventory(device_inventory_path):
            assert device_inventory_path
        """
    )

    result = pytester.runpytest_subprocess(f"--device-inventory={missing}", "-q")

    result.assert_outcomes(errors=1)
    assert str(missing.resolve()) in result.stdout.str()
    assert "--device-inventory 指向的清单文件不存在" in result.stdout.str()


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
