import contextlib
import io
import os
import signal
import subprocess

import pytest

import recorder
from recorder import (
    RecordingError,
    ScreenRecording,
    ask_run_id_and_test_case,
    build_filename,
    detect_capture_backend,
    polarion_url,
    sanitize,
    today_folder,
    unique_path,
)
from datetime import datetime


class FakeText:
    """Stand-in for questionary.text: feeds queued answers, captures prompts."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.defaults = []
        self.messages = []

    def __call__(self, message, default=""):
        self.defaults.append(default)
        self.messages.append(message)
        prompt = self

        class Prompt:
            def ask(_):
                return prompt.answers.pop(0) if prompt.answers else None

        return Prompt()


class FakeConfirm:
    """Stand-in for questionary.confirm: feeds queued answers, captures defaults."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.defaults = []
        self.messages = []

    def __call__(self, message, default=False):
        self.defaults.append(default)
        self.messages.append(message)
        prompt = self

        class Prompt:
            def ask(_):
                return prompt.answers.pop(0) if prompt.answers else False

        return Prompt()


class TestSanitize:
    def test_strips_unsafe_characters(self):
        assert sanitize("run/ 123:tc") == "run-123-tc"

    def test_trims_edges(self):
        assert sanitize("--x--") == "x"

    def test_caps_length(self):
        assert len(sanitize("x" * 200)) == 60

    def test_empty_stays_empty(self):
        assert sanitize("") == ""


class TestBuildFilename:
    def test_minimal_is_timestamped(self):
        now = datetime(2026, 9, 14, 15, 30, 5)
        assert build_filename(now) == "2026-09-14_15-30-05.mp4"

    def test_pieces_joined_with_prefixes(self):
        now = datetime(2026, 9, 14, 8, 0, 0)
        name = build_filename(
            now, vehicle_name="truck-807", run_id="42", test_case_id="TC-9"
        )
        assert name == "2026-09-14_08-00-00_truck-807_run-42_tc-TC-9.mp4"

    def test_blank_pieces_left_out(self):
        now = datetime(2026, 9, 14, 8, 0, 0)
        assert build_filename(now, vehicle_name="", run_id="", test_case_id="TC-9") == (
            "2026-09-14_08-00-00_tc-TC-9.mp4"
        )


class TestUniquePath:
    def test_free_path_unchanged(self, tmp_path):
        assert unique_path(str(tmp_path / "a.mp4")) == str(tmp_path / "a.mp4")

    def test_appends_counter(self, tmp_path):
        first = tmp_path / "a.mp4"
        first.write_text("x")
        assert unique_path(str(first)) == str(tmp_path / "a-2.mp4")
        (tmp_path / "a-2.mp4").write_text("x")
        assert unique_path(str(first)) == str(tmp_path / "a-3.mp4")


class TestPolarionUrl:
    def test_none_without_id(self):
        assert polarion_url("") is None
        assert polarion_url("   ") is None

    def test_formats_id_in(self, monkeypatch):
        monkeypatch.setattr(recorder, "POLARION_URL_TEMPLATE", "https://x/polarion/#{id}")
        assert polarion_url("TC-123") == "https://x/polarion/#TC-123"


class TestTodayFolder:
    def test_creates_dated_folder(self, tmp_path):
        folder = today_folder(base=str(tmp_path), now=datetime(2026, 9, 14))
        assert folder == str(tmp_path / "2026-09-14")
        import os

        assert os.path.isdir(folder)

    def test_existing_folder_reused(self, tmp_path):
        today_folder(base=str(tmp_path), now=datetime(2026, 9, 14))
        folder = today_folder(base=str(tmp_path), now=datetime(2026, 9, 14))
        assert folder == str(tmp_path / "2026-09-14")


