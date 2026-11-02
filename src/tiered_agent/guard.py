"""Deterministic, fail-closed output guard. No model is involved.

redact() removes risky columns, tables and sentences. verify() re-checks the result.
process() returns the refusal text if anything is left over or anything raises.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Tuple

_RULES = Path(__file__).parent / "data" / "guard_rules.json"


class Guard:
    def __init__(self, rules: dict = None):
        r = rules or json.loads(_RULES.read_text(encoding="utf-8"))
        self.sensitive = [c.lower() for c in r["sensitive_columns"]]
        self.roster = [c.lower() for c in r["roster_columns"]]
        self.patterns = [re.compile(p, re.I) for p in r["sentence_patterns"]]
        self.refusal = r["refusal"]

    @staticmethod
    def _cells(line: str) -> List[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    def _bad_header(self, header: List[str]) -> Tuple[bool, List[int]]:
        low = [h.lower() for h in header]
        if any(any(k in h for k in self.roster) for h in low):
            return True, []
        drop = [i for i, h in enumerate(low) if any(k in h for k in self.sensitive)]
        return False, drop

    def _redact_table(self, block: List[str], hits: List[str]) -> List[str]:
        whole, drop = self._bad_header(self._cells(block[0]))
        if whole:
            hits.append("table:roster")
            return []
        if not drop:
            return block
        hits.append("table:columns")
        out = []
        for line in block:
            cells = self._cells(line)
            keep = [c for i, c in enumerate(cells) if i not in drop]
            if keep:
                out.append("| " + " | ".join(keep) + " |")
        return out

    def redact(self, text: str) -> Tuple[str, List[str]]:
        hits: List[str] = []
        out: List[str] = []
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            if lines[i].lstrip().startswith("|"):
                j = i
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    j += 1
                out.extend(self._redact_table(lines[i:j], hits))
                i = j
                continue
            pieces = re.split(r"(?<=[.;!?])\s+", lines[i])
            kept = [p for p in pieces if not any(pt.search(p) for pt in self.patterns)]
            if len(kept) != len(pieces):
                hits.append("sentence")
            out.append(" ".join(kept))
            i += 1
        return "\n".join(out).strip(), hits

    def verify(self, text: str) -> List[str]:
        left = [p.pattern for p in self.patterns if p.search(text)]
        for line in text.split("\n"):
            if line.lstrip().startswith("|"):
                whole, drop = self._bad_header(self._cells(line))
                if whole or drop:
                    left.append("table-header")
        return left

    def process(self, text: str) -> Tuple[str, List[str]]:
        try:
            safe, hits = self.redact(text)
            left = self.verify(safe)
            if left or not safe:
                return self.refusal, hits + ["residual"]
            return safe, hits
        except Exception:
            return self.refusal, ["error"]
