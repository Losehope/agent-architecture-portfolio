"""Plan-first intent layer: the model proposes a plan, code validates it.

Keywords are only a prior used when the model output is unusable; they never override a valid plan.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List

KINDS = ("lookup", "pack", "qa", "external")

PLAN_PROMPT = (
    "[task:plan]\nYou are an intent planner. Reply with JSON only: "
    '{"intents":[{"kind":"lookup|pack|qa|external"}]}. '
    "lookup=benchmark numbers, pack=keyword lists, qa=knowledge questions, "
    "external=strategy advice that needs a specialist agent. One question may need several."
)


@dataclass
class Plan:
    kinds: List[str]
    source: str  # "llm" or "prior"


def keyword_prior(question: str) -> List[str]:
    q = question.lower()
    kinds = []
    if any(w in q for w in ("cpm", "ctr", "cvr", "benchmark", "rate")):
        kinds.append("lookup")
    if any(w in q for w in ("keyword", "search terms", "word pack")):
        kinds.append("pack")
    if any(w in q for w in ("strategy", "recommend", "how should")):
        kinds.append("external")
    return kinds or ["qa"]


def _parse(raw: str) -> List[str]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return []
    try:
        intents = json.loads(m.group(0)).get("intents", [])
    except (ValueError, AttributeError):
        return []
    kinds = []
    for it in intents if isinstance(intents, list) else []:
        k = it.get("kind") if isinstance(it, dict) else None
        if k in KINDS and k not in kinds:
            kinds.append(k)
    return kinds


def make_plan(llm, question: str) -> Plan:
    try:
        kinds = _parse(llm.complete(PLAN_PROMPT, question))
    except Exception:
        kinds = []
    if kinds:
        return Plan(kinds, "llm")
    return Plan(keyword_prior(question), "prior")
