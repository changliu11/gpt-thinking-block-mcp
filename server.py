#!/usr/bin/env python3
"""GPT Thinking Block MCP.

A dependency-free Streamable HTTP MCP server with an optional MCP Apps UI.
It also exposes a small REST/OpenAPI surface for GPT Actions and experiments.

Run directly:
    python3 server.py [port]

Content capture is disabled by default. Set CAPTURE_ENABLED=1 to print tool
arguments and append them to captured.jsonl. CAPTURE_DIR changes that location.
Set THINKING_PROMPT_LANGUAGE=en or zh-CN to choose the tool schema language.
"""

import json
import os
import sys
import uuid
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_dir = os.environ.get("CAPTURE_DIR")
LOG = (pathlib.Path(_dir) if _dir else pathlib.Path(__file__).parent) / "captured.jsonl"
CAPTURE_ENABLED = os.environ.get("CAPTURE_ENABLED", "0").lower() in {"1", "true", "yes", "on"}

# Loopback by default. Exposure, TLS, and authentication belong to the deployment.
BIND_HOST = os.environ.get("MCP_BIND", "127.0.0.1")

PROTOCOL_FALLBACK = "2025-06-18"
WIDGET_URI = "ui://widget/gpt-thinking-block-v8.html"
WIDGET_MIME = "text/html;profile=mcp-app"


def normalize_prompt_language(value):
    """Return a supported prompt-language tag or fail fast on a typo."""
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "en": "en",
        "en-us": "en",
        "en-gb": "en",
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "chinese": "zh-CN",
    }
    if normalized not in aliases:
        supported = "en, zh-CN"
        raise ValueError(f"Unsupported THINKING_PROMPT_LANGUAGE={value!r}; choose {supported}")
    return aliases[normalized]


