from __future__ import annotations

import base64
import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from settings import settings

from .bdd import parse_bdd_step_lines

# Caps for self-contained (data: URL) HTML so files stay shareable but not unbounded.
_MAX_SHOT_EMBED_BYTES = 12 * 1024 * 1024
_MAX_TRACE_EMBED_BYTES = 15 * 1024 * 1024

_SKIP_PREV = re.compile(r"^skipped \(previous step failed\)$", re.I)

# Same structure as `BDD_HEADER_RE` / `BDD_STEP_RE` in AutomationSpikeSectionCards (View Test Case).
_BDD_HEADER_RE = re.compile(
    r"^(Feature|Rule|Background|Scenario(?:\s+Outline)?|Examples?)\s*:\s*(.*)$",
    re.I,
)
_BDD_STEP_RE = re.compile(r"^(Given|When|Then|And|But)\b\s+(.+)$", re.I)
_BDD_STAR_RE = re.compile(r"^\*\s+(.+)$")


def _e(s: object) -> str:
    return html.escape(str(s) if s is not None else "", quote=True)


def _format_report_datetime() -> str:
    dt = datetime.now().astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _bdd_keyword_class(kw: str) -> str:
    n = (kw or "").lower()
    if n == "given":
        return "bdd-kw bdd-kw--given"
    if n == "when":
        return "bdd-kw bdd-kw--when"
    if n == "then":
        return "bdd-kw bdd-kw--then"
    return "bdd-kw bdd-kw--and"


def _format_bdd_to_html(bdd: str) -> str:
    """BDD with Given/When/Then/And colors matching View Test Case."""
    s = (bdd or "").replace("\r\n", "\n").replace("\r", "\n")
    if not s.strip():
        return '<p class="bdd-empty"></p>'

    out: list[str] = ['<div class="bdd-body"><div class="bdd-lines">']
    for line in s.split("\n"):
        t = line.rstrip("\n")
        tr = t.strip()
        if not tr:
            out.append(
                '<div class="bdd-line bdd-line--spacer" aria-hidden="true"></div>'
            )
            continue
        if tr.startswith("#"):
            out.append(f'<div class="bdd-line bdd-line--comment">{_e(t)}</div>')
            continue
        if tr.startswith("|") and "|" in tr:
            out.append(f'<div class="bdd-line bdd-line--table">{_e(t)}</div>')
            continue
        m = _BDD_HEADER_RE.match(tr)
        if m:
            h1, h2 = m.group(1), m.group(2)
            title = (
                f' <span class="bdd-hdr-title">{_e(h2)}</span>' if h2 else ""
            )
            out.append(
                f'<div class="bdd-line bdd-line--header">'
                f'<span class="bdd-hdr-label">{_e(h1)}:</span>{title}</div>'
            )
            continue
        m = _BDD_STEP_RE.match(tr)
        if m:
            kw, rest = m.group(1), m.group(2)
            cls = _bdd_keyword_class(kw)
            out.append(
                f'<div class="bdd-line bdd-line--step">'
                f'<span class="{cls}">{_e(kw)}</span> '
                f'<span class="bdd-line-body">{_e(rest)}</span></div>'
            )
            continue
        m = _BDD_STAR_RE.match(tr)
        if m:
            out.append(
                f'<div class="bdd-line bdd-line--step">'
                f'<span class="bdd-kw bdd-kw--and">*</span> '
                f'<span class="bdd-line-body">{_e(m.group(1))}</span></div>'
            )
            continue
        toks = tr.split()
        if tr.startswith("@") and toks and all(x.startswith("@") for x in toks):
            out.append(f'<div class="bdd-line bdd-line--tags">{_e(t)}</div>')
            continue
        out.append(f'<div class="bdd-line bdd-line--plain">{_e(t)}</div>')

    out.append("</div></div>")
    return "\n".join(out)


def _step_pass(s: dict | None) -> bool | None:
    if s is None:
        return None
    p = s.get("pass")
    if p is True or p == 1:
        return True
    if p is False or p == 0:
        return False
    return bool(p)


def _show_err_in_analysis(err: object) -> bool:
    if err is None:
        return False
    t = str(err).strip()
    if not t:
        return False
    return _SKIP_PREV.match(t) is None


def _build_step_index_map(steps: list[dict]) -> tuple[dict[int, dict], bool]:
    m: dict[int, dict] = {}
    for s in steps:
        k = s.get("step_index")
        if k is not None and isinstance(k, (int, float)):
            m[int(k)] = s
    return m, len(m) > 0


def _screenshot_href_api(run_id: str, screenshot_path: str | None) -> str | None:
    if not screenshot_path:
        return None
    parts = [x for x in str(screenshot_path).replace("\\", "/").split("/") if x]
    if not parts:
        return None
    tail = parts[-1]
    rid = quote(str(run_id), safe="")
    t = quote(tail, safe="")
    return f"/api/automation/artifacts/{rid}/{t}"


def _artifact_file_path(run_id: str, screenshot_path: str | None) -> Path | None:
    if not screenshot_path or not str(run_id).strip():
        return None
    parts = [x for x in str(screenshot_path).replace("\\", "/").split("/") if x]
    if not parts:
        return None
    rid = str(run_id).strip()
    base = Path(settings.automation_artifacts_dir) / rid
    if parts[0] == rid:
        rest = parts[1:]
        if not rest:
            return None
        return base.joinpath(*rest)
    return base / parts[-1]


def _image_mime(path: Path) -> str:
    s = path.suffix.lower()
    if s in (".jpg", ".jpeg"):
        return "image/jpeg"
    if s == ".webp":
        return "image/webp"
    return "image/png"


def _read_file_data_uri(mime: str, path: Path, *, max_bytes: int) -> str | None:
    try:
        if not path.is_file():
            return None
        sz = path.stat().st_size
        if sz > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    b64 = base64.standard_b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _screenshot_ref(
    run_id: str, screenshot_path: str | None, *, embed_portable: bool
) -> str | None:
    if not screenshot_path:
        return None
    if not embed_portable:
        return _screenshot_href_api(run_id, screenshot_path)
    p = _artifact_file_path(run_id, str(screenshot_path))
    if p is None:
        return None
    mime = _image_mime(p)
    return _read_file_data_uri(mime, p, max_bytes=_MAX_SHOT_EMBED_BYTES)


def _trace_zip_path(run_id: str) -> Path | None:
    rid = str(run_id or "").strip()
    if not rid:
        return None
    return Path(settings.automation_artifacts_dir) / rid / "trace.zip"


