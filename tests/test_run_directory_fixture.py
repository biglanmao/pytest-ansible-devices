"""受管运行目录的 pytest 集成测试（PAD-FR-21 / PAD-FR-22）。"""

import json

import pytest

from pytest_ansible_devices.run_directory import RUN_MARKER, find_run_dirs


def test_new_options_are_registered(pytester):
    result = pytester.runpytest_subprocess("--help")

    result.stdout.fnmatch_lines(
        [
            "*--device-run-dir*",
            "*--device-run-retention*",
            "*--device-verbosity*",
        ]
    )
    # 日志根目录已移除：日志要么在 session 目录，要么通过 envvars 细分到 run 目录。
    assert "--device-log-dir" not in result.stdout.str()


def test_unconfigured_fixtures_are_disabled(pytester):
    pytester.makepyfile(
        """
        import os

        def test_disabled(
            device_run_root,
            device_session_dir,
            device_run_retention,
            device_verbosity,
        ):
            assert device_run_root is None
            assert device_session_dir is None
            assert "ANSIBLE_LOG_PATH" not in os.environ
            assert device_run_retention == "failed"
            assert device_verbosity is None
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


def test_factory_creates_managed_run(pytester, tmp_path):
    run_root = (tmp_path / "managed").resolve()

    pytester.makepyfile(
        f"""
        import os
        from pathlib import Path

        def test_managed(
            device_run_root,
            device_session_dir,
            device_run_dir,
        ):
            assert device_run_root == Path({str(run_root)!r})
            assert device_session_dir.parent == device_run_root
            assert Path(os.environ["ANSIBLE_LOG_PATH"]) == (
                device_session_dir / "ansible.log"
            )

            with device_run_dir("op") as run:
                assert run.path.is_absolute()
                assert run.path.is_relative_to(device_session_dir)
                assert str(run) == str(run.path)
                assert run.envvars["ANSIBLE_LOG_PATH"] == str(
                    run.path / "ansible.log"
                )
                run.artifact_dir.mkdir()
                (run.artifact_dir / "stdout").write_text("x")
                run.set_outcome("passed")

            assert (run.path / ".pad-run.json").is_file()
            assert not run.artifact_dir.exists()
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={run_root}", "-q"
    )

    result.assert_outcomes(passed=1)


def test_failed_test_keeps_artifacts(pytester, tmp_path):
    run_root = tmp_path / "managed"

    pytester.makepyfile(
        """
        def test_fail(device_run_dir):
            with device_run_dir("op") as run:
                run.artifact_dir.mkdir()
                (run.artifact_dir / "stdout").write_text("x")
            assert False, "expected failure"
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={run_root}", "-q"
    )

    result.assert_outcomes(failed=1)
    runs = find_run_dirs(run_root)
    assert len(runs) == 1
    manifest = json.loads(
        (runs[0].path / RUN_MARKER).read_text(encoding="utf-8")
    )
    assert manifest["outcome"] == "failed"
    assert manifest["action"] == "keep"
    assert (runs[0].artifact_dir / "stdout").is_file()


def test_passed_test_cleans_artifacts(pytester, tmp_path):
    run_root = tmp_path / "managed"

    pytester.makepyfile(
        """
        def test_ok(device_run_dir):
            with device_run_dir("op") as run:
                run.artifact_dir.mkdir()
                (run.artifact_dir / "stdout").write_text("x")
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={run_root}", "-q"
    )

    result.assert_outcomes(passed=1)
    runs = find_run_dirs(run_root)
    assert len(runs) == 1
    manifest = json.loads(
        (runs[0].path / RUN_MARKER).read_text(encoding="utf-8")
    )
    assert manifest["outcome"] == "passed"
    assert manifest["action"] == "delete"
    assert not runs[0].artifact_dir.exists()


def test_unconfigured_factory_uses_temporary_directory(pytester):
    pytester.makepyfile(
        """
        def test_fallback(device_run_dir):
            with device_run_dir("op") as run:
                path = run.path
                assert "pad_run_" in str(path)
                run.artifact_dir.mkdir()
                (run.artifact_dir / "stdout").write_text("x")
            assert not path.exists()
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


def test_multiple_runs_in_one_test(pytester, tmp_path):
    run_root = tmp_path / "managed"

    pytester.makepyfile(
        """
        def test_many(device_run_dir):
            with device_run_dir("op-a") as first:
                with device_run_dir("op-b") as second:
                    assert first.path != second.path
                    first.set_outcome("failed")
                    second.set_outcome("failed")
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={run_root}", "-q"
    )

    result.assert_outcomes(passed=1)
    assert len(find_run_dirs(run_root)) == 2


def test_ini_values_are_used(pytester, tmp_path):
    run_root = tmp_path / "managed"
    pytester.makeini(
        f"""
        [pytest]
        device_run_dir = {run_root}
        device_run_retention = all
        device_verbosity = 1
        """
    )

    pytester.makepyfile(
        """
        def test_values(
            device_run_root,
            device_run_retention,
            device_verbosity,
            device_run_dir,
        ):
            assert device_run_root is not None
            assert device_run_retention == "all"
            assert device_verbosity == 1
            with device_run_dir("op") as run:
                assert run.retention == "all"
                assert run.verbosity == 1
                run.set_outcome("passed")
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


def test_cli_overrides_ini_values(pytester, tmp_path):
    run_root = tmp_path / "managed"
    pytester.makeini(
        """
        [pytest]
        device_run_retention = all
        device_verbosity = 1
        """
    )

    pytester.makepyfile(
        """
        def test_values(device_run_retention, device_verbosity):
            assert device_run_retention == "none"
            assert device_verbosity == 2
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={run_root}",
        "--device-run-retention=none",
        "--device-verbosity=2",
        "-q",
    )

    result.assert_outcomes(passed=1)