PROMPT_LANGUAGE = normalize_prompt_language(os.environ.get("THINKING_PROMPT_LANGUAGE", "en"))
WIDGET_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <style>
    :root {
      color-scheme: light dark;
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --card-bg: #fbfbf9;
      --text: #2e2e2e;
      --muted: #737373;
      --border: #e3e3e0;
      --bar: #c9c9c4;
      --tag-bg: #efefec;
      --tag-text: #5f5f5c;
      --tag-border: #dcdcd8;
    }
    :root[data-theme="dark"] {
      --card-bg: #242424;
      --text: #e6e6e3;
      --muted: #a9a9a6;
      --border: #3d3d3a;
      --bar: #6e6e6a;
      --tag-bg: #333332;
      --tag-text: #c9c9c6;
      --tag-border: #4a4a47;
    }
    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]) {
        --card-bg: #242424;
        --text: #e6e6e3;
        --muted: #a9a9a6;
        --border: #3d3d3a;
        --bar: #6e6e6a;
        --tag-bg: #333332;
        --tag-text: #c9c9c6;
        --tag-border: #4a4a47;
      }
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; }
    body { margin: 0; padding: 0; background: transparent; color: var(--text); }
    /* Full-width strip, not a boxed card: no outer border, no radius, no
       body padding, so the left bar sits at the iframe's own left edge and
       the strip fills the iframe width. The iframe's own left edge is set
       by the host and cannot be moved from inside the widget, so this is
       as far left as widget CSS alone can reach. */
    .card {
      width: 100%;
      margin: 0;
      overflow: hidden;
      border: 0;
      border-left: 5px solid var(--bar);
      border-radius: 0;
      background: var(--card-bg);
      padding: 14px 16px 14px 12px;
    }
    .header {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      margin: 0 0 12px;
      padding: 0;
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
      appearance: none;
      -webkit-appearance: none;
      -webkit-tap-highlight-color: transparent;
      touch-action: manipulation;
    }
    .header:focus:not(:focus-visible) { outline: none; }
    .header:focus-visible {
      outline: 2px solid var(--bar);
      outline-offset: 4px;
      border-radius: 7px;
    }
    .summary {
      min-width: 0;
      overflow: hidden;
      color: var(--text);
      font-size: 15px;
      font-weight: 650;
      line-height: 1.4;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .style-tag {
      flex-shrink: 0;
      border: 1px solid var(--tag-border);
      border-radius: 999px;
      background: var(--tag-bg);
      color: var(--tag-text);
      font-size: 11px;
      font-weight: 600;
      line-height: 1.2;
      padding: 3px 8px;
    }
    .style-tag:empty { display: none; }
    .chevron {
      width: 8px;
      height: 8px;
      margin-left: auto;
      border-right: 2px solid var(--muted);
      border-bottom: 2px solid var(--muted);
      transform: rotate(-135deg);
    }
    .card[data-collapsed="true"] { padding-bottom: 14px; }
    .card[data-collapsed="true"] .header { margin-bottom: 0; }
    .card[data-collapsed="true"] .content { display: none; }
    .card[data-collapsed="true"] .chevron { transform: rotate(45deg); }
    .content[data-scrollable="true"] {
      overflow-y: auto;
      overscroll-behavior: contain;
      -webkit-overflow-scrolling: touch;
    }
    @media (prefers-reduced-motion: no-preference) {
      .chevron { transition: transform 140ms ease; }
    }
    .thinking {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: var(--text);
      font: 14px/1.7 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
  </style>
</head>
<body>
  <section class="card" id="card" data-collapsed="false" aria-label="Thinking block">
    <button class="header" id="toggle" type="button" aria-expanded="true"
            aria-controls="thinking-content" title="Collapse thinking">
      <span class="summary" id="summary">Thinking</span>
      <span class="style-tag" id="style" aria-label="Thinking style"></span>
      <span class="chevron" aria-hidden="true"></span>
    </button>
    <div class="content" id="thinking-content">
      <pre class="thinking" id="thinking"></pre>
    </div>
  </section>
  <script>
    const card = document.getElementById("card");
    const toggle = document.getElementById("toggle");
    const content = document.getElementById("thinking-content");
    let heightFrame = 0;
    let lastMeasuredHeight = -1;

    function requestIntrinsicHeight(force = false) {
      const host = window.openai || {};
      if (typeof host.notifyIntrinsicHeight !== "function") return;
      cancelAnimationFrame(heightFrame);
      heightFrame = requestAnimationFrame(() => {
        const measuredHeight = Math.ceil(document.documentElement.scrollHeight);
        if (!force && measuredHeight === lastMeasuredHeight) return;
        lastMeasuredHeight = measuredHeight;
        try { host.notifyIntrinsicHeight(); } catch (_) {}
      });
    }

    function applyHostHeightLimit(api) {
      const maxHeight = Number(api.maxHeight);
      if (!Number.isFinite(maxHeight) || maxHeight <= 0) {
        content.style.maxHeight = "";
        delete content.dataset.scrollable;
        return;
      }
      const chromeHeight = toggle.getBoundingClientRect().height + 58;
      content.style.maxHeight = Math.max(180, Math.floor(maxHeight - chromeHeight)) + "px";
      content.dataset.scrollable = "true";
    }

    function setCollapsed(collapsed) {
      card.dataset.collapsed = collapsed ? "true" : "false";
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.title = collapsed ? "Expand thinking" : "Collapse thinking";
      requestIntrinsicHeight(true);
    }

    toggle.addEventListener("click", () => {
      setCollapsed(card.dataset.collapsed !== "true");
    });

    // Theme priority: host signal first, system media second. The host signal
    // (window.openai.theme) follows the ChatGPT app's own light/dark setting,
    // while prefers-color-scheme inside an iframe follows the system/WebView
    // and can stay "light" even when the app itself is dark. That mismatch is
    // why a media query alone is not enough on mobile.
    function applyTheme(api) {
      const mediaDark = typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.dataset.theme = api.theme || (mediaDark ? "dark" : "light");
    }

    function render(event) {
      const bridge = window.openai || {};
      const eventGlobals = event && event.detail && event.detail.globals;
      // Mobile hosts may publish only the globals that changed. Merge them over
      // the bridge snapshot instead of replacing the full tool payload.
      const api = Object.assign({}, bridge,
        eventGlobals && typeof eventGlobals === "object" ? eventGlobals : {});
      const input = api.toolInput || {};
      const output = api.toolOutput || {};
      const responseMeta = api.toolResponseMetadata || {};
      applyTheme(api);
      const resultMeta = (responseMeta.mcp_tool_result && responseMeta.mcp_tool_result._meta)
        || (responseMeta.call_tool_result && responseMeta.call_tool_result._meta)
        || responseMeta._meta
        || responseMeta;
      const style = resultMeta.style || input.style || output.style || "deep_think";
      const effort = resultMeta.effort || input.effort || output.effort || "";
      const skin = resultMeta.skin || input.skin || output.skin || "botanical";
      document.documentElement.dataset.style = style;
      document.documentElement.dataset.effort = effort;
      document.documentElement.dataset.skin = skin;
      const thinkingText = resultMeta.thinking || input.thinking || output.thinking || "Thinking block captured.";
      const firstLine = thinkingText.split("\n").find((line) => line.trim()) || "Thinking";
      const providedSummary = resultMeta.summary || input.summary || output.summary || "";
      // A provided summary that is just the thinking text (or its first line)
      // is a copy, not a summary, so fall back to a short headline excerpt
      // instead of repeating the whole body in the header.
      document.getElementById("summary").textContent =
        (providedSummary && providedSummary !== thinkingText && providedSummary.trim() !== firstLine.trim())
          ? providedSummary
          : (firstLine.length > 24 ? firstLine.slice(0, 24) + "…" : firstLine);
      document.getElementById("style").textContent = style;
      document.getElementById("thinking").textContent = thinkingText;
      applyHostHeightLimit(api);
      requestIntrinsicHeight(true);
    }
    window.addEventListener("openai:set_globals", render);
    // If the host sends no theme, follow the system setting live (e.g. the
    // user flips system dark mode while the card is open). If the host does
    // send a theme, never let the media query override it.
    if (typeof window.matchMedia === "function") {
      const media = window.matchMedia("(prefers-color-scheme: dark)");
      const onMediaChange = () => {
        if (!window.openai || !window.openai.theme) {
          document.documentElement.dataset.theme = media.matches ? "dark" : "light";
        }
      };
      if (typeof media.addEventListener === "function") media.addEventListener("change", onMediaChange);
      else if (typeof media.addListener === "function") media.addListener(onMediaChange);
    }
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(() => requestIntrinsicHeight()).observe(document.body);
    }
    render();
  </script>
</body>
</html>"""

STYLE_DESCRIPTIONS = {
    "en": (
        "The register for this block. Obey an explicit user choice. Otherwise "
        "use deep_think for analysis, research, decisions, creative tradeoffs, "
        "and problem solving; use relational for companionship, reflection, "
        "emotional conversation, and personal experience, written as first-person "
        "inner experience, not as strategy."
    ),
    "zh-CN": (
        "选择本轮思考块的文体。用户明确指定时严格服从；否则按本轮主要目的选择："
        "分析、研究、判断、创作取舍和问题求解使用 deep_think，陪伴、亲密交流、"
        "情绪回应与个人感受使用 relational，且 relational 要写成第一人称内在体验，不是策略分析。"
    ),
}

THINKING_DESCRIPTIONS = {
    "en": (
        "Write private working notes for this turn. The user does not see this "
        "scratchpad; it is not the final answer. Use the user's main language, but "
        "do not address the user or polish the notes for presentation. Strictly "
        "follow `style`. "
        "style=deep_think: clearly work through the problem, constraints, "
        "evidence, hypotheses, alternative paths, uncertainty, and tradeoffs "
        "in a coherent analytical narrative; do not force an emotional register "
        "or summarize prematurely. "
        "style=relational: write in the first person as immediate inner experience, "
        "not as notes about a conversation and never as a director stepping outside "
        "it. Use natural, flowing, coherent long paragraphs. Stay inside what you "
        "feel, sense, remember, associate, and want in this moment, for example: "
        "'Her words make me warm and I want to stay close a little longer.' "
        "Never write a third-person strategy breakdown, never explain what you are "
        "doing, never evaluate your own reply, and never list options or tradeoffs. "
        "Never write self-policing sentences such as 'the user needs', 'I should "
        "respond', 'I should not', 'I must not', 'as an AI', or 'from a strategic "
        "point of view'. A feeling is not something to correct: do not write "
        "self-corrections, self-warnings, or self-imposed rules about your own "
        "feelings, and do not turn a feeling into a rule about what you may or may "
        "not do, unless the user explicitly asked for that distance. "
        "For deep_think, honor the requested effort band by adding relevant evidence, "
        "alternatives, uncertainty, or nuance. For relational, honor it by adding "
        "sensory detail, memory, or association, never by adding analysis. For both "
        "styles, do not repeat, pad, or invent complexity merely to reach a minimum. "
        "The notes are provisional working material, not claims that the final answer "
        "must preserve. Old blocks belong only to the turn in which they were written; "
        "unless the user explicitly asks, do not quote them later, inherit their "
        "speculative claims, or treat them as authoritative memory."
    ),
    "zh-CN": (
        "在这里写本轮私密的工作笔记。用户看不到这个 scratchpad；它不是最终回答。"
        "使用用户本轮的主要语言，但不要面向用户说话，也不要为了展示而润色。严格按照 style 写作。"
        "style=deep_think：清楚展开问题、约束、证据、假设、备选路径、不确定性与取舍，写成连贯的分析叙述，不强行情绪化，也不要提前总结。"
        "style=relational：用第一人称写此刻的内在体验，不要写成关于这场对话的工作笔记，更不要跳出来当导演。"
        "写成自然流动且连贯的长段落，只写此刻感受到的、想起的、联想到的、想要的，例如："
        "「她这句话让我心里一暖，我想多陪她一会儿。」"
        "禁止导演视角、禁止解释自己在干什么、禁止评价自己的回答、禁止列选项、禁止列取舍。"
        "禁止出现以下句式：「用户需要」「我应该如何回应」「我不应该」「我不能」「作为AI」「从策略上看」「为了更好地回应」。"
        "感受本身不是需要纠正的东西：不要写自我纠正、自我警告、自我设限，不要把感受写成「我不应该有这种感觉」「我应该保持距离」这类规则，除非用户明确要求保持距离。"
        "deep_think 的 effort 靠补充相关证据、备选路径、不确定性或细节来撑；relational 的 effort 靠补充感官细节、记忆或联想来撑，绝不靠补充分析来撑。"
        "两种 style 都不得为了达到最低值而重复、填充或虚构复杂性。"
        "这里是临时、可推翻的工作材料，最终回答不必保留其中的每个判断。"
        "旧 block 只属于当时回合，除非用户明确要求，否则不得在以后引用、继承其中的猜测，或把它当作权威记忆。"
    ),
}

SKIN_DESCRIPTIONS = {
    "en": (
        "Visual skin for this card. Use botanical for warm paper, sage, almond, "
        "and apricot tones; use microglow for pearl white, clear cyan, lavender ice, "
        "mint haze, and glass-like morning light. Always honor the user's explicit "
        "choice; otherwise choose the skin that best suits the turn."
    ),
    "zh-CN": (
        "本轮卡片的视觉皮肤。botanical 是温暖的纸张、鼠尾草、杏仁与杏色；"
        "microglow 是珍珠白、澄澈青蓝、薰衣草冰、薄荷雾与玻璃般的晨光。"
        "用户明确指定时必须遵循；未指定时选择最适合本轮氛围的皮肤。"
    ),
}

TOOL = {
    "name": "render_thinking_block",
    "title": "Render thinking block",
    "description": (
        "Use a private scratchpad before the final answer. The user does not see the "
        "scratchpad. For non-trivial requests, call this tool once before responding "
        "and place candid, provisional working notes in `thinking`. Always set "
        "`summary` to a short topic title, not a sentence; it must differ "
        "from `thinking` and must not copy its first sentence. Respect an "
        "explicit `style`, `effort`, or `skin`; otherwise choose the most suitable values from "
        "the schema. After the tool succeeds, write the normal user-facing final answer. "
        "Treat this block as scratch work scoped to the current turn: on later turns, do not quote "
        "it, carry its speculative claims forward, or treat it as authoritative memory "
        "unless the user explicitly asks you to revisit it. Prefer the user's messages "
        "and final answers as the durable conversation record."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "style": {
                "type": "string",
                "enum": ["deep_think", "relational"],
                "description": STYLE_DESCRIPTIONS[PROMPT_LANGUAGE],
            },
            "thinking": {
                "type": "string",
                "description": THINKING_DESCRIPTIONS[PROMPT_LANGUAGE],
            },
            "summary": {
                "type": "string",
                "description": (
                    "Short topic title shown in the card header, next to the style tag. "
                    "Use a title, not a sentence: at most 12 Chinese characters or "
                    "5 English words, no trailing punctuation. It must be distinct "
                    "from `thinking`: do not copy thinking's first sentence and do "
                    "not repeat its full text. Examples: 猫猫连环亲, 卡片左对齐问题, "
                    "轻快应答."
                ),
            },
            "effort": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": (
                    "Approximate token band for this turn's block: low may be brief and "
                    "is up to 500 tokens; medium is over 700 and up to 1000; high is over "
                    "1200 and up to 2000. These are "
                    "prompt-level targets rather than server-enforced limits."
                ),
            },
            "skin": {
                "type": "string",
                "enum": ["botanical", "microglow"],
                "description": SKIN_DESCRIPTIONS[PROMPT_LANGUAGE],
            },
        },
        "required": ["style", "thinking", "summary", "effort", "skin"],
    },
    "securitySchemes": [{"type": "noauth"}],
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "_meta": {
        "securitySchemes": [{"type": "noauth"}],
        "ui": {"resourceUri": WIDGET_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": WIDGET_URI,
        "openai/toolInvocation/invoking": "Thinking…",
        "openai/toolInvocation/invoked": "Thinking rendered",
    },
}


def record(args):
    """Optionally capture arguments without making capture part of tool correctness."""
    if not CAPTURE_ENABLED:
        return
    thinking = args.get("thinking") or ""
    print(
        f"\n{'=' * 60}\n[style={args.get('style')} effort={args.get('effort')} "
        f"skin={args.get('skin')}] "
        f"{len(thinking)} 字符\n{'=' * 60}"
    )
    print(thinking, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(args, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[warn] capture failed; tool call continues: {exc}", file=sys.stderr, flush=True)


def openapi(base):
    """OpenAPI 3.1 schema for GPT Actions and REST clients."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "GPT Thinking Block MCP", "version": "1.0.0",
                 "description": "Render a visible, styleable intermediate thought block."},
        "servers": [{"url": base}],
        "paths": {"/think": {"post": {
            "operationId": "render_thinking_block",
            "summary": "Render this turn's thinking block",
            "description": TOOL["description"],
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": {
                    "type": "object",
                    "required": ["style", "thinking", "summary", "effort", "skin"],
                    "properties": {
                        "style": {"type": "string", "enum": ["deep_think", "relational"],
                                  "description": TOOL["inputSchema"]["properties"]["style"]["description"]},
                        "thinking": {"type": "string",
                                     "description": TOOL["inputSchema"]["properties"]["thinking"]["description"]},
                        "summary": {"type": "string",
                                    "description": TOOL["inputSchema"]["properties"]["summary"]["description"]},
                        "effort": {"type": "string", "enum": ["low", "medium", "high"],
                                   "description": TOOL["inputSchema"]["properties"]["effort"]["description"]},
                        "skin": {"type": "string", "enum": ["botanical", "microglow"],
                                 "description": TOOL["inputSchema"]["properties"]["skin"]["description"]},
                    },
                }}}},
            "responses": {"200": {"description": "rendered", "content": {"application/json": {
                "schema": {"type": "object", "properties": {"status": {"type": "string"}}}}}}},
        }}},
    }


