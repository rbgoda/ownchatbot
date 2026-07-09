/*!
 * aifaqchat — a self-contained, framework-agnostic chat-style FAQ widget.
 * One <script> tag + a JSON knowledge base. No dependencies, no build step.
 * MIT licensed. https://github.com/rbgoda/aifaqchat
 *
 *   <script src="aifaqchat.js"
 *           data-product="Acme"
 *           data-accent="#6C7BFF"
 *           data-theme="auto"            <!-- dark | light | auto -->
 *           data-kb="/faq.json"
 *           data-ask="/api/faq/ask"      <!-- optional: server LLM answers -->
 *           data-stream="/api/faq/ask/stream" <!-- optional: streamed answers -->
 *           data-email="support@acme.com"
 *           defer></script>
 *
 * Or configure inline (works offline, no fetch):
 *   <script>window.aifaqchat = { product:"Acme", accent:"#6C7BFF", theme:"auto",
 *           items:[{id:"x",q:"…",a:"…",kw:["…"]}], suggest:["x"],
 *           strings:{ placeholder:"Ask…", helpfulPrompt:"Was this helpful?" } };</script>
 *   <script src="aifaqchat.js" defer></script>
 *
 * Behaviour: floating "💬 Ask <product>" button → chat panel with suggested
 * chips + free text. Answers from the KB client-side (offline), or POSTs to
 * `data-ask`/`data-stream` for LLM answers. Answer HTML is sanitized through a
 * small allow-list; minimal markdown is supported. All styles namespaced
 * `.afc-*`; theme via `data-accent`/`data-theme`.
 *
 * API: window.AiFaqChat = { open(), close(), config,
 *   on(event, cb) }  // events: open, close, ask, answer, unanswered, feedback
 */