def _resolve_trace_for_report(
    run_id: str,
    trace_href_api: str | None,
    *,
    embed_portable: bool,
) -> tuple[str | None, bool]:
    """Returns (href for the trace download link, trace_too_large_to_embed)."""
    if embed_portable:
        z = _trace_zip_path(run_id)
        if z is None or not z.is_file():
            return (None, False)
        try:
            sz = z.stat().st_size
        except OSError:
            return (None, False)
        if sz > _MAX_TRACE_EMBED_BYTES:
            return (None, True)
        u = _read_file_data_uri("application/zip", z, max_bytes=_MAX_TRACE_EMBED_BYTES)
        return (u, False)
    if trace_href_api and str(trace_href_api).strip():
        return (str(trace_href_api).strip(), False)
    return (None, False)


def _step_blocks_html(
    run_id: str,
    bdd: str,
    steps: list[dict],
    *,
    embed_portable: bool = True,
) -> str:
    line_texts = parse_bdd_step_lines(bdd)
    by_idx, has_index = _build_step_index_map(steps)
    parts: list[str] = []

    if not line_texts and steps:
        ordered = sorted(
            steps,
            key=lambda x: int(x.get("step_index") or 0),
        )
        for s in ordered:
            line = (str(s.get("step_text") or "").strip() or "—")
            parts.append(
                _one_step_block(run_id, line, s, embed_portable=embed_portable),
            )
        return "\n".join(parts)

    for i, raw_line in enumerate(line_texts):
        if has_index:
            s = by_idx.get(i)
        else:
            s = steps[i] if i < len(steps) else None
        line = (raw_line.strip() or "—")
        if s is None:
            parts.append(
                f'<div class="step skipped">'
                f'<p class="line">{_e(line)}</p>'
                f"</div>"
            )
        else:
            parts.append(
                _one_step_block(run_id, line, s, embed_portable=embed_portable)
            )
    if has_index and line_texts:
        line_n = len(line_texts)
        for k in sorted(x for x in by_idx if x >= line_n):
            s = by_idx.get(k)
            if not s:
                continue
            line = (str(s.get("step_text") or "").strip() or f"Step {k}")
            parts.append(
                _one_step_block(run_id, line, s, embed_portable=embed_portable)
            )
    return "\n".join(parts)


def _one_step_block(
    run_id: str, line: str, s: dict, *, embed_portable: bool = True
) -> str:
    sp = _step_pass(s)
    err_s = str(s.get("err") or "").lower()
    if sp is True:
        status_cls = "ok"
    elif sp is False and "skip" in err_s:
        status_cls = "skipped"
    elif sp is False:
        status_cls = "bad"
    else:
        status_cls = "unknown"
    err = s.get("err")
    show_reason = _show_err_in_analysis(err) and sp is not True
    err_html = ""
    if show_reason and err is not None:
        if status_cls == "bad":
            err_html = f'<pre class="reason reason--fail">{_e(err)}</pre>'
        else:
            err_html = f'<pre class="reason">{_e(err)}</pre>'
    sh = s.get("screenshot_path")
    href = _screenshot_ref(
        run_id, str(sh) if sh else None, embed_portable=embed_portable
    )
    shot_html = ""
    if href:
        tb = "noopener noreferrer" if href.startswith("data:") else "noreferrer"
        tbt = "" if href.startswith("data:") else ' target="_blank"'
        shot_html = (
            f'<details class="shot-details">'
            f'<summary class="shot-summary">Screenshot</summary>'
            f'<a class="shot-link" href="{_e(href)}"{tbt} rel="{tb}">'
            f'<img class="shot" src="{_e(href)}" alt="" loading="lazy" /></a>'
            f"</details>"
        )
    return (
        f'<div class="step {status_cls}">'
        f'<p class="line">{_e(line)}</p>'
        f"{err_html}{shot_html}</div>"
    )


def _nav_label_text(jira: str, title: str) -> str:
    j = (jira or "").strip() or "—"
    t = (title or "Untitled").strip() or "Untitled"
    if len(t) > 96:
        t = t[:95] + "…"
    return f"{j} · {t}"


def _step_is_skipped(s: dict) -> bool:
    sp = _step_pass(s)
    err_s = str(s.get("err") or "").lower()
    return sp is False and "skip" in err_s


def _all_steps_skipped(steps: list) -> bool:
    if not isinstance(steps, list) or not steps:
        return False
    for s in steps:
        if not isinstance(s, dict) or not _step_is_skipped(s):
            return False
    return True


def _case_nav_data_status(c: dict[str, Any]) -> str:
    raw = c.get("case_status") or c.get("result") or ""
    u = str(raw).strip().upper()
    if u in ("PASS", "FAIL", "ABORTED", "SKIPPED"):
        return {
            "PASS": "pass",
            "FAIL": "fail",
            "ABORTED": "aborted",
            "SKIPPED": "skipped",
        }[u]
    if c.get("ok") is True:
        return "pass"
    if _all_steps_skipped(c.get("steps") or []):
        return "skipped"
    return "fail"


def _html_report_nav_status_filter() -> str:
    return (
        f'<div class="report-nav-filter">'
        f'<label class="report-nav-filter-label" for="reportStatusSelect">Status</label>'
        f'<select class="report-nav-filter-select" id="reportStatusSelect" '
        f'aria-label="Filter test cases by status">'
        f'<option value="all" selected>All</option>'
        f'<option value="pass">Pass</option>'
        f'<option value="skipped">Skipped</option>'
        f'<option value="aborted">Aborted</option>'
        f'<option value="fail">Fail</option>'
        f"</select></div>"
    )


def _nav_st_classes(st: str) -> str:
    st = (st or "fail").strip().lower()
    if st not in ("pass", "fail", "aborted", "skipped"):
        st = "fail"
    return f"report-nav-item report-nav--st-{st}"


def _format_trace_block(
    trace_href: str, *, download_name: str | None = None
) -> str:
    tq = _e(trace_href)
    dpart = (
        f' download="{_e(download_name)}"'
        if (download_name and download_name.strip())
        else ""
    )
    tblank = ' target="_blank"' if not trace_href.startswith("data:") else ""
    is_embed = trace_href.startswith("data:")
    hint_tx = (
        "The link downloads a self-contained copy from this file. Open it with: "
        "<kbd class=\"trace-kbd\">npx playwright show-trace</kbd> &lt;file&gt;."
        if is_embed
        else "Open with: <kbd class=\"trace-kbd\">npx playwright show-trace</kbd> &lt;file&gt;."
    )
    return (
        f'<section class="report-trace-outer" aria-label="Playwright trace file">'
        f'<div class="trace-banner">'
        f'<div class="trace-banner-label">Playwright Trace File</div>'
        f'<div class="trace-banner-row">'
        f'<p class="trace-banner-hint">'
        f"{hint_tx}"
        f"</p>"
        f'<a class="trace-dl" href="{tq}" rel="noreferrer"{tblank}{dpart} '
        f'aria-label="Download Playwright trace file">'
        f'<svg class="trace-dl-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">'
        f'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        f'<polyline points="7 10 12 15 17 10"/>'
        f'<line x1="12" y1="15" x2="12" y2="3"/>'
        f"</svg></a>"
        f"</div></div></section>"
    )