def test_run_directory_can_be_private_data_dir(
    pytester, pytester_inventory, tmp_path
):
    run_root = tmp_path / "managed"

    pytester.makepyfile(
        f"""
        from pathlib import Path
        import ansible_runner

        def test_runner(device_run_dir):
            with device_run_dir("adhoc", verbosity=2) as run:
                result = ansible_runner.run(
                    private_data_dir=run,
                    inventory={pytester_inventory!r},
                    host_pattern="web1",
                    module="ping",
                    envvars=run.envvars,
                    verbosity=run.verbosity,
                    quiet=True,
                )

                assert result.status == "successful"
                assert Path(result.config.private_data_dir) == run.path
                assert run.artifact_dir in Path(result.config.artifact_dir).parents
                assert result.config.verbosity == 2
                assert "-vv" in result.config.command
                assert run.log_path.is_file()
                run.set_outcome(result)
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={run_root}",
        f"--device-inventory={pytester_inventory}",
        "-q",
    )

    result.assert_outcomes(passed=1)


def test_explicit_private_data_dir_is_not_intercepted(
    pytester, pytester_inventory, tmp_path
):
    run_root = tmp_path / "managed"

    pytester.makepyfile(
        f"""
        from pathlib import Path
        import ansible_runner

        def test_explicit(device_run_dir, tmp_path):
            explicit = tmp_path / "explicit"
            explicit.mkdir()
            result = ansible_runner.run(
                private_data_dir=str(explicit),
                inventory={pytester_inventory!r},
                host_pattern="web1",
                module="ping",
                quiet=True,
            )
            assert result.status == "successful"
            assert Path(result.config.private_data_dir) == explicit
            assert explicit.is_dir()
            assert list(Path({str(run_root)!r}).glob("**/.pad-run.json")) == []
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={run_root}",
        f"--device-inventory={pytester_inventory}",
        "-q",
    )

    result.assert_outcomes(passed=1)


def test_run_root_must_be_directory(pytester, tmp_path):
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x", encoding="utf-8")

    pytester.makepyfile(
        """
        def test_root(device_run_root):
            assert device_run_root is not None
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={not_a_dir}", "-q"
    )

    result.assert_outcomes(errors=1)
    assert "运行目录不是目录" in result.stdout.str()


# ------------------------------------------------------ 全局 ANSIBLE_LOG_PATH
def test_global_log_env_shares_session_id(pytester, tmp_path):
    run_root = tmp_path / "managed"

    pytester.makepyfile(
        """
        import os
        from pathlib import Path

        def test_global_log(device_session_dir):
            log_path = Path(os.environ["ANSIBLE_LOG_PATH"])
            assert log_path.name == "ansible.log"
            assert log_path.parent.is_dir()
            # 全局日志与 private_data_dir 共用同一个 session id。
            assert log_path.parent == device_session_dir
        """
    )

    result = pytester.runpytest_subprocess(f"--device-run-dir={run_root}", "-q")

    result.assert_outcomes(passed=1)


def test_global_log_env_disabled_without_options(pytester):
    pytester.makepyfile(
        """
        import os

        def test_no_global_log():
            assert "ANSIBLE_LOG_PATH" not in os.environ
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=1)


def test_global_log_env_respects_existing_env(pytester, tmp_path, monkeypatch):
    existing = tmp_path / "user-ansible.log"
    monkeypatch.setenv("ANSIBLE_LOG_PATH", str(existing))

    pytester.makepyfile(
        """
        import os

        def test_keep_user_log():
            assert os.environ["ANSIBLE_LOG_PATH"].endswith("user-ansible.log")
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={tmp_path / 'managed'}", "-q"
    )

    result.assert_outcomes(passed=1)


def test_global_log_env_per_xdist_worker(pytester, tmp_path):
    """每个 worker 有独立的 session 目录，全局日志直接落在各自 session 根下。"""
    pytest.importorskip("xdist")
    run_root = tmp_path / "managed"

    pytester.makepyfile(
        """
        import os
        from pathlib import Path

        def check(device_session_dir):
            log_path = Path(os.environ["ANSIBLE_LOG_PATH"])
            # 日志直接位于本 worker 的 session 目录下，不再有 gwN 子目录。
            assert log_path.parent == device_session_dir
            assert log_path.name == "ansible.log"
            assert device_session_dir.parent.name != "gw0"
            assert device_session_dir.parent.name != "gw1"

        def test_worker_log_a(device_session_dir):
            check(device_session_dir)

        def test_worker_log_b(device_session_dir):
            check(device_session_dir)
        """
    )

    result = pytester.runpytest_subprocess(
        f"--device-run-dir={run_root}", "-n", "2", "-q"
    )

    result.assert_outcomes(passed=2)

    # 两个 worker 各自生成 session 目录（session id 含 pid），互不共用。
    session_dirs = sorted(p for p in run_root.iterdir() if p.is_dir())
    assert len(session_dirs) == 2
    assert not list(run_root.glob("*/gw*"))
