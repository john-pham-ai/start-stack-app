"""Truck fetch: script construction, output parsing, and the ssh round trip
(via a fake ssh binary, so no truck is needed)."""

import json

import pytest

import truck
from truck import TruckError, fetch_run_id, main, parse_output, remote_script, setup_ssh

ROOT = "/media/hotswap1/frontier/truck-805/2026/09/15/2026-09-15_14-48-57_truck-805"
OLD = "/media/hotswap1/frontier/truck-805/2026/09/14/2026-09-14_09-00-00_truck-805"


def fake_ssh(tmp_path, lines, exit_code=0):
    """Write a stand-in ssh binary that prints the given tab-separated lines."""
    path = tmp_path / "fake-ssh"
    body = "#!/bin/sh\n"
    for line in lines:
        body += "printf '%s\\n'\n" % line
    if exit_code:
        body += "echo 'ssh: connect refused' >&2\nexit %d\n" % exit_code
    else:
        body += "cat >/dev/null\n"
    path.write_text(body)
    path.chmod(0o755)
    return str(path)


class TestRemoteScript:
    def test_root_filled_and_hostname_derives_vehicle(self):
        script = remote_script("/media/hotswap1/frontier")
        assert "/media/hotswap1/frontier/truck-" in script
        assert "date +%Y/%m/%d" in script
        assert "{ROOT}" not in script  # placeholder fully replaced

    def test_no_request_data_in_script(self):
        # The vehicle comes from the hostname — a caller value never appears.
        assert "{VEHICLE}" not in remote_script("/media/hotswap1/frontier")


class TestParseOutput:
    def test_todays_run(self):
        out = f"HOSTNAME\ttruck-805-primarypc\nTODAY\t{ROOT}\nLATEST\t{ROOT}\n"
        info = parse_output(out, "805")
        assert info["run_id"] == "2026-09-15_14-48-57_truck-805"
        assert info["path"] == ROOT
        assert info["date"] == "2026/09/15"
        assert info["vehicle"] == "805"
        assert info["warning"] == ""

    def test_no_run_today_falls_back_with_warning(self):
        out = f"HOSTNAME\ttruck-805-primarypc\nTODAY\t\nLATEST\t{OLD}\n"
        info = parse_output(out, "")
        assert info["run_id"] == "2026-09-14_09-00-00_truck-805"
        assert info["date"] == "2026/09/14"
        assert "earlier day" in info["warning"]

    def test_requested_vehicle_mismatch_warns(self):
        out = f"HOSTNAME\ttruck-805-primarypc\nTODAY\t{ROOT}\nLATEST\t{ROOT}\n"
        info = parse_output(out, "812")
        assert "not 812" in info["warning"]

    def test_novehicle_is_an_error(self):
        with pytest.raises(TruckError):
            parse_output("HOSTNAME\tlaptop\nNOVEHICLE\n", "")

    def test_no_hostname_is_an_error(self):
        with pytest.raises(TruckError):
            parse_output("TODAY\t/x\n", "")

    def test_non_truck_hostname_is_an_error(self):
        with pytest.raises(TruckError):
            parse_output("HOSTNAME\tbuild-server-1\nTODAY\t/x\n", "")

    def test_no_runs_found_is_an_error(self):
        with pytest.raises(TruckError):
            parse_output("HOSTNAME\ttruck-805-primarypc\nTODAY\t\nLATEST\t\n", "")


