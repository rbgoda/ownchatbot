# 🤖 ownchatbot

A tiny, **self-hosted AI chatbot for your website**. Point it at your site → it
crawls the pages and builds a Q&A knowledge base → you drop **one `<script>` tag**
on your site and a chat widget answers visitors, grounded on your content.

- **No lock-in, no SaaS** — runs on your machine (or your server).
- **Free to run** — use [Ollama](https://ollama.com) locally (no API key), or a free
  [Groq](https://console.groq.com/keys) / [Gemini](https://aistudio.google.com/apikey) key.
- **One-tag embed** — plain `<script>`, no iframe, no build step.
- Works even **without any LLM** (falls back to best-matching Q&A).

---

## Quick start

### macOS / Linux

```bash
git clone https://github.com/rbgoda/ownchatbot.git
cd ownchatbot
./run.sh
```

### Windows

```powershell
git clone https://github.com/rbgoda/ownchatbot.git
cd ownchatbot
powershell -ExecutionPolicy Bypass -File run.ps1
```

*(or just double-click **`run.bat`**)*

The first run creates a virtual environment and installs the dependencies
(FastAPI + httpx). Then open:

- **http://localhost:8200** — admin: paste your website URL, click **Build**, copy the embed snippet.
- **http://localhost:8200/demo** — a pretend website with the widget live, so you can test it.

> Prefer to run it by hand? `pip install -r requirements.txt` then
> `python -m uvicorn ownchatbot.server:app --port 8200`.

---

## Add an LLM (optional but recommended)

Without an LLM the bot returns the closest Q&A. For natural, grounded answers,
add one — **two ways**:

**A) In the admin page (easiest).** Open http://localhost:8200, use the
**🧠 AI backend** panel: pick a provider (ChatGPT, Claude, …), paste your key,
click **🔌 Test my key**, then **Save**. It takes effect immediately — no
restart. Your key is stored locally in `llm.json` (git-ignored) and never shown
back in the browser.

**B) In `.env`.** Copy `.env.example` → `.env` and set **one** provider:

```ini
# ChatGPT (OpenAI):
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# …or Claude (Anthropic — via its OpenAI-compatible endpoint):
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-3-5-haiku-latest

# …or free/local: LLM_PROVIDER=ollama (no key) · groq · gemini · openrouter
```

Supported providers: **openai** (ChatGPT), **anthropic** (Claude), ollama,
groq, gemini, openrouter, cerebras, mistral, qwen, deepseek. Any
OpenAI-compatible endpoint works — set `LLM_PROVIDER` plus that provider's
`*_API_KEY` (and optional `*_MODEL` / `*_BASE_URL`).

Restart `run.sh` / `run.ps1` after editing `.env`.

---

## Embed on your real website

After building, the admin page shows a snippet like this — paste it just before
`</body>` on any page:

```html
<script src="http://localhost:8200/aifaqchat.js"
        data-ask="http://localhost:8200/api/faq/ask"
        data-kb="http://localhost:8200/faq.json"
        data-product="Acme Support"
        data-accent="#6c7bff"
        defer></script>
```

When you deploy `ownchatbot` to a real host, swap `http://localhost:8200` for
your server's URL. Handy widget attributes:

| attribute | what it does |
|-----------|--------------|
| `data-product` | name shown in the chat header |
| `data-accent` | brand colour (hex) |
| `data-theme` | `dark` / `light` / `auto` |
| `data-email` | fallback "contact us" address |
| `data-ask` | grounded-answer endpoint (LLM) |
| `data-kb` | knowledge-base JSON URL |

---

## How it works

```
your site ──crawl──▶ pages ──generate──▶ kb.json ──serve──▶ widget
                     (crawler)  (LLM/heuristic)     (FastAPI)  (aifaqchat.js)
```

- `ownchatbot/crawler.py` — fetches a few pages (SSRF-guarded; optional JS render).
- `ownchatbot/generator.py` — turns page text into Q&A (LLM, or keyword heuristic).
- `ownchatbot/faq_router.py` — `/api/faq/ask` grounds answers on the KB only.
- `ownchatbot/web/aifaqchat.js` — the embeddable widget (sanitized HTML, a11y, theming).

## Endpoints

| method | path | purpose |
|--------|------|---------|
| `GET`  | `/` | admin UI |
| `GET`  | `/demo` | demo site with the widget |
| `POST` | `/api/build` | crawl a URL → build the KB (`{url, product?, max_pages?}`) |
| `POST` | `/api/faq/ask` | grounded answer to a question |
| `GET`  | `/faq.json` | the knowledge base |
| `GET`  | `/aifaqchat.js` | the widget script |

## Security notes

- The crawler blocks private/loopback addresses (SSRF guard) — it only fetches public sites.
- Widget answers are HTML-sanitized through an allow-list before rendering.
- `.env` and `kb.json` are git-ignored — your keys and data never get committed.

## License

MIT — see [LICENSE](LICENSE). The widget derives from the open-source
`aifaqchat` component.