class TestAskRunIdAndTestCase:
    TRUCK_INFO = {
        "vehicle": "805",
        "run_id": "2026-09-15_14-48-57_truck-805",
        "path": "/media/hotswap1/frontier/truck-805/2026/09/15/2026-09-15_14-48-57_truck-805",
        "date": "2026/09/15",
        "hostname": "truck-805-primarypc",
        "warning": "",
    }

    @pytest.fixture(autouse=True)
    def default_no_pull(self, monkeypatch):
        """Every test in this class starts with the toggle answering No
        (the first-time default); truck tests swap in their own FakeConfirm."""
        monkeypatch.setattr(recorder.questionary, "confirm", FakeConfirm([False]))

    def test_normal_flow(self, monkeypatch):
        fake = FakeText(["run-42", "TC-99"])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        state = {}
        result = ask_run_id_and_test_case("en", state)
        assert result == ("run-42", "TC-99", False)
        assert state["recording"]["skip_polarion"] is False
        assert state["recording"]["last_test_case_id"] == "TC-99"

    def test_skip(self, monkeypatch):
        monkeypatch.setattr(recorder.questionary, "text", FakeText(["run-42", "skip"]))
        state = {}
        assert ask_run_id_and_test_case("en", state) == ("run-42", "", True)
        assert state["recording"]["skip_polarion"] is True

    def test_blank_means_skip(self, monkeypatch):
        monkeypatch.setattr(recorder.questionary, "text", FakeText(["run-42", ""]))
        state = {}
        assert ask_run_id_and_test_case("en", state) == ("run-42", "", True)

    def test_back_re_asks_run_id(self, monkeypatch):
        monkeypatch.setattr(
            recorder.questionary, "text", FakeText(["run-1", "back", "run-2", "TC-5"])
        )
        state = {}
        assert ask_run_id_and_test_case("en", state) == ("run-2", "TC-5", False)

    def test_remembered_defaults(self, monkeypatch):
        state = {"recording": {"skip_polarion": True, "last_test_case_id": "TC-77"}}

        fake = FakeText(["run-9", "TC-1"])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        ask_run_id_and_test_case("ja", state)
        # skip_polarion was remembered, so the test-case prompt defaults to 'skip'.
        assert fake.defaults[1] == "skip"

        fake = FakeText(["run-9", "TC-77"])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        ask_run_id_and_test_case("ja", state)
        # The test case id just entered is now the remembered default.
        assert fake.defaults[1] == "TC-1"

    def test_prompts_go_through_translations(self, monkeypatch):
        fake = FakeText(["run-42", "TC-1"])
        confirm = FakeConfirm([False])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        monkeypatch.setattr(recorder.questionary, "confirm", confirm)
        ask_run_id_and_test_case("ja", {})
        assert confirm.messages[0] == "トラックから最新の run id を取得しますか？"
        assert fake.messages[0] == "run-id を貼り付けてください（任意 — 空欄のまま Enter でスキップ）"
        assert "Polarion のテストケース ID" in fake.messages[1]

    def test_toggle_yes_fetches_and_skips_the_paste(self, monkeypatch, capsys):
        # Yes at the toggle: the fetch runs, prints what it found, and the
        # paste prompt is skipped entirely — straight to the test case.
        fake = FakeText(["TC-9"])
        confirm = FakeConfirm([True])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        monkeypatch.setattr(recorder.questionary, "confirm", confirm)
        monkeypatch.setattr(recorder.truck, "fetch_run_id", lambda vehicle="": dict(self.TRUCK_INFO))
        state = {}
        result = ask_run_id_and_test_case("en", state)
        out = capsys.readouterr().out
        assert "run_id: 2026-09-15_14-48-57_truck-805" in out
        assert "/media/hotswap1/frontier/truck-805/" in out
        # The paste prompt was skipped: only the test-case prompt happened.
        assert len(fake.messages) == 1
        assert "Polarion" in fake.messages[0]
        assert result == ("2026-09-15_14-48-57_truck-805", "TC-9", False)
        # First-ever run defaults the toggle to No; the Yes is remembered.
        assert confirm.defaults[0] is False
        assert state["recording"]["pull_truck_run_id"] is True

    def test_toggle_shows_the_fallback_warning(self, monkeypatch, capsys):
        fake = FakeText(["skip"])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        monkeypatch.setattr(recorder.questionary, "confirm", FakeConfirm([True]))
        monkeypatch.setattr(
            recorder.truck, "fetch_run_id", lambda vehicle="": dict(self.TRUCK_INFO, warning="No runs today.")
        )
        result = ask_run_id_and_test_case("en", {})
        assert "⚠️  No runs today." in capsys.readouterr().out  # shown, not hidden
        assert result == ("2026-09-15_14-48-57_truck-805", "", True)

    def test_toggle_failure_falls_back_to_manual_paste(self, monkeypatch, capsys):
        def boom(vehicle=""):
            raise recorder.truck.TruckError("could not SSH to applied@192.168.1.11")

        fake = FakeText(["manual-42", "TC-2"])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        monkeypatch.setattr(recorder.questionary, "confirm", FakeConfirm([True]))
        monkeypatch.setattr(recorder.truck, "fetch_run_id", boom)
        result = ask_run_id_and_test_case("en", {})
        out = capsys.readouterr().out
        assert "Could not fetch the run id:" in out
        assert "could not SSH" in out
        assert fake.defaults[0] == ""  # the paste prompt came back empty
        assert result == ("manual-42", "TC-2", False)

    def test_toggle_choice_is_remembered_as_the_default(self, monkeypatch):
        # A remembered Yes pre-selects Yes; switching to No is remembered too.
        confirm = FakeConfirm([False])
        monkeypatch.setattr(recorder.questionary, "text", FakeText(["run-42", "TC-1"]))
        monkeypatch.setattr(recorder.questionary, "confirm", confirm)
        state = {"recording": {"pull_truck_run_id": True}}
        ask_run_id_and_test_case("en", state)
        assert confirm.defaults[0] is True  # remembered answer was the default
        assert state["recording"]["pull_truck_run_id"] is False  # and the No was saved

    def test_toggle_ctrl_c_means_no(self, monkeypatch):
        confirm = FakeConfirm([None])
        fake = FakeText(["run-42", "TC-1"])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        monkeypatch.setattr(recorder.questionary, "confirm", confirm)
        state = {}
        result = ask_run_id_and_test_case("en", state)
        assert fake.messages[0] == "Paste the run id (optional — press Enter to leave blank)"
        assert result == ("run-42", "TC-1", False)
        assert state["recording"]["pull_truck_run_id"] is False

    def test_back_after_fetch_re_prompts_as_paste_not_toggle(self, monkeypatch):
        # 'back' at the test-case prompt re-asks the run id with the
        # fetched id as the paste default; the toggle is not asked again.
        fetched = self.TRUCK_INFO["run_id"]
        fake = FakeText(["back", fetched, "skip"])
        confirm = FakeConfirm([True])
        monkeypatch.setattr(recorder.questionary, "text", fake)
        monkeypatch.setattr(recorder.questionary, "confirm", confirm)
        monkeypatch.setattr(recorder.truck, "fetch_run_id", lambda vehicle="": dict(self.TRUCK_INFO))
        result = ask_run_id_and_test_case("en", {})
        assert len(confirm.messages) == 1  # toggle asked exactly once
        # Prompt order: test case, then (after 'back') the paste — whose
        # default is the fetched id.
        assert "Polarion" in fake.messages[0]
        assert fake.messages[1] == "Paste the run id (optional — press Enter to leave blank)"
        assert fake.defaults[1] == fetched
        assert result == (fetched, "", True)


