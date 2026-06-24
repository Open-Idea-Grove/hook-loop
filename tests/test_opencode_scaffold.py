import json

import pytest

from hook_loop.opencode_scaffold import build_opencode_scaffold, install_opencode_scaffold
from hook_loop.dsl import DslError


def _custom_dsl():
    return {
        "loop": {
            "id": "approval_loop",
            "initial_state": "draft",
            "states": ["draft", "reviewing", "accepted", "stopped"],
            "terminal_states": ["accepted", "stopped"],
            "stop_state": "stopped",
            "events": ["submit", "approval_granted"],
            "transitions": [
                {"from": "draft", "event": "submit", "to": "reviewing"},
                {"from": "reviewing", "event": "approval_granted", "to": "accepted"},
            ],
        },
        "codex": {
            "event_map": [
                {"codex_event": "UserPromptSubmit", "when": {"prompt_match": "(?i)submit"}, "emit": "submit"}
            ]
        },
    }


def test_build_opencode_scaffold_generates_plugin_and_dsl(tmp_path):
    files = build_opencode_scaffold(destination=tmp_path, dsl_path=None, profile="software_delivery")

    assert ".opencode/plugins/hook_loop.js" in files
    assert "hook-loop.json" in files
    plugin = files[".opencode/plugins/hook_loop.js"]
    assert "HookLoopPlugin" in plugin
    assert "opencode-hook" in plugin
    assert "Bun.spawn" in plugin
    assert "enforceHookDecision" in plugin
    assert "metadata?.exit" in plugin
    assert "sessionIdFrom(input, output)" in plugin
    assert "session.created" in plugin  # event handler still handles session.created
    assert "blocked by hook-loop stop policy" not in plugin
    assert 'await callHookLoop("session.idle", payload);' in plugin


def test_build_opencode_scaffold_with_dsl_path_embeds_custom_loop(tmp_path):
    dsl_path = tmp_path / "custom.json"
    dsl_path.write_text(json.dumps(_custom_dsl()), encoding="utf-8")

    files = build_opencode_scaffold(destination=tmp_path, dsl_path=dsl_path, profile="custom")
    loop = json.loads(files["hook-loop.json"])
    assert loop["loop"]["id"] == "approval_loop"


def test_build_opencode_scaffold_plugin_uses_absolute_hook_bin(tmp_path):
    files = build_opencode_scaffold(destination=tmp_path, dsl_path=None, profile="software_delivery")
    plugin = files[".opencode/plugins/hook_loop.js"]
    # The plugin must reference hook-loop via an absolute path or Bun.spawn
    assert "HOOK_BIN" in plugin


def test_install_opencode_scaffold_dry_run_does_not_write(tmp_path):
    result = install_opencode_scaffold(
        profile="software_delivery",
        destination=tmp_path,
        dry_run=True,
    )
    assert result.written == []
    assert result.planned
    assert not (tmp_path / ".opencode").exists()


def test_install_opencode_scaffold_writes_plugin_and_dsl(tmp_path):
    result = install_opencode_scaffold(
        profile="software_delivery",
        destination=tmp_path,
        dry_run=False,
    )
    plugin = tmp_path / ".opencode" / "plugins" / "hook_loop.js"
    loop_config = tmp_path / "hook-loop.json"
    assert plugin in result.written
    assert loop_config in result.written
    assert plugin.exists()
    assert loop_config.exists()
    assert "HookLoopPlugin" in plugin.read_text(encoding="utf-8")


def test_install_opencode_scaffold_with_invalid_dsl_raises(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(DslError, match="invalid JSON"):
        install_opencode_scaffold(profile="custom", destination=tmp_path, dry_run=False, dsl_path=broken)
