"""aifaqchat — optional drop-in FastAPI router.

Most sites only need the client-side widget (aifaqchat.js + a faq.json) — it
answers from the KB with zero backend. Mount THIS router only if you also want
free-text questions answered by your LLM, grounded on the same KB.

Dependency-light and host-agnostic: you inject your own LLM call, optional
streaming LLM, optional semantic retriever, rate-limiter, and an unanswered-
question hook, so it carries no product coupling.

    from faq_router import make_faq_router

    def my_llm(system: str, user: str) -> str:
        return my_gateway.complete(system, user, max_tokens=300)   # your stack

    app.include_router(make_faq_router(
        kb_path="faq.json", product="Acme",
        llm=my_llm,                       # omit → returns the best-match KB answer
        llm_stream=my_stream,             # optional: enables POST /ask/stream (SSE)
        retriever=my_semantic_search,     # optional: (items, query, k) -> list[dict]
        rate_limit=lambda req: None,      # optional throttle (raise HTTPException)
        on_unanswered=lambda q: log(q),   # optional: capture KB gaps
    ))
    # → GET  /api/faq/faq   → {"items":[...], "suggest":[...]}
    #   POST /api/faq/ask         {question, history?} → {answer, sources, suggestions}
    #   POST /api/faq/ask/stream  {question, history?} → text/event-stream (if llm_stream)

Then point the widget at it: data-ask="/api/faq/ask" (and optionally
data-stream="/api/faq/ask/stream").
Public by default (KB is marketing content); pass auth=[Depends(...)] to gate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

_WORD = re.compile(r"[a-z0-9]+")

# A single chat turn the client may pass for multi-turn context.
class _Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class _Ask(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[_Turn] = Field(default_factory=list, max_length=12)


def _load_kb(kb_path: str) -> tuple[list[dict], list[str]]:
    raw = json.loads(Path(kb_path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw, [e["id"] for e in raw[:6]]
    items = raw.get("items") or raw.get("entries") or []
    return items, raw.get("suggest") or [e["id"] for e in items[:6]]


def _search(items: list[dict], query: str, k: int = 4) -> list[dict]:
    ql = query.lower()
    toks = set(_WORD.findall(ql))
    scored: list[tuple[int, dict]] = []
    for e in items:
        s = 0
        for kw in e.get("kw", []):
            if kw in ql:
                s += 4 if (" " in kw or len(kw) > 4) else 1
        hay = set(_WORD.findall((e.get("q", "") + " " + e.get("a", "")).lower()))
        s += len(toks & hay)
        if e.get("topic"):
            s += 3 * len(toks & set(_WORD.findall(e["topic"].lower())))
        if s:
            scored.append((s, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:k]]


def _build_system(product: str, contact: str, hits: list[dict]) -> str:
    ctx = "\n\n".join(f"Q: {e.get('q','')}\nA: {e.get('a','')}" for e in hits)
    return (
        f"You are the {product} help assistant. Answer using ONLY the reference Q&A "
        "below. Be concise and friendly (2-4 sentences). If the references don't cover "
        f"it, say you're not sure and suggest reaching {contact} — never invent features "
        "or pricing.\n\nReference Q&A:\n" + ctx
    )


def _build_user(question: str, history: list[_Turn]) -> str:
    """Fold prior turns into the user prompt so the (system, user) LLM contract
    stays stable while still carrying multi-turn context."""
    if not history:
        return question
    convo = "\n".join(f"{t.role.capitalize()}: {t.content}" for t in history[-8:])
    return f"Conversation so far:\n{convo}\n\nUser: {question}"


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def make_faq_router(
    *,
    kb_path: str,
    product: str = "this product",
    contact: str = "support",
    llm: Callable[[str, str], str] | None = None,
    llm_stream: Callable[[str, str], Iterable[str]] | None = None,
    retriever: Callable[[list[dict], str, int], list[dict]] | None = None,
    rate_limit: Callable[[Request], None] | None = None,
    on_unanswered: Callable[[str], None] | None = None,
    prefix: str = "/api/faq",
    auth: list | None = None,
    reload_kb: bool = False,
) -> APIRouter:
    """Build a FAQ router.

    `llm(system, user)->str` enables grounded free-text answers; without it /ask
    returns the best-matching KB entry. `llm_stream(system, user)->iterable[str]`
    enables POST /ask/stream (Server-Sent Events). `retriever(items, query, k)`
    overrides the built-in keyword search (e.g. embeddings). `on_unanswered(q)`
    fires whenever nothing in the KB matches — the most valuable signal for
    improving the KB. `reload_kb` re-reads the file each request (handy in dev).
    """
    router = APIRouter(prefix=prefix, dependencies=auth or [])
    _cache = _load_kb(kb_path)
    find = retriever or _search

    def kb() -> tuple[list[dict], list[str]]:
        return _load_kb(kb_path) if reload_kb else _cache

    def _miss_payload(suggest: list[str]) -> dict:
        return {
            "answer": f"I'm the {product} assistant — try a question from the list, "
                      f"or reach {contact}.",
            "sources": [],
            "suggestions": [{"id": i} for i in suggest],
        }

    @router.get("/faq")
    def get_faq() -> dict:
        items, suggest = kb()
        return {"items": items, "suggest": suggest}

    @router.post("/ask")
    def ask(payload: _Ask, request: Request) -> dict:
        if rate_limit:
            rate_limit(request)
        items, suggest = kb()
        hits = find(items, payload.question, 4)
        if not hits:
            if on_unanswered:
                try:
                    on_unanswered(payload.question)
                except Exception:  # noqa: BLE001 — logging must never 500 the help box
                    pass
            return _miss_payload(suggest)

        related = [{"id": e["id"], "q": e.get("q", "")} for e in hits[1:]]
        if llm is None:
            top = hits[0]
            return {"answer": top.get("a", ""), "sources": [{"id": top["id"]}],
                    "suggestions": related or [{"id": i} for i in suggest]}

        system = _build_system(product, contact, hits)
        user = _build_user(payload.question, payload.history)
        try:
            answer = (llm(system, user) or "").strip() or hits[0].get("a", "")
        except Exception:  # noqa: BLE001 — never 500 the help box
            answer = hits[0].get("a", "")
        return {"answer": answer, "sources": [{"id": e["id"], "q": e.get("q", "")} for e in hits],
                "suggestions": related or [{"id": i} for i in suggest]}

    if llm_stream is not None:
        @router.post("/ask/stream")
        def ask_stream(payload: _Ask, request: Request) -> StreamingResponse:
            if rate_limit:
                rate_limit(request)
            items, suggest = kb()
            hits = find(items, payload.question, 4)

            def gen():
                if not hits:
                    if on_unanswered:
                        try:
                            on_unanswered(payload.question)
                        except Exception:  # noqa: BLE001
                            pass
                    miss = _miss_payload(suggest)
                    yield _sse({"delta": miss["answer"]})
                    yield _sse({"suggestions": miss["suggestions"]})
                    yield "data: [DONE]\n\n"
                    return
                system = _build_system(product, contact, hits)
                user = _build_user(payload.question, payload.history)
                streamed = False
                try:
                    for chunk in llm_stream(system, user):
                        if chunk:
                            streamed = True
                            yield _sse({"delta": chunk})
                except Exception:  # noqa: BLE001 — fall back to the KB answer
                    if not streamed:
                        yield _sse({"delta": hits[0].get("a", "")})
                related = [{"id": e["id"], "q": e.get("q", "")} for e in hits[1:]]
                yield _sse({"suggestions": related or [{"id": i} for i in suggest]})
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