def _format_trace_too_large_block() -> str:
    return (
        f'<section class="report-trace-outer" aria-label="Playwright trace file">'
        f'<div class="trace-banner trace-banner--subtle">'
        f'<div class="trace-banner-label">Playwright Trace File</div>'
        f'<p class="trace-size-note">A trace was recorded but is not embedded in this HTML '
        f"because the file is larger than the in-report limit. Open this report from the app "
        f"or copy <code>trace.zip</code> from the run folder if you need it.</p>"
        f"</div></section>"
    )


def _html_dash_hbar_row(label: str, value: int, max_v: int, mod: str) -> str:
    mv = max(max_v, 1)
    pct = min(100.0, 100.0 * float(value) / float(mv))
    return (
        f'<div class="report-dash-hbar">'
        f'<span class="report-dash-hbar-l">{_e(label)}</span>'
        f'<div class="report-dash-hbar-t" role="presentation">'
        f'<div class="report-dash-hbar-f report-dash-hbar-f--{mod}" style="width:{pct:.1f}%"></div>'
        f"</div>"
        f'<span class="report-dash-hbar-n">{_e(str(int(value)))}</span>'
        f"</div>"
    )


def _html_section_case_dashboard(ok: bool) -> str:
    cpass, cfail = (1, 0) if ok else (0, 1)
    m = 1
    rows = [
        _html_dash_hbar_row("Pass", cpass, m, "pass"),
        _html_dash_hbar_row("Fail", cfail, m, "fail"),
    ]
    return (
        f'<section class="report-dash" aria-label="Test Status">'
        f'<h2 class="section-title"><span class="title-accent">Test Status</span></h2>'
        f'<div class="report-dash-kpis">'
        f'<div class="report-dash-kpi"><span class="report-dash-kpi-v report-dash-kpi-v--ok">{_e(str(cpass))}</span>'
        f'<span class="report-dash-kpi-l">Passed</span></div>'
        f'<div class="report-dash-kpi"><span class="report-dash-kpi-v report-dash-kpi-v--bad">{_e(str(cfail))}</span>'
        f'<span class="report-dash-kpi-l">Failed</span></div>'
        f"</div>"
        f'<div class="report-dash-bars">{"".join(rows)}</div>'
        f"</section>"
    )


def _html_hero_landing_single() -> str:
    return (
        f'<div class="report-landing-hero">'
        f'<h1 class="report-landing-title">Dashboard</h1>'
        f"</div>"
    )


def _html_hero_landing_suite() -> str:
    return (
        f'<div class="report-landing-hero">'
        f'<p class="report-landing-kicker">Suite Run</p>'
        f'<h1 class="report-landing-title">Dashboard</h1>'
        f"</div>"
    )


def _html_landing_page_single(ok: bool) -> str:
    inner = _html_hero_landing_single() + _html_section_case_dashboard(ok)
    return f'<div class="report-landing-wrap">{inner}</div>'


def _html_suite_run_dashboard(cases: list[dict[str, Any]]) -> str:
    n_case = len(cases)
    cpass = sum(1 for c in cases if c.get("ok"))
    cfail = n_case - cpass
    max_c = max(cpass, cfail, 1)
    bar_rows = [
        _html_dash_hbar_row("Pass", cpass, max_c, "pass"),
        _html_dash_hbar_row("Fail", cfail, max_c, "fail"),
    ]
    return (
        f'<section class="report-dash report-dash--suite" aria-label="Test Status">'
        f'<h2 class="section-title"><span class="title-accent">Test Status</span></h2>'
        f'<div class="report-dash-kpis">'
        f'<div class="report-dash-kpi"><span class="report-dash-kpi-v">{_e(str(n_case))}</span>'
        f'<span class="report-dash-kpi-l">Total</span></div>'
        f'<div class="report-dash-kpi"><span class="report-dash-kpi-v report-dash-kpi-v--ok">{_e(str(cpass))}</span>'
        f'<span class="report-dash-kpi-l">Passed</span></div>'
        f'<div class="report-dash-kpi"><span class="report-dash-kpi-v report-dash-kpi-v--bad">{_e(str(cfail))}</span>'
        f'<span class="report-dash-kpi-l">Failed</span></div>'
        f"</div>"
        f'<div class="report-dash-bars">{"".join(bar_rows)}</div>'
        f"</section>"
    )


def _html_landing_page_suite(cases: list[dict[str, Any]]) -> str:
    return (
        f'<div class="report-landing-wrap">'
        f"{_html_hero_landing_suite()}"
        f"{_html_suite_run_dashboard(cases)}"
        f"</div>"
    )


def _build_case_content_html(
    run_id: str,
    title: str,
    bdd: str,
    url: str,
    ok: bool,
    steps: list[dict],
    log: list[str],
    *,
    jira_id: str = "",
    analysis: str = "",
    trace_href: str | None = None,
    embed_portable: bool = True,
) -> str:
    h = _e(title or "Spike")
    u = _e(url)
    jira_e = _e((jira_id or "").strip() or "—")
    report_dt = _e(_format_report_datetime())
    overall = "PASS" if ok else "FAIL"
    bdd_pre = _format_bdd_to_html(bdd)
    step_html = _step_blocks_html(
        run_id, bdd, steps, embed_portable=embed_portable
    )
    post = (analysis or "").strip()
    post_block = (
        f'<div class="post-summary">{_e(post)}</div>'
        if post
        else '<div class="post-summary post-summary--empty"></div>'
    )
    th_eff, th_big = _resolve_trace_for_report(
        run_id, trace_href, embed_portable=embed_portable
    )
    if th_big:
        trace_block = _format_trace_too_large_block()
    elif th_eff:
        dl = None
        if th_eff.startswith("data:") and str(run_id).strip():
            rid8 = str(run_id).replace("-", "")[:8] or "trace"
            dl = f"playwright-trace-{rid8}.zip"
        trace_block = _format_trace_block(th_eff, download_name=dl)
    else:
        trace_block = ""
    log_txt = _e("\n".join(log[-200:]))
    result_mod = "pass" if ok else "fail"
    return f"""<header class="report-header">
  <div class="report-header-top">
    <div class="report-header-row">
      <h1 class="report-title">{h}</h1>
      <span class="result-badge result-badge--{result_mod}">{_e(overall)}</span>
    </div>
  </div>
  <dl class="report-meta">
    <dt>Date &amp; time</dt><dd class="report-datetime">{report_dt}</dd>
    <dt>JIRA ID</dt><dd class="report-jira">{jira_e}</dd>
    <dt>URL</dt><dd><a class="report-url" href="{u}">{u}</a></dd>
    <dt>Run ID</dt><dd><code class="report-id">{_e(run_id)}</code></dd>
  </dl>
</header>
<section class="report-section"><h2 class="section-title section-title--steps"><span class="title-accent">Test Steps</span></h2>
<div class="bdd-wrap">{bdd_pre}</div>
</section>
<section class="report-section"><h2 class="section-title section-title--results"><span class="title-accent">Test Results</span></h2>
<div class="report-steps">
{step_html}
</div>
</section>
<section class="report-section"><h2 class="section-title">Post-Run Summary</h2>
{post_block}
</section>
{trace_block}
<section class="report-section"><h2 class="section-title">Debug log</h2>
<pre class="log">{log_txt}</pre>
</section>"""


