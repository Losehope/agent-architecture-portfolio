"""Orchestrator: plan -> run arms -> compose -> guard; external work is async with a held draft."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .arms.base import ArmResult
from .arms.lookup import LookupArm
from .arms.packs import PackArm
from .arms.qa import QAArm
from .async_bridge import Bridge, Delivery, SpecialistAgent
from .guard import Guard
from .llm import MockLLM
from .planner import make_plan

ANSWER_PROMPT = (
    "[task:answer]\nAnswer the question using only the materials. Keep numbers and tables as written. "
    "End with the list of sources if any."
)


@dataclass
class Reply:
    text: str
    ref: Optional[str] = None
    trace: List[dict] = field(default_factory=list)


class Orchestrator:
    def __init__(self, llm=None, specialist: SpecialistAgent = None, guard: Guard = None,
                 draft_deadline_s: float = 720.0):
        self.llm = llm or MockLLM()
        self.guard = guard or Guard()
        self.arms = {"lookup": LookupArm(self.llm), "pack": PackArm(self.llm), "qa": QAArm()}
        self.delivery = Delivery(self.llm, self.guard, draft_deadline_s)
        self.bridge = Bridge(specialist or SpecialistAgent(), self.delivery)

    def _compose(self, question: str, materials: List[ArmResult]) -> str:
        payload = [{"arm": m.arm, "text": m.text, "sources": m.sources} for m in materials]
        text = self.llm.complete(ANSWER_PROMPT, json.dumps({"question": question, "materials": payload}))
        srcs = sorted({s for m in materials for s in m.sources})
        return text + (f"\n\nSources: {', '.join(srcs)}" if srcs else "")

    def handle(self, question: str) -> Reply:
        trace: List[dict] = []
        plan = make_plan(self.llm, question)
        trace.append({"step": "plan", "kinds": plan.kinds, "source": plan.source})
        materials: List[ArmResult] = []
        for kind in plan.kinds:
            if kind == "external":
                continue
            t0 = time.monotonic()
            res = self.arms[kind].run(question)
            materials.append(res)
            trace.append({"step": "arm", "arm": kind, "meta": res.meta, "ms": round((time.monotonic() - t0) * 1000)})
        draft = self._compose(question, materials) if materials else ""
        if "external" in plan.kinds:
            if not draft:
                draft = self._compose(question, [self.arms["qa"].run(question)])
            ref = self.bridge.submit(question, draft)
            self.delivery.hold_draft(ref, draft)
            trace.append({"step": "external", "ref": ref})
            receipt = f"Your question was accepted for specialist analysis. Reference: {ref}."
            return Reply(receipt, ref, trace)
        text, hits = self.guard.process(draft)
        trace.append({"step": "guard", "hits": hits})
        return Reply(text, None, trace)