class TestRecordingError:
    def test_is_an_exception(self):
        assert issubclass(RecordingError, Exception)


class TestRunRecordingFlow:
    """The shared ask -> record -> stop -> keep/name flow, with internals mocked."""

    @pytest.fixture
    def flow_setup(self, monkeypatch, tmp_path):
        """Patch every interactive piece of run_recording_flow; returns a
        dict the test can tweak (each key maps to the mocked behavior)."""
        knobs = {
            "deps": (True, None),
            "start": True,
            "keep": True,
            "start_error": None,
        }
        events = []

        class FakeRecording:
            def __init__(self):
                self.discarded = False
                self.finalized_with = None

            def start(self):
                if knobs["start_error"]:
                    raise RecordingError(knobs["start_error"])
                events.append("start")

            def stop(self):
                events.append("stop")

            def discard(self):
                self.discarded = True
                events.append("discard")

            def finalize(self, vehicle_name="", run_id="", test_case_id="", metadata=None):
                self.finalized_with = (vehicle_name, run_id, test_case_id, metadata)
                events.append("finalize")
                return "/tmp/fake.mp4", "/tmp/fake.json"

        fake_recording_holder = {}

        monkeypatch.setattr(recorder, "ensure_recording_deps", lambda: knobs["deps"])
        monkeypatch.setattr(
            recorder, "wait_for_start", lambda prompt: (events.append("ask"), knobs["start"])[1]
        )
        monkeypatch.setattr(recorder, "ScreenRecording", FakeRecording)
        monkeypatch.setattr(recorder, "wait_for_stop", lambda rec, label=None, hint=None: None)
        monkeypatch.setattr(
            recorder, "wait_for_keep_or_discard", lambda prompt: (events.append("keep?"), knobs["keep"])[1]
        )
        monkeypatch.setattr(
            recorder,
            "ask_run_id_and_test_case",
            lambda lang, state, vehicle_name="": (events.append("name"), ("run-1", "TC-1", False))[1],
        )
        monkeypatch.setattr(recorder, "save_state", lambda state: events.append("save"))

        @contextlib.contextmanager
        def fake_keypress():
            events.append("keypress")
            yield

        monkeypatch.setattr(recorder, "keypress_mode", fake_keypress)
        return knobs, events, fake_recording_holder

    def test_happy_path(self, flow_setup):
        knobs, events, _holder = flow_setup
        state = {}
        result = recorder.run_recording_flow("ja", state, vehicle_name="truck-807", metadata={"m": 1})
        assert result == ("/tmp/fake.mp4", "/tmp/fake.json")
        assert events == ["keypress", "ask", "start", "stop", "keep?", "name", "finalize", "save"]
        # State was updated by the (mocked) run-id/test-case prompt step.

    def test_deps_unavailable_returns_none(self, flow_setup, capsys):
        knobs, events, _holder = flow_setup
        knobs["deps"] = (False, "install something")
        assert recorder.run_recording_flow("en", {}) is None
        assert "install something" in capsys.readouterr().out
        assert events == []  # nothing else ran

    def test_skip_at_start_prompt(self, flow_setup):
        knobs, events, _holder = flow_setup
        knobs["start"] = False
        assert recorder.run_recording_flow("en", {}) is None
        assert events == ["keypress", "ask"]

    def test_capture_failure(self, flow_setup, capsys):
        knobs, events, _holder = flow_setup
        knobs["start_error"] = "no capture tool"
        assert recorder.run_recording_flow("en", {}) is None
        assert "no capture tool" in capsys.readouterr().out

    def test_discard(self, flow_setup, capsys):
        knobs, events, _holder = flow_setup
        knobs["keep"] = False
        # A discard is its own sentinel (not None, which means skipped or
        # failed) so the wizard can loop back to its start menu.
        assert recorder.run_recording_flow("en", {}) is recorder.DISCARDED
        assert events == ["keypress", "ask", "start", "stop", "keep?", "discard"]
        out = capsys.readouterr().out
        assert "discarded" in out

    def test_discard_in_japanese(self, flow_setup, capsys):
        knobs, events, _holder = flow_setup
        knobs["keep"] = False
        recorder.run_recording_flow("ja", {})
        assert "破棄しました" in capsys.readouterr().out


