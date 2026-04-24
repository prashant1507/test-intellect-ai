from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from settings import settings

from . import cancel
from . import suite_state
from .errors import SpikeUserError
from .run_report_html import render_batch_report_html
from .spike import run_automation_spike
from .store import (
    append_suite_case_run_history,
    list_suite_cases,
    set_suite_case_last_analysis,
    set_suite_case_last_run_id_only,
)


def suite_report_path() -> Path:
    p = Path(settings.automation_reports_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / f"suite_{uuid.uuid4()}.html"


def run_suite_sequential(
    case_ids: list[str] | None,
    *,
    default_url: str = "",
    clear_cancel: bool = True,
) -> dict[str, Any]:
    if clear_cancel:
        cancel.clear_for_new_suite()
    want = {str(x).strip() for x in (case_ids or []) if str(x).strip()}
    all_cases = list_suite_cases()
    if not want:
        to_run = list(all_cases)
    else:
        to_run = [c for c in all_cases if str(c.get("id") or "") in want]
    report_id = str(uuid.uuid4())
    p = Path(settings.automation_reports_dir) / f"{report_id}.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    batch_cases: list[dict[str, Any]] = []
    d_url = (default_url or "").strip()
    single_target = len(to_run) == 1 and bool(want)
    for c in to_run:
        if cancel.is_stop_all_suite():
            break
        cid = str(c.get("id") or "")
        t = c.get("title") or "Untitled"
        saved_u = str(c.get("url") or "").strip()
        if single_target and d_url:
            u_run = d_url
        else:
            u_run = saved_u or d_url
        suite_state.set_running_case(cid or None)
        try:
            r = run_automation_spike(
                t,
                str(c.get("bdd") or ""),
                u_run,
                html_dom=(c.get("html_dom") or None),
                jira_id=str(c.get("jira_id") or ""),
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
            if em == can_msg:
                st = "ABORTED"
                rid = str(getattr(e, "run_id", "") or "")
                r = {
                    "error": em,
                    "status": "aborted",
                    "run_id": rid,
                }
            else:
                st = "FAIL"
                rid = str(getattr(e, "run_id", "") or "")
                r = {
                    "error": em,
                    "status": "failed",
                    "run_id": rid,
                }
        except Exception as e:  # noqa: BLE001
            st = "FAIL"
            rid = ""
            r = {"error": str(e), "status": "failed", "run_id": rid}
        finally:
            suite_state.clear_running_case()
        if (
            cid
            and str(rid or "").strip()
            and st in ("ABORTED", "FAIL")
        ):
            set_suite_case_last_run_id_only(cid, str(rid).strip())
        if cid:
            append_suite_case_run_history(cid, str(rid or ""), st)
        results.append(
            {
                "case_id": cid,
                "title": t,
                "result": st,
                "run_id": rid,
                "status": r.get("status", "failed"),
            }
        )
        tru = r.get("trace_url")
        trace_href = tru if isinstance(tru, str) and tru.strip() else None
        batch_cases.append(
            {
                "run_id": str(rid or ""),
                "title": t,
                "bdd": str(c.get("bdd") or ""),
                "url": u_run,
                "ok": st == "PASS",
                "case_status": st,
                "steps": r.get("steps") or [],
                "debug_logs": r.get("debug_logs") or [],
                "analysis": str(r.get("analysis") or ""),
                "jira_id": str(c.get("jira_id") or ""),
                "trace_href": trace_href,
            }
        )
    if batch_cases:
        body = render_batch_report_html(report_id, batch_cases)
    else:
        body = (
            f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
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