def _emit_report_document(page_title: str, body_html: str) -> str:
    return _REPORT_HEAD.format(page_title=page_title) + body_html + _REPORT_TAIL

_REPORT_HEAD = """
<!doctype html>
<html lang="en" data-theme="dark"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="color-scheme" content="dark light"/>
<title>{page_title}</title>
<style>
:root, [data-theme="dark"]{{
  color-scheme:dark;
  --bg:#0c1017;
  --bg-grad-1:#111827;
  --bg-grad-2:#0c1017;
  --card:#151c27;
  --text:#e5e7eb;
  --muted:#94a3b8;
  --bd:#2d3a4d;
  --bd-strong:#3d4f66;
  --accent:#60a5fa;
  --code-bg:#1e293b;
  --title-steps:#38bdf8;
  --title-results:#4ade80;
  --pass:#22c55e;
  --pass-bg:rgba(34,197,94,.14);
  --pass-line:#22c55e;
  --fail:#ef4444;
  --fail-bg:rgba(239,68,68,.12);
  --fail-line:#ef4444;
  --skip:#a8a29e;
  --skip-bg:rgba(168,162,158,.12);
  --unk:#94a3b8;
  --shadow:0 1px 3px rgba(0,0,0,.35),0 4px 14px rgba(0,0,0,.2);
  --radius:10px;
  --font:ui-sans-serif,system-ui,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SFMono-Regular","SF Mono",Menlo,Consolas,monospace;
}}
[data-theme="light"]{{
  color-scheme:light;
  --bg:#f1f4f8;
  --bg-grad-1:#e8eef6;
  --bg-grad-2:#eef2f7;
  --card:#fff;
  --text:#0f172a;
  --muted:#64748b;
  --bd:#e2e8f0;
  --bd-strong:#cbd5e1;
  --accent:#2563eb;
  --code-bg:#f1f5f9;
  --title-steps:#0284c7;
  --title-results:#16a34a;
  --pass:#059669;
  --pass-bg:#ecfdf5;
  --pass-line:#22c55e;
  --fail:#dc2626;
  --fail-bg:#fef2f2;
  --fail-line:#ef4444;
  --skip:#78716c;
  --skip-bg:#f5f5f4;
  --unk:#94a3b8;
  --shadow:0 1px 2px rgba(15,23,42,.06),0 4px 12px rgba(15,23,42,.05);
}}
*,*::before,*::after{{box-sizing:border-box}}
body{{
  margin:0;
  min-height:100vh;
  font:15px/1.55 var(--font);
  color:var(--text);
  background:linear-gradient(165deg,var(--bg-grad-1) 0%,var(--bg) 40%,var(--bg-grad-2) 100%);
  padding:1.5rem 1rem 2.5rem;
  transition:background .2s ease,color .15s ease;
}}
.report-wrap{{
  max-width:min(100%,52rem);
  margin:0 auto;
}}
.report-wrap--nav{{
  max-width:min(100%,80rem);
}}
.report-toolbar{{
  display:flex;
  justify-content:flex-end;
  margin:0 0 0.75rem;
  min-height:2.1rem;
}}
.report-layout{{
  display:flex;
  flex-direction:row;
  align-items:flex-start;
  gap:0.9rem 1rem;
  max-width:100%;
  min-width:0;
}}
.report-nav{{
  flex:0 0 clamp(18rem,26vw,26rem);
  max-width:min(42%,28rem);
  min-width:16rem;
  position:sticky;
  top:0.75rem;
  align-self:flex-start;
  max-height:calc(100vh - 2.5rem);
  overflow-y:auto;
  -webkit-overflow-scrolling:touch;
  padding:0.2rem 0.4rem 0.6rem 0.15rem;
  box-sizing:border-box;
}}
.report-nav-list{{
  list-style:none;
  margin:0;
  padding:0;
}}
.report-nav-list li{{
  margin:0 0 0.55rem 0;
}}
.report-nav-list li:last-child{{
  margin-bottom:0;
}}
.report-nav-item{{
  display:block;
  width:100%;
  text-align:left;
  padding:0.7rem 0.9rem;
  font-size:0.88rem;
  line-height:1.45;
  font-family:var(--font);
  color:var(--text);
  background:var(--card);
  border:1px solid var(--bd);
  border-radius:10px;
  cursor:pointer;
  box-sizing:border-box;
  box-shadow:0 1px 0 rgba(15,23,42,.04);
  white-space:normal;
  word-break:normal;
  overflow-wrap:break-word;
  hyphens:none;
}}
.report-nav-item:hover{{
  border-color:var(--bd-strong);
}}
.report-nav-item.is-active{{
  border-color:var(--accent);
  box-shadow:0 0 0 1px color-mix(in srgb, var(--accent) 50%, var(--bd));
  background:color-mix(in srgb, var(--accent) 8%, var(--card));
}}
.report-nav-filter{{
  display:flex;
  flex-direction:row;
  flex-wrap:nowrap;
  align-items:center;
  justify-content:flex-start;
  gap:0.5rem;
  margin:0 0 0.65rem 0.15rem;
  min-width:0;
}}
.report-nav-filter-label{{
  flex-shrink:0;
  font-size:0.8rem;
  font-weight:600;
  letter-spacing:0.01em;
  color:var(--muted);
}}
.report-nav-filter-select{{
  flex:1 1 auto;
  min-width:0;
  font-size:0.8rem;
  font-family:var(--font);
  color:var(--text);
  background:var(--card);
  border:1px solid var(--bd);
  border-radius:8px;
  padding:0.45rem 0.55rem;
  cursor:pointer;
}}
.report-nav--st-pass{{
  color:var(--pass) !important;
}}
.report-nav--st-fail{{
  color:var(--fail) !important;
}}
.report-nav--st-aborted{{
  color:#f59e0b;
}}
[data-theme="light"] .report-nav--st-aborted{{
  color:#d97706;
}}
.report-nav--st-skipped{{
  color:var(--skip) !important;
}}
.report-panel--status-hidden{{
  display:none !important;
}}
.report-panels{{
  flex:1 1 12rem;
  min-width:0;
  max-width:100%;
  box-sizing:border-box;
  padding-top:0.2rem;
}}
.report-panel{{
  display:none;
  min-width:0;
}}
.report-panel.is-active{{
  display:block;
  animation:rep-fade 0.2s ease;
}}
#panel-dash.report-panel{{
  min-width:0;
}}
.report-landing-wrap{{
  width:100%;
  max-width:100%;
  box-sizing:border-box;
  padding:0 0 0.35rem 0;
}}
.report-landing-hero{{
  margin:0 0 1.1rem 0;
  padding:0.85rem 1rem 1rem;
  background:var(--card);
  border:1px solid var(--bd);
  border-radius:var(--radius);
  box-shadow:var(--shadow);
  break-inside:avoid;
}}
.report-landing-kicker{{
  margin:0 0 0.35rem 0;
  font-size:0.78rem;
  font-weight:600;
  letter-spacing:0.04em;
  text-transform:none;
  color:var(--muted);
}}
.report-landing-title{{
  margin:0 0 0.4rem 0;
  font-size:1.45rem;
  font-weight:700;
  line-height:1.2;
  color:var(--text);
  letter-spacing:-0.02em;
}}
.report-landing-sub{{
  margin:0;
  font-size:0.88rem;
  line-height:1.5;
  color:var(--muted);
  max-width:42rem;
}}
.report-dash{{
  margin:0 0 1.1rem 0;
  padding:0.85rem 1rem 1rem;
  background:var(--card);
  border:1px solid var(--bd);
  border-radius:var(--radius);
  box-shadow:var(--shadow);
  break-inside:avoid;
}}
.report-dash--suite .section-title{{
  margin-top:0;
}}
.report-dash-kpis{{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(6.5rem,1fr));
  gap:0.65rem 0.9rem;
  margin:0 0 0.9rem 0;
}}
.report-dash-kpi{{
  display:flex;
  flex-direction:column;
  gap:0.2rem;
  min-width:0;
}}
.report-dash-kpi-v{{
  font-size:1.35rem;
  font-weight:700;
  font-variant-numeric:tabular-nums;
  line-height:1.15;
  color:var(--text);
}}
.report-dash-kpi-v--ok{{color:var(--pass);}}
.report-dash-kpi-v--bad{{color:var(--fail);}}
.report-dash-kpi-l{{
  font-size:0.75rem;
  color:var(--muted);
  line-height:1.3;
}}
.result-badge.report-dash-kpi-v{{
  font-size:0.85rem;
  padding:0.2rem 0.55rem;
  align-self:flex-start;
}}
.report-dash-hint{{
  margin:0 0 0.75rem 0;
  font-size:0.8rem;
  color:var(--muted);
  line-height:1.45;
}}
.report-dash-bars{{
  display:flex;
  flex-direction:column;
  gap:0.45rem;
  margin:0 0 0.75rem 0;
}}
.report-dash-hbar{{
  display:grid;
  grid-template-columns:3.5rem 1fr 2.25rem;
  align-items:center;
  gap:0.4rem 0.5rem;
  font-size:0.8rem;
  min-width:0;
}}
.report-dash-hbar-l{{color:var(--muted);font-weight:500;}}
.report-dash-hbar-t{{
  height:0.6rem;
  border-radius:5px;
  background:color-mix(in srgb, var(--bd) 55%, var(--card));
  overflow:hidden;
  min-width:0;
}}
.report-dash-hbar-f{{
  height:100%;
  border-radius:5px;
  min-width:0;
}}
.report-dash-hbar-f--pass{{background:linear-gradient(90deg,#22c55e,#4ade80);}}
.report-dash-hbar-f--fail{{background:linear-gradient(90deg,#dc2626,#f87171);}}
.report-dash-hbar-f--skip{{background:linear-gradient(90deg,#d97706,#fbbf24);}}
.report-dash-hbar-f--unk{{background:linear-gradient(90deg,#64748b,#94a3b8);}}
.report-dash-hbar-n{{
  text-align:right;
  font-variant-numeric:tabular-nums;
  font-weight:600;
  color:var(--text);
}}
@keyframes rep-fade{{
  from{{opacity:0.85;}}
  to{{opacity:1;}}
}}
@media (max-width:52rem){{
  .report-layout{{
    flex-direction:column;
  }}
  .report-nav{{
    position:relative;
    top:auto;
    max-width:100%;
    max-height:none;
    flex:0 0 auto;
    width:100%;
  }}
  .report-nav-list{{
    display:flex;
    flex-wrap:wrap;
    gap:0.35rem;
  }}
  .report-nav-list li{{
    margin:0;
    flex:1 1 min(100%,18rem);
    min-width:min(100%,16rem);
  }}
  .report-nav-item{{
    padding:0.65rem 0.85rem;
    font-size:0.86rem;
  }}
}}
.report-header{{
  background:var(--card);
  border:1px solid var(--bd);
  border-radius:var(--radius);
  box-shadow:var(--shadow);
  padding:1.1rem 1.25rem 1.2rem;
  margin-bottom:1.25rem;
}}
.report-header-top{{
  display:flex;
  flex-wrap:wrap;
  align-items:flex-start;
  justify-content:space-between;
  gap:0.65rem 1rem;
  margin-bottom:0.9rem;
}}
.report-header-row{{
  display:flex;
  flex-wrap:wrap;
  align-items:flex-start;
  justify-content:space-between;
  gap:0.75rem 1rem;
  flex:1 1 12rem;
  min-width:0;
}}
.report-header-actions{{
  display:inline-flex;
  flex-wrap:wrap;
  align-items:center;
  gap:0.5rem;
  flex-shrink:0;
}}
.report-theme-btn{{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:2.1rem;
  height:2.1rem;
  padding:0;
  font-size:0.75rem;
  font-weight:600;
  font-family:var(--font);
  color:var(--text);
  background:var(--code-bg);
  border:1px solid var(--bd);
  border-radius:8px;
  cursor:pointer;
  line-height:0;
}}
.report-theme-btn:hover{{filter:brightness(1.12);}}
.report-theme-btn:focus-visible{{
  outline:2px solid var(--accent);
  outline-offset:2px;
}}
.theme-ico{{display:block;width:18px;height:18px;}}
/* Dark: show sun (switch to light). Light: show moon (switch to dark). */
[data-theme="dark"] .theme-ico--sun{{display:block;}}
[data-theme="dark"] .theme-ico--moon{{display:none;}}
[data-theme="light"] .theme-ico--sun{{display:none;}}
[data-theme="light"] .theme-ico--moon{{display:block;}}
.report-title{{
  font-size:1.35rem;
  font-weight:650;
  letter-spacing:-0.02em;
  line-height:1.3;
  margin:0;
  color:var(--text);
  flex:1 1 10rem;
  min-width:0;
}}
.result-badge{{
  display:inline-flex;
  align-items:center;
  padding:0.35rem 0.75rem;
  border-radius:999px;
  font-size:0.78rem;
  font-weight:700;
  letter-spacing:0.06em;
  text-transform:uppercase;
  flex-shrink:0;
}}
.result-badge--pass{{
  background:var(--pass-bg);
  color:var(--pass-line);
  border:1px solid color-mix(in srgb, var(--pass-line) 35%, transparent);
}}
.result-badge--fail{{
  background:var(--fail-bg);
  color:var(--fail-line);
  border:1px solid color-mix(in srgb, var(--fail-line) 35%, transparent);
}}
.report-meta{{
  display:grid;
  grid-template-columns:1fr;
  gap:0.5rem 1rem;
  margin:0;
  font-size:0.88rem;
}}
@media (min-width:520px){{
  .report-meta{{grid-template-columns:auto 1fr;align-items:baseline;column-gap:1.25rem;row-gap:0.4rem;}}
  .report-meta dt{{grid-column:1;}}
  .report-meta dd{{grid-column:2;margin:0;min-width:0;}}
}}
.report-meta dt{{
  margin:0;
  color:var(--muted);
  font-weight:500;
  font-size:0.8rem;
  text-transform:uppercase;
  letter-spacing:0.04em;
}}
.report-meta dd{{word-break:break-word;}}
.report-url{{color:var(--accent);text-decoration:none;border-bottom:1px solid color-mix(in srgb, var(--accent) 40%, transparent);}}
.report-url:hover{{text-decoration:underline;border-bottom-color:transparent;}}
code.report-id{{
  font-family:var(--mono);
  font-size:0.8em;
  background:var(--code-bg);
  padding:0.15rem 0.4rem;
  border-radius:6px;
  color:var(--text);
  word-break:break-all;
  border:1px solid var(--bd);
}}
.report-section{{
  background:var(--card);
  border:1px solid var(--bd);
  border-radius:var(--radius);
  box-shadow:var(--shadow);
  padding:1rem 1.15rem 1.2rem;
  margin-bottom:1rem;
}}
.section-title{{
  font-size:0.95rem;
  font-weight:600;
  letter-spacing:-0.01em;
  margin:0 0 0.9rem;
  padding-bottom:0.55rem;
  border-bottom:1px solid var(--bd);
  color:var(--muted);
}}
.section-title .title-accent{{
  font-weight:700;
}}
.section-title--steps .title-accent{{color:var(--title-steps);}}
.section-title--results .title-accent{{color:var(--title-results);}}
.report-trace-outer{{
  margin:0 0 1rem;
  max-width:100%;
  min-width:0;
  box-sizing:border-box;
}}
.trace-banner{{
  display:flex;
  flex-direction:column;
  gap:0.45rem;
  min-width:0;
  width:100%;
  padding:0.65rem 0.9rem;
  border:1px solid var(--bd);
  border-radius:8px;
  background:var(--card);
  box-sizing:border-box;
  box-shadow:0 1px 0 rgba(15,23,42,.04);
}}
[data-theme="dark"] .trace-banner{{box-shadow:0 1px 0 rgba(255,255,255,.04);}}
.trace-banner--subtle .trace-banner-label{{margin:0 0 0.35rem;}}
.trace-size-note{{
  margin:0;
  font-size:0.75rem;
  line-height:1.45;
  color:var(--muted);
}}
.trace-size-note code{{
  font-size:0.72rem;
  font-family:var(--mono);
  background:var(--code-bg);
  padding:0.1em 0.3em;
  border-radius:4px;
  border:1px solid var(--bd);
}}
.trace-banner-label{{
  font-size:0.8rem;
  font-weight:600;
  letter-spacing:0.01em;
  color:var(--muted);
  margin:0;
}}
.trace-banner-row{{
  display:flex;
  flex-direction:row;
  align-items:center;
  justify-content:space-between;
  gap:0.35rem 0.5rem;
  width:100%;
  max-width:100%;
  box-sizing:border-box;
}}
.trace-banner-hint{{
  display:block;
  margin:0;
  flex:1 1 auto;
  min-width:0;
  font-size:0.75rem;
  line-height:1.4;
  color:var(--muted);
}}
.trace-kbd{{
  display:inline;
  font-family:var(--mono);
  font-size:0.65rem;
  padding:0.05rem 0.25rem;
  border-radius:3px;
  background:color-mix(in srgb, var(--muted) 12%, var(--card));
  border:1px solid color-mix(in srgb, var(--bd) 90%, transparent);
  color:var(--text);
  vertical-align:0.1em;
}}
.trace-dl{{
  display:inline-flex;
  flex-shrink:0;
  align-items:center;
  justify-content:center;
  width:2rem;
  height:2rem;
  color:var(--accent);
  border-radius:6px;
  text-decoration:none;
  border:1px solid var(--bd);
  background:var(--code-bg);
  box-sizing:border-box;
}}
.trace-dl:hover{{
  filter:brightness(1.12);
  color:var(--text);
  border-color:var(--bd-strong);
}}
.trace-dl-icon{{display:block;}}
.bdd-wrap{{
  margin:0;
  background:var(--code-bg);
  border:1px solid var(--bd);
  border-left:3px solid var(--title-steps);
  border-radius:8px;
  padding:0.9rem 1rem;
  color:var(--text);
}}
.bdd-empty{{margin:0;font-size:0.85rem;color:var(--muted);}}
.bdd-lines{{
  display:flex;
  flex-direction:column;
  gap:0.2rem;
  font-size:0.9rem;
  line-height:1.5;
  font-family:var(--font);
}}
.bdd-line--spacer{{min-height:0.35rem;}}
.bdd-line--header{{
  margin-top:0.4rem;
  font-weight:600;
  font-size:0.88rem;
  word-break:break-word;
}}
.bdd-line--header:first-child,
.bdd-line--spacer + .bdd-line--header{{
  margin-top:0;
}}
.bdd-hdr-label{{
  color:#2563eb;
}}
[data-theme="dark"] .bdd-hdr-label{{
  color:#60a5fa;
}}
.bdd-hdr-title{{font-weight:500;color:var(--text);}}
.bdd-kw{{
  font-weight:600;
  font-size:0.88rem;
}}
.bdd-kw--given{{
  color:#15803d;
}}
[data-theme="dark"] .bdd-kw--given{{
  color:#4ade80;
}}
.bdd-kw--when{{
  color:#1d4ed8;
}}
[data-theme="dark"] .bdd-kw--when{{
  color:#93c5fd;
}}
.bdd-kw--then{{
  color:#7c3aed;
}}
[data-theme="dark"] .bdd-kw--then{{
  color:#c4b5fd;
}}
.bdd-kw--and{{
  color:#64748b;
}}
[data-theme="dark"] .bdd-kw--and{{
  color:#94a3b8;
}}
.bdd-line-body{{
  color:var(--text);
  font-weight:400;
}}
.bdd-line--comment{{
  font-size:0.82rem;
  font-style:italic;
  color:var(--muted);
  word-break:break-word;
}}
.bdd-line--table{{
  font-family:var(--mono);
  font-size:0.78rem;
  line-height:1.4;
  white-space:pre-wrap;
  word-break:break-all;
  color:var(--text);
  padding:0.1rem 0;
}}
.bdd-line--tags{{
  color:var(--muted);
  font-size:0.82rem;
}}
.bdd-line--plain{{
  color:var(--text);
  word-break:break-word;
}}
.post-summary{{
  margin:0;
  min-height:3.5rem;
  white-space:pre-wrap;
  word-break:break-word;
  overflow-wrap:anywhere;
  font-size:0.9rem;
  line-height:1.58;
  color:var(--text);
  background:transparent;
  border:none;
  padding:0.1rem 0 0;
}}
.post-summary--empty{{
  min-height:0;
  padding:0;
}}
pre.reason{{
  margin:0.35rem 0 0;
  white-space:pre-wrap;word-break:break-word;
  font-family:var(--mono);
  font-size:0.8rem;
  line-height:1.45;
  background:var(--fail-bg);
  border:1px solid color-mix(in srgb, var(--fail-line) 45%, var(--bd));
  border-radius:8px;
  padding:0.65rem 0.8rem;
  color:var(--fail-line);
}}
pre.reason--fail{{
  border-left:3px solid var(--fail-line);
}}
.step.skipped pre.reason{{
  color:var(--skip);
  border-color:var(--bd);
  background:var(--skip-bg);
}}
.report-steps{{}}
.step{{
  position:relative;
  border:1px solid var(--bd);
  border-radius:9px;
  padding:0.75rem 0.9rem 0.85rem;
  margin:0.55rem 0 0;
  background:var(--card);
  box-shadow:0 1px 0 rgba(15,23,42,.04);
  transition:background .15s ease,border-color .15s ease;
}}
[data-theme="dark"] .step{{box-shadow:0 1px 0 rgba(255,255,255,.04);}}
.step:first-child{{margin-top:0;}}
.step .line{{
  margin:0 0 0.5rem 0;
  white-space:pre-wrap;word-break:break-word;
  font-size:0.95rem;
  line-height:1.45;
  color:var(--text);
  border-left:3px solid var(--bd-strong);
  padding-left:0.5rem;
  margin-left:-0.15rem;
}}
.step.ok .line{{
  border-left-color:var(--pass-line);
  color:var(--text);
}}
.step.bad .line{{
  border-left-color:var(--fail-line);
  color:var(--text);
}}
.step.ok{{
  border-left:4px solid var(--pass-line);
  background:var(--card);
}}
.step.bad{{
  border-left:4px solid var(--fail-line);
  background:var(--card);
}}
.step.unknown{{
  border-left:4px solid var(--unk);
}}
.step.skipped{{
  border-left:4px solid #a8a29e;
  background:var(--card);
}}
.step.skipped .line{{
  color:var(--muted);
  border-left-color:#a8a29e;
}}
.shot-details{{
  margin:0.6rem 0 0 0;
}}
.shot-summary{{
  list-style:none;
  display:flex;
  flex-direction:row;
  align-items:center;
  gap:0.4rem;
  font-size:0.75rem;
  font-weight:600;
  text-transform:uppercase;
  letter-spacing:0.05em;
  color:var(--muted);
  cursor:pointer;
  user-select:none;
  padding:0.15rem 0;
}}
.shot-summary::before{{
  content:"\\25B6";
  flex-shrink:0;
  font-size:0.55rem;
  line-height:1;
  color:var(--muted);
  transform:rotate(0deg);
  transition:transform 0.18s ease,color 0.15s;
}}
.shot-details[open] > .shot-summary::before{{
  transform:rotate(90deg);
}}
.shot-details .shot-summary::-webkit-details-marker{{display:none;}}
.shot-link{{display:block;margin:0.4rem 0 0 0;max-width:100%;}}
.shot{{
  max-width:100%;
  height:auto;
  border:1px solid var(--bd-strong);
  border-radius:6px;
  box-shadow:0 2px 8px rgba(0,0,0,.2);
  vertical-align:top;
}}
code{{
  font-family:var(--mono);
  font-size:0.88em;
  background:var(--code-bg);
  padding:0.12em 0.35em;
  border-radius:4px;
  color:var(--text);
  border:1px solid var(--bd);
}}
a{{color:var(--accent);}}
pre.log{{
  margin:0;
  font-size:0.75rem;
  line-height:1.45;
  font-family:var(--mono);
  background:#020617;
  color:#e2e8f0;
  border:1px solid var(--bd);
  border-radius:8px;
  padding:0.75rem 0.9rem;
  white-space:pre-wrap;
  word-break:break-word;
  max-height:20rem;
  overflow:auto;
}}
[data-theme="light"] pre.log{{
  background:#0f172a;
  color:#e2e8f0;
}}
@media print{{
  body{{background:#fff!important;color:#000!important;}}
  [data-theme="dark"]{{color-scheme:light;}}
  .report-header,.report-section,.report-landing-hero,.report-dash{{box-shadow:none;break-inside:avoid;}}
  .report-nav{{display:none;}}
  .report-panel--status-hidden{{display:block!important;}}
  .report-panel,#panel-dash{{display:block!important;}}
  .report-wrap--nav .report-panels .report-panel{{page-break-inside:avoid;}}
  pre.log{{max-height:none;}}
  .report-theme-btn{{display:none;}}
}}
</style>
</head><body>
"""