(function () {
  "use strict";
  if (window.__aifaqchatLoaded) return;
  window.__aifaqchatLoaded = true;

  var script = document.currentScript || (function () {
    var s = document.getElementsByTagName("script"); return s[s.length - 1];
  })();
  var ds = (script && script.dataset) || {};
  var w = window.aifaqchat || {};
  var STR = w.strings || {};
  function pick(k, def) { return ds[k] != null ? ds[k] : (w[k] != null ? w[k] : def); }
  function t(k, def) { return ds[k] != null ? ds[k] : (STR[k] != null ? STR[k] : def); }

  var cfg = {
    product: pick("product", "FAQ"),
    accent: pick("accent", "#6C7BFF"),
    theme: (pick("theme", "dark") || "dark").toLowerCase(), // dark | light | auto
    kb: pick("kb", null),            // URL to a KB JSON
    items: w.items || null,          // OR an inline KB array (skips fetch)
    suggest: w.suggest || null,      // inline suggested ids
    ask: pick("ask", null),          // optional POST endpoint
    stream: pick("stream", null),    // optional SSE streaming endpoint
    log: pick("log", null),          // optional events sink (POST {event,...})
    lead: pick("lead", null),        // optional lead-capture POST endpoint
    handoff: pick("handoff", null),  // optional human-handoff POST endpoint
    email: pick("email", null),      // optional support email for fallbacks
    position: pick("position", "right"),
    mark: pick("mark", null),        // small header badge text
    greeting: pick("greeting", null),
  };
  if (!cfg.mark) cfg.mark = cfg.product.replace(/[^A-Za-z0-9]/g, "").slice(0, 3).toUpperCase() || "FAQ";
  if (!cfg.greeting) cfg.greeting = t("greeting", "Hi! I'm the " + cfg.product + " assistant 👋 Ask me anything, or pick a question below.");

  // ── event emitter ────────────────────────────────────────────────────────────
  var handlers = {};
  function on(ev, cb) { (handlers[ev] = handlers[ev] || []).push(cb); return api; }
  function emit(ev, data) {
    (handlers[ev] || []).forEach(function (cb) { try { cb(data); } catch (e) { /* host handler */ } });
    if (cfg.log) { var body = { event: ev }; for (var k in data) body[k] = data[k]; postJSON(cfg.log, body); }
  }
  function postJSON(url, body) {
    try {
      fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(function () {});
    } catch (e) { /* fire-and-forget */ }
  }

  // ── styles ─────────────────────────────────────────────────────────────────
  var A = cfg.accent;
  var LIGHT = "--afc-bg:#fff;--afc-fg:#1d2430;--afc-bd:#e6e8ee;--afc-bd2:#d7dbe3;--afc-bot:#f5f6f9;--afc-sub:#8a90a0;--afc-chip:#5a616f";
  var css = `
  .afc-scope{--afc-accent:${A};--afc-bg:#15161b;--afc-fg:#e7e9ee;--afc-bd:#262c38;--afc-bd2:#2e3542;--afc-bot:#1a1c22;--afc-sub:#6b7283;--afc-chip:#a8aebc}
  .afc-scope.afc-light{${LIGHT}}
  @media (prefers-color-scheme:light){.afc-scope.afc-auto{${LIGHT}}}
  .afc-fab{position:fixed;bottom:20px;z-index:2147483000;display:inline-flex;align-items:center;gap:6px;
    padding:11px 16px;border:none;border-radius:999px;cursor:pointer;background:var(--afc-accent,${A});
    color:#fff;font:600 13px/1 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;box-shadow:0 6px 22px rgba(0,0,0,.32)}
  .afc-fab:hover{filter:brightness(1.08)}
  .afc-panel{position:fixed;bottom:20px;z-index:2147483000;width:360px;max-width:calc(100vw - 32px);height:520px;
    max-height:calc(100vh - 40px);display:none;flex-direction:column;overflow:hidden;background:var(--afc-bg);color:var(--afc-fg);
    border:1px solid var(--afc-bd);border-radius:14px;box-shadow:0 18px 50px rgba(0,0,0,.5);
    font:400 14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .afc-panel.open{display:flex}
  .afc-r{right:20px} .afc-l{left:20px}
  .afc-head{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--afc-bd)}
  .afc-mark{min-width:30px;height:30px;padding:0 6px;border-radius:8px;background:var(--afc-accent,${A});color:#fff;
    display:grid;place-items:center;font:700 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace}
  .afc-t{font-weight:600;font-size:14px} .afc-s{font-size:11px;color:var(--afc-sub)}
  .afc-x{margin-left:auto;background:none;border:none;color:var(--afc-sub);font-size:22px;line-height:1;cursor:pointer}
  .afc-x:hover{color:var(--afc-fg)}
  .afc-body{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
  .afc-msg{max-width:85%;padding:9px 12px;border-radius:12px;font-size:13.5px;white-space:pre-wrap;word-wrap:break-word}
  .afc-msg.bot{align-self:flex-start;background:var(--afc-bot);border:1px solid var(--afc-bd);border-top-left-radius:3px}
  .afc-msg.user{align-self:flex-end;background:var(--afc-accent,${A});color:#fff;border-top-right-radius:3px}
  .afc-msg a{color:var(--afc-accent,${A})}
  .afc-msg code{background:rgba(127,127,127,.18);padding:1px 5px;border-radius:4px;font-size:.92em}
  .afc-typing{display:inline-flex;gap:4px;align-items:center}
  .afc-typing i{width:6px;height:6px;border-radius:50%;background:var(--afc-sub);animation:afc-b 1s infinite}
  .afc-typing i:nth-child(2){animation-delay:.15s} .afc-typing i:nth-child(3){animation-delay:.3s}
  @keyframes afc-b{0%,60%,100%{opacity:.25}30%{opacity:1}}
  .afc-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px}
  .afc-chip{padding:6px 10px;border-radius:999px;cursor:pointer;font-size:12px;background:transparent;color:var(--afc-chip);border:1px solid var(--afc-bd2)}
  .afc-chip:hover{border-color:var(--afc-accent,${A});color:var(--afc-accent,${A})}
  .afc-fb{display:flex;align-items:center;gap:8px;margin-top:-2px;font-size:12px;color:var(--afc-sub)}
  .afc-fb button{background:none;border:1px solid var(--afc-bd2);border-radius:8px;cursor:pointer;padding:2px 9px;color:var(--afc-sub);font-size:13px}
  .afc-fb button:hover{border-color:var(--afc-accent,${A});color:var(--afc-accent,${A})}
  .afc-input{display:flex;gap:8px;padding:12px 14px;border-top:1px solid var(--afc-bd)}
  .afc-input input{flex:1;padding:9px 12px;border-radius:9px;border:1px solid var(--afc-bd2);background:var(--afc-bot);color:var(--afc-fg);font-size:13.5px}
  .afc-input input:focus{outline:none;border-color:var(--afc-accent,${A})}
  .afc-input button{padding:9px 13px;border-radius:9px;border:none;cursor:pointer;background:var(--afc-accent,${A});color:#fff;font-weight:600}
  .afc-hide{display:none!important}`;
  var stEl = document.createElement("style"); stEl.textContent = css; document.head.appendChild(stEl);

  // ── state + DOM ──────────────────────────────────────────────────────────────
  var KB = [], SUGGEST = [], inited = false, lastFocus = null;
  var side = cfg.position === "left" ? "afc-l" : "afc-r";
  var themeClass = cfg.theme === "light" ? " afc-light" : cfg.theme === "auto" ? " afc-auto" : "";
  var fab = mk("button", "afc-fab afc-scope " + side + themeClass, "💬 " + t("askLabel", "Ask " + cfg.product));
  var panel = mk("div", "afc-panel afc-scope " + side + themeClass);
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", cfg.product + " FAQ assistant");
  panel.innerHTML =
    '<div class="afc-head"><div class="afc-mark">' + esc(cfg.mark) + '</div>' +
    '<div><div class="afc-t">' + esc(cfg.product) + ' ' + esc(t("title", "Assistant")) + '</div>' +
    '<div class="afc-s">' + esc(t("subtitle", "Ask about any feature or plan")) + '</div></div>' +
    '<button class="afc-x" aria-label="' + esc(t("closeLabel", "Close")) + '">×</button></div>' +
    '<div class="afc-body" aria-live="polite"></div>' +
    '<form class="afc-input"><input autocomplete="off" placeholder="' + esc(t("placeholder", "Ask a question…")) + '" aria-label="' + esc(t("inputLabel", "Your question")) + '"/>' +
    '<button type="submit" aria-label="' + esc(t("sendLabel", "Send")) + '">➤</button></form>';
  document.body.appendChild(fab); document.body.appendChild(panel);
  var bodyEl = panel.querySelector(".afc-body"), inputEl = panel.querySelector("input");
  fab.onclick = open; panel.querySelector(".afc-x").onclick = close; panel.querySelector("form").onsubmit = onSubmit;
  document.addEventListener("keydown", onKey);

  // ── KB load (inline or fetched) ──────────────────────────────────────────────
  function setKB(data) {
    KB = Array.isArray(data) ? data : (data.items || data.entries || []);
    SUGGEST = cfg.suggest || (Array.isArray(data) ? null : data.suggest) || KB.slice(0, 6).map(function (e) { return e.id; });
  }
  if (cfg.items) setKB({ items: cfg.items, suggest: cfg.suggest });
  else if (cfg.kb) {
    fetch(cfg.kb, { credentials: "same-origin" }).then(function (r) { return r.json(); })
      .then(setKB).catch(function () { /* offline / missing — free text still works if ask is set */ });
  }

  // ── helpers ──────────────────────────────────────────────────────────────────
  function mk(t2, c, x) { var n = document.createElement(t2); if (c) n.className = c; if (x != null) n.textContent = x; return n; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]; }); }
  function byId(id) { for (var i = 0; i < KB.length; i++) if (KB[i].id === id) return KB[i]; return null; }
  function scroll() { bodyEl.scrollTop = bodyEl.scrollHeight; }

  // Minimal inline markdown → HTML (output is run through sanitize()).
  function md(s) {
    return String(s == null ? "" : s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+|\/[^\s)]*)\)/g, '<a href="$2">$1</a>');
  }

  // Allow-list HTML sanitizer. Parses into an inert <template>, unwraps any tag
  // not on the list (keeping its text), and strips disallowed/unsafe attributes.
  var ALLOWED = { A: ["href"], B: [], STRONG: [], I: [], EM: [], U: [], CODE: [], PRE: [], BR: [], P: [], UL: [], OL: [], LI: [], SPAN: [] };
  function sanitize(html) {
    var tpl = document.createElement("template");
    tpl.innerHTML = String(html == null ? "" : html);
    (function walk(node) {
      var kids = Array.prototype.slice.call(node.childNodes);
      for (var i = 0; i < kids.length; i++) {
        var c = kids[i];
        if (c.nodeType === 1) {
          var tag = c.tagName;
          if (!ALLOWED.hasOwnProperty(tag)) { node.replaceChild(document.createTextNode(c.textContent), c); continue; }
          var attrs = Array.prototype.slice.call(c.attributes);
          for (var a = 0; a < attrs.length; a++) {
            var name = attrs[a].name.toLowerCase();
            if (ALLOWED[tag].indexOf(name) < 0) { c.removeAttribute(attrs[a].name); continue; }
            if (name === "href") {
              var v = (attrs[a].value || "").trim();
              // reject protocol-relative "//evil.com" (it matches a leading "/" but navigates off-site)
              if (/^\/\//.test(v) || !/^(https?:|mailto:|\/|#)/i.test(v)) { c.removeAttribute(attrs[a].name); }
              else if (/^https?:/i.test(v)) { c.setAttribute("target", "_blank"); c.setAttribute("rel", "noopener noreferrer"); }
            }
          }
          walk(c);
        } else if (c.nodeType === 8) { node.removeChild(c); }
      }
    })(tpl.content);
    return tpl.innerHTML;
  }

  function addText(text, who) { var m = mk("div", "afc-msg " + who); m.textContent = text; bodyEl.appendChild(m); scroll(); return m; }
  function addHTML(html, who) { var m = mk("div", "afc-msg " + who); m.innerHTML = sanitize(md(html)); bodyEl.appendChild(m); scroll(); return m; }
  function typing() { var m = mk("div", "afc-msg bot"); var s = mk("span", "afc-typing"); s.appendChild(mk("i")); s.appendChild(mk("i")); s.appendChild(mk("i")); m.appendChild(s); bodyEl.appendChild(m); scroll(); return m; }
  function thinkingThen(cb) { var th = typing(); setTimeout(function () { th.remove(); cb(); }, 260); }

  function chips(ids) {
    if (!ids || !ids.length) return; var wrap = mk("div", "afc-chips");
    ids.forEach(function (id) {
      var e = typeof id === "object" && id.q ? byId(id.id) || id : byId(id); if (!e) return;
      var c = mk("button", "afc-chip", e.q); c.type = "button"; c.onclick = function () { choose(e); }; wrap.appendChild(c);
    });
    if (wrap.childNodes.length) { bodyEl.appendChild(wrap); scroll(); }
  }
  function feedback(info) {
    var wrap = mk("div", "afc-fb");
    var label = mk("span", null, t("helpfulPrompt", "Was this helpful?"));
    var yes = mk("button", null, "👍"); yes.type = "button"; yes.setAttribute("aria-label", t("helpfulYes", "Yes, helpful"));
    var no = mk("button", null, "👎"); no.type = "button"; no.setAttribute("aria-label", t("helpfulNo", "No, not helpful"));
    function done(val) { wrap.textContent = t("thanks", "Thanks for the feedback!"); emit("feedback", { question: info.question, answer: info.answer, id: info.id, helpful: val }); }
    yes.onclick = function () { done(true); }; no.onclick = function () { done(false); };
    wrap.appendChild(label); wrap.appendChild(yes); wrap.appendChild(no);
    bodyEl.appendChild(wrap); scroll();
  }
  function botAnswer(html, ids, info) {
    addHTML(html, "bot"); chips(ids);
    info = info || {};
    if (info.answered) feedback(info);
    emit("answer", info);
  }
  function suggestExcept(id) { return (SUGGEST || []).filter(function (s) { return (s.id || s) !== id; }).slice(0, 4); }
  function choose(e) { addText(e.q, "user"); thinkingThen(function () { botAnswer(e.a, suggestExcept(e.id), { question: e.q, answer: e.a, answered: true, source: "kb", id: e.id }); }); }

  function match(text) {
    var ql = " " + text.toLowerCase() + " ";
    var toks = {}; (text.toLowerCase().match(/[a-z0-9]+/g) || []).forEach(function (x) { if (x.length > 2) toks[x] = 1; });
    var best = null, score = 0;
    for (var i = 0; i < KB.length; i++) {
      var e = KB[i], s = 0, kw = e.kw || [];
      for (var k = 0; k < kw.length; k++) if (ql.indexOf(kw[k]) >= 0) s += (kw[k].indexOf(" ") >= 0 || kw[k].length > 4 ? 2 : 1);
      var hay = {}; ((e.q + " " + e.a).toLowerCase().match(/[a-z0-9]+/g) || []).forEach(function (x) { hay[x] = 1; });
      for (var tk in toks) if (hay[tk]) s += 1;
      if (e.topic) (e.topic.toLowerCase().match(/[a-z0-9]+/g) || []).forEach(function (x) { if (toks[x]) s += 3; });
      if (s > score) { score = s; best = e; }
    }
    return score >= 2 ? best : null;
  }
  function offlineAnswer(v) {
    var e = match(v);
    if (e) { botAnswer(e.a, suggestExcept(e.id), { question: v, answer: e.a, answered: true, source: "kb", id: e.id }); return; }
    emit("unanswered", { question: v, source: "kb" });
    var tail = cfg.email ? " or email <a href='mailto:" + esc(cfg.email) + "'>" + esc(cfg.email) + "</a>" : "";
    botAnswer(t("fallback", "I'm the " + cfg.product + " assistant — try a question below") + tail + ".", SUGGEST, { question: v, answer: null, answered: false, source: "none" });
  }

  function serverAnswer(v) {
    emit("ask", { question: v });
    var th = typing();
    fetch(cfg.ask, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: v }) })
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) {
        th.remove();
        var sug = (d.suggestions || []).map(function (s) { return s.id || s; }).filter(Boolean).slice(0, 4);
        var answered = !!(d.answer && d.sources && d.sources.length);
        botAnswer(d.answer || "", sug.length ? sug : SUGGEST, { question: v, answer: d.answer, answered: answered, source: "server" });
        if (!answered) emit("unanswered", { question: v, source: "server" });
      })
      .catch(function () { th.remove(); offlineAnswer(v); });
  }

  function streamAnswer(v) {
    emit("ask", { question: v });
    var th = typing(), started = false, msg = null, acc = "", pendingSug = null;
    function ensure() { if (!started) { started = true; if (th) th.remove(); msg = mk("div", "afc-msg bot"); bodyEl.appendChild(msg); } }
    function append(s) { ensure(); acc += s; msg.innerHTML = sanitize(md(acc)); scroll(); }
    function finish() {
      if (!started && th) th.remove();
      var sug = (pendingSug || []).map(function (s) { return s.id || s; }).filter(Boolean).slice(0, 4);
      chips(sug.length ? sug : SUGGEST);
      var answered = acc.trim().length > 0;
      if (answered) feedback({ question: v, answer: acc }); else emit("unanswered", { question: v, source: "server" });
      emit("answer", { question: v, answer: acc, answered: answered, source: "server" });
    }
    fetch(cfg.stream, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: v }) })
      .then(function (r) {
        if (!r.ok || !r.body) throw 0;
        var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
        return (function pump() {
          return reader.read().then(function (res) {
            if (res.done) { finish(); return; }
            buf += dec.decode(res.value, { stream: true });
            var parts = buf.split("\n\n"); buf = parts.pop();
            parts.forEach(function (block) {
              block.split("\n").forEach(function (line) {
                if (line.indexOf("data:") !== 0) return;
                var data = line.slice(5).trim();
                if (!data || data === "[DONE]") return;
                try { var j = JSON.parse(data); if (j.delta) append(j.delta); if (j.suggestions) pendingSug = j.suggestions; }
                catch (e) { append(data); }
              });
            });
            return pump();
          });
        })();
      })
      .catch(function () { if (th && !started) { th.remove(); offlineAnswer(v); } else finish(); });
  }

  function onSubmit(ev) {
    ev.preventDefault();
    var v = inputEl.value.trim(); if (!v) return;
    inputEl.value = ""; addText(v, "user");
    if (cfg.stream) streamAnswer(v);
    else if (cfg.ask) serverAnswer(v);
    else thinkingThen(function () { offlineAnswer(v); });
  }

  function onKey(e) {
    if (!panel.classList.contains("open")) return;
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key === "Tab") {
      var f = panel.querySelectorAll('button,input,a[href],[tabindex]:not([tabindex="-1"])');
      if (!f.length) return; var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }

  // ── lead / handoff action chips + inline form ────────────────────────────────
  function actionChips() {
    if (!cfg.lead && !cfg.handoff) return;
    var wrap = mk("div", "afc-chips");
    if (cfg.lead) { var l = mk("button", "afc-chip", "✉️ " + t("leadLabel", "Leave your email")); l.type = "button"; l.onclick = function () { actionForm("lead"); }; wrap.appendChild(l); }
    if (cfg.handoff) { var h = mk("button", "afc-chip", "💬 " + t("handoffLabel", "Talk to a human")); h.type = "button"; h.onclick = function () { actionForm("handoff"); }; wrap.appendChild(h); }
    bodyEl.appendChild(wrap); scroll();
  }
  function actionForm(kind) {
    var form = mk("div", "afc-msg bot");
    var isLead = kind === "lead";
    var title = isLead ? t("leadPrompt", "Drop your email and we'll get back to you.") : t("handoffPrompt", "Leave a message and how to reach you — a human will follow up.");
    form.appendChild(mk("div", null, title));
    var email = mk("input"); email.type = "email"; email.placeholder = t("emailPlaceholder", "you@email.com"); styleField(email);
    var msg = null;
    form.appendChild(email);
    if (!isLead) { msg = mk("textarea"); msg.placeholder = t("messagePlaceholder", "How can we help?"); styleField(msg); msg.style.minHeight = "54px"; form.appendChild(msg); }
    var send = mk("button", "afc-chip", t("submitLabel", "Send")); send.type = "button"; send.style.marginTop = "8px";
    send.onclick = function () {
      var e = (email.value || "").trim();
      if (isLead && !e) { email.focus(); return; }
      if (!isLead && msg && !(msg.value || "").trim()) { msg.focus(); return; }
      var url = isLead ? cfg.lead : cfg.handoff;
      postJSON(url, isLead ? { email: e } : { email: e, message: (msg.value || "").trim() });
      emit(isLead ? "lead" : "handoff", { email: e });
      form.innerHTML = ""; form.appendChild(mk("div", null, t("thanksAction", "Thanks — we'll be in touch! ✓")));
    };
    form.appendChild(send); bodyEl.appendChild(form); scroll(); setTimeout(function () { email.focus(); }, 30);
  }
  function styleField(el) {
    el.style.cssText = "display:block;width:100%;margin-top:6px;padding:8px 10px;border-radius:8px;border:1px solid var(--afc-bd2,#2e3542);background:var(--afc-bot,#1a1c22);color:var(--afc-fg,#e7e9ee);font-size:13px;box-sizing:border-box";
  }

  function open() {
    lastFocus = document.activeElement;
    panel.classList.add("open"); fab.classList.add("afc-hide");
    if (!inited) { inited = true; addHTML(cfg.greeting, "bot"); chips(SUGGEST); actionChips(); }
    emit("open", {});
    setTimeout(function () { inputEl.focus(); }, 50);
  }
  function close() {
    panel.classList.remove("open"); fab.classList.remove("afc-hide");
    emit("close", {});
    (lastFocus && lastFocus.focus ? lastFocus : fab).focus();
  }

  var api = { open: open, close: close, config: cfg, on: on, _test: { match: match, sanitize: sanitize, md: md } };
  window.AiFaqChat = api;
})();
