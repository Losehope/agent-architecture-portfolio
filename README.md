# tiered-agent: a minimal reference architecture

A small, runnable reference for a customer-facing Q&A agent that mixes cheap deterministic paths,
bounded model loops and a slow external specialist agent. It is a clean-room project: all data is
synthetic, there is no company code, and it needs no network or API key by default.

## Run

```bash
PYTHONPATH=src python3 -m tiered_agent.demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Python 3.9+ and the standard library only.

To use a real model, pass an OpenAI-compatible client:

```python
from tiered_agent.llm import OpenAICompatLLM
from tiered_agent.orchestrator import Orchestrator
orch = Orchestrator(llm=OpenAICompatLLM())   # reads LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
```

## What the demo shows

| Question | Plan | Path |
|---|---|---|
| return policy | qa | keyword retrieval, answer cites its source file |
| Apparel CPM/CTR | lookup | L1 deterministic table lookup |
| "Electronic goods" CPM | lookup | L1 misses, L2 bounded tool loop resolves the category |
| hiking boots terms | pack | L0 exact match on the pack tree |
| Home CPM + budget plan | lookup + external | receipt at once, local draft held, fused reply delivered later |

Every reply carries a `trace` with the plan, the arms that ran, timings and guard hits.

## Layout

```
src/tiered_agent/
  planner.py        plan-first intent: model proposes, code validates against a whitelist
  orchestrator.py   plan -> arms -> compose -> guard; hands external work to the bridge
  arms/lookup.py    L1 deterministic, L2 bounded tool loop with a number guard
  arms/packs.py     L0 exact, L1 model tree navigation with timeout, L2 clarification card
  arms/qa.py        keyword retrieval with source names
  async_bridge.py   slow specialist agent, held draft, fusion, timeout flush, idempotent send
  guard.py          deterministic fail-closed output guard
  llm.py            LLM protocol, OpenAI-compatible client, offline MockLLM
docs/               architecture.md, design.md, product.md
tests/test_all.py   23 tests: guard, planner, arms, delivery, end to end
```

## Docs

- [docs/architecture.md](docs/architecture.md): diagram, components, request flows
- [docs/design.md](docs/design.md): design decisions and trade-offs
- [docs/product.md](docs/product.md): product document