# --- capture backend detection -----------------------------------------------

DISPLAY_VARS = ("WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP")


@pytest.fixture(autouse=True)
def clean_display_env(monkeypatch):
    """Start every recorder test from a clean, headless environment."""
    for var in DISPLAY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    """A PATH directory where tests can place fake executables."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir) + ":" + os.environ.get("PATH", ""))
    return bin_dir


@pytest.fixture
def isolated_bin(tmp_path, monkeypatch):
    """A PATH directory that is the ONLY thing on PATH.

    For tests that must not see real tools installed on the host (e.g.
    gpu-screen-recorder when the developer running the tests has it).
    """
    bin_dir = tmp_path / "iso-bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


def put_tool(bin_dir, name):
    exe = bin_dir / name
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    return exe


class TestDetectCaptureBackend:
    def test_macos(self, monkeypatch):
        monkeypatch.setattr(recorder.sys, "platform", "darwin")
        backend, _capture_input, hint = detect_capture_backend()
        assert (backend, hint) == ("avfoundation", None)

    def test_x11_uses_display(self, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":42")
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        backend, capture_input, hint = detect_capture_backend()
        assert (backend, capture_input, hint) == ("x11grab", ":42", None)

    def test_x11_defaults_when_no_display_var(self, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        assert detect_capture_backend()[:2] == ("x11grab", ":0")

    def test_wayland_kde_prefers_gpu_screen_recorder(self, monkeypatch, fake_bin):
        put_tool(fake_bin, "gpu-screen-recorder")
        put_tool(fake_bin, "wf-recorder")  # installed too — must NOT win on KDE
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        assert detect_capture_backend()[0] == "gpu-screen-recorder"

    def test_wayland_kde_falls_back_to_wf_recorder(self, monkeypatch, isolated_bin):
        put_tool(isolated_bin, "wf-recorder")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        assert detect_capture_backend()[0] == "wf-recorder"

    def test_wayland_kde_with_nothing_installed(self, monkeypatch, isolated_bin):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        backend, _input, hint = detect_capture_backend()
        assert backend is None
        assert "gpu-screen-recorder" in hint

    def test_wayland_sway_prefers_wf_recorder(self, monkeypatch, fake_bin):
        put_tool(fake_bin, "gpu-screen-recorder")
        put_tool(fake_bin, "wf-recorder")  # installed too — must win on sway
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "SWAY")
        assert detect_capture_backend()[0] == "wf-recorder"

    def test_wayland_gnome_hint_mentions_gsr(self, monkeypatch, isolated_bin):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
        backend, _input, hint = detect_capture_backend()
        assert backend is None
        assert "gpu-screen-recorder" in hint

    def test_headless(self):
        backend, _input, hint = detect_capture_backend()
        assert backend is None
        assert "No graphical session" in hint

    def test_wayland_env_wins_over_x11(self, monkeypatch, fake_bin):
        # Both WAYLAND_DISPLAY and DISPLAY set (typical Wayland + XWayland):
        # Wayland wins, and x11grab must not be used.
        put_tool(fake_bin, "gpu-screen-recorder")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        assert detect_capture_backend()[0] == "gpu-screen-recorder"


class TestInstallers:
    def test_brew(self, monkeypatch, fake_bin):
        put_tool(fake_bin, "brew")
        label, command = recorder._installer_for("ffmpeg")
        assert (label, command) == ("brew", ["brew", "install", "ffmpeg"])

    def test_apt(self, monkeypatch, fake_bin):
        put_tool(fake_bin, "apt")
        label, command = recorder._installer_for("wf-recorder")
        assert (label, command) == ("apt", ["sudo", "apt-get", "install", "-y", "wf-recorder"])

    def test_pacman(self, monkeypatch, isolated_bin):
        # isolated_bin: on a machine with real apt on PATH, apt would win
        # over the fake pacman (apt is preferred in INSTALLERS).
        put_tool(isolated_bin, "pacman")
        label, command = recorder._installer_for("gpu-screen-recorder")
        assert (label, command) == (
            "pacman",
            ["sudo", "pacman", "-S", "--needed", "--noconfirm", "gpu-screen-recorder"],
        )

    def test_none_without_package_manager(self, monkeypatch, fake_bin):
        # Scrub PATH down to just the empty fake dir so no real package
        # manager can be found.
        monkeypatch.setenv("PATH", str(fake_bin))
        assert recorder._installer_for("ffmpeg") == (None, None)

    def test_try_install_runs_the_installer(self, monkeypatch, isolated_bin):
        put_tool(isolated_bin, "pacman")
        ran = []

        def fake_run(command, check=None):
            ran.append(command)

        monkeypatch.setattr(recorder.subprocess, "run", fake_run)
        ok, hint = recorder._try_install("gpu-screen-recorder")
        assert ok is False  # the fake pacman didn't actually install anything
        assert ran == [["sudo", "pacman", "-S", "--needed", "--noconfirm", "gpu-screen-recorder"]]

    def test_try_install_noop_when_present(self, fake_bin):
        put_tool(fake_bin, "wf-recorder")
        ok, hint = recorder._try_install("wf-recorder")
        assert ok is True


class FakeStdin:
    """stdin pipe that records writes and tolerates being closed."""

    def __init__(self):
        self.written = b""
        self.closed = False

    def write(self, data):
        self.written += data

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeProc:
    """Minimal stand-in for subprocess.Popen results."""

    def __init__(self, alive=True):
        self._alive = alive
        self.returncode = None if alive else 1
        self.stdin = FakeStdin() if alive else None
        self.signals = []
        self.terminated = False
        self.killed = False
        self.was_waited = False

    def poll(self):
        return self.returncode if not self._alive else None

    def wait(self, timeout=None):
        self.was_waited = True
        self._alive = False
        self.returncode = 0
        return 0

    def send_signal(self, sig):
        self.signals.append(sig)

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False


class TestScreenRecordingCapture:
    @pytest.fixture
    def recording(self, tmp_path):
        return ScreenRecording(base=str(tmp_path), now=datetime(2026, 9, 14, 12))

    def test_ffmpeg_command_tail(self, recording):
        cmd = recording._ffmpeg_command(["-f", "x11grab", "-i", ":0"])
        assert cmd[:5] == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        assert cmd[5:7] == ["-f", "x11grab"]
        assert cmd[-1] == recording.temp_path
        for flag in ("-c:v", "libx264", "-movflags", "+faststart", "-pix_fmt", "yuv420p"):
            assert flag in cmd

    def test_x11grab_command(self, recording, monkeypatch):
        captured = {}

        def fake_spawn(cmd, stdin=None):
            captured["cmd"] = cmd
            return FakeProc(), None

        monkeypatch.setattr(recording, "_spawn", fake_spawn)
        proc, mode = recording._start_x11grab(":3.1")
        assert mode == recording.STOP_FFMPEG_STDIN
        cmd = captured["cmd"]
        assert cmd[cmd.index("-f") + 1] == "x11grab"
        assert cmd[cmd.index("-i") + 1] == ":3.1"
        assert "-draw_mouse" in cmd

    def test_avfoundation_retries_without_framerate(self, recording, monkeypatch):
        attempts = []

        def fake_spawn(cmd, stdin=None):
            attempts.append(cmd)
            if len(attempts) == 1:
                return None, "framerate not supported"
            return FakeProc(), None

        monkeypatch.setattr(recording, "_spawn", fake_spawn)
        recording._start_avfoundation("2")
        assert len(attempts) == 2
        assert "-framerate" in attempts[0]
        assert "-framerate" not in attempts[1]
        assert attempts[0][-1].endswith(".mp4")

    def test_tool_commands(self, recording, monkeypatch):
        captured = []

        def fake_spawn(cmd, stdin=None):
            captured.append((cmd, stdin))
            return FakeProc(), None

        monkeypatch.setattr(recording, "_spawn", fake_spawn)
        proc, mode = recording._start_tool("gpu-screen-recorder")
        cmd = captured[0][0]
        # -c is the container, -f the framerate (gsr versions vary), and the
        # portal session token is remembered so the share dialog asks once.
        assert cmd[0] == "gpu-screen-recorder"
        assert cmd[cmd.index("-c") + 1] == "mp4"
        assert cmd[cmd.index("-f") + 1] == "30"
        assert cmd[cmd.index("-w") + 1] == "portal"
        assert cmd[cmd.index("-restore-portal-session") + 1] == "yes"
        assert cmd[cmd.index("-portal-session-token-filepath") + 1] == recording._gsr_portal_token_path()
        assert cmd[-1] == recording.temp_path
        assert mode == recording.STOP_SIGINT
        assert captured[0][1] == subprocess.DEVNULL

        proc, mode = recording._start_tool("wf-recorder")
        assert captured[1][0] == ["wf-recorder", "-f", recording.temp_path]
        assert mode == recording.STOP_SIGINT

    def test_spawn_reports_immediate_death(self, recording, monkeypatch):
        def fake_popen(cmd, **kwargs):
            return FakeProc(alive=False)

        monkeypatch.setattr(recorder.subprocess, "Popen", fake_popen)
        # The real FakeProc has no stderr; give it one.
        class DeadProc(FakeProc):
            def __init__(self):
                super().__init__(alive=False)
                self.stderr = io.BytesIO(b"nope")

        monkeypatch.setattr(recorder.subprocess, "Popen", lambda cmd, **kw: DeadProc())
        proc, error = recording._spawn(["whatever"])
        assert proc is None
        assert error == "nope"

    def test_start_raises_when_no_backend(self, recording, monkeypatch):
        monkeypatch.setattr(recorder, "detect_capture_backend", lambda: (None, None, "no session"))
        with pytest.raises(RecordingError, match="no session"):
            recording.start()

    def test_start_x11grab_needs_ffmpeg(self, recording, monkeypatch):
        monkeypatch.setattr(recorder, "detect_capture_backend", lambda: ("x11grab", ":0", None))
        monkeypatch.setattr(recorder, "ffmpeg_available", lambda: False)
        with pytest.raises(RecordingError, match="ffmpeg"):
            recording.start()

    def test_stop_sends_q_to_ffmpeg(self, recording):
        recording.proc = FakeProc()
        recording._stop_mode = recording.STOP_FFMPEG_STDIN
        recording._started_at = 100.0
        recording.stop()
        assert recording.proc.stdin.written == b"q"
        assert recording.proc.stdin.closed
        assert recording.proc.was_waited

    def test_stop_sends_sigint_to_tools(self, recording):
        recording.proc = FakeProc()
        recording._stop_mode = recording.STOP_SIGINT
        recording.stop()
        assert recording.proc.signals == [signal.SIGINT]
        assert recording.proc.was_waited

    def test_stop_on_already_dead_process(self, recording):
        recording.proc = FakeProc(alive=False)
        recording._stop_mode = recording.STOP_SIGINT
        recording._started_at = 10.0
        duration = recording.stop()
        assert recording.proc.signals == []
        assert duration is not None


class TestEnsureRecordingDeps:
    def test_x11_installs_ffmpeg_if_missing(self, monkeypatch, fake_bin):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(recorder, "_try_install", lambda pkg: (pkg == "ffmpeg", None))
        ok, hint = recorder.ensure_recording_deps()
        assert ok is True

    def test_x11_ffmpeg_install_failure(self, monkeypatch, fake_bin):
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(recorder, "_try_install", lambda pkg: (False, "install ffmpeg yourself"))
        ok, hint = recorder.ensure_recording_deps()
        assert ok is False
        assert "ffmpeg" in hint

    def test_wayland_auto_installs_preferred_tool(self, monkeypatch, fake_bin):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        monkeypatch.setattr(
            recorder,
            "_try_install",
            lambda pkg: (True, None) if pkg == "gpu-screen-recorder" else (False, "nope"),
        )
        ok, hint = recorder.ensure_recording_deps()
        assert ok is True

    def test_headless_fails(self):
        ok, hint = recorder.ensure_recording_deps()
        assert ok is False
        assert hint

    def test_backend_present_needs_nothing(self, monkeypatch, fake_bin):
        put_tool(fake_bin, "gpu-screen-recorder")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        monkeypatch.setattr(recorder, "_try_install", lambda pkg: pytest.fail("should not install"))
        ok, _hint = recorder.ensure_recording_deps()
        assert ok is True


class TestVehicleRidesAlong:
    """The recording flow's vehicle name reaches the fetch, so a configured
    per-truck SSH alias is used when one exists."""

    def test_vehicle_name_passed_to_fetch(self, monkeypatch):
        seen = []

        monkeypatch.setattr(
            recorder.questionary, "confirm",
            lambda message, default=False: type("P", (), {"ask": lambda s: True})(),
        )
        monkeypatch.setattr(
            recorder.questionary, "text",
            lambda message, default="": type("P", (), {"ask": lambda s: "skip"})(),
        )
        monkeypatch.setattr(
            recorder, "fetch_truck_run_id",
            lambda lang, vehicle_name="": seen.append(vehicle_name) or "run-x",
        )
        run_id, _tc, _skipped = ask_run_id_and_test_case("en", {}, "truck-805")
        assert seen == ["truck-805"]
        assert run_id == "run-x"
