"""插件命令行选项与 fixture 注册的集成测试。"""


def test_cli_options_are_registered(pytester):
    """``--device-inventory`` / ``--device-private-data-dir`` 应出现在 --help 中。"""
    result = pytester.runpytest_subprocess("--help")
    result.stdout.fnmatch_lines(
        [
            "*--device-inventory*",
            "*--device-private-data-dir*",
        ]
    )


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


def test_fixtures_read_cli_options(pytester, pytester_inventory):
    """fixture 应原样返回命令行传入的清单与工作目录。"""
    private_data_dir = pytester.path / "runner"
    pytester.makepyfile(
        f"""
        def test_option_values(device_inventory_path, device_private_data_dir):
            assert device_inventory_path == {str(pytester_inventory)!r}
            assert device_private_data_dir == {str(private_data_dir)!r}
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-inventory={pytester_inventory}",
        f"--device-private-data-dir={private_data_dir}",
        "-q",
    )

    result.assert_outcomes(passed=1)


def test_private_data_dir_defaults_to_none(pytester):
    """未提供 --device-private-data-dir 时 fixture 返回 None（由调用方决定临时目录）。"""
    pytester.makepyfile(
        """
        def test_default(device_private_data_dir):
            assert device_private_data_dir is None
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


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
