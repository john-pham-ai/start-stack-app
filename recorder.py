"""Screen recording for start_stack runs.

Recordings go into a folder named for today's date under RECORDINGS_DIR. While
recording, the file has a temporary name; once the run is over it's renamed to
carry the run id and the Polarion test case it covers, and a sidecar .json is
written next to it with the Polarion link and the command that was built.

Capture backends, picked automatically per machine:

- macOS            ffmpeg's avfoundation (needs Screen Recording permission for
                   your terminal in System Settings > Privacy & Security)
- Linux, X11       ffmpeg's x11grab
- Linux, Wayland    gpu-screen-recorder (KDE/GNOME desktops) or wf-recorder
                   (wlroots compositors such as Sway/Hyprland)

Missing tools are auto-installed when a supported package manager (brew, apt,
dnf, pacman) is available; otherwise the error explains what to install.
"""

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.parse
from datetime import datetime

import questionary

import truck

from state import load_state, save_state
from translations import t

# Where dated recording folders are created. Override with the env var.
RECORDINGS_DIR = os.path.expanduser(os.environ.get("RECORDINGS_DIR", "~/screen_recordings"))

# Polarion work item link. {id} is replaced with the test case id you enter.
# Edit this line (or set the POLARION_URL_TEMPLATE env var) to point at your
# actual Polarion server — this placeholder won't resolve to anything real.
POLARION_URL_TEMPLATE = os.environ.get(
    "POLARION_URL_TEMPLATE",
    "https://polarion.example.com/polarion/#/workitem?id={id}",
)

IN_PROGRESS_NAME = ".recording-in-progress"
MAX_PART_LEN = 60

# Returned by run_recording_flow when the user discarded the recording —
# distinct from None (skipped/failed) so the wizard can send a discard back
# to its start menu without treating a skip the same way.
DISCARDED = object()

# Package managers we can auto-install with, in the order we prefer them.
INSTALLERS = [
    ("brew", ["brew", "install", "{pkg}"]),
    ("apt", ["sudo", "apt-get", "install", "-y", "{pkg}"]),
    ("dnf", ["sudo", "dnf", "install", "-y", "{pkg}"]),
    ("pacman", ["sudo", "pacman", "-S", "--needed", "--noconfirm", "{pkg}"]),
]

# Compositors whose screenshare protocol (zwlr_screencopy) wf-recorder needs.
WLROOTS_DESKTOPS = ("SWAY", "HYPRLAND", "RIVER", "LABWC", "WAYFIRE", "NIRI", "WESTON")


class RecordingError(Exception):
    """The capture tool could not be started, or died before we could stop it."""


# --- capture backend detection -----------------------------------------------


def _desktop():
    return os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def _is_wayland():
    return bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "wayland"


