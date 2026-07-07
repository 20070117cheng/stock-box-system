# -*- coding: utf-8 -*-
import json

from core.config import DEFAULTS, load_config, save_config


def test_defaults_keys():
    for key in ["stop_profit_pct", "fixed_loss_pct", "high_threshold_pct",
                "add_position_size", "initial_size", "default_lookback_months",
                "kd_period", "near_cross_gap"]:
        assert key in DEFAULTS


def test_load_config_overlays_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"stop_profit_pct": 8.0}), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg["stop_profit_pct"] == 8.0
    assert cfg["fixed_loss_pct"] == DEFAULTS["fixed_loss_pct"]


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(str(tmp_path / "nope.json"))
    assert cfg == DEFAULTS


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg = dict(DEFAULTS)
    cfg["fixed_loss_pct"] = 5.0
    save_config(cfg, str(p))
    assert load_config(str(p))["fixed_loss_pct"] == 5.0
