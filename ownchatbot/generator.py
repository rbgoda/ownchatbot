"""chataiq — LLM FAQ generator.

Turns raw source text (crawled pages, pasted text) into clean Q&A pairs. Uses the
multi-provider LLM (chataiq/llm.py). Degrades gracefully: with no LLM configured it
falls back to a heading/paragraph heuristic so the pipeline still produces entries.
"""
from __future__ import annotations

import json
import re

from . import llm

_SYSTEM = (
    "You write concise FAQ entries for a website's help assistant. Given source "
    "content, produce natural question/answer pairs that a visitor would actually "
    "ask. Answer ONLY from the content — never invent features, prices, or claims. "
    "Keep answers to 1-3 sentences. Return STRICT JSON: an array of objects with "
    'keys "q", "a", and "kw" (a list of 3-6 lowercase keywords). No prose, JSON only.'
)


def _truncate(text: str, limit: int = 6000) -> str:
    return text if len(text) <= limit else text[:limit]


def _parse_json_array(raw: str) -> list[dict]:
    raw = raw.strip()
    # tolerate ```json fences / leading prose
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        q = str(item.get("q", "")).strip()
        a = str(item.get("a", "")).strip()
        if not q or not a:
            continue
        kw = item.get("kw") or []
        kw = [str(k).lower().strip() for k in kw if str(k).strip()][:8]
        out.append({"q": q, "a": a, "kw": kw})
    return out


def _keywords(q: str, a: str) -> list[str]:
    stop = {"the", "and", "for", "are", "you", "your", "does", "with", "what", "how", "can", "this", "that", "use"}
    words = re.findall(r"[a-z0-9]{3,}", (q + " " + a).lower())
    seen, kw = set(), []
    for w in words:
        if w in stop or w in seen:
            continue
        seen.add(w)
        kw.append(w)
        if len(kw) >= 6:
            break
    return kw


def _heuristic(text: str, max_items: int) -> list[dict]:
    """No-LLM fallback: split into paragraphs, make a Q from the first line."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 60]
    out = []
    for p in paras[:max_items]:
        first = p.split("\n", 1)[0].strip().rstrip(".")
        q = first if first.endswith("?") else f"What about {first[:60]}?"
        a = p.replace("\n", " ").strip()[:400]
        out.append({"q": q, "a": a, "kw": _keywords(q, a)})
    return out


def generate(text: str, max_items: int = 8, cfg: dict | None = None) -> list[dict]:
    """Return a list of {q, a, kw} from source text, using LLM `cfg` if usable."""
    text = (text or "").strip()
    if not text:
        return []
    if not llm.usable(cfg):
        return _heuristic(text, max_items)
    user = (
        f"Produce up to {max_items} FAQ entries from this content. JSON array only.\n\n"
        + _truncate(text)
    )
    try:
        raw = llm.chat(_SYSTEM, user, cfg=cfg, max_tokens=1200)
    except Exception:  # noqa: BLE001 — fall back rather than fail the source
        return _heuristic(text, max_items)
    items = _parse_json_array(raw)
    if not items:
        return _heuristic(text, max_items)
    for it in items:
        if not it.get("kw"):
            it["kw"] = _keywords(it["q"], it["a"])
    return items[:max_items]


def generate_from_pages(pages: list[dict], per_page: int = 4, total: int = 16, cfg: dict | None = None) -> list[dict]:
    """Generate across crawled pages, capped at `total`."""
    out: list[dict] = []
    for page in pages:
        if len(out) >= total:
            break
        out.extend(generate(page.get("text", ""), max_items=per_page, cfg=cfg))
    # de-dup by lowercased question
    seen, deduped = set(), []
    for it in out:
        key = it["q"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped[:total]