def _is_x11():
    return not _is_wayland() and (
        bool(os.environ.get("DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "x11"
    )


def _preferred_wayland_tools():
    """Capture tools for this Wayland session, in the order we'd rather use them.

    wf-recorder only understands wlroots compositors; KDE/GNOME Wayland need
    gpu-screen-recorder (which talks to the xdg-desktop-portal instead).
    """
    desktop = _desktop()
    if any(name in desktop for name in WLROOTS_DESKTOPS):
        return "wf-recorder", "gpu-screen-recorder"
    return "gpu-screen-recorder", "wf-recorder"


def detect_capture_backend():
    """Return (backend, capture_input, install_hint) for this machine.

    backend is one of "avfoundation", "x11grab", "gpu-screen-recorder",
    "wf-recorder" — or None, with install_hint explaining what's missing.
    """
    if sys.platform == "darwin":
        return "avfoundation", None, None

    if _is_wayland():
        for tool in _preferred_wayland_tools():
            if shutil.which(tool):
                return tool, None, None
        preferred = _preferred_wayland_tools()[0]
        _label, command = _installer_for(preferred)
        how = "'{}'".format(" ".join(command)) if command else f"'{preferred}'"
        return (
            None,
            None,
            f"Wayland screen capture needs '{preferred}'. Install it (e.g. {how}) and try again.",
        )

    if _is_x11():
        return "x11grab", os.environ.get("DISPLAY") or ":0", None

    return None, None, "No graphical session found (neither Wayland nor X11) — can't record the screen."


# --- dependency management ----------------------------------------------------


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def _installer_for(pkg):
    """Pick a package-manager install command for pkg, based on what's on PATH."""
    for pm, template in INSTALLERS:
        if shutil.which(pm):
            return pm, [part.format(pkg=pkg) for part in template]
    return None, None


def _try_install(pkg):
    """Install pkg with whatever package manager is around. Returns (ok, hint)."""
    if shutil.which(pkg):
        return True, None
    label, command = _installer_for(pkg)
    if command is None:
        return False, f"'{pkg}' is not installed and no supported package manager was found."
    print(f"{pkg} not found — installing it with {label} (this may take a minute)...")
    try:
        subprocess.run(command, check=True)
    except (subprocess.CalledProcessError, OSError):
        return False, f"Could not install '{pkg}' automatically — install it yourself and try again."
    if not shutil.which(pkg):
        return False, f"'{pkg}' was installed but still isn't on PATH — open a new terminal and try again."
    return True, None


def ensure_ffmpeg():
    """Make sure ffmpeg is on PATH, installing it if it's missing.

    Returns True if ffmpeg is available (already, or after installing it),
    False if it's still missing and needs to be installed by hand.
    """
    ok, _hint = _try_install("ffmpeg")
    return ok


def ensure_recording_deps():
    """Make sure this machine has what it needs to record the screen.

    Returns (ok, hint): ok is True when a capture backend is ready to go;
    otherwise hint explains what to install.
    """
    backend, _capture_input, hint = detect_capture_backend()
    if backend is None:
        # On Wayland the missing piece is the capture tool — try to install it.
        if _is_wayland():
            preferred = _preferred_wayland_tools()[0]
            ok, hint = _try_install(preferred)
            if ok:
                return True, None
        return False, hint

    if backend in ("avfoundation", "x11grab"):
        if not ensure_ffmpeg():
            _label, command = _installer_for("ffmpeg")
            how = "'{}'".format(" ".join(command)) if command else "e.g. 'brew install ffmpeg'"
            return False, f"ffmpeg could not be installed automatically — install it yourself ({how}) and try again."
    return True, None


# --- capture -----------------------------------------------------------------


def find_screen_device():
    """Return the avfoundation device index of the screen, e.g. "2".

    The index shifts depending on how many cameras are attached, so it's
    looked up by name rather than hardcoded.
    """
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
    )
    # Device listing goes to stderr, and ffmpeg exits non-zero after printing it.
    for line in proc.stderr.splitlines():
        match = re.search(r"\[(\d+)\]\s+Capture screen", line)
        if match:
            return match.group(1)
    return None


def today_folder(base=None, now=None):
    """Create (if needed) and return today's dated folder, e.g. .../2026-07-25."""
    base = base if base is not None else RECORDINGS_DIR
    now = now or datetime.now()
    folder = os.path.join(base, now.strftime("%Y-%m-%d"))
    os.makedirs(folder, exist_ok=True)
    return folder


def sanitize(part):
    """Make a pasted run id or test case id safe to put in a filename."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (part or "").strip()).strip("-_.")
    return cleaned[:MAX_PART_LEN]


def build_filename(now, vehicle_name="", run_id="", test_case_id="", ext=".mp4"):
    """Assemble <date>_<time>[_vehicle][_run-<id>][_tc-<id>].<ext>.

    Empty pieces are left out entirely, so a recording with nothing filled in
    still gets a unique timestamped name.
    """
    parts = [now.strftime("%Y-%m-%d_%H-%M-%S")]
    for prefix, value in (("", vehicle_name), ("run-", run_id), ("tc-", test_case_id)):
        clean = sanitize(value)
        if clean:
            parts.append(prefix + clean)
    return "_".join(parts) + ext


def unique_path(path):
    """Add -2, -3, ... if something is already sitting at this path."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{root}-{n}{ext}"):
        n += 1
    return f"{root}-{n}{ext}"


def polarion_url(test_case_id):
    """Build the Polarion work item link, or None if there's no test case id."""
    clean = (test_case_id or "").strip()
    if not clean:
        return None
    return POLARION_URL_TEMPLATE.format(id=clean)


