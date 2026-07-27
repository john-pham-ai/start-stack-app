TRANSLATIONS = {
    "title": {"en": "start_stack command builder", "ja": "start_stack コマンドビルダー"},
    "vehicle_name": {"en": "vehicle_name", "ja": "車両名（vehicle_name）"},
    "vehicle_name_number_prompt": {
        "en": "vehicle_name — enter just the number (e.g. 807 for truck-807)",
        "ja": "車両名 — 数字だけを入力（例: 807 → truck-807）（vehicle_name）",
    },
    "nav_hint": {
        "en": "(type 'back' to go back, 'quit' to quit)",
        "ja": "（戻るには back、終了するには quit と入力）",
    },
    "launch_config": {"en": "launch_config", "ja": "起動設定（launch_config）"},
    "map_key": {"en": "map_key (optional)", "ja": "マップキー（map_key・任意）"},
    "route": {"en": "route (optional)", "ja": "ルート（route・任意）"},
    "enable_japan_driving": {"en": "enable_japan_driving", "ja": "日本走行モードを有効化（enable_japan_driving）"},
    "none_option": {"en": "-- none --", "ja": "-- なし --"},
    "build_command": {"en": "Build command", "ja": "コマンドを作成"},
    "command_heading": {"en": "Command", "ja": "コマンド"},
    "copy_to_clipboard": {"en": "Copy to clipboard", "ja": "クリップボードにコピー"},
    "copied": {"en": "Copied!", "ja": "コピーしました！"},
    "copy_failed": {"en": "Copy failed — copy manually.", "ja": "コピーに失敗しました。手動でコピーしてください。"},
    "switch_language": {"en": "日本語", "ja": "English"},
    "language_prompt": {"en": "Language / 言語", "ja": "Language / 言語"},
    "copied_clipboard": {"en": "(copied to clipboard)", "ja": "（クリップボードにコピーしました）"},
    "could_not_copy": {"en": "(could not copy to clipboard)", "ja": "（クリップボードにコピーできませんでした）"},
    "back": {"en": "<< Back", "ja": "<< 戻る"},
    "quit": {"en": "Quit", "ja": "終了"},
    "yes": {"en": "Yes", "ja": "はい"},
    "no": {"en": "No", "ja": "いいえ"},
    "cancelled": {"en": "Cancelled.", "ja": "キャンセルしました。"},
    "record_prompt": {
        "en": "Record the screen for this run? Press 'r' to start, or 'q' to skip: ",
        "ja": "この実行の画面を録画しますか？ 開始するには 'r'、スキップするには 'q' を押してください： ",
    },
    "ffmpeg_missing": {
        "en": "(Could not install ffmpeg automatically — skipping screen recording. Install it yourself, e.g. 'brew install ffmpeg', then run this again.)",
        "ja": "（ffmpeg を自動インストールできなかったため、画面録画をスキップします。'brew install ffmpeg' などで手動インストールしてから、もう一度実行してください。）",
    },
    "record_failed": {
        "en": "Could not start recording:",
        "ja": "録画を開始できませんでした：",
    },
    "record_started": {
        "en": "Recording started.",
        "ja": "録画を開始しました。",
    },
    "press_s_to_stop": {"en": "press 's' to stop", "ja": "停止するには 's' を押してください"},
    "keep_or_discard_prompt": {
        "en": "Keep this recording, or discard it? (k = keep, d = discard): ",
        "ja": "この録画を保存しますか、破棄しますか？（k = 保存、d = 破棄）： ",
    },
    "recording_discarded": {"en": "Recording discarded.", "ja": "録画を破棄しました。"},
    "run_id_prompt": {
        "en": "Paste the run id (optional — press Enter to leave blank)",
        "ja": "run-id を貼り付けてください（任意 — 空欄のまま Enter でスキップ）",
    },
    "test_case_prompt": {
        "en": "Paste the Polarion test case id (type 'skip' for none, 'back' to re-enter the run id)",
        "ja": "Polarion のテストケース ID を貼り付けてください（無しの場合は 'skip'、run-id をやり直す場合は 'back'）",
    },
    "recording_label": {"en": "Recording", "ja": "録画中"},
    "recording_saved": {"en": "Recording saved:", "ja": "録画を保存しました："},
    "open_folder": {"en": "Open recording folder", "ja": "録画フォルダを開く"},
    "polarion_link": {"en": "Polarion link:", "ja": "Polarion リンク："},
}


def t(lang, key):
    return TRANSLATIONS[key].get(lang, TRANSLATIONS[key]["en"])
