from __future__ import annotations

import json


def build_mcp_goto_code(url: str, tw: int) -> str:
    u = json.dumps(url)
    return f"async (page) => {{ await page.goto({u}, {{ waitUntil: 'domcontentloaded', timeout: {int(tw)} }}); }}"


def build_mcp_stabilize_code(tw: int) -> str:
    t = min(int(tw), 60_000)
    return f"async (page) => {{ await page.waitForLoadState('load', {{ timeout: {t} }}).catch(() => {{}}); return 'ok'; }}"


def build_mcp_content_code() -> str:
    return "async (page) => { return await page.content(); }"


def build_mcp_count_code(selector: str) -> str:
    s = json.dumps(selector)
    return f"async (page) => JSON.stringify({{ c: await page.locator({s}).count() }});"


def build_mcp_computed_style_code(selector: str) -> str:
    s = json.dumps(selector)
    return f"""async (page) => {{
  const s = {s};
  const n = await page.locator(s).count();
  if (n < 1) return JSON.stringify({{ count: 0, selector: s, computed: null }});
  const computed = await page.locator(s).first().evaluate((el) => {{
    const c = getComputedStyle(el);
    const keys = ["color","background-color","display","visibility","opacity","font-size","width","height","position","z-index","border-color","pointer-events","overflow"];
    return Object.fromEntries(keys.map((k) => [k, c.getPropertyValue(k)]));
  }});
  return JSON.stringify({{ count: n, selector: s, computed }});
}}"""


def build_mcp_screenshot_b64_code() -> str:
    return "async (page) => { const b = await page.screenshot({ fullPage: true, type: 'png' }); return b.toString('base64'); }"


def build_mcp_step_code(selector: str, action: str, value: str, tw: int) -> str:
    s = json.dumps(selector)
    act = json.dumps(action)
    v0 = json.dumps(value or "")
    w = int(tw)
    return f"""async (page) => {{
  const tw = {w};
  const s = {s};
  const act = {act};
  const v0 = {v0};
  const loc = page.locator(s).first;
  const done = (ok, err, ex) => JSON.stringify({{ ok, err: err == null || err === false ? null : String(err), extra: ex || {{}} }});
  try {{
    if (act === "click") {{ await loc.click({{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "dblclick") {{ await loc.dblclick({{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "fill") {{ await loc.fill(v0, {{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "clear") {{ await loc.clear({{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "focus") {{ await loc.focus({{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "hover") {{ await loc.hover({{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "check") {{ await loc.check({{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "uncheck") {{ await loc.uncheck({{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "press") {{
      const k = (v0 || "").trim();
      if (!k) return done(false, "press requires value (key name)", {{}});
      await loc.press(k, {{ timeout: tw }});
      return done(true, null, {{}});
    }}
    if (act === "press_sequentially") {{
      if (!(v0 || "").trim()) return done(false, "press_sequentially requires value", {{}});
      await loc.pressSequentially(v0, {{ timeout: tw }});
      return done(true, null, {{}});
    }}
    if (act === "select_option") {{
      const vs = (v0 || "").trim();
      if (!vs) return done(false, "select_option requires value", {{}});
      const low = vs.toLowerCase();
      if (low.startsWith("value:")) await loc.selectOption({{ value: vs.split(":", 2)[1].trim(), timeout: tw }});
      else if (low.startsWith("label:")) await loc.selectOption({{ label: vs.split(":", 2)[1].trim(), timeout: tw }});
      else if (low.startsWith("index:")) await loc.selectOption({{ index: parseInt(vs.split(":", 2)[1].trim(), 10), timeout: tw }});
      else await loc.selectOption({{ label: vs, timeout: tw }});
      return done(true, null, {{}});
    }}
    if (act === "scroll_into_view") {{ await loc.scrollIntoViewIfNeeded({{ timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "get_text") {{
      const text = (await loc.innerText({{ timeout: tw }})) || "";
      const sub = (v0 || "").trim();
      if (sub && !text.includes(sub)) return done(false, "get_text: " + sub + " not in text", {{ actual_text: text }});
      return done(true, null, {{ actual_text: text }});
    }}
    if (act === "assert_text") {{
      const text = (await loc.innerText({{ timeout: tw }})).trim();
      if (text !== (v0 || "").trim()) return done(false, "text mismatch: " + text + " != " + v0, {{ actual_text: text }});
      return done(true, null, {{ actual_text: text }});
    }}
    if (act === "assert_contains") {{
      if (!(v0 || "").trim()) return done(false, "assert_contains requires value", {{}});
      const text = (await loc.innerText({{ timeout: tw }})) || "";
      if (!text.includes(v0)) return done(false, "assert_contains", {{ actual_text: text }});
      return done(true, null, {{ actual_text: text }});
    }}
    if (act === "assert_visible") {{ await loc.waitFor({{ state: 'visible', timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "assert_hidden") {{ await loc.waitFor({{ state: 'hidden', timeout: tw }}); return done(true, null, {{}}); }}
    if (act === "assert_value") {{
      const iv = await loc.inputValue({{ timeout: tw }});
      if (iv !== v0) return done(false, "value mismatch: " + iv + " != " + v0, {{}});
      return done(true, null, {{}});
    }}
    if (act === "assert_checked") {{ if (!await loc.isChecked({{ timeout: tw }})) return done(false, "not checked", {{}}); return done(true, null, {{}}); }}
    if (act === "assert_unchecked") {{ if (await loc.isChecked({{ timeout: tw }})) return done(false, "expected unchecked", {{}}); return done(true, null, {{}}); }}
    if (act === "assert_enabled") {{ if (!await loc.isEnabled({{ timeout: tw }})) return done(false, "not enabled", {{}}); return done(true, null, {{}}); }}
    if (act === "assert_disabled") {{ if (await loc.isEnabled({{ timeout: tw }})) return done(false, "expected disabled", {{}}); return done(true, null, {{}}); }}
    if (act === "assert_class") {{
      if (!(v0 || "").trim()) return done(false, "assert_class requires value", {{}});
      const c = (await loc.getAttribute("class")) || "";
      if (!c.includes(v0.trim())) return done(false, "class mismatch: " + c, {{}});
      return done(true, null, {{}});
    }}
    if (act === "assert_placeholder") {{
      if (!(v0 || "").trim()) return done(false, "assert_placeholder requires value", {{}});
      await loc.waitFor({{ state: 'attached', timeout: tw }});
      const p = await loc.getAttribute("placeholder");
      if (p !== v0) return done(false, "placeholder mismatch: " + p, {{}});
      return done(true, null, {{}});
    }}
    if (act === "assert_attribute") {{
      const raw = (v0 || "").trim();
      const eq = raw.indexOf("=");
      if (eq < 0) return done(false, "assert_attribute needs name=value", {{}});
      const an = raw.slice(0, eq).trim();
      const av = raw.slice(eq + 1);
      if (!an) return done(false, "assert_attribute empty name", {{}});
      await loc.waitFor({{ state: 'attached', timeout: tw }});
      const got = await loc.getAttribute(an) || "";
      if (an.toLowerCase() === "class") {{
        if (!got.includes(av.trim())) return done(false, "class token mismatch: " + got, {{}});
        return done(true, null, {{}});
      }}
      if (got !== av.trim()) return done(false, "attr " + an + " mismatch: " + got, {{}});
      return done(true, null, {{}});
    }}
    return done(false, "unhandled action: " + act, {{}});
  }} catch (e) {{
    const m = (e && e.message) ? e.message : String(e);
    return done(false, m, {{}});
  }}
}}"""
