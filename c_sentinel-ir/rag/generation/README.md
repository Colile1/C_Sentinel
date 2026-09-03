# rag/generation/ — **Phase 2**

Turns retrieved evidence into an answer. Kept deliberately separate from retrieval so that the
generation strategy can change without touching the part that has to be explained and defended.

## Planned files

| File | Responsibility |
|------|----------------|
| `templates.py` | One answer template per intent, filled from the evidence. Template-based generation is explicitly acceptable and fully marked, and it cannot hallucinate — every slot comes from a retrieved node |
| `llm_generator.py` | Optional: the same evidence passed to an LLM under a strict grounding instruction. Selected by configuration, never the default. Falls back to templates when no key is configured |
| `answer.py` | `Answer` — the answer text, the evidence, and the retrieval method used. `render()` prints the answer followed by the evidence block |
| `main.py` | The question-answering entry point and a small CLI for the demo |

## The rule

An answer may contain no claim that is not present in the evidence. When the LLM path is used, the
prompt supplies the retrieved subgraph and forbids outside knowledge, and the evidence block is
printed regardless — so a marker can check every sentence against the graph.

Whether the demo uses the LLM path or the template path is an open question in `plans.md`, closing
at build step 19. Templates are the safe default; the LLM is an upgrade, not a dependency.

Done when: the same question answered through both paths yields the same facts, and both display
the same evidence.
