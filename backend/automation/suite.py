from __future__ import annotations

import html
import json
import uuid
from pathlib import Path
from typing import Any

from settings import settings

from . import cancel
from . import suite_state
from .errors import SpikeUserError
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
    rows: list[str] = []
    results: list[dict] = []
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
        rows.append(
            f"<tr><td>{html.escape(t, quote=True)}</td><td>{st}</td><td><code>{html.escape(rid, quote=True)}</code></td></tr>"
        )
        results.append(
            {
                "case_id": cid,
                "title": t,
                "result": st,
                "run_id": rid,
                "status": r.get("status", "failed"),
            }
        )
    body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Suite {report_id[:8]}</title>
<style>table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px;font-family:system-ui}}</style>
</head><body><h1>Automation suite</h1><p>Report id: {html.escape(report_id, quote=True)}</p>
<p>Cases in suite: {len(all_cases)} — cases run: {len(to_run)}</p>
<table><thead><tr><th>Title</th><th>Result</th><th>Run id</th></tr></thead><tbody>
{"".join(rows)}</tbody></table>
<h2>JSON</h2><pre style="background:#f5f5f5;padding:8px;overflow:auto">{html.escape(json.dumps(results, ensure_ascii=False, indent=2), quote=True)}</pre>
</body></html>"""
    p.write_text(body, encoding="utf-8")
    report_url = f"/api/automation/suite-reports/{p.name}"
    return {
        "report_id": report_id,
        "case_count": len(results),
        "case_total": len(to_run),
        "results": results,
        "report_url": report_url,
    }
