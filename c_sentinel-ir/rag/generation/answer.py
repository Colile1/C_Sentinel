"""
answer.py - the answer, its evidence, and how they are displayed together.

An `Answer` is never just text. It carries the `Evidence` it was built from and
the name of the generation method that built it, and `render()` prints the
answer followed by the evidence block - because the specification's requirement
is not "produce an answer" but "produce an answer whose every claim maps to
displayed retrieved evidence". Printing the two together is what makes that
checkable in the demo.

Author: Colile
"""

from __future__ import annotations

from dataclasses import dataclass

from rag.retrieval.evidence import Evidence


@dataclass(frozen=True)
class Answer:
    """
    Purpose: a generated answer bound to the evidence that grounds it.
    Inputs:  question - what was asked; text - the answer; evidence - what it
             was built from; method - which generator produced it.
    Output:  `render()` prints the answer and then the evidence block.
    """

    question: str
    text: str
    evidence: Evidence
    method: str = "template"

    @property
    def is_grounded(self) -> bool:
        """
        Purpose: whether this answer rests on retrieved evidence at all. A
                 "the graph does not know" answer is honest but not grounded,
                 and the demo distinguishes the two.
        Inputs:  none beyond the instance.
        Output:  True when the evidence holds at least one node.
        """
        return not self.evidence.is_empty

    def render(self) -> str:
        """
        Purpose: the full display - question, answer, then the evidence block
                 under its four required headings.
        Inputs:  none beyond the instance.
        Output:  the block as text.
        """
        return "\n".join(
            [
                f"Question: {self.question}",
                f"Answer: {self.text}",
                f"Generation method: {self.method}",
                "",
                self.evidence.render(),
            ]
        )