class ScreenRecording:
    """One screen recording: start() -> stop() -> finalize()."""

    # How stop() asks the capture process to finish:
    STOP_FFMPEG_STDIN = "ffmpeg-stdin"  # send 'q' on stdin
    STOP_SIGINT = "sigint"  # send SIGINT

    def __init__(self, base=None, now=None):
        self.now = now or datetime.now()
        self.folder = today_folder(base, self.now)
        self.temp_path = unique_path(os.path.join(self.folder, IN_PROGRESS_NAME + ".mp4"))
        self.proc = None
        self.duration_seconds = None
        self._started_at = None
        self._stop_mode = None

    def _ffmpeg_command(self, capture_args):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        cmd += capture_args
        # Shared output settings: fast to encode, playable everywhere, and
        # +faststart writes the index at the front so the file is fine even
        # if the copy gets interrupted.
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            self.temp_path,
        ]
        return cmd

    def _spawn(self, cmd, stdin=subprocess.PIPE):
        proc = subprocess.Popen(
            cmd,
            stdin=stdin,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # If the capture settings are rejected, the process exits almost
        # immediately.
        time.sleep(1.5)
        if proc.poll() is not None:
            return None, (proc.stderr.read() or b"").decode(errors="replace").strip()
        return proc, None

    def _start_avfoundation(self, device):
        # Not every machine accepts an explicit framerate for screen capture,
        # so fall back to letting the device pick its own.
        error = None
        for extra in (["-framerate", "30"], []):
            cmd = self._ffmpeg_command(
                ["-f", "avfoundation", "-capture_cursor", "1"] + extra + ["-i", f"{device}:none"]
            )
            proc, error = self._spawn(cmd)
            if proc is not None:
                return proc, self.STOP_FFMPEG_STDIN
        raise RecordingError(error or "ffmpeg exited immediately after starting.")

    def _start_x11grab(self, display):
        cmd = self._ffmpeg_command(["-f", "x11grab", "-framerate", "30", "-draw_mouse", "1", "-i", display])
        proc, error = self._spawn(cmd)
        if proc is None:
            raise RecordingError(error or "ffmpeg exited immediately after starting.")
        return proc, self.STOP_FFMPEG_STDIN

    def _gsr_portal_token_path(self):
        # One token per recordings root: the screen-share approval dialog
        # appears on the first recording only, then gsr restores the session
        # from this file on its own.
        return os.path.join(os.path.dirname(self.folder), ".gsr-portal-session")

    def _start_tool(self, backend):
        if backend == "gpu-screen-recorder":
            cmd = [
                "gpu-screen-recorder",
                "-w", "portal",
                "-restore-portal-session", "yes",
                "-portal-session-token-filepath", self._gsr_portal_token_path(),
                "-c", "mp4",  # container (this gsr version's -f is framerate)
                "-f", "30",
                "-o", self.temp_path,
            ]
        else:  # wf-recorder
            cmd = ["wf-recorder", "-f", self.temp_path]
        proc, error = self._spawn(cmd, stdin=subprocess.DEVNULL)
        if proc is None:
            raise RecordingError(error or f"{backend} exited immediately after starting.")
        return proc, self.STOP_SIGINT

    def start(self):
        """Start capturing. Returns the temporary file being written."""
        backend, capture_input, hint = detect_capture_backend()
        if backend is None:
            raise RecordingError(hint or "No screen capture backend available on this system.")

        # Start the clock before the ~1.5s spawn check: the capture process
        # is already recording by the time we're sure it started, and the
        # file always ends up slightly longer than the on-screen timer.
        self._started_at = time.monotonic()

        if backend == "avfoundation":
            if not ffmpeg_available():
                raise RecordingError("ffmpeg is not installed or not on PATH (try: brew install ffmpeg).")
            device = find_screen_device()
            if device is None:
                raise RecordingError(
                    "Could not find a screen capture device in ffmpeg's avfoundation list."
                )
            self.proc, self._stop_mode = self._start_avfoundation(device)
        elif backend == "x11grab":
            if not ffmpeg_available():
                raise RecordingError(
                    "ffmpeg is not installed or not on PATH "
                    "(try: sudo apt-get install ffmpeg / sudo pacman -S ffmpeg)."
                )
            self.proc, self._stop_mode = self._start_x11grab(capture_input)
        else:
            self.proc, self._stop_mode = self._start_tool(backend)

        return self.temp_path

    def elapsed_seconds(self):
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def stop(self):
        """Ask the capture process to finish writing, so the .mp4 ends up playable."""
        if self.proc is None:
            return None
        if self._started_at is not None:
            self.duration_seconds = round(time.monotonic() - self._started_at, 1)

        if self.proc.poll() is None:
            if self._stop_mode == self.STOP_FFMPEG_STDIN:
                try:
                    self.proc.stdin.write(b"q")
                    self.proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            else:
                try:
                    self.proc.send_signal(signal.SIGINT)
                except (ProcessLookupError, OSError):
                    pass
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()

        if self._stop_mode == self.STOP_FFMPEG_STDIN:
            try:
                self.proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        return self.duration_seconds

    def discard(self):
        """Delete the temporary recording instead of keeping it."""
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def finalize(self, vehicle_name="", run_id="", test_case_id="", metadata=None):
        """Rename the finished recording and write its sidecar .json.

        Returns (video_path, sidecar_path).
        """
        filename = build_filename(
            self.now, vehicle_name=vehicle_name, run_id=run_id, test_case_id=test_case_id
        )
        video_path = unique_path(os.path.join(self.folder, filename))
        os.rename(self.temp_path, video_path)

        record = {
            "recorded_at": self.now.isoformat(timespec="seconds"),
            "duration_seconds": self.duration_seconds,
            "video_file": os.path.basename(video_path),
            "run_id": (run_id or "").strip(),
            "polarion_test_case_id": (test_case_id or "").strip(),
            "polarion_url": polarion_url(test_case_id),
        }
        record.update(metadata or {})

        sidecar_path = os.path.splitext(video_path)[0] + ".json"
        with open(sidecar_path, "w") as f:
            json.dump(record, f, indent=2)
            f.write("\n")
        return video_path, sidecar_path


# --- interactive plumbing ----------------------------------------------------


@contextlib.contextmanager
def keypress_mode():
    """Put the terminal into cbreak + no-echo mode for single-key prompts.

    Wrap the *whole* start -> stop -> keep/discard sequence in one `with`
    block rather than switching modes around each individual keystroke —
    toggling per-keystroke leaves a window where the terminal is briefly
    back in canonical mode, and a key landing in that window gets stuck in
    the line-discipline buffer waiting for a newline that never comes.
    """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        no_echo = termios.tcgetattr(fd)
        no_echo[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, no_echo)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _read_key():
    """Block for a single keypress from stdin (call within `keypress_mode()`)."""
    return sys.stdin.read(1)


def wait_for_key(prompt, keys):
    """Print `prompt`, then block until one of `keys` is pressed; return it, lowercased."""
    print(prompt, end="", flush=True)
    while True:
        key = _read_key().lower()
        if key in keys:
            print()
            return key


def wait_for_start(prompt="Record the screen for this run? Press 'r' to start, or 'q' to skip: "):
    """Block until 'r' (start) or 'q' (skip) is pressed. Returns True for 'r'."""
    return wait_for_key(prompt, keys=("r", "q")) == "r"


def wait_for_keep_or_discard(prompt="Keep this recording, or discard it? (k = keep, d = discard): "):
    """Block until 'k' (keep) or 'd' (discard) is pressed. Returns True for 'k'."""
    return wait_for_key(prompt, keys=("k", "d")) == "k"


def wait_for_stop(recording, label="Recording", hint="press 's' to stop"):
    """Show a live "recording" line with an elapsed timer until 's' is pressed.

    A background thread redraws the line every second; the main thread blocks
    reading keypresses and ignores anything but 's'. Ctrl+C still propagates
    normally (cbreak mode leaves signal generation on).
    """
    stop_event = threading.Event()

    def tick():
        while not stop_event.is_set():
            minutes, seconds = divmod(int(recording.elapsed_seconds()), 60)
            print(f"\r● {label}... {minutes:02d}:{seconds:02d} ({hint})", end="", flush=True)
            stop_event.wait(1)

    ticker = threading.Thread(target=tick, daemon=True)
    ticker.start()
    try:
        while _read_key().lower() != "s":
            pass
    finally:
        stop_event.set()
        ticker.join(timeout=2)
        print()


def hyperlink(path, label=None):
    """Wrap a filesystem path in an OSC 8 terminal hyperlink to file://<path>.

    Terminals that support it (iTerm2, VS Code, kitty, wezterm, recent
    Terminal.app) render `label` as clickable and open the folder in Finder;
    terminals that don't just show the label as plain text.
    """
    abs_path = os.path.abspath(path)
    uri = "file://" + urllib.parse.quote(abs_path)
    text = label if label is not None else abs_path
    return f"\x1b]8;;{uri}\x1b\\{text}\x1b]8;;\x1b\\"


def run_recording_flow(lang, state, vehicle_name="", metadata=None):
    """One full recording session: ask, record, stop, keep/name/finalize.

    This is the recording half of the wizard (launch.py) and the entirety
    of the standalone `recorder` entry point — one flow, so they stay
    identical. Prompts use the given language.

    Returns (video_path, sidecar_path) when a recording was kept and
    finalized; DISCARDED when it was discarded; None when recording was
    skipped or failed.
    """
    ready, hint = ensure_recording_deps()
    if not ready:
        print(t(lang, "record_setup_failed") + " " + (hint or "") + "\n")
        return None

    with keypress_mode():
        if not wait_for_start(t(lang, "record_prompt")):
            return None

        try:
            recording = ScreenRecording()
            recording.start()
        except RecordingError as exc:
            print(t(lang, "record_failed") + " " + str(exc) + "\n")
            return None

        print(t(lang, "record_started") + "\n")
        try:
            wait_for_stop(recording, label=t(lang, "recording_label"), hint=t(lang, "press_s_to_stop"))
        finally:
            recording.stop()

        if not wait_for_keep_or_discard(t(lang, "keep_or_discard_prompt")):
            recording.discard()
            print(t(lang, "recording_discarded") + "\n")
            return DISCARDED

    run_id, test_case_id, _skipped = ask_run_id_and_test_case(lang, state, vehicle_name)
    video_path, sidecar_path = recording.finalize(
        vehicle_name=vehicle_name, run_id=run_id, test_case_id=test_case_id, metadata=metadata
    )
    save_state(state)

    print(t(lang, "recording_saved") + " " + video_path)
    print(sidecar_path)
    print(hyperlink(os.path.dirname(video_path), label=t(lang, "open_folder")) + "\n")
    url = polarion_url(test_case_id)
    if url:
        print(t(lang, "polarion_link") + " " + url + "\n")
    return video_path, sidecar_path


def start_drive_recording(lang):
    """The recording half a closed-loop drive opens with: ask, then start.

    Unlike run_recording_flow, this does not block waiting for a stop
    key — the drive's own stop-to-stop prompts run in the meantime and
    the recording spans the whole run. Returns the live ScreenRecording,
    or None when the tester skipped (q) or the capture couldn't start
    (the reason is printed; the drive goes on unrecorded).
    """
    ready, hint = ensure_recording_deps()
    if not ready:
        print(t(lang, "record_setup_failed") + " " + (hint or "") + "\n")
        return None
    with keypress_mode():
        if not wait_for_start(t(lang, "loop_record_prompt")):
            return None
    try:
        recording = ScreenRecording()
        recording.start()
    except RecordingError as exc:
        print(t(lang, "record_failed") + " " + str(exc) + "\n")
        return None
    print(t(lang, "loop_recording_running") + "\n")
    return recording


def finish_drive_recording(lang, state, recording, vehicle_name="", metadata=None):
    """Close out a drive-long recording: stop, keep/discard, name, save.

    Stops the capture (the run just ended), asks keep or discard, and on
    keep runs the same run-id-and-test-case step every recording gets —
    the "pull the latest run id from the truck?" toggle included, so the
    drive's run id is one Yes away. Returns (video_path, sidecar_path),
    DISCARDED, or None when there was nothing to finish.
    """
    if recording is None:
        return None
    recording.stop()
    print("\n" + t(lang, "loop_recording_stopped").format(seconds=recording.duration_seconds) + "\n")
    with keypress_mode():
        if not wait_for_keep_or_discard(t(lang, "keep_or_discard_prompt")):
            recording.discard()
            print(t(lang, "recording_discarded") + "\n")
            return DISCARDED

    run_id, test_case_id, _skipped = ask_run_id_and_test_case(lang, state, vehicle_name)
    video_path, sidecar_path = recording.finalize(
        vehicle_name=vehicle_name, run_id=run_id, test_case_id=test_case_id, metadata=metadata
    )
    save_state(state)

    print(t(lang, "recording_saved") + " " + video_path)
    print(sidecar_path)
    print(hyperlink(os.path.dirname(video_path), label=t(lang, "open_folder")) + "\n")
    url = polarion_url(test_case_id)
    if url:
        print(t(lang, "polarion_link") + " " + url + "\n")
    return video_path, sidecar_path


def fetch_truck_run_id(lang, vehicle_name=""):
    """Fetch the latest run id from the cabled truck (truck.py).

    vehicle_name rides along so a configured per-truck alias (set up via
    `truck setup`) is used when one exists. Prints what was fetched so the
    tester can sanity-check it before accepting; on failure prints the
    readable error instead. Returns the run id, or "" so the prompt comes
    back empty for a manual paste.
    """
    number = (vehicle_name or "").strip()
    if number.startswith("truck-"):
        number = number[len("truck-"):]
    try:
        info = truck.fetch_run_id(number)
    except truck.TruckError as err:
        print(t(lang, "truck_error_prefix") + " " + str(err) + "\n")
        return ""

    date = info.get("date", "")
    header = " · ".join(part for part in (info["vehicle"], info["hostname"], date) if part)
    print(header)
    print("run_id: " + info["run_id"])
    print("path:   " + info["path"])
    if info.get("warning"):
        print("⚠️  " + info["warning"])
    print("")
    return info["run_id"]


def ask_run_id_and_test_case(lang, state, vehicle_name=""):
    """Ask the pull-or-paste toggle, the run id, then the test case id.

    vehicle_name (e.g. "truck-805") is passed to the fetch so a configured
    per-truck SSH alias is used when one exists. First a Yes/No toggle:
    pull the latest run id off the cabled truck? The answer is remembered
    in state and pre-selected next time. Yes fetches and prints it
    (vehicle, hostname, run id, full log path, any warning), then goes
    straight to the test case prompt; a failed fetch falls back to the
    paste prompt. No gives the paste prompt directly (optional — leave it
    blank to skip). 'back' at the test case prompt re-asks the run id as a
    paste with the current value as the default — the toggle isn't asked
    again within the same flow. The skip choice for the test case is
    remembered too, as is the last test case id used.

    Returns (run_id, test_case_id, skipped_polarion).
    """
    recording_state = state.setdefault("recording", {})
    toggle_done = False
    run_id = ""
    while True:
        fetched = ""
        if not toggle_done:
            pull = questionary.confirm(
                t(lang, "pull_truck_prompt"),
                default=recording_state.get("pull_truck_run_id", False),
            ).ask()
            if pull is None:  # Ctrl-C at the toggle — same as a No
                pull = False
            recording_state["pull_truck_run_id"] = bool(pull)
            toggle_done = True
            if pull:
                fetched = fetch_truck_run_id(lang, vehicle_name)  # "" if it failed
                run_id = fetched

        if not fetched:
            answer = questionary.text(t(lang, "run_id_prompt"), default=run_id).ask()
            run_id = (answer or "").strip()

        skip_default = recording_state.get("skip_polarion", False)
        default_tc = "skip" if skip_default else recording_state.get("last_test_case_id", "")
        tc_answer = questionary.text(t(lang, "test_case_prompt"), default=default_tc).ask()
        tc_answer = (tc_answer or "").strip()

        if tc_answer.lower() == "back":
            continue
        skipped = tc_answer.lower() == "skip" or tc_answer == ""

        recording_state["skip_polarion"] = skipped
        test_case_id = "" if skipped else tc_answer
        if not skipped and test_case_id:
            recording_state["last_test_case_id"] = test_case_id
        return run_id, test_case_id, skipped


def main():
    """Standalone entry point: record, then name and tag the recording.

    Run via `./recorder.sh` (aliased to `recorder`) when you just want to
    capture a screen recording without going through the full start_stack
    command wizard — or from the wizard itself, via "Record the screen only"
    on its first menu.
    """
    run_recording_flow("en", load_state())


if __name__ == "__main__":
    main()
