import json

from hook_loop.codex_scaffold import build_codex_scaffold, install_codex_scaffold


def test_builds_software_delivery_hooks_json():
    files = build_codex_scaffold(profile="software_delivery", command_prefix="hook-loop")

    assert ".codex/hooks.json" in files
    assert ".codex/hooks/hook_loop_codex.py" in files
    assert "hook-loop.json" in files
    hooks = json.loads(files[".codex/hooks.json"])
    loop = json.loads(files["hook-loop.json"])
    assert "PreToolUse" in hooks["hooks"]
    assert "PermissionRequest" in hooks["hooks"]
    assert "PostToolUse" in hooks["hooks"]
    assert "Stop" in hooks["hooks"]
    assert "codex-hook --event PreToolUse" in json.dumps(hooks)
    assert loop["loop"]["id"] == "software_delivery"


def test_install_scaffold_dry_run_does_not_write_files(tmp_path):
    result = install_codex_scaffold(
        profile="software_delivery",
        target="directory",
        destination=tmp_path,
        dry_run=True,
    )

    assert result.written == []
    assert result.planned
    assert not (tmp_path / ".codex").exists()


def test_install_scaffold_to_directory_writes_codex_files(tmp_path):
    result = install_codex_scaffold(
        profile="software_delivery",
        target="directory",
        destination=tmp_path,
        dry_run=False,
    )

    hooks_json = tmp_path / ".codex" / "hooks.json"
    hook_script = tmp_path / ".codex" / "hooks" / "hook_loop_codex.py"
    loop_config = tmp_path / "hook-loop.json"
    assert hooks_json in result.written
    assert hook_script in result.written
    assert loop_config in result.written
    assert hooks_json.exists()
    assert hook_script.exists()
    assert loop_config.exists()
    assert "hook-loop codex-hook" in hooks_json.read_text(encoding="utf-8")
