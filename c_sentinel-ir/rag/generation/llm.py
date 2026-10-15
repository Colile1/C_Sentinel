"""
llm.py - an optional, graph-grounded LLM answer generator for the RAG pipeline.

This is strictly a second generation path alongside rag/generation/templates.py,
never a replacement for it. `generate_llm()` is given ONLY the question and the
already-retrieved `Evidence` block - the same text `Evidence.render()` already
displays as proof of grounding - and is told to answer from that evidence alone.
It never touches retrieval, never sees anything Cypher did not return, and on
any failure (no key, network, timeout, rate limit, bad response) it returns
None so the caller falls back to the template generator, which always works.

Uses the free-tier Google Gemini API (google-genai SDK). Reads GEMINI_API_KEY
and the optional GEMINI_MODEL / GEMINI_MAX_TOKENS / GEMINI_TIMEOUT_SECONDS from
a project-root .env file (never committed - see .gitignore).

Author: Colile
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from rag.generation.answer import Answer
from rag.retrieval.evidence import Evidence

load_dotenv()

#: A fast model on the free tier. The larger flash models answer the same
#: prompt but are often overloaded (503) or slow (504) on the free tier, and
#: gemini-2.5-flash is closed to new keys (404).
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MIN_TIMEOUT_SECONDS = 10.0

_SYSTEM_INSTRUCTION = (
    "You are a SOC analyst assistant. Answer the question using ONLY the graph "
    "evidence provided below. Do not add any fact, name, technique, control or "
    "recommendation that is not present in the evidence. If the evidence does "
    "not contain the answer, say the graph does not hold it. Be concise - two "
    "or three sentences."
    # Without this, the model reads "Retrieved relationships: 0" literally and
    # says the graph holds nothing, when the link is the query itself: the
    # alerts alerts_for_service returns for auth-service ARE auth-service's
    # alerts. It explains how to read the evidence; it adds no facts.
    " How to read the evidence: the Retrieval method section names the Cypher "
    "query that was run and its parameters, and every retrieved node is a "
    "result of that query for those parameters, so it is linked to the "
    "parameter values even when no relationship is listed. The queries mean: "
    "alerts_for_service - alerts affecting the given service; "
    "users_high_severity - users who triggered events behind HIGH or CRITICAL "
    "alerts, with the alert each is linked to; threats_for_service - threats "
    "targeting the service, the weaknesses they exploit and the controls that "
    "mitigate them; controls_for_alert - the threat an alert indicates, the "
    "controls that mitigate it and the runbooks that support the response; "
    "dependency_impact - services that depend on the given service, hops being "
    "the number of dependency steps."
)


def _method_label(model_name: str) -> str:
    """
    Purpose: the generation method string shown in Answer.render(), naming the
             real model so the demo can defend exactly what produced the text.
    Inputs:  model_name - the Gemini model used.
    Output:  the label string.
    """
    return f"graph-grounded LLM ({model_name})"


def generate_llm(evidence: Evidence) -> Answer | None:
    """
    Purpose: try to phrase a grounded answer from already-retrieved evidence
             using Gemini; never invents evidence, never crashes the caller.
    Inputs:  evidence - the Evidence a Cypher query already retrieved.
    Output:  an Answer bound to that same evidence, or None when there is no
             key configured, the evidence is empty, or the call fails for any
             reason - the caller should fall back to the template generator.
    """
    if evidence.is_empty:
        return None

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    model_name = os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
    max_tokens = int(os.getenv("GEMINI_MAX_TOKENS") or "512")
    # Gemini rejects a request deadline under ten seconds with a 400, so a
    # shorter configured timeout is raised to the minimum rather than failing.
    timeout_seconds = max(float(os.getenv("GEMINI_TIMEOUT_SECONDS") or "10"), MIN_TIMEOUT_SECONDS)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        prompt = f"Question: {evidence.question}\n\n{evidence.render()}"

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                max_output_tokens=max_tokens,
                http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
            ),
        )

        text = (response.text or "").strip()
        if not text:
            return None

        return Answer(
            question=evidence.question,
            text=text,
            evidence=evidence,
            method=_method_label(model_name),
        )

    except Exception:  # noqa: BLE001 - any failure falls back to the template
        return None
