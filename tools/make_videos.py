#!/usr/bin/env python3
"""Generate the per-feature video guides in docs/videos/.

What you see is the real app: the TUI runs in a pty (pyte renders the
terminal), the web UI runs a real Flask server driven by Playwright —
no mocked prompts, no staged screenshots. Frames are drawn by Pillow
(terminal text on a dark card, a caption bar underneath — the captions
are the narration; the videos are silent by design) and encoded by
ffmpeg.

Regenerate everything with:

    ./venv/bin/python tools/make_videos.py            # all videos
    ./venv/bin/python tools/make_videos.py 01-start-menu-shortcuts

Runs are hermetic: ROUTES_SYNC/APP_UPDATE are pinned off, the wizard's
state file is a throwaway seeded JSON, and shared presets come from a
throwaway directory — the developer's real state and the network are
never touched.

Step shapes (TUI): {"press": key, "wait": s, "caption": str} — one
keypress; {"keys": text, "wait": s, "caption": ...} — typed out;
{"pause": s, "caption": ...} — hold the current screen. Every TUI video
implicitly begins at the language prompt (main()'s first step) — each
spec starts with Enter for English.
"""

import io
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
os.environ["ROUTES_SYNC"] = "off"
os.environ["APP_UPDATE"] = "off"
os.environ["TERM"] = "xterm-256color"
os.environ["PROMPT_TOOLKIT_NO_CPR"] = "1"  # no CPR warnings in the pty

import pyte
from PIL import Image, ImageDraw, ImageFont

COLS, ROWS = 96, 34
FPS = 10
FRAME_W = 1360
TERM_PAD = 36

BG = (26, 26, 32)
FG = (222, 222, 222)
ACCENT = (255, 175, 0)
CAPTION_BG = (14, 14, 18)
CAPTION_FG = (140, 180, 255)

VIDEOS_DIR = os.path.join(APP_DIR, "docs", "videos")
VIDEO_LANG = os.environ.get("VIDEO_LANG", "en")  # en | ja — captions, cards, dir
if VIDEO_LANG not in ("en", "ja"):
    raise SystemExit(f"unknown VIDEO_LANG {VIDEO_LANG!r}")
if VIDEO_LANG != "en":
    VIDEOS_DIR = os.path.join(VIDEOS_DIR, VIDEO_LANG)
FFMPEG = shutil.which("ffmpeg")

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
CJK_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"


def is_cjk(char):
    return ord(char) >= 0x2E80


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(text, fnt, width):
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if fnt.getbbox(candidate)[2] <= width - 2 * TERM_PAD:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines[:2]


def caption_font(caption):
    """SANS has no Japanese glyphs — captions in 日本語 render in Noto CJK."""
    if any(is_cjk(c) for c in caption):
        return font(CJK, 22)
    return font(SANS, 22)


def caption_bar(draw, caption, top, width):
    draw.rectangle((0, top, width, top + 84), fill=CAPTION_BG)
    fnt = caption_font(caption)
    for i, line in enumerate(wrap(caption, fnt, width)):
        draw.text((TERM_PAD, top + 12 + i * 30), line, fill=CAPTION_FG, font=fnt)


