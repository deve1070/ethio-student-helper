"""Test of /v1/explain's SSE progress stream (api/routes_explain.py): confirms the
stream parses into the expected sequence of {"stage": ...} events followed by one
final {"done": true, ...} event, and that a mid-stream failure (LLMUnavailableError)
surfaces as a {"done": true, "error": ...} event rather than an HTTP error status
(the response is already a 200 text/event-stream by the time a workflow failure can
happen, so it can't become an HTTP error code at that point).
Run from backend/:   python test/test_explain_route.py"""

import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class FakeSession:
    def query(self, *a, **kw):
        return self

    def filter(self, *a, **kw):
        return self

    def __iter__(self):
        return iter([("chemistry",)])

    def close(self):
        pass


stub("db.session", SessionLocal=lambda: FakeSession())
stub("db.models", Textbook=types.SimpleNamespace(subject="subject", grade="grade"))
stub("config")
stub("config.constants", SUPPORTED_GRADES=[9, 10, 11, 12])
sys.modules["config"].constants = sys.modules["config.constants"]
stub("llm.client", LLMClient=lambda **kw: object())


class _Identity:
    """Stands in for DecomposingRetriever: routes_explain.py wraps whatever
    build_textbook_retriever() returns with this, but the fake retriever beneath it
    is never actually invoked (stream_full_pipeline is stubbed below too), so this
    only needs to exist, not do anything."""
    def __init__(self, inner, planner_llm):
        self.inner = inner


stub("retriever.decompose", DecomposingRetriever=_Identity)
stub(
    "retriever.builder",
    RetrieverBuilder=lambda: types.SimpleNamespace(
        build_textbook_retriever=lambda grade, subject: object()
    ),
)

STAGES = ["Checking if your textbook covers this...", "Writing an answer...", "Finding the right pages..."]
FINAL = {"draft_answer": "The answer is X.", "citations": [{"textbook": "Chemistry Grade 9", "unit": "Unit 1"}]}
workflow_state = {"fail": False}


class FakeWorkflow:
    def stream_full_pipeline(self, question, retriever):
        if workflow_state["fail"]:
            from llm.retry import LLMUnavailableError
            raise LLMUnavailableError("busy")
        for s in STAGES:
            yield s
        yield FINAL


stub("agents.workflow", AgentWorkflow=FakeWorkflow)
stub("llm.retry", LLMUnavailableError=type("LLMUnavailableError", (Exception,), {}))

import api.routes_explain as R
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(R.router)
c = TestClient(app)


def parse_sse(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in text.split("\n\n") if line.startswith("data: ")]


# --- bad grade: rejected before streaming starts (pydantic's Field(ge=9, le=12) on
# ExplainRequest catches this before explain()'s body even runs - a 422, not explain()'s
# own 400 check, which is effectively unreachable since SUPPORTED_GRADES is the same [9-12]
# range as that Field constraint) ---
r = c.post("/v1/explain", json={"grade": 7, "subject": "chemistry", "question": "What is an atom?"})
assert r.status_code == 422, r.text

# --- happy path: every stage event, then the final answer event ---
r = c.post("/v1/explain", json={"grade": 9, "subject": "chemistry", "question": "What is an atom?"})
assert r.status_code == 200, r.text
events = parse_sse(r.text)
assert [e["stage"] for e in events[:-1]] == STAGES, events
assert events[-1] == {
    "done": True,
    "answer": "The answer is X.",
    "citations": [{"textbook": "Chemistry Grade 9", "unit": "Unit 1", "page": None}],
    "credits_charged": 0,
}, events[-1]

# --- mid-stream failure: an error event, not an HTTP error status (already 200) ---
workflow_state["fail"] = True
r = c.post("/v1/explain", json={"grade": 9, "subject": "chemistry", "question": "What is an atom?"})
assert r.status_code == 200, r.text
events = parse_sse(r.text)
assert events == [{"done": True, "error": "The AI service is busy or unreachable right now. Please try again in a minute."}], events

print("EXPLAIN ROUTE SSE TESTS PASSED")