_REPORT_TAIL = """

<script>
(function () {{
  var key = "automation-run-report-theme";
  var root = document.documentElement;
  function apply(t) {{
    root.setAttribute("data-theme", t);
    try {{ localStorage.setItem(key, t); }} catch (e) {{}}
    var btn = document.getElementById("reportThemeToggle");
    if (btn) {{
      var dark = t === "dark";
      btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    }}
  }}
  try {{
    var saved = localStorage.getItem(key);
    if (saved === "light" || saved === "dark") apply(saved);
    else apply("dark");
  }} catch (e) {{ apply("dark"); }}
  var toggle = document.getElementById("reportThemeToggle");
  if (toggle) {{
    toggle.addEventListener("click", function () {{
      var cur = root.getAttribute("data-theme") || "dark";
      apply(cur === "dark" ? "light" : "dark");
    }});
  }}
  document.querySelectorAll(".report-nav-item").forEach(function (btn) {{
    btn.addEventListener("click", function () {{
      var id = btn.getAttribute("data-target");
      if (!id) return;
      document.querySelectorAll(".report-nav-item").forEach(function (b) {{
        b.classList.remove("is-active");
        b.removeAttribute("aria-current");
      }});
      document.querySelectorAll(".report-panel").forEach(function (p) {{ p.classList.remove("is-active"); }});
      btn.classList.add("is-active");
      btn.setAttribute("aria-current", "page");
      var el = document.getElementById(id);
      if (el) {{ el.classList.add("is-active"); }}
    }});
  }});
  var fsel = document.getElementById("reportStatusSelect");
  if (fsel) {{
    function applyNavStatusFilter() {{
      var v = fsel.value;
      var all = (v === "all");
      document.querySelectorAll("li[data-report-case-status]").forEach(function (li) {{
        var st = li.getAttribute("data-report-case-status");
        li.style.display = (all || st === v) ? "" : "none";
      }});
      document.querySelectorAll("article[data-report-case-status]").forEach(function (art) {{
        var st = art.getAttribute("data-report-case-status");
        if (all) {{ art.classList.remove("report-panel--status-hidden"); return; }}
        if (st === v) {{ art.classList.remove("report-panel--status-hidden"); }}
        else {{ art.classList.add("report-panel--status-hidden"); }}
      }});
      var activeP = document.querySelector(".report-panel.is-active");
      if (activeP && activeP.getAttribute("data-report-case-status") && activeP.classList.contains("report-panel--status-hidden")) {{
        var dashBtn = document.querySelector('.report-nav-item[data-target="panel-dash"]');
        if (dashBtn) {{ dashBtn.click(); }}
      }}
    }}
    fsel.addEventListener("change", applyNavStatusFilter);
  }}
}})();
</script>
</body></html>"""

