from __future__ import annotations

import base64
import html
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from settings import settings

from .bdd import parse_bdd_step_lines
from .tag_csv import parse_tag_tokens

_MAX_SHOT_EMBED_BYTES = 12 * 1024 * 1024
_MAX_TRACE_EMBED_BYTES = 15 * 1024 * 1024

_SKIP_PREV = re.compile(r"^skipped \(previous step failed\)$", re.I)

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


def _nav_label_text(jira: str, title: str, tag: str = "") -> str:
    j = (jira or "").strip() or "—"
    t = (title or "Untitled").strip() or "Untitled"
    if len(t) > 96:
        t = t[:95] + "…"
    parts: list[str] = []
    parts.extend(parse_tag_tokens(tag))
    parts.append(j)
    parts.append(t)
    return " · ".join(parts)


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


def _single_case_pass_fail_skip(ok: bool, steps: list) -> tuple[int, int, int]:
    if ok:
        return (1, 0, 0)
    if _all_steps_skipped(steps):
        return (0, 0, 1)
    return (0, 1, 0)


def _case_badge_from_status(ok: bool, case_status: str | None) -> tuple[str, str]:
    u = (case_status or "").strip().upper()
    if u == "ABORTED":
        return ("ABORTED", "aborted")
    if ok:
        return ("PASS", "pass")
    return ("FAIL", "fail")


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
        '<div class="report-nav-filter">'
        '<label class="report-nav-filter-label" for="reportStatusSelect">Status</label>'
        '<select class="report-nav-filter-select" id="reportStatusSelect" '
        'aria-label="Filter test cases by status">'
        '<option value="all" selected>All</option>'
        '<option value="pass">Pass</option>'
        '<option value="skipped">Skipped</option>'
        '<option value="aborted">Aborted</option>'
        '<option value="fail">Fail</option>'
        "</select></div>"
    )


def _tag_data_pipe(c: dict[str, Any] | None, *, tag: str = "") -> str:
    if c is not None:
        s = str(c.get("tag") or "")
    else:
        s = tag
    return "|".join(parse_tag_tokens(s))


def _tag_filter_choices(
    cases: list[dict[str, Any]] | None, *, single_tag: str = ""
) -> tuple[list[str], bool]:
    if cases is not None:
        s: set[str] = set()
        has_untagged = False
        for c in cases:
            toks = parse_tag_tokens(str(c.get("tag") or ""))
            if not toks:
                has_untagged = True
            else:
                s.update(toks)
        return (sorted(s, key=lambda x: (x.lower(), x)), has_untagged)
    toks = parse_tag_tokens(single_tag)
    if not toks:
        return ([], True)
    return (toks, False)


def _html_report_tag_filter(unique_tags: list[str], include_untagged: bool) -> str:
    opts: list[str] = [
        '<div class="report-nav-filter">',
        '<label class="report-nav-filter-label" for="reportTagSelect">Tag</label>',
        '<select class="report-nav-filter-select" id="reportTagSelect" '
        'aria-label="Filter test cases by tag">',
        '<option value="all" selected>All</option>',
    ]
    for t in unique_tags:
        opts.append(f'<option value="{_e(t)}">{_e(t)}</option>')
    if include_untagged:
        opts.append('<option value="__untagged__">No tag</option>')
    opts.append("</select></div>")
    return "".join(opts)


def _html_report_filters_aside(unique_tags: list[str], include_untagged: bool) -> str:
    return (
        f'<aside class="report-nav-filters-aside" aria-label="Report filters">'
        f'<div class="report-nav-filters-stack">'
        f"{_html_report_nav_status_filter()}"
        f"{_html_report_tag_filter(unique_tags, include_untagged)}"
        f"</div></aside>"
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
        '<section class="report-trace-outer" aria-label="Playwright trace file">'
        '<div class="trace-banner trace-banner--subtle">'
        '<div class="trace-banner-label">Playwright Trace File</div>'
        '<p class="trace-size-note">A trace was recorded but is not embedded in this HTML '
        "because the file is larger than the in-report limit. Open this report from the app "
        "or copy <code>trace.zip</code> from the run folder if you need it.</p>"
        "</div></section>"
    )


def _html_extent_topbar(*, copy_id: str = "", copy_label: str = "Copy id") -> str:
    dt = _e(_format_report_datetime())
    cap = (copy_id or "").strip()
    if cap:
        cap_e = _e(cap)
        copy_ico = (
            '<svg class="report-extent-copy-ico" xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
            "<path d=\"M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1\"/>"
            "</svg>"
        )
        copy_btn = (
            f'<div class="report-extent-ids">'
            f'<code class="report-extent-id" title="{cap_e}">{cap_e}</code> '
            f'<button type="button" class="report-extent-copy" data-report-copy="{cap_e}" '
            f'aria-label="{_e(copy_label)}" title="{_e(copy_label)}">{copy_ico}</button>'
            f"</div>"
        )
    else:
        copy_btn = ""
    return (
        '<header class="report-extent-topbar" role="banner">'
        '<div class="report-extent-brand">'
        '<span class="report-extent-mark" aria-hidden="true"></span>'
        "<div>"
        '<span class="report-extent-title">Test Intellect AI</span>'
        '<span class="report-extent-sub">Automation test report</span>'
        "</div>"
        "</div>"
        f'<div class="report-extent-meta">'
        f'<p class="report-extent-when">Generated {dt}</p>'
        f"{copy_btn}"
        f"</div>"
        "</header>"
    )


