"""Lookup arm: deterministic fast path (L1), bounded model tool loop (L2) only when L1 cannot resolve.

Numbers are never invented: the L2 answer must only contain numbers that appeared in tool results.
"""
from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import ArmResult

_CSV = Path(__file__).parent.parent / "data" / "metrics.csv"
DATA_PERIOD = "2026-W40 (synthetic data)"
LOOP_PROMPT = (
    "[task:lookup_loop]\nYou may call one tool per turn. Reply with JSON only: "
    '{"tool":"query","args":{"channel":?,"category":?,"goal":?}} or {"final":"<answer>"}. '
    "Use only values from vocab. Never write a number that is not in tool_results."
)


class LookupArm:
    def __init__(self, llm, rows: List[Dict[str, str]] = None, max_rounds: int = 2, deadline_s: float = 8.0):
        self.llm, self.max_rounds, self.deadline_s = llm, max_rounds, deadline_s
        if rows is None:
            with _CSV.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.rows = rows
        self.vocab = {k: sorted({r[k] for r in self.rows}) for k in ("channel", "category", "goal")}

    def _match(self, question: str, column: str) -> List[str]:
        q = question.lower()
        return [v for v in self.vocab[column] if v.lower() in q]

    def query(self, channel=None, category=None, goal=None) -> str:
        sel = [r for r in self.rows
               if (not channel or r["channel"] == channel) and (not category or r["category"] == category)
               and (not goal or r["goal"] == goal)]
        sel.sort(key=lambda r: -float(r["spend_share"]))  # order by weight, never display it
        if not sel:
            return ""
        lines = ["| channel | category | goal | cpm | ctr% | cvr% |", "|---|---|---|---|---|---|"]
        lines += [f"| {r['channel']} | {r['category']} | {r['goal']} | {r['cpm']} | {r['ctr']} | {r['cvr']} |"
                  for r in sel]
        return "\n".join(lines) + f"\n\nData period: {DATA_PERIOD}"

    def run(self, question: str) -> ArmResult:
        channels, cats, goals = (self._match(question, c) for c in ("channel", "category", "goal"))
        if cats:  # L1: dimensions resolved, no model call. Unspecified channel means all channels.
            table = self.query(channels[0] if len(channels) == 1 else None, cats[0], goals[0] if goals else None)
            return ArmResult("lookup", table, ["metrics.csv"], {"level": "L1"})
        body = self._loop(question)
        if body:
            return ArmResult("lookup", body, ["metrics.csv"], {"level": "L2"})
        opts = ", ".join(self.vocab["category"])
        return ArmResult("lookup", f"No matching category found. Available categories: {opts}.",
                         [], {"level": "none"})

    def _loop(self, question: str) -> Optional[str]:
        start, results = time.monotonic(), []
        for _ in range(self.max_rounds):
            if time.monotonic() - start > self.deadline_s:
                return None
            req = json.dumps({"question": question, "vocab": self.vocab, "tool_results": results})
            try:
                msg = json.loads(self.llm.complete(LOOP_PROMPT, req))
            except Exception:
                return None
            if "final" in msg:
                return msg["final"] if self._numbers_ok(msg["final"], results) and msg["final"] else None
            args = msg.get("args") or {}
            allowed = {k: v for k, v in args.items() if k in self.vocab and v in self.vocab[k]}
            out = self.query(**allowed) if msg.get("tool") == "query" and allowed else ""
            if not out:
                return None
            results.append(out)
        return None

    @staticmethod
    def _numbers_ok(final: str, results: List[str]) -> bool:
        seen = set(re.findall(r"\d+(?:\.\d+)?", "\n".join(results)))
        return all(n in seen for n in re.findall(r"\d+(?:\.\d+)?", final))