def text_card(title, subtitle=""):
    img = Image.new("RGB", (FRAME_W, 720), BG)
    draw = ImageDraw.Draw(img)
    big = font(CJK, 42) if any(is_cjk(c) for c in title) else font(SANS_BOLD, 44)
    small = font(CJK, 24) if any(is_cjk(c) for c in subtitle) else font(SANS, 24)
    draw.text((FRAME_W // 2, 320), title, fill=FG, font=big, anchor="mm")
    if subtitle:
        draw.text((FRAME_W // 2, 400), subtitle, fill=CAPTION_FG, font=small, anchor="mm")
    return img


# --- TUI recording -----------------------------------------------------------


class PtySession:
    """Anything recorded in a real terminal: pyte renders the pty's output,
    steps type real keys, every tick is a frame with a caption bar."""

    def __init__(self, argv, cwd=None, env=None, settle=1.5):
        self.screen = pyte.Screen(COLS, ROWS)
        self.stream = pyte.ByteStream(self.screen)
        self.frames_dir = tempfile.mkdtemp(prefix="frames-")
        self.count = 0
        self._extra_env = env or {}
        pid, fd = os.forkpty()
        if pid == 0:
            if cwd:
                os.chdir(cwd)
            os.environ.update(self._extra_env)
            # Tell the pty its real size, or bash/readline assume 80 columns
            # and redraw long lines garbled against pyte's wider screen.
            import fcntl
            import struct
            import termios
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
            os.environ["COLUMNS"], os.environ["LINES"] = str(COLS), str(ROWS)
            # execv PATH-searches nothing — resolve the binary up front.
            resolved = shutil.which(argv[0]) or argv[0]
            os.execv(resolved, argv)
        self.pid, self.fd = pid, fd
        self._feed(settle)

    def _feed(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            r, _, _ = select.select([self.fd], [], [], max(0.01, deadline - time.time()))
            if not r:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                return
            if not data:
                return
            self.stream.feed(data)

    def snap(self, caption):
        mono, bold = font(MONO, 17), font(MONO_BOLD, 17)
        cjk, cjk_bold = font(CJK, 16), font(CJK_BOLD, 16)
        char_w = bold.getbbox("M")[2]
        term_h = ROWS * 20 + 2 * TERM_PAD
        img = Image.new("RGB", (FRAME_W, term_h + 84), BG)
        draw = ImageDraw.Draw(img)
        for y in range(ROWS):
            row = self.screen.buffer[y]
            for x in range(COLS):
                cell = row[x]
                char = cell.data
                if not char or char == " ":
                    continue  # blank, or the placeholder half of a wide char
                color = ACCENT if cell.bold else FG
                if is_cjk(char):
                    fnt = cjk_bold if cell.bold else cjk
                else:
                    fnt = bold if cell.bold else mono
                draw.text((TERM_PAD + x * char_w, TERM_PAD + y * 20), char,
                          fill=color, font=fnt)
        cy = TERM_PAD + (min(self.screen.cursor.y, ROWS - 1) + 1) * 20
        cx = TERM_PAD + min(self.screen.cursor.x, COLS - 1) * char_w
        draw.rectangle((cx, cy - 3, cx + char_w, cy), fill=FG)
        caption_bar(draw, caption, term_h, FRAME_W)
        img.save(os.path.join(self.frames_dir, f"{self.count:05d}.png"))
        self.count += 1

    def hold(self, seconds, caption):
        for _ in range(int(seconds * FPS)):
            self._feed(1.0 / FPS)
            self.snap(caption)

    def wait_for_timelapse(self, text, caption, timeout=180.0):
        """Fast-forward until text shows: one frame per second of real time,
        played at FPS — so a 60s dependency install becomes ~6s of video with
        the caption saying what a real first run takes."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._feed(1.0)
            self.snap(caption)
            if any(text in line for line in self.screen.display):
                return True
        raise RuntimeError(f"never saw {text!r} on screen")

    def wait_for(self, text, caption, timeout=12.0):
        """Feed (and keep filming) until text shows on screen — steps sync
        on the prompt they act on instead of on fixed delays."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if any(text in line for line in self.screen.display):
                return True
            self._feed(1.0 / FPS)
            self.snap(caption)
        raise RuntimeError(f"never saw {text!r} on screen")

    def type(self, text, total, caption):
        """Type text spread over ~total seconds, then hold for the rest."""
        per_char = max(0.04, 0.6 * total / max(1, len(text)))
        for char in text:
            os.write(self.fd, char.encode())
            self._feed(per_char)
            self.snap(caption)
        self.hold(max(0.0, total - per_char * len(text)), caption)

    def press(self, key, seconds, caption):
        os.write(self.fd, key.encode())
        self.hold(seconds, caption)

    def close(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass

    def encode(self, out_path, title, subtitle):
        first = Image.open(os.path.join(self.frames_dir, "00000.png"))
        card = text_card(title, subtitle).resize(first.size)
        for _ in range(24):  # ~2.4s of end card
            card.save(os.path.join(self.frames_dir, f"{self.count:05d}.png"))
            self.count += 1
        _encode(self.frames_dir, out_path)
        shutil.rmtree(self.frames_dir, ignore_errors=True)


class TuiSession(PtySession):
    """A real launch.main() in a pty."""

    def __init__(self, state, shared_dir=None):
        seed = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(state, seed)
        seed.close()
        self._seed_path = seed.name
        harness = (
            "import sys; "
            f"sys.path.insert(0, {APP_DIR!r}); "
            "import state as state_module; "
            f"state_module.STATE_PATH = {self._seed_path!r}; "
            + (f"import shared_presets; shared_presets.PRESETS_DIR = {shared_dir!r}; "
               if shared_dir else "")
            + "import launch; launch.main()"
        )
        super().__init__([sys.executable, "-c", harness])

    def close(self):
        super().close()
        os.unlink(self._seed_path)


class ShellSession(PtySession):
    """A real bash in a pty, for the clone/first-run setup video.

    HOME is a throwaway sandbox so the launcher's automatic `launch`-alias
    setup (and anything else bashy) writes there, never to the developer's
    real rc files. cwd is the prepared clone with its venv pre-built, so
    ./launch.sh reaches the language prompt quickly; captions say what a
    genuinely-first run adds (venv + dependency install, ~a minute).
    """

    def __init__(self, cwd):
        self.home = tempfile.mkdtemp(prefix="video-home-")
        # A cwd-showing prompt (the default --norc one hides where you are).
        self._rcfile = os.path.join(self.home, ".bashrc_video")
        with open(self._rcfile, "w") as f:
            f.write("PS1='\\w\\$ '\n")
        super().__init__(
            ["bash", "--noprofile", "--rcfile", self._rcfile],
            cwd=cwd,
            env={"HOME": self.home, "TERM": os.environ.get("TERM", "xterm-256color"),
                 "PATH": os.environ["PATH"], "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"},
            settle=0.8,
        )

    def close(self):
        super().close()
        shutil.rmtree(self.home, ignore_errors=True)


# --- Web recording -----------------------------------------------------------


class WebSession:
    """The real Flask server on a scratch port, driven by Playwright."""

    def __init__(self, state, shared_dir=None, port=5057):
        self.frames_dir = tempfile.mkdtemp(prefix="frames-")
        self.count = 0
        seed = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(state, seed)
        seed.close()
        self._seed_path = seed.name
        harness = (
            "import sys; "
            f"sys.path.insert(0, {APP_DIR!r}); "
            "import state as state_module; "
            f"state_module.STATE_PATH = {self._seed_path!r}; "
            + (f"import shared_presets; shared_presets.PRESETS_DIR = {shared_dir!r}; "
               if shared_dir else "")
            + f"import app; app.app.run(port={port}, debug=False)"
        )
        import socket
        # Refuse to record against a stranger: a stale server from an
        # aborted run on the same port would serve old code and old state
        # (this happened — a zombie kept the pre-fix combobox alive).
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                raise SystemExit(
                    f"port {port} is already in use — kill the stale server "
                    f"(pgrep -af app.app.run) before recording"
                )
        except OSError:
            pass
        self.port = port
        self.proc = subprocess.Popen(
            [sys.executable, "-c", harness],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 860})
        for _ in range(120):  # wait for OUR server socket, then load once
            if self.proc.poll() is not None:
                raise SystemExit("the Flask server exited during startup")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.25)
        self.page.goto(f"http://127.0.0.1:{port}/", wait_until="load", timeout=30000)

    def snap(self, caption):
        try:
            png = self.page.screenshot()
        except Exception:  # mid-navigation (a form POST): settle, retry once
            self.page.wait_for_load_state()
            png = self.page.screenshot()
        shot = Image.open(io.BytesIO(png)).convert("RGB")
        shot = shot.resize((FRAME_W, int(shot.height * FRAME_W / shot.width)))
        height = shot.height + 84
        height += height % 2  # h264 needs even dimensions
        img = Image.new("RGB", (FRAME_W, height), BG)
        img.paste(shot, (0, 0))
        draw = ImageDraw.Draw(img)
        caption_bar(draw, caption, shot.height, FRAME_W)
        img.save(os.path.join(self.frames_dir, f"{self.count:05d}.png"))
        self.count += 1

    def hold(self, seconds, caption):
        for _ in range(int(seconds * FPS)):
            self.snap(caption)

    def close(self):
        for step in (self.browser.close, self._pw.stop, self.proc.terminate):
            try:
                step()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        try:
            os.unlink(self._seed_path)
        except OSError:
            pass

    def encode(self, out_path, title, subtitle):
        first = Image.open(os.path.join(self.frames_dir, "00000.png"))
        card = text_card(title, subtitle).resize(first.size)
        for _ in range(24):
            card.save(os.path.join(self.frames_dir, f"{self.count:05d}.png"))
            self.count += 1
        _encode(self.frames_dir, out_path)
        shutil.rmtree(self.frames_dir, ignore_errors=True)


# --- encoding -----------------------------------------------------------------


def _encode(frames_dir, out_path):
    if FFMPEG is None:
        raise SystemExit("ffmpeg not found on PATH — install it to encode videos.")
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-framerate", str(FPS),
         "-i", os.path.join(frames_dir, "%05d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", out_path],
        check=True,
    )
    print(f"encoded {out_path}")


# --- video specs --------------------------------------------------------------

def _hist(vehicle, config, route, japan):
    from stack_options import build_command
    return {"vehicle_name": vehicle, "launch_config": config, "route": route,
            "enable_japan_driving": japan, "built_at": "2026-09-16T09:00:00",
            "custom": False,
            "command": build_command(vehicle, config, route, japan)}


def seeded_state():
    return {
        "presets": {
            "night loop": {
                "vehicle_name": "truck-807", "launch_config": "sds_road_readiness",
                "route": "shoreline_straight", "enable_japan_driving": False,
            },
            "mtv costco run": {
                "vehicle_name": "truck-812", "launch_config": "sds_road_readiness",
                "route": "12min_costco_poi", "enable_japan_driving": False,
            },
        },
        "loops": {
            "japan mileage": {
                "vehicle_name": "truck-807", "launch_config": "etc_sds_road_readiness",
                "enable_japan_driving": True,
                "stops": ["heiwajima_road_10kph", "heiwajima_roof_10kph"],
            },
        },
        "history": [
            _hist("truck-810", "etc_sds_road_readiness", "heiwajima_road_10kph", True),
            _hist("truck-812", "sds_road_readiness", "whisman_92_loop", False),
            _hist("truck-805", "sds_road_readiness", "12min_costco_poi", False),
            _hist("truck-809", "sds_road_readiness", "crows_landing_cw_outer_loop", False),
        ],
    }


def shared_demo_dir():
    d = tempfile.mkdtemp(prefix="shared-presets-")
    with open(os.path.join(d, "japan demo route.json"), "w") as f:
        json.dump({"vehicle_name": "truck-807", "launch_config": "etc_sds_road_readiness",
                   "route": "heiwajima_road_10kph",
                   "enable_japan_driving": True, "kind": "values",
                   "exported_by": "teammate"}, f)
    return d


# --- Japanese layer -----------------------------------------------------------
# VIDEO_LANG=ja swaps in Japanese title cards, captions — and the TUI session
# itself runs in 日本語 (the language step picks 2), so what's recorded is the
# UI a Japanese-speaking tester actually sees. The ja caption lists align
# with each spec's steps: two language-pick steps first, then one per en step.

# Steps sync on prompt text; the Japanese UI shows its own, so the
# English expect-strings map to what the 日本語 UI actually displays.
# (vehicle_name / launch_config / enable_japan_driving appear verbatim inside
# the Japanese labels already.)
JA_EXPECT = {
    "What do you want to do?": "何をしますか？",
    "route (optional)": "ルート",
    "Preset name": "プリセット名",
    "Stop 1": "停留所 1",
    "Stop 2": "停留所 2",
    "Language": "言語",
    "Which preset should be shared?": "どのプリセットを共有しますか？",
}

JA_LANG_STEPS = [
    {"expect": "言語", "press": "\x1b[B", "wait": 1.0,
     "caption": "まず言語の選択です。↓ で 日本語 へ。"},
    {"press": "\r", "wait": 1.8,
     "caption": "Enter で確定 — これ以降、すべて日本語で表示されます。"},
]

JA_TITLES = {
    "01-start-menu-shortcuts": (
        "スタートメニューとショートカットキー",
        "プリセットは ! @ # …・ループは Q/W/E/R・最近の実行は A/S/D/F（最下部）",
    ),
    "02-build-command": (
        "start_stack コマンドを作成する",
        "ウィザード: 車両・起動設定・ルート・日本走行モード",
    ),
    "03-route-autofill": (
        "ルート選択: 入力してオートコンプリート",
        "ルート名でもマップ名でも絞り込めます。Tab で候補を確定",
    ),
    "04-closed-loop": (
        "クローズドループ走行モード（日本）",
        "停留所（ルート）を順に並べたループを作成 — 日本走行モードは自動的に有効",
    ),
    "05-shared-presets": (
        "リポジトリ経由でプリセットを共有",
        "書き出し → ファイルを送る → presets/ にコミット → 全マシンに自動反映",
    ),
    "06-web-ui": (
        "Web UI",
        "ルートのコンボボックス・プリセット・ブラウザでコマンド作成",
    ),
}

JA_CAPTIONS = {
    "01-start-menu-shortcuts": [
        "スタートメニュー。すべての項目にショートカットがあります — ! は「night loop」プリセット、ワンキーで選べます。",
        "!（shift+1）を押すと、ハイライトが最初のプリセットへ移動します。",
        "Enter で実行 — コマンドが組み立てられ、クリップボードにコピーされ、最近の実行に記録されます。",
        "コマンドごとに録画の確認があります — q でスキップ。",
        "メニューに戻りました。a は直近4件の最近の実行から最新の1件（メニュー最下部）。",
        "Enter でそのコマンドを再構築 — ウィザードをやり直す必要はありません。",
        "q で録画をスキップ。",
        "w は2つ目の日本ループのショートカット（Q/W/E/R — 保存済みループごとに1つ、最大4つ）。",
        "固定項目は 1〜9: 作成・録画のみ・実行ID取得・SSHセットアップ・カスタム保存・ループ作成・終了。",
    ],
    "02-build-command": [
        "「新しいコマンドを作成」。",
        "Enter。",
        "車両: 数字だけ入力 — 807 で truck-807 になります。",
        "Enter で確定。",
        "起動設定: 前回の選択が先頭に固定されています — Enter で採用。",
        "次はルート — 入力してオートコンプリートするプロンプトです（別の動画で解説）。",
        "空欄のまま Enter でルートなし（任意項目です）。",
        "日本走行モード: 日本語を選んだので初期値は「はい」。矢印 + Enter で選びます。",
        "完成 — フラグごとに改行されたコマンドがクリップボードにコピー済み。シェルに貼り付けて実行します。",
    ],
    "03-route-autofill": [
        "新しいコマンドを作成。",
        "Enter。",
        "車両: 807。",
        "Enter。",
        "起動設定 — Enter。",
        "ルートのプロンプトです。ルート名の一部を入力…",
        "…マップ名でも構いません —「heiwajima」で180以上のルートから数件に絞り込まれます。",
        "Tab でハイライトされた候補を確定（↑/↓ でリスト内を移動）。",
        "Enter で決定。",
        "日本走行モード: いいえ。",
        "ルートは --route として付加されます — マップのフラグは不要、ルート自身がマップ情報を持ちます。",
    ],
    "04-closed-loop": [
        "「クローズドループ走行ルートを作成（日本）」— ショートカット 6。",
        "Enter。",
        "まず基本コマンド: 車両 807（このモードでは日本走行モードが強制的に有効になります）。",
        "Enter。",
        "起動設定 — Enter。単一のルートは指定しません。停留所がそれを定義します。",
        "日本走行モードの確認がありますが、ループでは常に有効 — Enter。",
        "停留所1: ウィザードと同じ入力式ルート選択。",
        "Tab。",
        "Enter で停留所を追加。",
        "'done' で停留所の入力を終了（空行や「ルート完了」の行でも同じ）。",
        "名前を付けます — メニューの Q/W/E/R の表示名になります。",
        "名前…",
        "保存しました。走行は停留所を順に進み、最後の停留所の後は1周目に戻って繰り返します。",
    ],
    "05-shared-presets": [
        "（共有）と表示されたプリセットはリポジトリの presets/ 由来 — 管理者がコミットすると、各マシンの次回起動で自動的に届きます。",
        "これは個人プリセット — 書き出してチームメイトにも使えるようにします。",
        "作成されました（通常どおりクリップボードにもコピー）。",
        "q で録画の確認をスキップ。",
        "8)「プリセットを書き出して共有」— 表示されたキーがそのままショートカットです。",
        "Enter。",
        "一覧に出るのは共有可能なプリセットだけ — ウィザードの選択内容から作られたものです。",
        "↓ で「<< 戻る」の次へ…",
        "…「night loop」で Enter。共有ファイルが exports/night loop.json に書き出されます — このファイルを送ってください。",
        "受け取った側が presets/<名前>.json としてコミットすると、全マシンの次回起動で（共有）付きで現れます。",
    ],
    "06-web-ui": [
        "127.0.0.1:5050?lang=ja — TUI と同じ選択肢・プリセット・履歴をブラウザで。",
        "ルート欄はコンボボックス: クリックすると全ルートがマップごとに表示されます。",
        "数文字入力 — ルート名・値・マップ名のいずれでも絞り込めます。",
        "↓ で目的のものへ…",
        "…",
        "…Enter で選択（クリックでも構いません）。",
        "「コマンドを作成」— 同じ形式のコマンドが出力され、自動でコピーされます。",
        "プリセットも同じ使い方。リポジトリ共有のものは「（共有）」と表示され、書き出し/読み込みでやり取りできます。",
    ],
}


# Prompt texts the specs sync on before pressing keys.
MENU, VEH, CFG, ROUTE, JP = (
    "What do you want to do?", "vehicle_name", "launch_config",
    "route (optional)", "enable_japan_driving",
)

LANG = [{"expect": "Language", "press": "\r", "wait": 1.6, "caption":
         "First: the language. Enter for English (2 for 日本語 — everything you'll see exists in both)."}]

TUI_VIDEOS = {
    "01-start-menu-shortcuts": {
        "title": "The start menu: shortcut keys",
        "subtitle": "presets ! @ # … loops Q/W/E/R · recents A/S/D/F at the bottom",
        "state": seeded_state, "shared": shared_demo_dir,
        "steps": LANG + [
            {"expect": MENU, "pause": 4.0, "caption": "The start menu. Every entry has a shortcut — ! is the 'night loop' preset, one keystroke away."},
            {"press": "!", "wait": 1.8, "caption": "Press ! (shift+1) — the highlight jumps to the first preset."},
            {"press": "\r", "wait": 3.5, "caption": "Enter runs it: the command is built, copied to your clipboard, remembered in Recent."},
            {"press": "q", "wait": 2.0, "caption": "Every command gets a recording offer — q skips it."},
            {"expect": MENU, "press": "a", "wait": 1.8, "caption": "Back at the menu. a — the newest of the last 4 recent runs, at the bottom."},
            {"press": "\r", "wait": 3.0, "caption": "Enter rebuilds that command — no re-walking the wizard."},
            {"press": "q", "wait": 1.8, "caption": "q skips the recording again."},
            {"expect": MENU, "press": "w", "wait": 2.0, "caption": "w is the second Japan-loop shortcut (Q/W/E/R — one per saved loop, 4 max)."},
            {"pause": 2.5, "caption": "Fixed entries take 1–9: build, record-only, truck fetch, SSH setup, save-custom, loops, quit."},
        ],
    },
    "02-build-command": {
        "title": "Building a start_stack command",
        "subtitle": "the wizard: vehicle · launch config · route · Japan toggle",
        "state": lambda: {}, "shared": None,
        "steps": LANG + [
            {"expect": MENU, "press": "1", "wait": 1.2, "caption": "Build a new command."},
            {"press": "\r", "wait": 1.6, "caption": "Enter."},
            {"expect": VEH, "keys": "807", "wait": 1.6, "caption": "Vehicle: type just the number — 807 becomes truck-807."},
            {"press": "\r", "wait": 1.6, "caption": "Enter accepts it."},
            {"expect": CFG, "press": "\r", "wait": 2.2, "caption": "Launch config: the remembered default is pinned first — Enter takes it."},
            {"expect": ROUTE, "pause": 2.2, "caption": "The route is next — a type-to-autofill prompt (its own video)."},
            {"press": "\r", "wait": 2.0, "caption": "Blank + Enter leaves the route out; it's optional."},
            {"expect": JP, "press": "\r", "wait": 2.2, "caption": "Japan driving toggle: No for an English run."},
            {"pause": 3.5, "caption": "The command — one flag per line, already on your clipboard. Paste it into the shell and go."},
        ],
    },
    "03-route-autofill": {
        "title": "The route prompt: type to autofill",
        "subtitle": "route names and map names both filter · Tab accepts the highlighted suggestion",
        "state": lambda: {}, "shared": None,
        "steps": LANG + [
            {"expect": MENU, "press": "1", "wait": 1.0, "caption": "Build a new command."},
            {"press": "\r", "wait": 1.2, "caption": "Enter."},
            {"expect": VEH, "keys": "807", "wait": 1.2, "caption": "Vehicle: 807..."},
            {"press": "\r", "wait": 1.4, "caption": "Enter."},
            {"expect": CFG, "press": "\r", "wait": 1.6, "caption": "Launch config — Enter."},
            {"expect": ROUTE, "pause": 2.2, "caption": "The route prompt. Type a few letters of a route name..."},
            {"keys": "heiwajima", "wait": 2.6, "caption": "...or a map name — 'heiwajima' narrows 180+ routes to a handful."},
            {"press": "\t", "wait": 2.0, "caption": "Tab accepts the highlighted suggestion (up/down browse the list)."},
            {"press": "\r", "wait": 2.0, "caption": "Enter submits it."},
            {"expect": JP, "press": "\r", "wait": 2.0, "caption": "Japan toggle: No."},
            {"pause": 3.0, "caption": "The route rides along as --route — the map never needs a flag, routes carry their own."},
        ],
    },
    "04-closed-loop": {
        "title": "Closed-loop mileage mode (Japan)",
        "subtitle": "build a loop of route stops — Japan driving forced on, saved under a name",
        "state": lambda: {}, "shared": None,
        "steps": LANG + [
            {"expect": MENU, "press": "6", "wait": 1.4, "caption": "Build a closed-loop mileage route (Japan) — shortcut 6."},
            {"press": "\r", "wait": 1.4, "caption": "Enter."},
            {"expect": VEH, "keys": "807", "wait": 1.4, "caption": "The base command first: vehicle 807 (Japan driving is forced on for this mode)."},
            {"press": "\r", "wait": 1.4, "caption": "Enter."},
            {"expect": CFG, "press": "\r", "wait": 2.0, "caption": "Launch config — Enter. No single route: the stops define them."},
            {"expect": JP, "press": "\r", "wait": 1.8, "caption": "The Japan toggle is asked but forced on for loops — Enter."},
            {"expect": "Stop 1", "keys": "heiwajima", "wait": 2.4, "caption": "Stop 1: the same type-to-autofill picker."},
            {"press": "\t", "wait": 1.4, "caption": "Tab."},
            {"press": "\r", "wait": 1.6, "caption": "Enter adds the stop."},
            {"expect": "Stop 2", "keys": "done", "wait": 1.8, "caption": "'done' ends the stop list (a blank line or the done row work too)."},
            {"press": "\r", "wait": 2.0, "caption": "Name it — that's what the menu's Q/W/E/R entry will show."},
            {"expect": "Preset name", "keys": "jp mileage", "wait": 1.8, "caption": "The name..."},
            {"press": "\r", "wait": 3.5, "caption": "Saved. Driving it walks the stops in order, wraps back to stop 1 for another lap, and only ends when you say so."},
        ],
    },
    "05-shared-presets": {
        "title": "Sharing presets through the repo",
        "subtitle": "export → send the file in → presets/ in the repo → every machine, automatically",
        "state": seeded_state, "shared": shared_demo_dir,
        "steps": LANG + [
            {"expect": MENU, "pause": 3.0, "caption": "Presets marked (shared) come from the repo's presets/ — the owner commits them, and every machine picks them up on the next launch."},
            {"press": "@", "wait": 1.6, "caption": "This one is personal — export it so a teammate can run it too."},
            {"press": "\r", "wait": 2.8, "caption": "Built (and copied to the clipboard as usual)."},
            {"press": "q", "wait": 1.8, "caption": "q skips the recording offer."},
            {"expect": MENU, "press": "8", "wait": 1.8, "caption": "8) Export a preset to share — every entry's printed key is its shortcut."},
            {"press": "\r", "wait": 1.0, "caption": "Enter."},
            {"expect": "Which preset should be shared?", "pause": 1.8, "caption": "The picker lists only shareable presets — ones built from the wizard's choices."},
            {"press": "\x1b[B", "wait": 1.4, "caption": "Down, past Back..."},
            {"press": "\r", "wait": 3.0, "caption": "...Enter on 'night loop'. The share file lands in exports/night loop.json — send that file in."},
            {"pause": 3.5, "caption": "The recipient commits it as presets/<name>.json — and it appears on every machine, marked (shared), on the next launch."},
        ],
    },
}

WEB_VIDEOS = {
    "06-web-ui": {
        "title": "The web UI",
        "subtitle": "route combobox · presets · building the command in the browser",
        "state": seeded_state, "shared": shared_demo_dir,
        "steps": [
            {"goto": True, "wait": 3.0, "caption": "127.0.0.1:5050 — the same options, presets and history as the TUI, in the browser."},
            {"click": "#route-input", "wait": 2.2, "caption": "The route box is a combobox: click it and every route appears, grouped by map."},
            {"type": {"selector": "#route-input", "text": "heiwajima"}, "wait": 2.4,
             "caption": "Type a few letters — route names, values and map names all filter."},
            {"key": "ArrowDown", "wait": 1.2, "caption": "Arrow down to the one you want..."},
            {"key": "ArrowDown", "wait": 1.0, "caption": "..."},
            {"key": "Enter", "wait": 1.8, "caption": "...Enter picks it (a click works too)."},
            {"click": "button[value=build]", "wait": 2.2, "caption": "Build command — the same one-flag-per-line output, auto-copied."},
            {"pause": 3.0, "caption": "Presets load the same way; repo-shared ones are marked '(shared)', and Export/Import moves them in and out."},
        ],
    },
}


def run_tui(slug, spec):
    print(f"recording {slug} ({VIDEO_LANG}) ...")
    state = spec["state"]()
    shared = spec["shared"]() if spec["shared"] else tempfile.mkdtemp(prefix="no-shared-")
    session = TuiSession(state, shared)
    # ja runs swap the language step for a two-step 日本語 pick (the UI itself
    # then runs in Japanese) and take their captions from JA_CAPTIONS —
    # 2 language steps first, then one per remaining en step.
    steps = spec["steps"] if VIDEO_LANG == "en" else JA_LANG_STEPS + spec["steps"][1:]
    captions = ([s["caption"] for s in steps] if VIDEO_LANG == "en"
                else [s["caption"] for s in JA_LANG_STEPS] + JA_CAPTIONS[slug])
    title, subtitle = ((spec["title"], spec["subtitle"]) if VIDEO_LANG == "en"
                        else JA_TITLES[slug])
    try:
        for index, step in enumerate(steps):
            caption = captions[index]
            if "expect" in step:
                expected = step["expect"]
                if VIDEO_LANG == "ja":
                    expected = JA_EXPECT.get(expected, expected)
                session.wait_for(expected, caption)
            if "pause" in step:
                session.hold(step["pause"], caption)
            elif "press" in step:
                session.press(step["press"], step.get("wait", 1.0), caption)
            elif "keys" in step:
                session.type(step["keys"], step.get("wait", 1.0), caption)
        session.encode(
            os.path.join(VIDEOS_DIR, f"{slug}.mp4"), title, subtitle
        )
    finally:
        session.close()


def run_web(slug, spec):
    print(f"recording {slug} ({VIDEO_LANG}) ...")
    state = spec["state"]()
    shared = spec["shared"]() if spec["shared"] else tempfile.mkdtemp(prefix="no-shared-")
    session = WebSession(state, shared)
    if VIDEO_LANG == "ja":
        session.page.goto(f"http://127.0.0.1:{session.port}/?lang=ja")
    steps = spec["steps"]
    captions = ([s["caption"] for s in steps] if VIDEO_LANG == "en"
                else JA_CAPTIONS[slug])
    title, subtitle = ((spec["title"], spec["subtitle"]) if VIDEO_LANG == "en"
                       else JA_TITLES[slug])
    try:
        for index, step in enumerate(steps):
            caption = captions[index]
            if step.get("goto"):
                session.hold(step.get("wait", 2.0), caption)
            elif "click" in step:
                session.page.locator(step["click"]).click()
                session.page.wait_for_load_state()
                session.hold(step.get("wait", 1.5), caption)
            elif "type" in step:
                session.page.locator(step["type"]["selector"]).fill("")
                session.page.keyboard.type(step["type"]["text"], delay=80)
                session.hold(step.get("wait", 1.5), caption)
            elif "key" in step:
                session.page.keyboard.press(step["key"])
                session.page.wait_for_load_state()
                session.hold(step.get("wait", 1.5), caption)
            elif "pause" in step:
                session.hold(step["pause"], caption)
        session.encode(
            os.path.join(VIDEOS_DIR, f"{slug}.mp4"), title, subtitle
        )
    finally:
        session.close()


# --- setup/clone video ----------------------------------------------------------
# The real thing, start to finish: a live git clone of the repo, then a real
# first ./launch.sh — the venv build + dependency install + brain2 routes sync
# actually happen on camera, time-lapsed (1 frame per real second) so the
# quiet minute of installing plays in ~6 seconds. HOME is a sandbox, so the
# launcher's `launch`-alias setup writes there, not to real rc files.

REPO_URL = "https://github.com/john-pham-ai/start-stack-app.git"


SETUP_TITLES = {
    "en": ("Getting the tool", "git clone → first run — two commands"),
    "ja": ("ツールの入手", "git clone → 初回起動 — コマンド2つ"),
}

SETUP_STEPS = {
    "en": [
        {"pause": 2.5, "caption": "Two commands and you're running — here's the whole setup."},
        {"keys": "git clone " + REPO_URL + "\r", "wait": 4.5,
         "caption": "git clone the repo — github.com/john-pham-ai/start-stack-app."},
        {"expect": "start-stack-app", "keys": "cd start-stack-app\r", "wait": 1.2,
         "caption": "cd in."},
        {"keys": "./launch.sh\r", "wait": 2.5,
         "caption": "The first run creates the venv, installs dependencies, and adds a `launch` alias to your shell."},
        {"timelapse": "Language",
         "caption": "(fast-forward) about a minute in real time: venv, dependencies, and the brain2 routes sync." },
        {"press": "\r", "wait": 2.2,
         "caption": "That's it — pick your language and you're on the start menu."},
        {"expect": "What do you want to do?", "pause": 2.5,
         "caption": "The other videos on this page walk the menu and every feature."},
        {"press": "\x1b[A", "wait": 1.4,
         "caption": "↑ from the top wraps to the last entry — Quit, the menu's only exit."},
        {"press": "\r", "wait": 2.5,
         "caption": "Done. Next time just type `launch` from anywhere — or `./run.sh` for the web UI."},
    ],
    "ja": [
        {"pause": 2.5, "caption": "コマンド2つで導入完了です — 手順は以下のとおり。"},
        {"keys": "git clone " + REPO_URL + "\r", "wait": 4.5,
         "caption": "リポジトリを git clone します — github.com/john-pham-ai/start-stack-app。"},
        {"expect": "start-stack-app", "keys": "cd start-stack-app\r", "wait": 1.2,
         "caption": "cd で移動。"},
        {"keys": "./launch.sh\r", "wait": 2.5,
         "caption": "初回起動時は venv の作成・依存関係のインストール・`launch` エイリアスの追加が行われます。"},
        {"timelapse": "言語",
         "caption": "（早送り）実際は1分ほど: venv、依存関係、brain2 のルート同期。"},
        {"expect": "言語", "press": "\x1b[B", "wait": 1.0,
         "caption": "言語の選択 — ↓ で 日本語 へ。"},
        {"press": "\r", "wait": 2.2,
         "caption": "Enter で確定 — これだけでスタートメニューに進みます。"},
        {"expect": "何をしますか？", "pause": 2.5,
         "caption": "メニューの各機能は、このページの他の動画で解説しています。"},
        {"press": "\x1b[A", "wait": 1.4,
         "caption": "先頭で ↑ を押すと最後の項目 — 終了（このメニュー唯一の出口）— へ移動します。"},
        {"press": "\r", "wait": 2.5,
         "caption": "以上で導入完了。次回からはどのディレクトリでも `launch`、Web UI は `./run.sh` で起動できます。"},
    ],
}


def run_setup():
    print(f"recording 07-setup-clone ({VIDEO_LANG}) ...")
    scratch = tempfile.mkdtemp(prefix="setup-video-")  # the video clones into it
    session = ShellSession(scratch)
    try:
        for step in SETUP_STEPS[VIDEO_LANG]:
            caption = step["caption"]
            if "expect" in step:
                session.wait_for(step["expect"], caption, timeout=40)
            if "timelapse" in step:
                session.wait_for_timelapse(step["timelapse"], caption)
            elif "pause" in step:
                session.hold(step["pause"], caption)
            elif "press" in step:
                session.press(step["press"], step.get("wait", 1.5), caption)
            elif "keys" in step:
                session.type(step["keys"], step.get("wait", 2.0), caption)
        title, subtitle = SETUP_TITLES[VIDEO_LANG]
        session.encode(os.path.join(VIDEOS_DIR, "07-setup-clone.mp4"), title, subtitle)
    finally:
        session.close()
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    wanted = sys.argv[1:]
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    if not wanted or "07-setup-clone" in wanted:
        run_setup()
    for slug, spec in TUI_VIDEOS.items():
        if wanted and slug not in wanted:
            continue
        run_tui(slug, spec)
    for slug, spec in WEB_VIDEOS.items():
        if wanted and slug not in wanted:
            continue
        run_web(slug, spec)


if __name__ == "__main__":
    main()
