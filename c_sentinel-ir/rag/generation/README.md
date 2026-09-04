# rag/generation/ — **Phase 2**

Turns retrieved evidence into an answer. Kept deliberately separate from retrieval so that the
generation strategy can change without touching the part that has to be explained and defended.

## Files

| File | Responsibility |
|------|----------------|
| `templates.py` | One answer template per intent, filled from the evidence. Template-based generation is explicitly acceptable and fully marked, and it cannot hallucinate — every slot comes from a retrieved node. `generate(evidence) -> Answer` |
| `answer.py` | `Answer` — the answer text, the evidence, and the generation method used. `render()` prints the answer followed by the evidence block |
| `main.py` | `answer_question(question) -> Answer`, and the demo CLI |

`llm_generator.py` was planned here and is **deliberately not built** — see `DECISIONS.md` D-34.

## The rule

An answer may contain no claim that is not present in the evidence, and the evidence block is
printed alongside it — so a marker can check every sentence against the graph.

`rag/tests/test_grounding.py` enforces this mechanically rather than by reading: it extracts every
alert id, event id, technique id and service name from the answer text and asserts each appears in
the evidence's nodes, properties or bound parameters. A template that began asserting "T1110 is
commonly used by ransomware operators" — true, but not in the graph — fails there.

Two consequences of the same rule, both tested:

- **A missing property is omitted, not printed.** Not every optional property is populated; a `User`
  loaded from an event stream carries no `role`. Printing Python's `None` would read as a claim that
  the value is null, which is a claim no retrieved node made.
- **An empty retrieval is answered honestly.** When the graph holds nothing, the answer says so and
  names why. `Answer.is_grounded` is False for those, so the demo distinguishes "here is the answer"
  from "the graph does not know".

## The CLI

```bash
python -m rag.generation.main --questions   # the supported question types
python -m rag.generation.main --demo        # the step-19 question, on a real alert
python -m rag.generation.main "Which alerts affect auth-service?"
```

Needs `NEO4J_*` set and a reachable Neo4j; an answer that does not come from the graph is not an
answer this project prints.

Done when: every question type produces an answer whose claims all map to displayed evidence.
**Done** — evidence at `docs/evidence/step19-rag-answers.txt`.
