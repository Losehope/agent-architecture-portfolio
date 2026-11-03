# tiered-agent: a minimal reference architecture

A small, runnable reference for a customer-facing Q&A agent that mixes cheap deterministic paths,
bounded model loops and a slow external specialist agent. It is a clean-room project: all data is
synthetic, there is no company code, and it needs no network or API key by default.

## Product view

One entry point serves four kinds of questions. They differ in answer shape, determinism and latency,
so the product routes by question type instead of running one generic RAG chain:

| Question | Path | If it fails |
|---|---|---|
| benchmark number | deterministic table → bounded tool loop | ask the user to pick a category |
| terminology list | exact match → model tree navigation → clarification card | clarification card |
| policy / rule | light RAG (vector + BM25 + keyword, RRF) → heavy RAG (rewrite + rerank + multi-hop) | explicit "not found" |
| strategy advice | immediate receipt + held draft → specialist reply fused later | send the draft at the deadline |

The reasoning behind each choice — including what was rejected and what it cost — is in
[docs/product-decisions.md](docs/product-decisions.md); the full flows and states are in
[docs/product-design.md](docs/product-design.md). The scenarios and failure modes in both docs are
drawn from about 2,000 anonymized real questions: no customer names, account IDs, group IDs, links
or internal product names are included.

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
| return policy | qa | light RAG (vector + BM25 + keyword, RRF) first; heavy RAG (rewrite + rerank + multi-hop) on low confidence; answer cites its source file |
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
  arms/qa.py        keyword overlap only; light RAG (vector/BM25/keyword + RRF) and heavy RAG are design-only
  async_bridge.py   slow specialist agent, held draft, fusion, timeout flush, idempotent send
  guard.py          deterministic fail-closed output guard
  llm.py            LLM protocol, OpenAI-compatible client, offline MockLLM
docs/               architecture.md, design.md, product.md
tests/test_all.py   23 tests: guard, planner, arms, delivery, end to end
```

## Docs

- [docs/product.md](docs/product.md): product brief — problem, users, capabilities, metrics
- [docs/product-design.md](docs/product-design.md): product design — user tasks, paths, flows, states, reply structure
- [docs/product-decisions.md](docs/product-decisions.md): 9 product decisions, each with alternatives and costs
- [docs/architecture.md](docs/architecture.md): diagram, components, request flows
- [docs/design.md](docs/design.md): engineering decisions and trade-offs