def render_spike_run_html(
    run_id: str,
    title: str,
    bdd: str,
    url: str,
    ok: bool,
    steps: list[dict],
    log: list[str],
    *,
    jira_id: str = "",
    analysis: str = "",
    trace_href: str | None = None,
    embed_portable: bool = True,
) -> str:
    jt = (jira_id or "").strip()
    landing = _html_landing_page_single(ok)
    case_block = _build_case_content_html(
        run_id,
        title,
        bdd,
        url,
        ok,
        steps,
        log,
        jira_id=jira_id,
        analysis=analysis,
        trace_href=trace_href,
        embed_portable=embed_portable,
    )
    st = _case_nav_data_status({"ok": ok, "steps": steps})
    nav_case_cls = _nav_st_classes(st)
    filter_html = _html_report_nav_status_filter()
    nav_dash = _e("Dashboard")
    nav_title = _e(_nav_label_text(jt, (title or "").strip()))
    body_html = f"""<div class="report-wrap report-wrap--nav">
  <div class="report-toolbar">
    <button type="button" class="report-theme-btn" id="reportThemeToggle" aria-label="Switch to light mode">
      <svg class="theme-ico theme-ico--sun" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4"/>
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
      </svg>
      <svg class="theme-ico theme-ico--moon" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
      </svg>
    </button>
  </div>
  <div class="report-layout">
    <nav class="report-nav" aria-label="Report sections">
{filter_html}
      <ul class="report-nav-list">
        <li>
          <button type="button" class="report-nav-item is-active" data-target="panel-dash" aria-current="page">{nav_dash}</button>
        </li>
        <li data-report-case-status="{st}">
          <button type="button" class="{nav_case_cls}" data-target="case-0">{nav_title}</button>
        </li>
      </ul>
    </nav>
    <div class="report-panels">
      <article id="panel-dash" class="report-panel is-active" tabindex="-1">
{landing}
      </article>
      <article id="case-0" class="report-panel" data-report-case-status="{st}" tabindex="-1">
{case_block}
      </article>
    </div>
  </div>
</div>"""
    return _emit_report_document("Report", body_html)