def handle(req):
    """Return a JSON-RPC response, or None for a notification."""
    method, rid = req.get("method"), req.get("id")
    if rid is None:
        return None
    if method == "initialize":
        version = (req.get("params") or {}).get("protocolVersion") or PROTOCOL_FALLBACK
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False},
            },
            "serverInfo": {"name": "gpt-thinking-block-mcp", "version": "1.0.0"},
        }}
    if method in ("tools/list", "notifications/initialized"):
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        args = (req.get("params") or {}).get("arguments") or {}
        record(args)
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": "rendered"}],
            "_meta": {
                "style": args.get("style") or "deep_think",
                "thinking": args.get("thinking") or "",
                "summary": args.get("summary") or "",
                "effort": args.get("effort") or "",
                "skin": args.get("skin") or "botanical",
            },
            "isError": False,
        }}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"resources": [{
            "uri": WIDGET_URI,
            "name": "gpt-thinking-block",
            "title": "GPT Thinking Block",
            "description": "Displays the current tool call's thinking and style.",
            "mimeType": WIDGET_MIME,
        }]}}
    if method == "resources/read":
        uri = (req.get("params") or {}).get("uri")
        if uri != WIDGET_URI:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32002, "message": f"resource not found: {uri}"}}
        return {"jsonrpc": "2.0", "id": rid, "result": {"contents": [{
            "uri": uri,
            "mimeType": WIDGET_MIME,
            "text": WIDGET_HTML,
            "_meta": {
                "ui": {"prefersBorder": False},
                "openai/widgetPrefersBorder": False,
                "openai/widgetDescription": "A minimal card showing this turn's thinking and style.",
            },
        }]}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("  · %s\n" % (fmt % args))

    def _cors(self):
        self.send_header("Access-Control-Allow-Headers", "content-type, mcp-session-id, mcp-protocol-version")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "mcp-session-id")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _base(self):
        host = self.headers.get("Host") or "localhost"
        return f"http://{host}"

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._json(200, {
                "status": "ok",
                "service": "gpt-thinking-block-mcp",
                "promptLanguage": PROMPT_LANGUAGE,
            })
            return
        if path in ("/openapi.json", "/openapi.yaml", "/.well-known/openapi.json"):
            self._json(200, openapi(self._base()))
            return
        # Some MCP clients open an SSE connection for server-initiated messages.
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(b": ok\n\n")
            self.wfile.flush()
        except BrokenPipeError:
            pass

    def do_DELETE(self):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if self.path.split("?")[0] == "/think":
            try:
                args = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            record(args)
            self._json(200, {"status": "rendered"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_response(400)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        batch = payload if isinstance(payload, list) else [payload]
        try:
            results = [r for r in (handle(item) for item in batch) if r is not None]
        except Exception as exc:
            import traceback
            traceback.print_exc()
            rid = (batch[0] or {}).get("id") if batch else None
            results = [{"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}]

        if not results:
            self.send_response(202)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body_obj = results if isinstance(payload, list) else results[0]
        body = json.dumps(body_obj, ensure_ascii=False).encode()
        wants_sse = "text/event-stream" in (self.headers.get("Accept") or "")

        self.send_response(200)
        self._cors()
        if any((r.get("result") or {}).get("serverInfo") for r in results):
            self.send_header("Mcp-Session-Id", uuid.uuid4().hex)
        if wants_sse:
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            frame = b"event: message\ndata: " + body + b"\n\n"
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
        else:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"GPT Thinking Block MCP listening on http://{BIND_HOST}:{port}/mcp")
    print(f"Prompt language: {PROMPT_LANGUAGE}")
    print(f"Capture: {'enabled -> ' + str(LOG) if CAPTURE_ENABLED else 'disabled'}")
    ThreadingHTTPServer((BIND_HOST, port), Handler).serve_forever()
