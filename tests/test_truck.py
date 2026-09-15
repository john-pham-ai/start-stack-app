"""Truck fetch: script construction, output parsing, and the ssh round trip
(via a fake ssh binary, so no truck is needed)."""

import json

import pytest

import truck
from truck import TruckError, fetch_run_id, main, parse_output, remote_script

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
