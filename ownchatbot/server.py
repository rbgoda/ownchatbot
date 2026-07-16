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
LLM_CFG_PATH = ROOT / "llm.json"                     # UI-saved provider/key (gitignored)


def _load_llmcfg() -> dict:
    try:
        d = json.loads(LLM_CFG_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_llmcfg(d: dict) -> None:
    LLM_CFG_PATH.write_text(json.dumps(d), encoding="utf-8")


def active_cfg():
    """UI-saved config (llm.json) wins; otherwise fall back to .env."""
    rc = _load_llmcfg()
    if rc.get("provider"):
        c = llm.make_config(rc["provider"], key=rc.get("key") or None, model=rc.get("model") or None)
        if llm.usable(c):
            return c
    return llm.env_default()


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


def _llm_call(system: str, user: str) -> str:
    """Dynamic: resolve the active config each call, so a key saved in the admin
    UI takes effect immediately. Returns '' when no LLM → faq_router falls back
    to the best-matching KB answer."""
    cfg = active_cfg()
    if not llm.usable(cfg):
        return ""
    try:
        return llm.chat(system, user, cfg=cfg, max_tokens=450)
    except Exception:  # noqa: BLE001 — never 500 the chat box
        return ""


_meta = _kbdata()
app = FastAPI(title="ownchatbot")

# grounded answers over the KB (LLM optional — without one it returns the best KB match)
app.include_router(make_faq_router(
    kb_path=str(KB_PATH),
    product=_meta.get("product", "this site"),
    contact=_meta.get("contact", "support"),
    llm=_llm_call,
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
    cfg = active_cfg()
    d = _kbdata()
    return {"ok": True, "product": d.get("product", "this site"), "count": len(d.get("items", [])),
            "llm": (cfg or {}).get("name") if llm.usable(cfg) else None,
            "model": (cfg or {}).get("model") if llm.usable(cfg) else None}


# ── LLM backend config (ChatGPT / Claude / …): pick, test, save ──────────────
class LlmCfgIn(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    key: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=120)


def _provider_names() -> list[str]:
    return [m["name"] for m in llm.providers_meta()]


def _friendly_llm_error(e: Exception) -> str:
    import httpx
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403):
            return "Invalid API key (or no access to this model)."
        if code == 404:
            return "Model not found for this provider — pick another model."
        if code == 429:
            return "Rate limited — wait a moment and retry."
        try:
            msg = e.response.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        return f"HTTP {code}: {msg[:120]}" if msg else f"HTTP {code}"
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return "Couldn't reach the provider (check the base URL / your network / that Ollama is running)."
    return str(e)[:160] or "Unknown error"


def _cfg_from(payload: LlmCfgIn):
    """Build a config from the form, reusing a previously-saved key when the box is blank."""
    prov = payload.provider.strip().lower()
    key = payload.key.strip()
    if not key:
        rc = _load_llmcfg()
        if rc.get("provider") == prov:
            key = rc.get("key", "")
    return prov, llm.make_config(prov, key=key or None, model=payload.model.strip() or None)


@app.get("/api/llm/providers")
def llm_providers():
    cfg = active_cfg()
    rc = _load_llmcfg()
    return {"providers": llm.providers_meta(),
            "active": {"provider": (cfg or {}).get("name"), "model": (cfg or {}).get("model"),
                       "usable": bool(llm.usable(cfg)),
                       "source": ("saved" if rc.get("provider") and llm.usable(cfg)
                                  else ("env" if llm.usable(cfg) else None))}}


@app.post("/api/llm/test")
def llm_test(payload: LlmCfgIn):
    prov, cfg = _cfg_from(payload)
    if prov not in _provider_names():
        return JSONResponse({"ok": False, "error": f"Unknown provider '{prov}'."}, status_code=400)
    if not llm.usable(cfg):
        return {"ok": False, "error": "Enter an API key for this provider first."}
    try:
        reply = llm.chat("You are a connection test. Reply with exactly: ok", "ping", cfg=cfg, max_tokens=5)
        return {"ok": True, "model": cfg["model"], "reply": (reply or "").strip()[:60] or "(empty)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "model": cfg["model"], "error": _friendly_llm_error(e)}


@app.post("/api/llm/save")
def llm_save(payload: LlmCfgIn):
    prov, _ = _cfg_from(payload)
    if prov not in _provider_names():
        return JSONResponse({"ok": False, "error": f"Unknown provider '{prov}'."}, status_code=400)
    key = payload.key.strip()
    if not key:                       # model-only change → keep the saved key
        rc = _load_llmcfg()
        if rc.get("provider") == prov:
            key = rc.get("key", "")
    _save_llmcfg({"provider": prov, "key": key, "model": payload.model.strip()})
    cfg = active_cfg()
    return {"ok": True, "provider": prov, "model": (cfg or {}).get("model"), "usable": bool(llm.usable(cfg))}


@app.post("/api/llm/clear")
def llm_clear():
    try:
        LLM_CFG_PATH.unlink()
    except FileNotFoundError:
        pass
    cfg = active_cfg()
    return {"ok": True, "provider": (cfg or {}).get("name"), "usable": bool(llm.usable(cfg))}


class BuildIn(BaseModel):
    url: str = Field(min_length=4, max_length=2000)
    product: str = Field(default="", max_length=80)
    max_pages: int = Field(default=8, ge=1, le=30)
    render: bool = False


@app.post("/api/build")
def build(payload: BuildIn):
    """Crawl the site → generate a Q&A KB → save it. The widget serves it live."""
    cfg = active_cfg()
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