class TestFetchRunID:
    def test_success_through_fake_ssh(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRUCK_SSH_BIN", fake_ssh(tmp_path, [
            "HOSTNAME\\ttruck-805-primarypc",
            f"TODAY\\t{ROOT}",
            f"LATEST\\t{ROOT}",
        ]))
        monkeypatch.setenv("TRUCK_SSH_TARGET", "applied@192.168.1.11")
        info = fetch_run_id("805")
        assert info["run_id"] == "2026-09-15_14-48-57_truck-805"
        assert info["path"] == ROOT
        assert info["hostname"] == "truck-805-primarypc"

    def test_vehicle_cross_check_without_argument(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRUCK_SSH_BIN", fake_ssh(tmp_path, [
            "HOSTNAME\\ttruck-805-primarypc",
            f"TODAY\\t{ROOT}",
            f"LATEST\\t{ROOT}",
        ]))
        info = fetch_run_id()
        assert info["vehicle"] == "805"

    def test_non_digit_vehicle_rejected_before_any_ssh(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setenv("TRUCK_SSH_BIN", fake_ssh(tmp_path, []))
        monkeypatch.setattr(truck.subprocess, "run", lambda *a, **k: called.append(1))
        with pytest.raises(TruckError):
            fetch_run_id("805; rm -rf /")
        assert not called

    def test_ssh_failure_255_is_readable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRUCK_SSH_BIN", fake_ssh(tmp_path, [], exit_code=255))
        with pytest.raises(TruckError) as exc:
            fetch_run_id("805")
        assert "could not SSH" in str(exc.value)
        assert "ssh applied@192.168.1.11" in str(exc.value)

    def test_timeout_is_readable(self, tmp_path, monkeypatch):
        sleeping = tmp_path / "slow-ssh"
        sleeping.write_text("#!/bin/sh\nsleep 5\n")
        sleeping.chmod(0o755)
        monkeypatch.setenv("TRUCK_SSH_BIN", str(sleeping))
        with pytest.raises(TruckError) as exc:
            fetch_run_id("805", timeout=1)
        assert "timed out" in str(exc.value)


class TestCLI:
    def test_plain_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("TRUCK_SSH_BIN", fake_ssh(tmp_path, [
            "HOSTNAME\\ttruck-805-primarypc",
            f"TODAY\\t{ROOT}",
            f"LATEST\\t{ROOT}",
        ]))
        assert main([]) == 0
        out = capsys.readouterr().out
        assert "run_id: 2026-09-15_14-48-57_truck-805" in out
        assert "path:   " + ROOT in out

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("TRUCK_SSH_BIN", fake_ssh(tmp_path, [
            "HOSTNAME\\ttruck-805-primarypc",
            f"TODAY\\t{ROOT}",
            f"LATEST\\t{ROOT}",
        ]))
        assert main(["--json"]) == 0
        info = json.loads(capsys.readouterr().out)
        assert info["run_id"] == "2026-09-15_14-48-57_truck-805"

    def test_error_json_goes_to_stdout_with_exit_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("TRUCK_SSH_BIN", fake_ssh(tmp_path, [], exit_code=255))
        assert main(["--json"]) == 1
        assert json.loads(capsys.readouterr().out)["error"]

    def test_error_plain_goes_to_stderr_with_exit_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("TRUCK_SSH_BIN", fake_ssh(tmp_path, [], exit_code=255))
        assert main([]) == 1
        assert "could not SSH" in capsys.readouterr().err

    def test_too_many_arguments(self, capsys):
        assert main(["805", "812"]) == 1
        assert "usage" in capsys.readouterr().err


PUB = "ssh-ed25519 FAKEPUBKEY truck-805"


@pytest.fixture
def setup_env(tmp_path, monkeypatch):
    """A temp ~/.ssh with fake keygen/ssh binaries pointed at by env."""
    monkeypatch.setenv("TRUCK_SSH_DIR", str(tmp_path / "ssh"))
    monkeypatch.setenv("TRUCK_SSH_TARGET", "applied@192.168.1.11")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("TRUCK_KEYGEN_BIN", str(bin_dir / "keygen"))
    (bin_dir / "keygen").write_text(
        '#!/bin/sh\numask 077\necho PRIVATE > "$9"\numask 022\necho %s > "$9.pub"\n' % PUB
    )
    (bin_dir / "keygen").chmod(0o755)
    monkeypatch.setenv("TRUCK_SSH_BIN", str(bin_dir / "ssh"))
    (bin_dir / "ssh").write_text(
        '#!/bin/sh\n[ -n "$FAKE_SSH_LOG" ] && printf \'%s\\n\' "$*" >> "$FAKE_SSH_LOG"\ncat >/dev/null\n'
        "printf 'HOSTNAME\\ttruck-805-primarypc\\n'\n"
        "printf 'TODAY\\t/media/hotswap1/frontier/truck-805/2026/09/15/2026-09-15_14-48-57_truck-805\\n'\n"
        "printf 'LATEST\\t/media/hotswap1/frontier/truck-805/2026/09/15/2026-09-15_14-48-57_truck-805\\n'\n"
        'exit "${FAKE_SSH_EXIT:-0}"\n'
    )
    (bin_dir / "ssh").chmod(0o755)
    return tmp_path / "ssh"


class TestSetupSSH:
    """setup_ssh against a temp ~/.ssh and fake binaries."""

    def read(self, env, *parts):
        return (env.joinpath(*parts)).read_text()

    def test_setup_creates_identity_and_alias(self, setup_env):
        env = setup_env
        res = setup_ssh("805")
        assert res["key_created"] and res["config_added"] and res["key_installed"]
        assert res["alias"] == "truck-805"  # the name is forced to the number
        assert res["public_key"] == PUB
        conf = self.read(env, "config")
        assert "Host truck-805" in conf
        assert "HostName 192.168.1.11" in conf
        assert "IdentityFile" in conf and "truck-805" in conf
        assert "UserKnownHostsFile" in conf and "known_hosts.d/truck-805" in conf
        # Private key is 0600.
        import stat as st
        assert st.S_IMODE((env / "truck-805").stat().st_mode) == 0o600

    def test_setup_is_idempotent(self, setup_env):
        env = setup_env
        first = setup_ssh("805")
        second = setup_ssh("805")
        assert first["key_created"] and not second["key_created"]
        assert first["config_added"] and not second["config_added"]
        assert self.read(env, "config").count("Host truck-805") == 1

    def test_setup_rejects_non_numbers(self, setup_env):
        for bad in ("", "805; rm -rf /", "abc", "truck-805"):
            with pytest.raises(TruckError):
                setup_ssh(bad)

    def test_failed_install_keeps_local_steps_and_gives_next_step(self, setup_env, monkeypatch):
        env = setup_env
        monkeypatch.setenv("FAKE_SSH_EXIT", "255")
        res = setup_ssh("805")
        assert res["key_created"] and res["config_added"]
        assert not res["key_installed"]
        assert "ssh-copy-id" in res["next_step"]
        assert "truck-805.pub" in res["next_step"]

    def test_password_goes_through_askpass(self, setup_env, monkeypatch):
        env = setup_env
        # Attempt 1 fails, attempt 2 (password) succeeds; the password must
        # reach ssh via the environment, never a command line.
        monkeypatch.setenv("FAKE_SSH_EXIT", "255")
        script = (env.parent / "bin" / "ssh").read_text()
        (env.parent / "bin" / "ssh").write_text(
            script.replace('exit "${FAKE_SSH_EXIT:-0}"',
                           '[ -n "$TRUCK_SSH_PASSWORD" ] && env | grep SSH_ASKPASS_REQUIRE >> "$TRUCK_SSH_DIR/../askpass.log" && exit 0\n'
                           'exit "${FAKE_SSH_EXIT:-0}"')
        )
        (env.parent / "bin" / "ssh").chmod(0o755)
        res = setup_ssh("805", password="sekret")
        assert res["key_installed"] and "password" in res["install_detail"]
        assert "SSH_ASKPASS_REQUIRE=force" in (env.parent / "askpass.log").read_text()

    def test_fetch_uses_alias_after_setup(self, setup_env, monkeypatch):
        env = setup_env
        log = env.parent / "sshlog"
        monkeypatch.setenv("FAKE_SSH_LOG", str(log))
        setup_ssh("805")
        info = fetch_run_id("805")
        assert info["run_id"] == "2026-09-15_14-48-57_truck-805"
        # The fetch's own ssh call (the last one) went to the alias, not the
        # raw address — the setup install call before it did, by design.
        last_call = log.read_text().strip().splitlines()[-1]
        assert "truck-805" in last_call
        assert "192.168.1.11" not in last_call

    def test_fetch_without_vehicle_or_alias_uses_raw_target(self, setup_env, monkeypatch):
        env = setup_env
        log = env.parent / "sshlog"
        monkeypatch.setenv("FAKE_SSH_LOG", str(log))
        fetch_run_id()
        assert "192.168.1.11" in log.read_text()


class TestSetupCLI:
    def test_setup_success_plain(self, setup_env, capsys):
        assert main(["setup", "805"]) == 0
        out = capsys.readouterr().out
        assert "truck-805: identity created" in out
        assert "public key installed" in out

    def test_setup_json_success(self, setup_env, capsys):
        assert main(["setup", "805", "--json"]) == 0
        res = json.loads(capsys.readouterr().out)
        assert res["alias"] == "truck-805" and res["key_installed"]

    def test_setup_json_install_failure_exit_1(self, setup_env, monkeypatch, capsys):
        monkeypatch.setenv("FAKE_SSH_EXIT", "255")
        assert main(["setup", "805", "--json"]) == 1
        res = json.loads(capsys.readouterr().out)
        assert not res["key_installed"]
        assert "ssh-copy-id" in res["next_step"]

    def test_setup_usage_without_number(self, capsys):
        assert main(["setup"]) == 1
        assert "usage" in capsys.readouterr().err


class TestInstallDiagnosis:
    def test_classify_install_detail(self):
        from truck import classify_install_detail
        assert "could not reach the truck" in classify_install_detail(
            "ssh: connect to host 192.168.1.11 port 22: Connection timed out")
        assert "could not reach the truck" in classify_install_detail(
            "ssh: connect to host 192.168.1.11 port 22: Connection refused")
        assert "your existing key was not accepted" in classify_install_detail(
            "Permission denied (publickey,password)")

    def test_unreachable_is_not_reported_as_key_rejection(self, setup_env, monkeypatch):
        env = setup_env
        monkeypatch.setenv("FAKE_SSH_EXIT", "255")
        script = (env.parent / "bin" / "ssh").read_text().replace(
            'cat >/dev/null',
            "cat >/dev/null; echo 'ssh: connect to host 192.168.1.11 port 22: Connection timed out' >&2",
        )
        (env.parent / "bin" / "ssh").write_text(script)
        (env.parent / "bin" / "ssh").chmod(0o755)
        res = setup_ssh("805")
        assert not res["key_installed"]
        assert "could not reach the truck" in res["install_detail"]
        assert "key was not accepted" not in res["install_detail"]

    def test_rejected_key_suggests_the_password(self, setup_env, monkeypatch):
        env = setup_env
        monkeypatch.setenv("FAKE_SSH_EXIT", "255")
        script = (env.parent / "bin" / "ssh").read_text().replace(
            'cat >/dev/null',
            "cat >/dev/null; echo 'Permission denied (publickey,password)' >&2",
        )
        (env.parent / "bin" / "ssh").write_text(script)
        (env.parent / "bin" / "ssh").chmod(0o755)
        res = setup_ssh("805")
        assert "your existing key was not accepted" in res["install_detail"]
        assert "give the truck's login password" in res["install_detail"]


class TestSetupCLIEdgeCases:
    def test_non_tty_stdin_does_not_crash(self, setup_env, monkeypatch, capsys):
        # getpass with a closed/non-interactive stdin (or Ctrl-D/Ctrl-C)
        # must skip the retry, not traceback.
        import truck as truck_module
        monkeypatch.setenv("FAKE_SSH_EXIT", "255")

        def eof(prompt=""):
            raise EOFError

        monkeypatch.setattr(truck_module.getpass, "getpass", eof)
        assert main(["setup", "805"]) == 1
        out = capsys.readouterr()
        assert "public key not installed" in out.out
        assert "ssh-copy-id" in out.out  # the manual next step is shown
        assert "Traceback" not in out.out and "Traceback" not in out.err

    def test_ctrl_c_at_password_skips_gracefully(self, setup_env, monkeypatch, capsys):
        import truck as truck_module
        monkeypatch.setenv("FAKE_SSH_EXIT", "255")

        def interrupted(prompt=""):
            raise KeyboardInterrupt

        monkeypatch.setattr(truck_module.getpass, "getpass", interrupted)
        assert main(["setup", "805"]) == 1  # no traceback, the next step is shown
        out = capsys.readouterr()
        assert "ssh-copy-id" in out.out
