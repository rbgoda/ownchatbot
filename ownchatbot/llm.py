"""chataiq — multi-provider LLM client (OpenAI-compatible), config-driven.

Every provider here speaks the OpenAI `/chat/completions` protocol, so adding
one is a dict entry. Calls take an explicit `cfg` (resolved per-account from the
dashboard Settings), falling back to the server `.env` default.

A config is a plain dict: {name, base, key, model, temperature, max_tokens}.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env(ROOT / ".env")

# ── provider registry ────────────────────────────────────────────────────────
# free: "yes" (no cost at all) · "tier" (generous free tier) · "paid"
PROVIDERS = {
    "openai": {
        "label": "OpenAI (ChatGPT)", "base": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini", "free": "paid", "signup": "https://platform.openai.com/api-keys",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "o4-mini"],
        "note": "ChatGPT models, native OpenAI API. gpt-4o-mini is cheap + great for FAQ. Key at platform.openai.com/api-keys.",
    },
    "anthropic": {
        "label": "Anthropic (Claude)", "base": "https://api.anthropic.com/v1", "key_env": "ANTHROPIC_API_KEY",
        "model": "claude-3-5-haiku-latest", "free": "paid", "signup": "https://console.anthropic.com/settings/keys",
        "models": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest", "claude-sonnet-4-20250514", "claude-opus-4-20250514"],
        "note": "Claude via Anthropic's OpenAI-compatible endpoint (Bearer auth). Haiku is fast + cheap. Key at console.anthropic.com.",
    },
    "ollama": {
        "label": "Ollama (local)", "base": "http://localhost:11434/v1", "key_env": None,
        "model": "llama3.2:1b", "free": "yes", "signup": "https://ollama.com/download",
        "models": ["llama3.2:1b", "llama3.2", "qwen2.5:1.5b", "qwen2.5", "gemma2:2b", "phi3", "mistral"],
        "note": "Runs entirely on your machine. No API key, no cost. Install Ollama, then `ollama pull <model>`.",
    },
    "groq": {
        "label": "Groq", "base": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile", "free": "tier", "signup": "https://console.groq.com/keys",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it", "mixtral-8x7b-32768"],
        "note": "Free tier, extremely fast. Grab a key in seconds at console.groq.com.",
    },
    "gemini": {
        "label": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY", "model": "gemini-2.0-flash", "free": "tier",
        "signup": "https://aistudio.google.com/apikey",
        "models": ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-flash-8b"],
        "note": "Generous free tier. Get a key from Google AI Studio.",
    },
    "openrouter": {
        "label": "OpenRouter (free models)", "base": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY", "model": "meta-llama/llama-3.3-70b-instruct:free", "free": "tier",
        "signup": "https://openrouter.ai/keys",
        "models": ["meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen-2.5-72b-instruct:free",
                   "google/gemma-2-9b-it:free", "mistralai/mistral-7b-instruct:free"],
        "note": "One key, many models — the `:free` ones cost nothing.",
    },
    "cerebras": {
        "label": "Cerebras", "base": "https://api.cerebras.ai/v1", "key_env": "CEREBRAS_API_KEY",
        "model": "llama-3.3-70b", "free": "tier", "signup": "https://cloud.cerebras.ai",
        "models": ["llama-3.3-70b", "llama3.1-8b"],
        "note": "Free tier, very fast inference.",
    },
    "mistral": {
        "label": "Mistral", "base": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY",
        "model": "mistral-small-latest", "free": "tier", "signup": "https://console.mistral.ai",
        "models": ["mistral-small-latest", "open-mistral-nemo", "mistral-large-latest"],
        "note": "Free tier available at console.mistral.ai.",
    },
    "qwen": {
        "label": "Qwen (DashScope)", "base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "key_env": "QWEN_API_KEY", "model": "qwen-plus", "free": "paid",
        "signup": "https://dashscope.console.aliyun.com",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
        "note": "Alibaba DashScope — paid, with trial credits.",
    },
    "deepseek": {
        "label": "DeepSeek", "base": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat", "free": "paid", "signup": "https://platform.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "note": "Low-cost, strong quality.",
    },
}

DEFAULT_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", os.environ.get("QWEN_TEMPERATURE", "0.3")) or 0.3)
DEFAULT_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", os.environ.get("QWEN_MAX_TOKENS", "600")) or 600)


def providers_meta() -> list[dict]:
    """Public metadata for the Settings UI — never includes secrets."""
    out = []
    for name, p in PROVIDERS.items():
        out.append({
            "name": name, "label": p["label"], "free": p["free"], "needs_key": p["key_env"] is not None,
            "signup": p["signup"], "model": p["model"], "models": p["models"], "note": p["note"],
            "env_key_set": bool(p["key_env"] and os.environ.get(p["key_env"], "").strip()),
        })
    return out


def make_config(provider: str, *, model: str | None = None, key: str | None = None,
                base_url: str | None = None, temperature: float | None = None,
                max_tokens: int | None = None) -> dict | None:
    p = PROVIDERS.get(provider)
    if not p:
        return None
    return {
        "name": provider,
        "base": (base_url or p["base"]).rstrip("/"),
        "key": (key or (os.environ.get(p["key_env"], "").strip() if p["key_env"] else "")),
        "model": model or p["model"],
        "temperature": DEFAULT_TEMPERATURE if temperature is None else temperature,
        "max_tokens": DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens,
    }


def env_default() -> dict | None:
    """Resolve the server-wide default from .env (LLM_PROVIDER or first keyed)."""
    explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()
    name = explicit if explicit in PROVIDERS else None
    if name is None:
        for n, p in PROVIDERS.items():
            if p["key_env"] and os.environ.get(p["key_env"], "").strip():
                name = n
                break
    if name is None:
        return None
    up = name.upper()
    return make_config(name, base_url=os.environ.get(f"{up}_BASE_URL"),
                       model=os.environ.get(f"{up}_MODEL"))


def default_name() -> str:
    cfg = env_default()
    return cfg["name"] if cfg else "none"


def available() -> bool:
    return env_default() is not None


def usable(cfg: dict | None) -> bool:
    if not cfg:
        return False
    p = PROVIDERS.get(cfg["name"])
    return bool(p and (cfg.get("key") or p["key_env"] is None))


def _headers(cfg: dict) -> dict:
    h = {"Content-Type": "application/json"}
    if cfg.get("key"):
        h["Authorization"] = f"Bearer {cfg['key']}"
    return h


def _msgs(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def chat(system: str, user: str, cfg: dict | None = None, max_tokens: int | None = None) -> str:
    cfg = cfg or env_default()
    if not usable(cfg):
        raise RuntimeError("no usable LLM provider configured")
    r = httpx.post(f"{cfg['base']}/chat/completions", headers=_headers(cfg),
                   json={"model": cfg["model"], "messages": _msgs(system, user),
                         "temperature": cfg["temperature"], "max_tokens": max_tokens or cfg["max_tokens"]},
                   timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def chat_stream(system: str, user: str, cfg: dict | None = None):
    cfg = cfg or env_default()
    if not usable(cfg):
        raise RuntimeError("no usable LLM provider configured")
    with httpx.stream("POST", f"{cfg['base']}/chat/completions", headers=_headers(cfg),
                      json={"model": cfg["model"], "messages": _msgs(system, user),
                            "temperature": cfg["temperature"], "max_tokens": cfg["max_tokens"], "stream": True},
                      timeout=180) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content")
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta:
                yield delta


def probe(cfg: dict) -> dict:
    """Quick liveness test for the Settings 'Test connection' button."""
    if not usable(cfg):
        return {"ok": False, "error": "Missing API key for this provider."}
    t0 = time.time()
    try:
        out = chat("You are a test. Reply with exactly: OK", "Say OK.", cfg=cfg, max_tokens=8)
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000),
                "sample": (out or "").strip()[:60], "model": cfg["model"], "provider": cfg["name"]}
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text[:160]
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {body or 'request rejected'}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:160]}


# back-compat for any caller using the old name
def provider_name() -> str:
    return default_name()
