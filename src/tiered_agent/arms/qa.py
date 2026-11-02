"""Knowledge QA arm: tiny keyword retrieval over markdown files, with source names."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from .base import ArmResult

_DOCS = Path(__file__).parent.parent / "data" / "docs"
_STOP = {"the", "a", "an", "is", "are", "of", "to", "for", "and", "in", "do", "i", "how", "what", "can", "my"}


def _tokens(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]


class QAArm:
    def __init__(self, docs: Dict[str, str] = None, top_k: int = 1):
        if docs is None:
            docs = {p.name: p.read_text(encoding="utf-8") for p in sorted(_DOCS.glob("*.md"))}
        self.docs, self.top_k = docs, top_k

    def run(self, question: str) -> ArmResult:
        q = set(_tokens(question))
        scored = []
        for name, text in self.docs.items():
            for para in (p.strip() for p in text.split("\n\n") if p.strip() and not p.startswith("#")):
                score = len(q & set(_tokens(para)))
                if score:
                    scored.append((score, name, para))
        scored.sort(key=lambda x: -x[0])
        top = scored[: self.top_k]
        if not top:
            return ArmResult("qa", "No relevant document found.", [], {"hits": 0})
        text = "\n\n".join(p for _, _, p in top)
        return ArmResult("qa", text, sorted({n for _, n, _ in top}), {"hits": len(top)})
