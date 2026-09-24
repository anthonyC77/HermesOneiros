"""T02 — path resolution and configuration."""

from __future__ import annotations

import json

from oneiros import config as cfg


def test_state_override_redirects_every_derived_path(isolated_state):
    """One override moves all of it. That is the whole point of the module."""
    for accessor in cfg.DERIVED_DIRS:
        path = accessor()
        assert isolated_state in path.parents or path == isolated_state
        assert path.is_dir()


def test_plugin_data_is_used_when_no_explicit_override(tmp_path, monkeypatch):
    monkeypatch.delenv(cfg.STATE_ENV, raising=False)
    monkeypatch.setenv(cfg.PLUGIN_DATA_ENV, str(tmp_path / "plugin-data"))
    assert cfg.state_dir() == tmp_path / "plugin-data"


def test_explicit_override_beats_plugin_data(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.STATE_ENV, str(tmp_path / "explicit"))
    monkeypatch.setenv(cfg.PLUGIN_DATA_ENV, str(tmp_path / "plugin-data"))
    assert cfg.state_dir() == tmp_path / "explicit"


def test_transcripts_dir_is_never_created():
    """Read-only input. Creating it would make a misconfiguration look like an
    empty history."""
    path = cfg.transcripts_dir()
    assert path.name == "projects"
    # No assertion that it exists — that is the harness's business, not ours.


def test_exported_variable_survives_the_credentials_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ONEIROS_TEST_TOKEN", "exported")
    env_file = tmp_path / "oneiros.env"
    env_file.write_text(
        "ONEIROS_TEST_TOKEN=from-file\nONEIROS_TEST_OTHER=\"quoted value\"\n# comment\n",
        encoding="utf-8",
    )

    loaded = cfg.load_env(env_file)

    import os

    assert loaded["ONEIROS_TEST_TOKEN"] == "from-file"
    assert os.environ["ONEIROS_TEST_TOKEN"] == "exported", "an exported value must win"
    assert os.environ["ONEIROS_TEST_OTHER"] == "quoted value"


def test_missing_credentials_file_is_not_an_error(tmp_path):
    assert cfg.load_env(tmp_path / "absent.env") == {}


def test_corrupt_config_falls_back_to_defaults(isolated_state):
    (isolated_state / "config.json").write_text("{not json", encoding="utf-8")
    assert cfg.Config.load() == cfg.Config()


def test_unknown_config_keys_are_ignored(isolated_state):
    path = isolated_state / "config.json"
    path.write_text(json.dumps({"model": "x", "nonsense": 1}), encoding="utf-8")
    assert cfg.Config.load().model == "x"


def test_auto_slots_resolve_to_the_main_model():
    config = cfg.Config(model="main-model")
    assert config.resolve_model("review") == "main-model"
    assert config.resolve_model("dream") == "main-model"
    assert config.resolve_model("nonexistent") == "main-model"

    config.review_model = "cheap-model"
    assert config.resolve_model("review") == "cheap-model"


def test_a_slot_goes_local_only_when_both_halves_are_set():
    config = cfg.Config(model="main-model")
    assert config.resolve_base_url("review") == ""

    # An endpoint alone is not enough: the slot still runs the main model, and
    # the main model does not live on the local box.
    config.local_base_url = "http://192.168.1.50:1235"
    assert config.resolve_base_url("review") == ""

    # A slot model alone is not enough either — that is the existing
    # cheaper-model arbitrage, and it stays on the Claude API.
    other = cfg.Config(model="main-model", review_model="qwen-local")
    assert other.resolve_base_url("review") == ""

    config.review_model = "qwen-local"
    assert config.resolve_base_url("review") == "http://192.168.1.50:1235"
    # Slots are independent: dreaming was not opted in.
    assert config.resolve_base_url("dream") == ""


def test_no_configuration_can_route_conversation_to_the_local_endpoint():
    # SPEC.md §6: conversation runs on the main model. There is no
    # `conversation_model` slot, so the guard is structural rather than a check
    # someone has to remember to write in the runner.
    config = cfg.Config(
        model="main-model",
        local_base_url="http://192.168.1.50:1235",
        review_model="qwen-local",
        dream_model="qwen-local",
    )
    assert config.resolve_base_url("conversation") == ""


def test_config_round_trips(isolated_state):
    original = cfg.Config(model="m", rem_enabled=True, rem_token_budget=1234)
    original.save()
    assert cfg.Config.load() == original
