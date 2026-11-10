"""通过 pytest 插件管理器 / fixture 获取 ``runner_context`` 的测试。"""


def test_plugin_exposes_runner_context(pytester):
    """插件对象与 fixture 应暴露同一个 runner_context 实现。"""
    pytester.makepyfile(
        """
        def test_access(pytestconfig, device_runner_context):
            plugin = pytestconfig.pluginmanager.get_plugin("pytest_ansible_devices")
            assert plugin is not None
            assert callable(plugin.runner_context)
            assert device_runner_context is plugin.runner_context

        def test_name(pytestconfig):
            plugin = pytestconfig.pluginmanager.get_plugin("pytest_ansible_devices")
            assert plugin.runner_context.__name__ == "runner_context"
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=2)


def test_disabled_plugin_returns_none(pytester):
    """禁用插件时 get_plugin 返回 None，由调用方自行判空。"""
    pytester.makepyfile(
        """
        def test_disabled(pytestconfig):
            assert pytestconfig.pluginmanager.get_plugin("pytest_ansible_devices") is None
        """
    )

    result = pytester.runpytest_subprocess(
        "-p", "no:pytest_ansible_devices", "-q"
    )

    result.assert_outcomes(passed=1)