def render_batch_report_html(
    report_id: str,
    cases: list[dict[str, Any]],
    *,
    embed_portable: bool = True,
) -> str:
    """One page: landing dashboard + left nav; click switches panel."""
    if not cases:
        return ""
    nav_items: list[str] = [
        '<li><button type="button" class="report-nav-item is-active" data-target="panel-dash" aria-current="page">'
        + _e("Dashboard")
        + "</button></li>"
    ]
    arts: list[str] = [
        '<article id="panel-dash" class="report-panel is-active" tabindex="-1">\n'
        f"{_html_landing_page_suite(cases)}\n"
        "</article>"
    ]
    for i, c in enumerate(cases):
        run_id = str(c.get("run_id") or "")
        t = str(c.get("title") or "Untitled")
        bdd = str(c.get("bdd") or "")
        u = str(c.get("url") or "").strip()
        ok = bool(c.get("ok"))
        steps = c.get("steps") or []
        if not isinstance(steps, list):
            steps = []
        log = c.get("debug_logs")
        if log is None:
            log = c.get("log")
        if log is None:
            log = []
        if isinstance(log, str):
            log = [log] if log.strip() else []
        if not isinstance(log, list):
            log = [str(log)]
        analysis = str(c.get("analysis") or "")
        jira = str(c.get("jira_id") or "")
        th = c.get("trace_href")
        trace_href: str | None
        if isinstance(th, str) and th.strip():
            trace_href = th.strip()
        else:
            trace_href = None
        case_block = _build_case_content_html(
            run_id,
            t,
            bdd,
            u,
            ok,
            steps,
            log,
            jira_id=jira,
            analysis=analysis,
            trace_href=trace_href,
            embed_portable=embed_portable,
        )
        cst = _case_nav_data_status(c)
        ncls = _nav_st_classes(cst)
        lbl = _e(_nav_label_text((jira or "").strip(), (t or "").strip()))
        nav_items.append(
            f'<li data-report-case-status="{_e(cst)}">'
            f'<button type="button" class="{ncls}" data-target="case-{i}">'
            f"{lbl}</button></li>"
        )
        arts.append(
            f'<article id="case-{i}" class="report-panel" data-report-case-status="{_e(cst)}" tabindex="-1">\n'
            f"{case_block}\n"
            f"</article>"
        )
    nav_html = "\n".join(nav_items)
    art_html = "\n".join(arts)
    filter_batch = _html_report_nav_status_filter()
    body_html = f"""<div class="report-wrap report-wrap--nav">
  <div class="report-toolbar">
    <button type="button" class="report-theme-btn" id="reportThemeToggle" aria-label="Switch to light mode">
      <svg class="theme-ico theme-ico--sun" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4"/>
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
      </svg>
      <svg class="theme-ico theme-ico--moon" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
      </svg>
    </button>
  </div>
  <div class="report-layout">
    <nav class="report-nav" aria-label="Report sections">
{filter_batch}
      <ul class="report-nav-list">
{nav_html}
      </ul>
    </nav>
    <div class="report-panels">
{art_html}
    </div>
  </div>
</div>"""
    return _emit_report_document("Report", body_html)
