"""Async bridge to a slow external specialist agent, plus the delivery leg.

submit() returns a receipt at once. A local draft is held; when the specialist answer arrives,
Delivery fuses draft and answer into ONE message, passes it through the guard, and sends it.
If the specialist is late, the draft is sent when its deadline passes (flush_expired).
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict

FUSE_PROMPT = (
    "[task:fuse]\nMerge the specialist answer and the background draft into one concise reply. "
    "Keep every number as written. Do not mention that two sources were merged."
)


@dataclass
class Message:
    ref: str
    kind: str  # fused | draft_timeout | late_update
    text: str


class SpecialistAgent:
    """Stand-in for a slow external agent owned by another team."""

    def __init__(self, delay_s: float = 0.2, answer: str = None):
        self.delay_s = delay_s
        self.answer = answer or (
            "Recommended plan: start with feed placements on two top categories and review weekly.\n"
            "Note: the market share of the leading vendor is 31%.")

    def run(self, question: str, context: str) -> str:
        time.sleep(self.delay_s)
        return self.answer


class Delivery:
    def __init__(self, llm, guard, draft_deadline_s: float = 720.0, clock: Callable[[], float] = time.monotonic):
        self.llm, self.guard, self.deadline_s, self.clock = llm, guard, draft_deadline_s, clock
        self.outbox: "queue.Queue[Message]" = queue.Queue()
        self._jobs: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def hold_draft(self, ref: str, draft: str) -> None:
        with self._lock:
            self._jobs[ref] = {"draft": draft, "due": self.clock() + self.deadline_s, "sent": False}

    def _claim(self, ref: str) -> bool:
        with self._lock:
            job = self._jobs.get(ref)
            if job is None or job["sent"]:
                return False
            job["sent"] = True
            return True

    def on_external(self, ref: str, answer: str) -> None:
        job = self._jobs.get(ref)
        if job is None:
            return
        if not self._claim(ref):
            text, _ = self.guard.process(answer)
            self.outbox.put(Message(ref, "late_update", text))
            return
        draft_safe, _ = self.guard.redact(job["draft"])
        ext_safe, _ = self.guard.redact(answer)
        try:
            fused = self.llm.complete(FUSE_PROMPT, json.dumps({"draft": draft_safe, "external": ext_safe}))
        except Exception:
            fused = draft_safe
        text, _ = self.guard.process(fused)  # second pass: the rewriter output is checked too
        self.outbox.put(Message(ref, "fused", text))

    def flush_expired(self) -> int:
        sent = 0
        for ref, job in list(self._jobs.items()):
            if self.clock() >= job["due"] and self._claim(ref):
                text, _ = self.guard.process(job["draft"])
                self.outbox.put(Message(ref, "draft_timeout", text))
                sent += 1
        return sent


class Bridge:
    def __init__(self, agent: SpecialistAgent, delivery: Delivery):
        self.agent, self.delivery = agent, delivery

    def submit(self, question: str, context: str) -> str:
        ref = "Q_" + uuid.uuid4().hex[:8]

        def work():
            try:
                self.delivery.on_external(ref, self.agent.run(question, context))
            except Exception:
                pass  # no answer: flush_expired() will send the held draft

        threading.Thread(target=work, daemon=True).start()
        return ref
