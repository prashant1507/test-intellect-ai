from __future__ import annotations

import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from settings import settings

from . import cancel
from . import suite_state
from .errors import SpikeUserError
from .prefs import (
    get_effective_automation_parallel_execution,
    get_run_environment_for_report,
)
from .run_report_html import render_batch_report_html
from .spike import run_automation_spike
from .store import (
    append_suite_case_run_history,
    list_suite_cases,
    set_suite_case_last_analysis,
    set_suite_case_last_run_id_only,
)
from .tag_csv import parse_jira_key_tokens, parse_tag_tokens


def _spike_type_for_suite_case(c: dict[str, Any]) -> str:
    st = str(c.get("spike_type") or "").strip().lower()
    if st in ("ui", "api"):
        return st
    toks = parse_tag_tokens(str(c.get("tag") or ""))
    if toks and toks[0].lower() == "api":
        return "api"
    return "ui"


def _apply_optional_suite_filters(
    cases: list[dict[str, Any]],
    *,
    use_tag_filter: bool,
    filter_tag_tokens: list[str],
    use_jira_filter: bool,
    filter_jira_keys: list[str],
) -> list[dict[str, Any]]:
    tag_w: set[str] | None = None
    if use_tag_filter and filter_tag_tokens:
        tag_w = {t.lower() for t in filter_tag_tokens}
    jira_w: set[str] | None = None
    if use_jira_filter and filter_jira_keys:
        jira_w = {j.lower() for j in filter_jira_keys}
    if tag_w is None and jira_w is None:
        return list(cases)
    out: list[dict[str, Any]] = []
    for c in cases:
        if tag_w is not None:
            ctags = {t.lower() for t in parse_tag_tokens(str(c.get("tag") or ""))}
            if not (ctags & tag_w):
                continue
        if jira_w is not None:
            cj = str(c.get("jira_id") or "").strip().lower()
            if cj not in jira_w:
                continue
        out.append(c)
    return out


