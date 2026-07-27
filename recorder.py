"""Screen recording for start_stack runs.

Recordings go into a folder named for today's date under RECORDINGS_DIR. While
recording, the file has a temporary name; once the run is over it's renamed to
carry the run id and the Polarion test case it covers, and a sidecar .json is
written next to it with the Polarion link and the command that was built.

Requires ffmpeg on PATH, and Screen Recording permission for your terminal
(System Settings > Privacy & Security > Screen & System Audio Recording).
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.parse
from datetime import datetime

import questionary

from state import load_state, save_state

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


class RecordingError(Exception):
    """ffmpeg could not be started, or died before we could stop it."""


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def _find_installer():
    """Pick a package manager to install ffmpeg with, based on what's on PATH."""
    if shutil.which("brew"):
        return "Homebrew", ["brew", "install", "ffmpeg"]
    if shutil.which("apt-get"):
        return "apt", ["sudo", "apt-get", "install", "-y", "ffmpeg"]
    if shutil.which("dnf"):
        return "dnf", ["sudo", "dnf", "install", "-y", "ffmpeg"]
    if shutil.which("pacman"):
        return "pacman", ["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"]
    return None, None


def ensure_ffmpeg():
    """Make sure ffmpeg is on PATH, installing it if it's missing.

    Returns True if ffmpeg is available (already, or after installing it),
    False if it's still missing and needs to be installed by hand.
    """
    if ffmpeg_available():
        return True

    label, command = _find_installer()
    if command is None:
        return False

    print(f"ffmpeg not found — installing it with {label} (this may take a minute)...")
    try:
        subprocess.run(command, check=True)
    except (subprocess.CalledProcessError, OSError):
        return False

    return ffmpeg_available()


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

    def __init__(self, base=None, now=None):
        self.now = now or datetime.now()
        self.folder = today_folder(base, self.now)
        self.temp_path = unique_path(os.path.join(self.folder, IN_PROGRESS_NAME + ".mp4"))
        self.proc = None
        self.duration_seconds = None
        self._started_at = None

    def _command(self, device, framerate):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "avfoundation"]
        cmd += ["-capture_cursor", "1"]
        if framerate:
            cmd += ["-framerate", "30"]
        cmd += ["-i", f"{device}:none"]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
        cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        cmd += [self.temp_path]
        return cmd

    def _spawn(self, device, framerate):
        proc = subprocess.Popen(
            self._command(device, framerate),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # If the capture settings are rejected, ffmpeg exits almost immediately.
        time.sleep(1.5)
        if proc.poll() is not None:
            return None, (proc.stderr.read() or b"").decode(errors="replace").strip()
        return proc, None

    def start(self):
        if not ffmpeg_available():
            raise RecordingError("ffmpeg is not installed or not on PATH (try: brew install ffmpeg).")
        device = find_screen_device()
        if device is None:
            raise RecordingError("Could not find a screen capture device in ffmpeg's avfoundation list.")

        # Not every machine accepts an explicit framerate for screen capture,
        # so fall back to letting the device pick its own.
        proc, error = self._spawn(device, framerate=True)
        if proc is None:
            proc, error = self._spawn(device, framerate=False)
        if proc is None:
            raise RecordingError(error or "ffmpeg exited immediately after starting.")

        self.proc = proc
        self._started_at = time.monotonic()
        return self.temp_path

    def elapsed_seconds(self):
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def stop(self):
        """Ask ffmpeg to finish writing, so the .mp4 ends up playable."""
        if self.proc is None:
            return None
        if self._started_at is not None:
            self.duration_seconds = round(time.monotonic() - self._started_at, 1)

        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"q")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
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


def _ask_run_id_and_test_case(state):
    """Same run id / test case id mini-wizard launch.py uses, standalone.

    'back' at the test case prompt re-asks the run id; 'skip' (or blank)
    means no test case id, and that choice is remembered in state.
    """
    recording_state = state.setdefault("recording", {})
    run_id = ""
    while True:
        answer = questionary.text(
            "Paste the run id (optional — press Enter to leave blank):", default=run_id
        ).ask()
        if answer is None:
            return run_id, "", True
        run_id = answer.strip()

        skip_default = recording_state.get("skip_polarion", False)
        default_tc = "skip" if skip_default else recording_state.get("last_test_case_id", "")
        tc_answer = questionary.text(
            "Paste the Polarion test case id (type 'skip' for none, 'back' to re-enter the run id):",
            default=default_tc,
        ).ask()
        if tc_answer is None:
            return run_id, "", True
        tc_answer = tc_answer.strip()

        if tc_answer.lower() == "back":
            continue
        if tc_answer.lower() == "skip" or tc_answer == "":
            return run_id, "", True
        return run_id, tc_answer, False


def main():
    """Standalone entry point: record, then name and tag the recording.

    Run via `./recorder.sh` (aliased to `recorder`) when you just want to
    capture a screen recording without going through the full start_stack
    command wizard.
    """
    state = load_state()

    if not ensure_ffmpeg():
        print(
            "Could not install ffmpeg automatically. Install it yourself "
            "(e.g. 'brew install ffmpeg') and try again.\n"
        )
        return

    with keypress_mode():
        if not wait_for_start():
            return

        try:
            recording = ScreenRecording()
            recording.start()
        except RecordingError as exc:
            print(f"Could not start recording: {exc}\n")
            return

        print("Recording started.\n")
        try:
            wait_for_stop(recording)
        finally:
            recording.stop()

        keep = wait_for_keep_or_discard()

    if not keep:
        recording.discard()
        print("Recording discarded.\n")
        return

    run_id, test_case_id, skipped_polarion = _ask_run_id_and_test_case(state)
    video_path, sidecar_path = recording.finalize(run_id=run_id, test_case_id=test_case_id)

    state["recording"]["skip_polarion"] = skipped_polarion
    if not skipped_polarion and test_case_id:
        state["recording"]["last_test_case_id"] = test_case_id
    save_state(state)

    print(f"Recording saved: {video_path}")
    print(sidecar_path)
    print(hyperlink(os.path.dirname(video_path), label="Open recording folder") + "\n")
    url = polarion_url(test_case_id)
    if url:
        print(f"Polarion link: {url}\n")


if __name__ == "__main__":
    main()
