"""shared_presets: repo presets, the export/import round trip, and the
merge that puts them in the menus."""

import json

import pytest

import shared_presets
from shared_presets import (
    PresetImportError,
    export_preset,
    import_preset_file,
    load_shared_presets,
    merge_presets,
    parse_preset_export,
    valid_shared_entry,
)

VALID = {
    "vehicle_name": "truck-807",
    "launch_config": "sds_road_readiness",
    "route": "shoreline_straight",
    "enable_japan_driving": False,
}


def write_preset(dir_path, name, entry):
    path = dir_path / f"{name}.json"
    path.write_text(json.dumps(entry), encoding="utf-8")
    return path


class TestLoadShared:
    def test_reads_valid_entries_in_name_order(self, tmp_path):
        for name in ("b_route", "a_route"):
            write_preset(tmp_path, name, VALID)
        shared, rejected = load_shared_presets(str(tmp_path))
        assert list(shared) == ["a_route", "b_route"]
        assert rejected == []
        assert shared["a_route"]["shared"] is True  # the UI's marker

    def test_malformed_json_is_skipped_not_fatal(self, tmp_path):
        write_preset(tmp_path, "good", VALID)
        (tmp_path / "bad.json").write_text("{not json")
        shared, rejected = load_shared_presets(str(tmp_path))
        assert list(shared) == ["good"]
        assert rejected == ["bad"]

    def test_non_json_files_ignored(self, tmp_path):
        write_preset(tmp_path, "good", VALID)
        (tmp_path / "README.md").write_text("not a preset")
        shared, rejected = load_shared_presets(str(tmp_path))
        assert list(shared) == ["good"]
        assert rejected == []

    def test_custom_command_presets_rejected(self, tmp_path):
        # Only values presets share: a raw command is the machine's own.
        write_preset(tmp_path, "raw", {"kind": "command", "command": "start_stack --flag"})
        shared, rejected = load_shared_presets(str(tmp_path))
        assert shared == {}
        assert rejected == ["raw"]

    def test_missing_or_wrong_typed_fields_rejected(self, tmp_path):
        write_preset(tmp_path, "no_route", {k: v for k, v in VALID.items() if k != "route"})
        write_preset(tmp_path, "japan_str", dict(VALID, enable_japan_driving="yes"))
        shared, rejected = load_shared_presets(str(tmp_path))
        assert shared == {}
        assert sorted(rejected) == ["japan_str", "no_route"]

    def test_bad_name_rejected(self, tmp_path):
        # The name becomes a menu title; chars outside letters/digits/
        # spaces/dashes stay out (slashes can't appear in a filename —
        # parse_preset_export covers those via upload names).
        write_preset(tmp_path, "route!", VALID)
        shared, rejected = load_shared_presets(str(tmp_path))
        assert shared == {}
        assert rejected == ["route!"]

    def test_metadata_is_kept(self, tmp_path):
        write_preset(tmp_path, "tagged", dict(VALID, exported_by="jp", exported_at="2026-09-16"))
        shared, _ = load_shared_presets(str(tmp_path))
        assert shared["tagged"]["exported_by"] == "jp"

    def test_missing_directory_is_empty(self, tmp_path):
        shared, rejected = load_shared_presets(str(tmp_path / "nope"))
        assert shared == {}
        assert rejected == []


class TestValidEntry:
    @pytest.mark.parametrize("name", ["a", "Shoreline Demo", "route-2"])
    def test_good_names(self, name):
        assert valid_shared_entry(dict(VALID), name)

    @pytest.mark.parametrize("name", ["", "../etc", "a" * 65, "route!", "a/b"])
    def test_bad_names(self, name):
        assert not valid_shared_entry(dict(VALID), name)

    def test_non_dict_is_invalid(self):
        assert not valid_shared_entry(["not", "a", "dict"], "x")


class TestMerge:
    def test_personal_first_and_wins_on_clash(self):
        # Entries come out of load_shared_presets carrying the marker.
        personal = {"mine": dict(VALID, route="r1")}
        shared = {
            "repo_one": dict(VALID, shared=True),
            "mine": dict(VALID, route="repo_version", shared=True),
        }
        merged = merge_presets(personal, shared)
        assert list(merged) == ["mine", "repo_one"]
        assert merged["mine"]["route"] == "r1"  # the personal copy, in place
        assert merged["repo_one"]["shared"] is True


class TestExport:
    def test_writes_the_share_file_with_provenance(self, tmp_path):
        path = export_preset("night loop", dict(VALID), exports_dir=str(tmp_path))
        assert path == str(tmp_path / "night loop.json")
        entry = json.loads((tmp_path / "night loop.json").read_text())
        assert entry["vehicle_name"] == "truck-807"
        assert entry["kind"] == "values"
        assert entry["exported_at"]  # a timestamp, for the recipient
        assert entry["exported_by"]  # $USER on this machine

    def test_round_trips_through_import(self, tmp_path):
        path = export_preset("night loop", dict(VALID), exports_dir=str(tmp_path))
        name, entry = import_preset_file(path)
        assert name == "night loop"
        assert entry == VALID  # metadata stripped, exactly the saved shape

    def test_custom_commands_cannot_be_shared(self, tmp_path):
        assert export_preset("raw", {"kind": "command", "command": "x"},
                              exports_dir=str(tmp_path)) is None

    def test_shared_entries_are_not_re_exported(self, tmp_path):
        # They already live in the repo — an export would just drift.
        assert export_preset("repo_one", dict(VALID, shared=True),
                              exports_dir=str(tmp_path)) is None

    def test_bad_name_refused_with_the_reason(self, tmp_path):
        with pytest.raises(PresetImportError):
            export_preset("route!", dict(VALID), exports_dir=str(tmp_path))


class TestImport:
    def test_file_name_becomes_preset_name(self, tmp_path):
        path = write_preset(tmp_path, "someone sent this", dict(VALID, kind="values"))
        name, entry = import_preset_file(str(path))
        assert name == "someone sent this"
        assert entry == VALID

    def test_bad_json_says_why(self, tmp_path):
        (tmp_path / "bad.json").write_text("{oops")
        with pytest.raises(PresetImportError):
            import_preset_file(str(tmp_path / "bad.json"))

    def test_custom_command_file_refused(self, tmp_path):
        write_preset(tmp_path, "raw", {"kind": "command", "command": "x"})
        with pytest.raises(PresetImportError):
            import_preset_file(str(tmp_path / "raw.json"))

    def test_bytes_variant_for_the_web_ui(self):
        data = json.dumps(dict(VALID, shared=True, exported_by="jp"))
        name, entry = parse_preset_export(data.encode(), "from web")
        assert name == "from web"
        assert entry == VALID

    def test_missing_file_says_why(self, tmp_path):
        with pytest.raises(PresetImportError):
            import_preset_file(str(tmp_path / "never.json"))