def _html_extent_donut(
    passed: int,
    failed: int,
    skipped: int = 0,
    *,
    aborted: int = 0,
) -> str:
    p = max(0, int(passed))
    f = max(0, int(failed))
    ab = max(0, int(aborted))
    sk = max(0, int(skipped))
    total = p + f + ab + sk
    if total <= 0:
        return ""
    pp = 100.0 * p / total
    fp = 100.0 * f / total
    abp = 100.0 * ab / total
    skp = 100.0 * sk / total
    cap = (
        f"Pass {p} ({pp:.0f}%), Fail {f} ({fp:.0f}%), "
        f"Aborted {ab} ({abp:.0f}%), Skipped {sk} ({skp:.0f}%)"
    )
    return (
        f'<div class="report-extent-donut-wrap" role="img" '
        f'aria-label="{_e(cap)}" title="{_e(cap)}">'
        f'<div class="report-extent-donut" style="--pct-pass:{pp:.2f};--pct-fail:{fp:.2f};'
        f'--pct-aborted:{abp:.2f};--pct-skip:{skp:.2f}">'
        f'<div class="report-extent-donut-hole">'
        f'<span class="report-extent-donut-total">{_e(str(total))}</span>'
        f'<span class="report-extent-donut-lbl">tests</span>'
        f"</div></div></div>"
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


def _html_section_case_dashboard(ok: bool, steps: list) -> str:
    cpass, cfail, cskip = _single_case_pass_fail_skip(ok, steps)
    m = 1
    rows = [
        _html_dash_hbar_row("Pass", cpass, m, "pass"),
        _html_dash_hbar_row("Fail", cfail, m, "fail"),
    ]
    if cskip:
        rows.append(_html_dash_hbar_row("Skipped", cskip, m, "skip"))
    donut = _html_extent_donut(cpass, cfail, cskip)
    if cskip:
        kpi_skip = (
            f'<div class="report-dash-kpi report-dash-kpi--extent">'
            f'<span class="report-dash-kpi-v report-dash-kpi-v--skip">{_e(str(cskip))}</span>'
            f'<span class="report-dash-kpi-l">Skipped</span></div>'
        )
    else:
        kpi_skip = ""
    return (
        f'<section class="report-dash report-dash--extent" aria-label="Test Status">'
        f'<h2 class="section-title"><span class="title-accent">Test Status</span></h2>'
        f'<div class="report-dash-row">'
        f"{donut}"
        f'<div class="report-dash-kpis">'
        f'<div class="report-dash-kpi report-dash-kpi--extent"><span class="report-dash-kpi-v report-dash-kpi-v--ok">{_e(str(cpass))}</span>'
        f'<span class="report-dash-kpi-l">Passed</span></div>'
        f'<div class="report-dash-kpi report-dash-kpi--extent"><span class="report-dash-kpi-v report-dash-kpi-v--bad">{_e(str(cfail))}</span>'
        f'<span class="report-dash-kpi-l">Failed</span></div>'
        f"{kpi_skip}"
        f"</div>"
        f"</div>"
        f'<div class="report-dash-bars">{"".join(rows)}</div>'
        f"</section>"
    )


def _html_hero_landing_single() -> str:
    return (
        '<div class="report-landing-hero report-landing-hero--extent">'
        '<p class="report-landing-kicker">Summary</p>'
        '<h1 class="report-landing-title">Execution Overview</h1>'
        '<p class="report-landing-desc">Single test run (ExtentReports-style layout)</p>'
        "</div>"
    )


def _bool_yn(b: object) -> str:
    if isinstance(b, bool):
        return "Yes" if b else "No"
    return "—"


def _ms_pretty(n: int) -> str:
    n = int(n)
    if n >= 1000 and n % 1000 == 0:
        return f"{n // 1000}s ({n} ms)"
    return f"{n} ms"


def _html_environment_section(
    run_environment: dict[str, Any] | None, *, for_landing: bool = True
) -> str:
    if not run_environment or not isinstance(run_environment, dict):
        return ""
    d = run_environment
    h_b = d.get("headless")
    if isinstance(h_b, bool) and d.get("headless_locked"):
        h_line = f'{_e("Yes" if h_b else "No")} <span class="report-env-locked">{_e("(AUTOMATION_HEADLESS)")}</span>'
    elif isinstance(h_b, bool):
        h_line = _e(_bool_yn(h_b))
    else:
        h_line = "—"
    rows: list[tuple[str, str]] = [
        ("Browser", _e(str(d.get("browser", "") or "—"))),
        ("Headless", h_line),
        (
            "Default timeout",
            _e(_ms_pretty(int(d.get("default_timeout_ms", 0) or 0))),
        ),
        (
            "Screenshot on pass",
            _e(_bool_yn(d.get("screenshot_on_pass"))),
        ),
        (
            "Generate trace file",
            _e(_bool_yn(d.get("trace_file_generation"))),
        ),
        (
            "Post-run analysis",
            _e(_bool_yn(d.get("post_run_analysis"))),
        ),
        (
            "Locator prerun (spike)",
            _e(_bool_yn(d.get("spike_prerun"))),
        ),
        (
            "Parallel execution (default)",
            _e(str(int(d.get("parallel_execution", 1) or 1))),
        ),
    ]
    inner = "".join(f"<dt>{_e(lab)}</dt><dd>{val}</dd>" for lab, val in rows)
    extra = " report-section--env-landing" if for_landing else ""
    return (
        f'<section class="report-section report-section--env{extra}" aria-label="Environment">'
        f'<h2 class="section-title"><span class="title-accent">Environment</span></h2>'
        f'<dl class="report-meta report-meta--env">'
        f"{inner}"
        f"</dl></section>"
    )


def _html_hero_landing_suite() -> str:
    return (
        '<div class="report-landing-hero report-landing-hero--extent">'
        '<p class="report-landing-kicker">Suite run</p>'
        '<h1 class="report-landing-title">Execution Overview</h1>'
        "</div>"
    )


def _html_landing_page_single(
    ok: bool,
    steps: list,
    *,
    tag: str = "",
    run_environment: dict[str, Any] | None = None,
) -> str:
    inner = (
        _html_hero_landing_single()
        + _html_environment_section(run_environment, for_landing=True)
        + _html_section_case_dashboard(ok, steps)
        + _html_tag_breakdown_for_single_case((tag or "").strip(), ok, steps)
    )
    return f'<div class="report-landing-wrap">{inner}</div>'


def _html_tag_breakdown_for_single_case(tag_raw: str, ok: bool, steps: list) -> str:
    labels = parse_tag_tokens(tag_raw)
    if not labels:
        labels = ["—"]
    cpass, cfail, cskip = _single_case_pass_fail_skip(ok, steps)
    max_c = 1
    blocks: list[str] = []
    for tag_label in labels:
        bar_rows = [
            _html_dash_hbar_row("Pass", cpass, max_c, "pass"),
            _html_dash_hbar_row("Fail", cfail, max_c, "fail"),
        ]
        if cskip:
            bar_rows.append(
                _html_dash_hbar_row("Skipped", cskip, max_c, "skip")
            )
        t = _e(tag_label)
        blocks.append(
            f'<div class="report-dash-by-tag-block" role="group" '
            f'aria-label="{_e("Tag: " + tag_label)}">'
            f'<p class="report-dash-by-tag-name">{t}</p>'
            f'<div class="report-dash-bars">{"".join(bar_rows)}</div></div>'
        )
    return (
        f'<section class="report-dash report-dash--by-tag" aria-label="Test status by tag">'
        f'<h2 class="section-title"><span class="title-accent">By Tag</span></h2>'
        f'{"".join(blocks)}'
        f"</section>"
    )


def _aggregate_cases_by_tag(
    cases: list[dict[str, Any]],
) -> list[tuple[str, int, int, int, int]]:
    d: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    bucket_idx = {"pass": 0, "fail": 1, "aborted": 2, "skipped": 3}
    for c in cases:
        toks = parse_tag_tokens(str(c.get("tag") or ""))
        if not toks:
            toks = ["—"]
        else:
            toks = list(dict.fromkeys(toks))
        b = _case_nav_data_status(c)
        i = bucket_idx.get(b, 1)
        for lab in toks:
            d[lab][i] += 1
    return sorted(
        ((k, v[0], v[1], v[2], v[3]) for k, v in d.items()),
        key=lambda t: (t[0] == "—", t[0].lower()),
    )


def _html_tag_breakdown_for_suite(cases: list[dict[str, Any]]) -> str:
    if not cases:
        return ""
    rows = _aggregate_cases_by_tag(cases)
    blocks: list[str] = []
    for label, cpass, cfail, cabort, cskip in rows:
        max_c = max(cpass, cfail, cabort, cskip, 1)
        bar_rows = [
            _html_dash_hbar_row("Pass", cpass, max_c, "pass"),
            _html_dash_hbar_row("Fail", cfail, max_c, "fail"),
            _html_dash_hbar_row("Aborted", cabort, max_c, "aborted"),
            _html_dash_hbar_row("Skipped", cskip, max_c, "skip"),
        ]
        t = _e(label)
        a = _e("Tag: " + label)
        blocks.append(
            f'<div class="report-dash-by-tag-block" role="group" aria-label="{a}">'
            f'<p class="report-dash-by-tag-name">{t}</p>'
            f'<div class="report-dash-bars">{"".join(bar_rows)}</div>'
            f"</div>"
        )
    return (
        f'<section class="report-dash report-dash--suite report-dash--by-tag" '
        f'aria-label="Test status by tag">'
        f'<h2 class="section-title"><span class="title-accent">By Tag</span></h2>'
        f'{"".join(blocks)}'
        f"</section>"
    )


def _html_suite_run_dashboard(cases: list[dict[str, Any]]) -> str:
    n_case = len(cases)
    cpass = sum(1 for c in cases if _case_nav_data_status(c) == "pass")
    cfail = sum(1 for c in cases if _case_nav_data_status(c) == "fail")
    cabort = sum(1 for c in cases if _case_nav_data_status(c) == "aborted")
    cskip = sum(1 for c in cases if _case_nav_data_status(c) == "skipped")
    max_c = max(cpass, cfail, cabort, cskip, 1)
    bar_rows = [
        _html_dash_hbar_row("Pass", cpass, max_c, "pass"),
        _html_dash_hbar_row("Fail", cfail, max_c, "fail"),
        _html_dash_hbar_row("Aborted", cabort, max_c, "aborted"),
    ]
    if cskip:
        bar_rows.append(_html_dash_hbar_row("Skipped", cskip, max_c, "skip"))
    donut = _html_extent_donut(cpass, cfail, cskip, aborted=cabort)
    kpi_skip = (
        (
            f'<div class="report-dash-kpi report-dash-kpi--extent">'
            f'<span class="report-dash-kpi-v report-dash-kpi-v--skip">{_e(str(cskip))}</span>'
            f'<span class="report-dash-kpi-l">Skipped</span></div>'
        )
        if cskip
        else ""
    )
    kpi_ab = (
        (
            f'<div class="report-dash-kpi report-dash-kpi--extent">'
            f'<span class="report-dash-kpi-v report-dash-kpi-v--aborted">{_e(str(cabort))}</span>'
            f'<span class="report-dash-kpi-l">Aborted</span></div>'
        )
        if cabort
        else ""
    )
    return (
        f'<section class="report-dash report-dash--suite report-dash--extent" aria-label="Test Status">'
        f'<h2 class="section-title"><span class="title-accent">Test Status</span></h2>'
        f'<div class="report-dash-row">'
        f"{donut}"
        f'<div class="report-dash-kpis">'
        f'<div class="report-dash-kpi report-dash-kpi--extent"><span class="report-dash-kpi-v">{_e(str(n_case))}</span>'
        f'<span class="report-dash-kpi-l">Total</span></div>'
        f'<div class="report-dash-kpi report-dash-kpi--extent"><span class="report-dash-kpi-v report-dash-kpi-v--ok">{_e(str(cpass))}</span>'
        f'<span class="report-dash-kpi-l">Passed</span></div>'
        f'<div class="report-dash-kpi report-dash-kpi--extent"><span class="report-dash-kpi-v report-dash-kpi-v--bad">{_e(str(cfail))}</span>'
        f'<span class="report-dash-kpi-l">Failed</span></div>'
        f"{kpi_ab}{kpi_skip}"
        f"</div></div>"
        f'<div class="report-dash-bars">{"".join(bar_rows)}</div>'
        f"</section>"
    )


def _html_landing_page_suite(cases: list[dict[str, Any]]) -> str:
    return (
        f'<div class="report-landing-wrap">'
        f"{_html_hero_landing_suite()}"
        f"{_html_suite_run_dashboard(cases)}"
        f"{_html_tag_breakdown_for_suite(cases)}"
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
    requirement_ticket_id: str = "",
    tag: str = "",
    analysis: str = "",
    trace_href: str | None = None,
    embed_portable: bool = True,
    run_environment: dict[str, Any] | None = None,
    case_status: str | None = None,
) -> str:
    h = _e(title or "Spike")
    u = _e(url)
    req_e = _e((requirement_ticket_id or "").strip() or "—")
    jira_e = _e((jira_id or "").strip() or "—")
    _tag_list = parse_tag_tokens(tag)
    tag_e = _e(" · ".join(_tag_list)) if _tag_list else "—"
    report_dt = _e(_format_report_datetime())
    overall, result_mod = _case_badge_from_status(ok, case_status)
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
    env_block = _html_environment_section(run_environment, for_landing=False)
    return f"""<header class="report-header">
  <div class="report-header-top">
    <div class="report-header-row">
      <h1 class="report-title">{h}</h1>
      <span class="result-badge result-badge--{result_mod}">{_e(overall)}</span>
    </div>
  </div>
  <dl class="report-meta">
    <dt>Date &amp; time</dt><dd class="report-datetime">{report_dt}</dd>
    <dt>Requirement ticket</dt><dd class="report-jira">{req_e}</dd>
    <dt>Test ID</dt><dd class="report-jira">{jira_e}</dd>
    <dt>Tags</dt><dd class="report-jira">{tag_e}</dd>
    <dt>URL</dt><dd><a class="report-url" href="{u}">{u}</a></dd>
    <dt>Run ID</dt><dd><code class="report-id">{_e(run_id)}</code></dd>
  </dl>
</header>
{env_block}
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
<section class="report-section"><h2 class="section-title">Debug Logs</h2>
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
  --extent-pass:#26a69a;
  --extent-fail:#ef5350;
  --extent-aborted:#f59e0b;
  --extent-skip:#ffb74d;
  --extent-bar:#1b5e20;
  --extent-bar2:#00897b;
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
  --extent-pass:#00897b;
  --extent-fail:#e53935;
  --extent-aborted:#d97706;
  --extent-skip:#fb8c00;
  --extent-bar:#2e7d32;
  --extent-bar2:#00695c;
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
  max-width:min(100%,96rem);
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
.report-layout--3col{{
  display:grid;
  grid-template-columns:minmax(15rem,24rem) minmax(0,1fr) minmax(12.5rem,18rem);
  align-items:start;
  gap:1rem 1.25rem;
  width:100%;
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
.report-layout--3col .report-nav{{
  flex:unset;
  max-width:100%;
  min-width:0;
  width:auto;
}}
.report-nav-filters-aside{{
  flex:0 0 minmax(12.5rem,18rem);
  min-width:0;
  position:sticky;
  top:0.75rem;
  align-self:start;
  max-height:calc(100vh - 2.5rem);
  overflow-y:auto;
  padding:0.2rem 0.15rem 0.6rem 0.25rem;
  box-sizing:border-box;
}}
.report-nav-filters-stack{{
  display:flex;
  flex-direction:column;
  gap:0.75rem;
}}
.report-nav-filters-aside .report-nav-filter{{
  flex-direction:column;
  align-items:stretch;
  margin:0;
  gap:0.35rem;
}}
.report-nav-filters-aside .report-nav-filter-label{{
  margin:0;
}}
.report-nav-filters-aside .report-nav-filter-select{{
  width:100%;
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
.report-dash--by-tag .section-title{{
  margin-top:0;
}}
.report-dash--by-tag.report-dash--suite{{
  margin-top:0.5rem;
}}
.report-dash-by-tag-block{{
  margin:0 0 0.9rem 0;
}}
.report-dash-by-tag-block:last-child{{
  margin-bottom:0;
}}
.report-dash-by-tag-name{{
  margin:0 0 0.45rem 0;
  font-size:0.9rem;
  font-weight:600;
  color:var(--text);
  font-family:var(--mono);
  word-break:break-word;
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
.report-dash-hbar-f--aborted{{background:linear-gradient(90deg,#f59e0b,#fbbf24);}}
.report-dash-hbar-f--skip{{background:linear-gradient(90deg,#d97706,#fbbf24);}}
.report-dash-hbar-f--unk{{background:linear-gradient(90deg,#64748b,#94a3b8);}}
.report-dash-hbar-n{{
  text-align:right;
  font-variant-numeric:tabular-nums;
  font-weight:600;
  color:var(--text);
}}
.report-extent-topbar{{
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  justify-content:space-between;
  gap:0.75rem 1.25rem;
  margin:0 0 1rem;
  padding:0.85rem 1.1rem;
  border-radius:var(--radius);
  background:linear-gradient(120deg,var(--extent-bar) 0%,var(--extent-bar2) 55%,#004d40 100%);
  color:#e8f5e9;
  box-shadow:0 2px 12px rgba(0,0,0,.25);
  border:1px solid color-mix(in srgb, #fff 12%, transparent);
}}
.report-extent-brand{{
  display:flex;
  align-items:center;
  gap:0.65rem;
  min-width:0;
}}
.report-extent-mark{{
  display:inline-block;
  width:0.5rem;
  height:2.25rem;
  border-radius:3px;
  background:linear-gradient(180deg,#a5d6a7,#4caf50);
  box-shadow:0 0 0 1px rgba(0,0,0,.15);
  flex-shrink:0;
}}
.report-extent-title{{
  display:block;
  font-size:1.1rem;
  font-weight:700;
  letter-spacing:0.02em;
  line-height:1.25;
}}
.report-extent-sub{{
  display:block;
  font-size:0.75rem;
  font-weight:500;
  opacity:0.88;
  margin-top:0.12rem;
  letter-spacing:0.04em;
  text-transform:uppercase;
}}
.report-extent-when{{
  margin:0;
  font-size:0.8rem;
  font-weight:500;
  opacity:0.92;
  font-family:var(--mono);
}}
.report-extent-meta{{
  text-align:right;
  display:flex;
  flex-direction:column;
  align-items:flex-end;
  gap:0.35rem;
  min-width:0;
}}
.report-extent-ids{{
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  justify-content:flex-end;
  gap:0.35rem 0.5rem;
  max-width:100%;
}}
.report-extent-id{{
  font-size:0.72rem;
  font-family:var(--mono);
  background:rgba(0,0,0,.2);
  padding:0.15rem 0.4rem;
  border-radius:4px;
  max-width:min(100%,18rem);
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}}
[data-theme="light"] .report-extent-id{{
  background:rgba(0,0,0,.1);
  color:var(--text);
}}
.report-extent-copy{{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  font:inherit;
  margin:0;
  padding:0.28rem;
  line-height:0;
  border-radius:5px;
  border:1px solid rgba(255,255,255,.35);
  background:rgba(255,255,255,.12);
  color:inherit;
  cursor:pointer;
}}
.report-extent-copy-ico{{display:block;}}
.report-extent-copy:hover{{background:rgba(255,255,255,.2);}}
.report-landing-hero--extent .report-landing-kicker{{
  color:var(--extent-bar2);
  font-weight:700;
  letter-spacing:0.12em;
  text-transform:uppercase;
  font-size:0.72rem;
  margin:0 0 0.35rem;
}}
[data-theme="dark"] .report-landing-hero--extent .report-landing-kicker{{
  color:#4db6ac;
}}
.report-landing-desc{{
  margin:0.45rem 0 0;
  font-size:0.86rem;
  color:var(--muted);
  line-height:1.45;
  max-width:40rem;
}}
.report-dash-row{{
  display:flex;
  flex-wrap:wrap;
  align-items:stretch;
  gap:1rem 1.25rem;
  margin:0 0 0.75rem 0;
}}
.report-extent-donut-wrap{{
  flex:0 0 auto;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:0.15rem 0.25rem 0.35rem 0;
}}
.report-extent-donut{{
  --a1:calc(var(--pct-pass)*3.6deg);
  --a2:calc((var(--pct-pass) + var(--pct-fail))*3.6deg);
  --a3:calc((var(--pct-pass) + var(--pct-fail) + var(--pct-aborted))*3.6deg);
  width:7.25rem;
  height:7.25rem;
  border-radius:50%;
  display:flex;
  align-items:center;
  justify-content:center;
  background:conic-gradient(
    var(--extent-pass) 0deg var(--a1),
    var(--extent-fail) var(--a1) var(--a2),
    var(--extent-aborted) var(--a2) var(--a3),
    var(--extent-skip) var(--a3) 360deg
  );
  box-shadow:0 2px 10px rgba(0,0,0,.2);
}}
.report-extent-donut-hole{{
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  width:4.4rem;
  height:4.4rem;
  border-radius:50%;
  background:var(--card);
  border:1px solid var(--bd);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
}}
.report-extent-donut-total{{
  font-size:1.25rem;
  font-weight:800;
  font-variant-numeric:tabular-nums;
  line-height:1.1;
  color:var(--text);
}}
.report-extent-donut-lbl{{
  font-size:0.65rem;
  font-weight:600;
  text-transform:uppercase;
  letter-spacing:0.08em;
  color:var(--muted);
  margin-top:0.1rem;
}}
.report-dash--extent .report-dash-kpis{{
  flex:1 1 12rem;
  min-width:0;
}}
.report-dash-kpi--extent{{
  background:color-mix(in srgb, var(--card) 88%, var(--bd));
  border:1px solid var(--bd);
  border-top:3px solid var(--accent);
  border-radius:10px;
  padding:0.55rem 0.7rem 0.6rem;
  box-shadow:0 1px 0 rgba(15,23,42,.04);
}}
[data-theme="dark"] .report-dash-kpi--extent{{
  border-top-color:var(--extent-bar2);
  box-shadow:0 1px 0 rgba(255,255,255,.04);
}}
.report-dash-kpi-v--skip{{color:var(--extent-skip);}}
.report-dash-kpi-v--aborted{{color:var(--extent-aborted);}}
@media (max-width:28rem){{
  .report-dash-row{{flex-direction:column;align-items:stretch;}}
  .report-extent-donut-wrap{{justify-content:flex-start;}}
}}
@keyframes rep-fade{{
  from{{opacity:0.85;}}
  to{{opacity:1;}}
}}
@media (max-width:52rem){{
  .report-layout{{
    flex-direction:column;
  }}
  .report-layout--3col{{
    display:flex;
    flex-direction:column;
    gap:0.85rem 1rem;
  }}
  .report-layout--3col .report-nav{{
    order:1;
  }}
  .report-layout--3col .report-panels{{
    order:2;
  }}
  .report-layout--3col .report-nav-filters-aside{{
    order:3;
    position:relative;
    top:auto;
    max-height:none;
    max-width:100%;
    width:100%;
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
.result-badge--aborted{{
  background:rgba(245,158,11,.14);
  color:#f59e0b;
  border:1px solid color-mix(in srgb, #f59e0b 38%, transparent);
}}
[data-theme="light"] .result-badge--aborted{{
  background:rgba(217,119,6,.1);
  color:#d97706;
  border:1px solid color-mix(in srgb, #d97706 35%, transparent);
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
.report-section--env-landing{{
  margin-bottom:0.9rem;
}}
.report-meta--env{{
  margin:0;
}}
.report-env-locked{{
  font-size:0.88em;
  color:var(--muted);
  font-style:italic;
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
  .report-nav,.report-nav-filters-aside{{display:none;}}
  .report-panel--status-hidden{{display:block!important;}}
  .report-panel,#panel-dash{{display:block!important;}}
  .report-wrap--nav .report-panels .report-panel{{page-break-inside:avoid;}}
  pre.log{{max-height:none;}}
  .report-theme-btn{{display:none;}}
}}
</style>
</head><body class="report-extent">
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
  function reportSetHashForPanel(id) {{
    if (!id) return;
    try {{
      var u = new URL(window.location.href);
      u.hash = id;
      if (history.replaceState) history.replaceState(null, "", u);
      else window.location.hash = id;
    }} catch (e) {{
      try {{ window.location.hash = id; }} catch (e2) {{}}
    }}
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
      reportSetHashForPanel(id);
    }});
  }});
  function reportRouteFromHash() {{
    var h = (location.hash || "").replace(/^#/, "");
    if (!h) return;
    if (h === "panel-dash" || /^case-\\d+$/.test(h)) {{
      var t = document.querySelector('.report-nav-item[data-target="' + h + '"]');
      if (t) t.click();
      setTimeout(function () {{ window.scrollTo(0, 0); }}, 0);
    }}
  }}
  window.addEventListener("hashchange", function () {{ reportRouteFromHash(); }});
  reportRouteFromHash();
  document.querySelectorAll("[data-report-copy]").forEach(function (cbtn) {{
    cbtn.addEventListener("click", function () {{
      var t = cbtn.getAttribute("data-report-copy");
      if (!t) return;
      var mark = function () {{
        var prev = cbtn.getAttribute("aria-label");
        cbtn.setAttribute("aria-label", "Copied");
        setTimeout(function () {{ if (prev) cbtn.setAttribute("aria-label", prev); }}, 1600);
      }};
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(t).then(mark).catch(function () {{ window.prompt("Copy:", t); }});
      }} else {{
        window.prompt("Copy:", t);
      }}
    }});
  }});
  var fsel = document.getElementById("reportStatusSelect");
  var tsel = document.getElementById("reportTagSelect");
  function rowMatchesTagFilters(art) {{
    if (!tsel) return true;
    var vTag = tsel.value;
    if (vTag === "all") return true;
    var tagPipe = (art.getAttribute("data-report-case-tags") || "").trim();
    if (vTag === "__untagged__") return !tagPipe;
    if (!tagPipe) return false;
    var parts = tagPipe.split("|");
    for (var i = 0; i < parts.length; i++) {{ if (parts[i] === vTag) return true; }}
    return false;
  }}
  function applyNavCaseFilters() {{
    var vSt = fsel ? fsel.value : "all";
    document.querySelectorAll("li[data-report-case-status]").forEach(function (li) {{
      var st = li.getAttribute("data-report-case-status");
      if (!st) return;
      var okSt = (vSt === "all" || st === vSt);
      var mTag = tsel ? rowMatchesTagFilters(li) : true;
      li.style.display = (okSt && mTag) ? "" : "none";
    }});
    document.querySelectorAll("article[data-report-case-status]").forEach(function (art) {{
      var st = art.getAttribute("data-report-case-status");
      if (!st) return;
      var okSt = (vSt === "all" || st === vSt);
      var mTag = tsel ? rowMatchesTagFilters(art) : true;
      if (okSt && mTag) {{ art.classList.remove("report-panel--status-hidden"); }}
      else {{ art.classList.add("report-panel--status-hidden"); }}
    }});
    var activeP = document.querySelector(".report-panel.is-active");
    if (activeP && activeP.getAttribute("data-report-case-status") && activeP.classList.contains("report-panel--status-hidden")) {{
      var dashBtn = document.querySelector('.report-nav-item[data-target="panel-dash"]');
      if (dashBtn) {{ dashBtn.click(); }}
    }}
  }}
  if (fsel) fsel.addEventListener("change", applyNavCaseFilters);
  if (tsel) tsel.addEventListener("change", applyNavCaseFilters);
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
    requirement_ticket_id: str = "",
    tag: str = "",
    analysis: str = "",
    trace_href: str | None = None,
    embed_portable: bool = True,
    run_environment: dict[str, Any] | None = None,
) -> str:
    jt = (jira_id or "").strip()
    ttag = (tag or "").strip()
    landing = _html_landing_page_single(
        ok, steps, tag=ttag, run_environment=run_environment
    )
    case_block = _build_case_content_html(
        run_id,
        title,
        bdd,
        url,
        ok,
        steps,
        log,
        jira_id=jira_id,
        requirement_ticket_id=requirement_ticket_id,
        tag=tag,
        analysis=analysis,
        trace_href=trace_href,
        embed_portable=embed_portable,
        run_environment=None,
    )
    st = _case_nav_data_status({"ok": ok, "steps": steps})
    nav_case_cls = _nav_st_classes(st)
    uniq_tags, inc_untagged = _tag_filter_choices(None, single_tag=ttag)
    filters_aside = _html_report_filters_aside(uniq_tags, inc_untagged)
    tag_pipe_attr = _e(_tag_data_pipe(None, tag=ttag))
    nav_dash = _e("Summary")
    nav_title = _e(_nav_label_text(jt, (title or "").strip(), ttag))
    st_esc = _e(st)
    extent_header = _html_extent_topbar(
        copy_id=str(run_id or "").strip(), copy_label="Copy run id"
    )
    body_html = f"""<div class="report-wrap report-wrap--nav">
{extent_header}
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
  <div class="report-layout report-layout--3col">
    <nav class="report-nav" aria-label="Report sections">
      <ul class="report-nav-list">
        <li>
          <button type="button" class="report-nav-item is-active" data-target="panel-dash" aria-current="page">{nav_dash}</button>
        </li>
        <li data-report-case-status="{st_esc}" data-report-case-tags="{tag_pipe_attr}">
          <button type="button" class="{nav_case_cls}" data-target="case-0">{nav_title}</button>
        </li>
      </ul>
    </nav>
    <div class="report-panels">
      <article id="panel-dash" class="report-panel is-active" tabindex="-1">
{landing}
      </article>
      <article id="case-0" class="report-panel" data-report-case-status="{st_esc}" data-report-case-tags="{tag_pipe_attr}" tabindex="-1">
{case_block}
      </article>
    </div>
{filters_aside}
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
        + _e("Summary")
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
        req_tid = str(c.get("requirement_ticket_id") or "")
        tag = str(c.get("tag") or "")
        th = c.get("trace_href")
        trace_href: str | None
        if isinstance(th, str) and th.strip():
            trace_href = th.strip()
        else:
            trace_href = None
        re_env = c.get("run_environment")
        run_env_for_case = re_env if isinstance(re_env, dict) else None
        cs_raw = c.get("case_status")
        case_st = str(cs_raw).strip() if cs_raw is not None else None
        case_block = _build_case_content_html(
            run_id,
            t,
            bdd,
            u,
            ok,
            steps,
            log,
            jira_id=jira,
            requirement_ticket_id=req_tid,
            tag=tag,
            analysis=analysis,
            trace_href=trace_href,
            embed_portable=embed_portable,
            run_environment=run_env_for_case,
            case_status=case_st or None,
        )
        cst = _case_nav_data_status(c)
        ncls = _nav_st_classes(cst)
        tag_pipe_attr = _e(_tag_data_pipe(c))
        lbl = _e(
            _nav_label_text(
                (jira or "").strip(), (t or "").strip(), (tag or "").strip()
            )
        )
        nav_items.append(
            f'<li data-report-case-status="{_e(cst)}" data-report-case-tags="{tag_pipe_attr}">'
            f'<button type="button" class="{ncls}" data-target="case-{i}">'
            f"{lbl}</button></li>"
        )
        arts.append(
            f'<article id="case-{i}" class="report-panel" data-report-case-status="{_e(cst)}" data-report-case-tags="{tag_pipe_attr}" tabindex="-1">\n'
            f"{case_block}\n"
            f"</article>"
        )
    nav_html = "\n".join(nav_items)
    art_html = "\n".join(arts)
    uniq_tags, inc_untagged = _tag_filter_choices(cases)
    filters_aside = _html_report_filters_aside(uniq_tags, inc_untagged)
    extent_header = _html_extent_topbar(
        copy_id=str(report_id or "").strip(), copy_label="Copy report id"
    )
    body_html = f"""<div class="report-wrap report-wrap--nav">
{extent_header}
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
  <div class="report-layout report-layout--3col">
    <nav class="report-nav" aria-label="Report sections">
      <ul class="report-nav-list">
{nav_html}
      </ul>
    </nav>
    <div class="report-panels">
{art_html}
    </div>
{filters_aside}
  </div>
</div>"""
    return _emit_report_document("Report", body_html)
