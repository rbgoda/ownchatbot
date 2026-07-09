"""ownchatbot server — crawl a site, build a KB, serve the chat widget.

Run:  python -m uvicorn ownchatbot.server:app --port 8200
Then open http://localhost:8200 (admin) — paste a URL, click Build, copy the
embed snippet. Test it live at http://localhost:8200/demo.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import crawler, generator, llm
from .faq_router import make_faq_router

ROOT = Path(__file__).resolve().parents[1]          # repo root (holds .env + kb.json)
WEB = Path(__file__).resolve().parent / "web"
KB_PATH = ROOT / "kb.json"


def _kbdata() -> dict:
    try:
        raw = json.loads(KB_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"product": "this site", "contact": "support", "items": raw}
    except Exception:  # noqa: BLE001
        return {"product": "this site", "contact": "support", "items": []}


def _write_kb(product: str, items: list[dict], contact: str = "support") -> None:
    for i, it in enumerate(items, 1):
        it.setdefault("id", f"q{i}")
    KB_PATH.write_text(json.dumps({"product": product, "contact": contact, "items": items},
                                  ensure_ascii=False, indent=2), encoding="utf-8")


if not KB_PATH.exists():
    _write_kb("this site", [])


def _llm_callable():
    cfg = llm.env_default()
    if not llm.usable(cfg):
        return None

    def _f(system: str, user: str) -> str:
        try:
            return llm.chat(system, user, cfg=cfg, max_tokens=450)
        except Exception:  # noqa: BLE001 — never 500 the chat box
            return ""
    return _f


_meta = _kbdata()
app = FastAPI(title="ownchatbot")

# grounded answers over the KB (LLM optional — without one it returns the best KB match)
app.include_router(make_faq_router(
    kb_path=str(KB_PATH),
    product=_meta.get("product", "this site"),
    contact=_meta.get("contact", "support"),
    llm=_llm_callable(),
    prefix="/api/faq",
    reload_kb=True,     # pick up rebuilds without a restart
))


@app.get("/", response_class=HTMLResponse)
def admin():
    return FileResponse(WEB / "admin.html")


@app.get("/demo", response_class=HTMLResponse)
def demo():
    return FileResponse(WEB / "demo.html")


@app.get("/aifaqchat.js")
def widget():
    return FileResponse(WEB / "aifaqchat.js", media_type="application/javascript")


@app.get("/faq.json")
def faq_json():
    return JSONResponse(_kbdata())


@app.get("/api/status")
def status():
    cfg = llm.env_default()
    d = _kbdata()
    return {"ok": True, "product": d.get("product", "this site"), "count": len(d.get("items", [])),
            "llm": (cfg or {}).get("name") if llm.usable(cfg) else None}


class BuildIn(BaseModel):
    url: str = Field(min_length=4, max_length=2000)
    product: str = Field(default="", max_length=80)
    max_pages: int = Field(default=8, ge=1, le=30)
    render: bool = False


@app.post("/api/build")
def build(payload: BuildIn):
    """Crawl the site → generate a Q&A KB → save it. The widget serves it live."""
    cfg = llm.env_default()
    url = payload.url if payload.url.startswith("http") else "https://" + payload.url
    try:
        pages = crawler.crawl(url, max_pages=payload.max_pages, render=payload.render)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"Crawl failed: {e}"}, status_code=400)
    if not pages:
        return JSONResponse({"error": "Couldn't fetch that URL (blocked, private, or empty)."}, status_code=400)
    items = generator.generate_from_pages(pages, cfg=cfg)
    if not items:
        return JSONResponse({"error": "Fetched the site but couldn't derive any Q&A. Try more pages or a richer page."},
                            status_code=400)
    product = payload.product.strip() or (pages[0].get("title") or url)[:80]
    _write_kb(product, items, contact=_meta.get("contact", "support"))
    return {"ok": True, "product": product, "pages": len(pages), "count": len(items),
            "ai": bool(llm.usable(cfg)), "questions": [it["q"] for it in items]}
