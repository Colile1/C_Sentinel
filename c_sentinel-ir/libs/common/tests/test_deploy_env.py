"""
test_deploy_env.py - deploy/.env reaches the host-side scripts, and never
overrides a variable that is already set.

Author: Colile
"""

from __future__ import annotations

import os

from common.deploy_env import load_deploy_env, parse_env_lines


def test_parse_skips_comments_blanks_and_strips_quotes():
    pairs = parse_env_lines(["# comment", "", "A=1", "B = two\r", 'C="quoted"', "noequals"])
    assert pairs == {"A": "1", "B": "two", "C": "quoted"}


def test_parse_keeps_equals_signs_inside_values():
    assert parse_env_lines(["URL=bolt://h:7687?a=b"]) == {"URL": "bolt://h:7687?a=b"}


def test_load_adds_missing_variables(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SENTINEL_TEST_NEW=from-file\n", encoding="utf-8")
    monkeypatch.delenv("SENTINEL_TEST_NEW", raising=False)
    assert load_deploy_env(env_file) == 1
    assert os.environ["SENTINEL_TEST_NEW"] == "from-file"
    monkeypatch.delenv("SENTINEL_TEST_NEW")


def test_load_never_overrides_the_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SENTINEL_TEST_SET=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SENTINEL_TEST_SET", "exported")
    assert load_deploy_env(env_file) == 0
    assert os.environ["SENTINEL_TEST_SET"] == "exported"


def test_missing_file_is_a_no_op(tmp_path):
    assert load_deploy_env(tmp_path / "absent.env") == 0
