"""LLM interface. MockLLM runs offline; OpenAICompatLLM talks to any /chat/completions endpoint.

Every system prompt starts with a "[task:<name>]" tag so one interface serves all roles.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import urllib.request
from typing import Protocol


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class OpenAICompatLLM:
    def __init__(self, base_url: str = "", api_key: str = "", model: str = "", timeout: float = 20.0):
        self.base_url = (base_url or os.environ["LLM_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["LLM_API_KEY"]
        self.model = model or os.environ["LLM_MODEL"]
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)["choices"][0]["message"]["content"]


class MockLLM:
    """Deterministic stand-in that implements each task with simple heuristics."""

    def complete(self, system: str, user: str) -> str:
        m = re.match(r"\[task:(\w+)\]", system)
        handler = getattr(self, "_" + (m.group(1) if m else ""), None)
        return handler(user) if handler else ""

    def _plan(self, user: str) -> str:
        from .planner import keyword_prior
        return json.dumps({"intents": [{"kind": k} for k in keyword_prior(user)]})

    def _lookup_loop(self, user: str) -> str:
        req = json.loads(user)
        if req["tool_results"]:
            return json.dumps({"final": req["tool_results"][-1]})
        words = re.findall(r"[a-z]+", req["question"].lower())
        for w in words:
            hit = difflib.get_close_matches(w, [c.lower() for c in req["vocab"]["category"]], n=1, cutoff=0.8)
            if hit:
                cat = next(c for c in req["vocab"]["category"] if c.lower() == hit[0])
                return json.dumps({"tool": "query", "args": {"category": cat}})
        return json.dumps({"final": ""})

    def _navigate(self, user: str) -> str:
        req = json.loads(user)
        words = set(re.findall(r"[a-z]+", req["question"].lower()))
        best, score = None, 0
        for path in req["outline"]:
            s = len(words & set(re.findall(r"[a-z]+", path.lower())))
            if s > score:
                best, score = path, s
        return json.dumps({"path": best})

    def _answer(self, user: str) -> str:
        req = json.loads(user)
        parts = [m["text"] for m in req["materials"]]
        return "\n\n".join(parts)

    def _fuse(self, user: str) -> str:
        req = json.loads(user)
        return "Specialist view:\n" + req["external"].strip() + "\n\nBackground:\n" + req["draft"].strip()
