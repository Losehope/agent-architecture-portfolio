"""Keyword-pack arm: L0 exact match, L1 model tree navigation, L2 clarification card."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .base import ArmResult

_JSON = Path(__file__).parent.parent / "data" / "packs.json"
NAV_PROMPT = (
    "[task:navigate]\nPick the single best path from outline for the question. "
    'Reply with JSON only: {"path":"A/B"} or {"path":null}.'
)


class PackArm:
    def __init__(self, llm, tree: Dict[str, Dict[str, List[str]]] = None, timeout_s: float = 10.0):
        self.llm, self.timeout_s = llm, timeout_s
        self.tree = tree if tree is not None else json.loads(_JSON.read_text(encoding="utf-8"))
        self.paths = [f"{a}/{b}" for a, subs in self.tree.items() for b in subs]

    def _render(self, path: str, level: str) -> ArmResult:
        a, b = path.split("/")
        terms = "\n".join(f"- {t}" for t in self.tree[a][b])
        return ArmResult("pack", f"Keyword pack: {path}\n{terms}", ["packs.json"], {"level": level, "path": path})

    def _navigate(self, question: str) -> Optional[str]:
        box: Dict[str, Optional[str]] = {}

        def work():
            try:
                box["p"] = json.loads(self.llm.complete(
                    NAV_PROMPT, json.dumps({"question": question, "outline": self.paths}))).get("path")
            except Exception:
                box["p"] = None

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(self.timeout_s)
        return box.get("p") if box.get("p") in self.paths else None

    def run(self, question: str) -> ArmResult:
        q = question.lower()
        exact = [p for p in self.paths if p.split("/")[1].lower() in q]
        if len(exact) == 1:
            return self._render(exact[0], "L0")
        path = self._navigate(question)
        if path:
            return self._render(path, "L1")
        return ArmResult("pack", "Which area do you mean? Options: " + ", ".join(self.paths),
                         [], {"level": "L2-clarify"})