def _run_one_suite_case(
    c: dict[str, Any],
    *,
    d_url: str,
    single_target: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cid = str(c.get("id") or "")
    t = c.get("title") or "Untitled"
    saved_u = str(c.get("url") or "").strip()
    if single_target and d_url:
        u_run = d_url
    else:
        u_run = saved_u or d_url
    if cid:
        suite_state.add_running_case(cid)
    r: dict[str, Any] = {"status": "failed", "run_id": ""}
    st: str
    try:
        try:
            r = run_automation_spike(
                t,
                str(c.get("bdd") or ""),
                u_run,
                html_dom=(c.get("html_dom") or None),
                jira_id=str(c.get("jira_id") or ""),
                tag=str(c.get("tag") or ""),
                requirement_ticket_id=str(c.get("requirement_ticket_id") or ""),
                write_run_html=False,
                spike_type=_spike_type_for_suite_case(c),
            )
            st = "PASS" if r.get("status") == "completed" else "FAIL"
            rid = r.get("run_id", "")
            if cid:
                set_suite_case_last_analysis(
                    cid, str(r.get("analysis") or ""), run_id=str(rid or "")
                )
        except SpikeUserError as e:
            can_msg = cancel.cancel_message().strip()
            em = str(e).strip()
            elogs = list(getattr(e, "logs", None) or [])
            if em == can_msg:
                st = "ABORTED"
                rid = str(getattr(e, "run_id", "") or "")
                r = {
                    "error": em,
                    "status": "aborted",
                    "run_id": rid,
                    "debug_logs": elogs,
                }
            else:
                st = "FAIL"
                rid = str(getattr(e, "run_id", "") or "")
                r = {
                    "error": em,
                    "status": "failed",
                    "run_id": rid,
                    "debug_logs": elogs,
                }
        except Exception as e:  # noqa: BLE001
            st = "FAIL"
            rid = ""
            r = {"error": str(e), "status": "failed", "run_id": rid}
    finally:
        if cid:
            suite_state.remove_running_case(cid)
    rid = str(r.get("run_id", "") or "")
    if (
        cid
        and str(rid or "").strip()
        and st in ("ABORTED", "FAIL")
    ):
        set_suite_case_last_run_id_only(cid, str(rid).strip())
    if cid:
        append_suite_case_run_history(cid, str(rid or ""), st)
    results_item = {
        "case_id": cid,
        "title": t,
        "result": st,
        "run_id": rid,
        "status": r.get("status", "failed"),
    }
    tru = r.get("trace_url")
    trace_href = tru if isinstance(tru, str) and tru.strip() else None
    batch_item = {
        "run_id": str(rid or ""),
        "title": t,
        "bdd": str(c.get("bdd") or ""),
        "url": u_run,
        "ok": st == "PASS",
        "case_status": st,
        "steps": r.get("steps") or [],
        "debug_logs": r.get("debug_logs") or [],
        "analysis": str(r.get("analysis") or r.get("error") or ""),
        "jira_id": str(c.get("jira_id") or ""),
        "requirement_ticket_id": str(c.get("requirement_ticket_id") or ""),
        "tag": str(c.get("tag") or ""),
        "trace_href": trace_href,
        "run_environment": get_run_environment_for_report(),
    }
    return results_item, batch_item


def _suite_skip_not_run_entry(
    c: dict[str, Any],
    *,
    d_url: str,
    single_target: bool,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cid = str(c.get("id") or "")
    t = c.get("title") or "Untitled"
    saved_u = str(c.get("url") or "").strip()
    if single_target and d_url:
        u_run = d_url
    else:
        u_run = saved_u or d_url
    if cid:
        append_suite_case_run_history(cid, "", "SKIPPED")
    results_item = {
        "case_id": cid,
        "title": t,
        "result": "SKIPPED",
        "run_id": "",
        "status": "skipped",
    }
    batch_item = {
        "run_id": "",
        "title": t,
        "bdd": str(c.get("bdd") or ""),
        "url": u_run,
        "ok": False,
        "case_status": "SKIPPED",
        "steps": [
            {
                "step_text": "Not executed",
                "pass": False,
                "err": reason,
            }
        ],
        "debug_logs": [],
        "analysis": "",
        "jira_id": str(c.get("jira_id") or ""),
        "requirement_ticket_id": str(c.get("requirement_ticket_id") or ""),
        "tag": str(c.get("tag") or ""),
        "trace_href": None,
        "run_environment": get_run_environment_for_report(),
    }
    return results_item, batch_item


def run_suite_sequential(
    case_ids: list[str] | None,
    *,
    default_url: str = "",
    clear_cancel: bool = True,
    use_tag_filter: bool = False,
    filter_tags: str = "",
    use_jira_filter: bool = False,
    filter_jira_ids: str = "",
) -> dict[str, Any]:
    if clear_cancel:
        cancel.clear_for_new_suite()
    want = {str(x).strip() for x in (case_ids or []) if str(x).strip()}
    all_cases = list_suite_cases()
    if not want:
        to_run = list(all_cases)
    else:
        to_run = [c for c in all_cases if str(c.get("id") or "") in want]
    f_tags = [t for t in parse_tag_tokens(filter_tags) if t]
    f_jira = [k for k in parse_jira_key_tokens(filter_jira_ids) if k]
    to_run = _apply_optional_suite_filters(
        to_run,
        use_tag_filter=use_tag_filter,
        filter_tag_tokens=f_tags,
        use_jira_filter=use_jira_filter,
        filter_jira_keys=f_jira,
    )
    report_id = str(uuid.uuid4())
    p = Path(settings.automation_reports_dir) / f"{report_id}.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    batch_cases: list[dict[str, Any]] = []
    d_url = (default_url or "").strip()
    single_target = len(to_run) == 1 and bool(want)
    parallel = get_effective_automation_parallel_execution()
    use_pool = parallel > 1 and len(to_run) > 1

    if not use_pool:
        ran = 0
        for c in to_run:
            if cancel.is_stop_all_suite():
                break
            ri, bi = _run_one_suite_case(
                c,
                d_url=d_url,
                single_target=single_target,
            )
            results.append(ri)
            batch_cases.append(bi)
            ran += 1
        if cancel.is_stop_all_suite():
            for c in to_run[ran:]:
                ri, bi = _suite_skip_not_run_entry(
                    c,
                    d_url=d_url,
                    single_target=single_target,
                    reason="Skipped (Suite run stopped)",
                )
                results.append(ri)
                batch_cases.append(bi)
    else:
        n = min(parallel, len(to_run))
        res_slots: list[dict[str, Any] | None] = [None] * len(to_run)
        batch_slots: list[dict[str, Any] | None] = [None] * len(to_run)

        def _work(idx: int) -> None:
            if cancel.is_stop_all_suite():
                return
            ri, bi = _run_one_suite_case(
                to_run[idx],
                d_url=d_url,
                single_target=single_target,
            )
            res_slots[idx] = ri
            batch_slots[idx] = bi

        it = iter(range(len(to_run)))
        futures: set = set()

        def _pump(ex: ThreadPoolExecutor) -> None:
            while len(futures) < n and not cancel.is_stop_all_suite():
                try:
                    idx = next(it)
                except StopIteration:
                    return
                futures.add(ex.submit(_work, idx))

        with ThreadPoolExecutor(max_workers=n) as pool:
            _pump(pool)
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for fut in done:
                    futures.discard(fut)
                    fut.result()
                if not cancel.is_stop_all_suite():
                    _pump(pool)
        for j in range(len(to_run)):
            if res_slots[j] is not None:
                results.append(res_slots[j])
                batch_cases.append(batch_slots[j])
            else:
                reason = (
                    "Skipped (Suite run stopped)"
                    if cancel.is_stop_all_suite()
                    else "skipped (not run)"
                )
                ri, bi = _suite_skip_not_run_entry(
                    to_run[j],
                    d_url=d_url,
                    single_target=single_target,
                    reason=reason,
                )
                results.append(ri)
                batch_cases.append(bi)
    if batch_cases:
        body = render_batch_report_html(report_id, batch_cases)
    else:
        body = (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
            '<title>Report</title></head><body><p>No cases in this run.</p></body></html>'
        )
    p.write_text(body, encoding="utf-8")
    report_url = f"/api/automation/suite-reports/{p.name}"
    return {
        "report_id": report_id,
        "case_count": len(results),
        "case_total": len(to_run),
        "results": results,
        "report_url": report_url,
    }
