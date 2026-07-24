TRANSLATIONS = {
    "title": {"en": "start_stack command builder", "ja": "start_stack コマンドビルダー"},
    "vehicle_name": {"en": "vehicle_name", "ja": "車両名（vehicle_name）"},
    "launch_config": {"en": "launch_config", "ja": "起動設定（launch_config）"},
    "map_key": {"en": "map_key (optional)", "ja": "マップキー（map_key・任意）"},
    "route": {"en": "route (optional)", "ja": "ルート（route・任意）"},
    "enable_japan_driving": {"en": "enable_japan_driving", "ja": "日本走行モードを有効化（enable_japan_driving）"},
    "local": {"en": "local", "ja": "ローカル実行（local）"},
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
}


def t(lang, key):
    return TRANSLATIONS[key].get(lang, TRANSLATIONS[key]["en"])
