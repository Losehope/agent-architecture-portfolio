"""Run: PYTHONPATH=src python3 -m tiered_agent.demo   (offline, uses MockLLM and synthetic data)"""
from __future__ import annotations

import json
import queue

from .async_bridge import SpecialistAgent
from .orchestrator import Orchestrator

QUESTIONS = [
    "What is the return policy for unused items?",
    "What are the CPM and CTR benchmarks for Apparel on feed?",
    "What are the CPM benchmarks for Electronic goods?",
    "Give me keyword terms for hiking boots",
    "What are the CPM benchmarks for Home and how should we plan the budget?",
]


def main() -> None:
    orch = Orchestrator(specialist=SpecialistAgent(delay_s=0.3))
    for q in QUESTIONS:
        print("=" * 72, "\nQ:", q)
        reply = orch.handle(q)
        print("trace:", json.dumps(reply.trace, ensure_ascii=False))
        print("A:", reply.text)
        if reply.ref:
            try:
                msg = orch.delivery.outbox.get(timeout=5)
                print(f"-- async delivery [{msg.kind}] {msg.ref}:\n{msg.text}")
            except queue.Empty:
                print("-- no async delivery within 5s")


if __name__ == "__main__":
    main()
