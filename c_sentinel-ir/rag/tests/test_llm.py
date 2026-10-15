"""
test_llm.py - the optional LLM generator falls back to the template on every
failure, and sees only the question and the retrieved evidence.

The Gemini SDK (`google.genai`) is replaced with a fake, so these tests never
reach the network and never need a key.

Author: Colile
"""

from __future__ import annotations

import sys
import types

import pytest

from rag.generation import llm, main
from rag.retrieval.evidence import Evidence, EvidenceNode

QUESTION = "Which alerts affect auth-service?"


def _evidence(empty: bool = False) -> Evidence:
    """Purpose: a one-node evidence block, or an empty one. Inputs: empty.
    Output: an `Evidence`."""
    nodes = () if empty else (EvidenceNode("Alert", "alt-0123456789ab", {"ruleName": "Multiple Failed Logins"}),)
    return Evidence(question=QUESTION, intent="SERVICE_ALERTS", query_key="alerts_for_service", nodes=nodes)


class _FakeModels:
    """Purpose: stands in for `client.models`, recording each request and
    replying with scripted text or raising a scripted error."""

    calls: list[dict] = []
    text: str | None = "Two alerts."
    error: Exception | None = None

    def generate_content(self, **request):
        _FakeModels.calls.append(request)
        if _FakeModels.error is not None:
            raise _FakeModels.error
        return types.SimpleNamespace(text=_FakeModels.text)


class _FakeClient:
    """Purpose: stands in for `genai.Client`."""

    def __init__(self, **_options):
        self.models = _FakeModels()


@pytest.fixture
def fake_sdk(monkeypatch):
    """Purpose: install a fake `google.genai` and a dummy key for one test."""
    _FakeModels.calls, _FakeModels.text, _FakeModels.error = [], "Two alerts.", None
    fake_types = types.SimpleNamespace(
        GenerateContentConfig=lambda **config: config,
        HttpOptions=lambda **options: options,
        ThinkingConfig=lambda **options: options,
    )
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = _FakeClient
    fake_genai.types = fake_types
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return _FakeModels


def test_no_key_never_calls_the_api(fake_sdk, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    assert llm.generate_llm(_evidence()) is None
    assert fake_sdk.calls == []


def test_empty_evidence_never_calls_the_api(fake_sdk):
    assert llm.generate_llm(_evidence(empty=True)) is None
    assert fake_sdk.calls == []


def test_any_api_error_falls_back(fake_sdk):
    fake_sdk.error = RuntimeError("quota exceeded")
    assert llm.generate_llm(_evidence()) is None


def test_an_empty_or_blocked_reply_falls_back(fake_sdk):
    fake_sdk.text = None
    assert llm.generate_llm(_evidence()) is None
    fake_sdk.text = "   "
    assert llm.generate_llm(_evidence()) is None


def test_the_model_sees_only_the_question_and_the_evidence(fake_sdk, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    evidence = _evidence()
    answer = llm.generate_llm(evidence)
    assert answer.text == "Two alerts."
    assert answer.method == "graph-grounded LLM (gemini-2.5-flash)"
    assert answer.evidence is evidence
    request = fake_sdk.calls[0]
    assert request["model"] == "gemini-2.5-flash"
    assert request["contents"] == f"Question: {QUESTION}\n\n{evidence.render()}"
    assert request["config"]["system_instruction"] == llm._SYSTEM_INSTRUCTION


def test_answer_question_falls_back_to_the_template(fake_sdk, monkeypatch):
    fake_sdk.error = RuntimeError("network down")
    monkeypatch.setattr(main, "retrieve", lambda question: _evidence())
    answer = main.answer_question(QUESTION, use_llm=True)
    assert answer.method == "template"


def test_answer_question_defaults_to_the_template(fake_sdk, monkeypatch):
    monkeypatch.setattr(main, "retrieve", lambda question: _evidence())
    assert main.answer_question(QUESTION).method == "template"
    assert fake_sdk.calls == []
