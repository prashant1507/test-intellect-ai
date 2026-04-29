from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from audit_store import append_audit
from keycloak_auth import claims_username, get_keycloak_claims
from settings import settings

from . import cancel
from .tag_csv import normalize_tag_csv
from .errors import SpikeUserError
from .spike import run_automation_spike_async
from .prefs import (
    get_effective_automation_browser,
    get_effective_automation_default_timeout_ms,
    get_effective_automation_headless,
    get_effective_automation_parallel_execution,
    get_effective_automation_post_analysis,
    get_effective_automation_screenshot_on_pass,
    get_effective_automation_trace_file_generation,
)
from .store import (
    add_suite_case,
    delete_all_selector_cache,
    delete_all_suite_cases,
    delete_selector_cache_by_rowid,
    delete_suite_case,
    get_run,
    get_suite_case,
    list_selector_cache_rows,
    list_suite_case_run_history,
    list_suite_cases,
    set_automation_kv,
    update_suite_case,
    would_duplicate_suite_case,
)
from . import suite_state
from .suite import run_suite_sequential

router = APIRouter(prefix="/automation", tags=["automation"])

Kc = Annotated[dict | None, Depends(get_keycloak_claims)]


def _maybe_automation_audit(kc: dict | None, ticket_id: str, action: str) -> None:
    if settings.mock:
        return
    u = claims_username(kc) if settings.use_keycloak and kc else ""
    t = (ticket_id or "").strip()
    a = (action or "").strip()
    if not t or not a:
        return
    append_audit(u, t, a, None)


_AUDIT_TICKET_SAVED_SUITE = "AUTOMATION_SAVED_SUITE"
_AUDIT_TICKET_SAVED_SELECTORS = "AUTOMATION_SAVED_SELECTORS"

_UUID_36 = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)
_CASE_ID = re.compile(r"^[\w.-]{1,200}$")
_RE_PER_RUN_HTML = re.compile(r"^[0-9a-fA-F-]{10,200}\.html$")
_RE_SUITE_PREFIX = re.compile(r"^suite_[0-9a-fA-F-]{10,200}\.html$")
_RE_SUITE_UUID_HTML = re.compile(
    r"^[0-9a-fA-F-]{8}-[0-9a-fA-F-]{4}-[0-9a-fA-F-]{4}-[0-9a-fA-F-]{4}-[0-9a-fA-F-]{12}\.html$"
)


def _parse_run_id(s: str) -> str:
    t = s.strip()
    if not t or not _UUID_36.match(t):
        raise HTTPException(status_code=400, detail="invalid run id")
    return t


def _parse_suite_case_id(case_id: str) -> str:
    t = (case_id or "").strip()
    if not t or not _CASE_ID.match(t):
        raise HTTPException(status_code=400, detail="invalid case id")
    return t


def _html_report_file_response(path: Path) -> FileResponse:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="text/html; charset=utf-8")


def _run_detail(row: dict, steps: list) -> dict[str, Any]:
    rid = row["id"]
    base = f"/api/automation/artifacts/{rid}"
    st = (row.get("summary_json") or "").strip() or "{}"
    try:
        summary = json.loads(st) if st else {}
    except json.JSONDecodeError:
        summary = {}
    tr_zip = Path(settings.automation_artifacts_dir) / str(rid) / "trace.zip"
    trace_on_disk = tr_zip.is_file()
    tr_url = f"{base}/trace.zip" if trace_on_disk else None
    out_s = []
    for s in steps:
        p = s.get("screenshot_path")
        if p and isinstance(p, str):
            p2 = f"{base}/{p.split('/', 1)[-1]}"
        else:
            p2 = None
        d = {**dict(s), "screenshot_url": p2, "pass": bool(s.get("pass"))}
        for k in ("pass", "step_index", "step_text", "selector", "action", "value", "err", "source", "screenshot_path"):
            d.pop(f"__{k}__", None)
        out_s.append(d)
    return {
        "run_id": rid,
        "status": row.get("status"),
        "fingerprint": row.get("fingerprint", ""),
        "error": row.get("error"),
        "used_cache": bool(row.get("used_cache")),
        "trace_stored": trace_on_disk,
        "trace_url": tr_url,
        "steps": out_s,
        "summary": summary,
    }


class SpikeRunIn(BaseModel):
    title: str = Field(default="Spike", max_length=500)
    bdd: str = Field(..., min_length=1, description="BDD line(s)")
    url: str = Field(..., min_length=1, description="UI: page URL. API: base URL (https://...).")
    spike_type: str = Field(
        default="ui",
        description='Run mode: "ui" (Playwright) or "api" (HTTP + LLM)',
    )
    html_dom: str | None = Field(default=None, max_length=2_000_000)
    jira_id: str = Field(default="", max_length=200)
    requirement_ticket_id: str = Field(default="", max_length=200)
    tag: str = Field(default="", max_length=200)

    @field_validator("jira_id", mode="before")
    @classmethod
    def _spike_jira_strip(cls, v: object) -> str:
        return (str(v) if v is not None else "").strip()[:200]

    @field_validator("requirement_ticket_id", mode="before")
    @classmethod
    def _spike_req_ticket_strip(cls, v: object) -> str:
        return (str(v) if v is not None else "").strip()[:200]

    @field_validator("tag", mode="before")
    @classmethod
    def _spike_tag_strip(cls, v: object) -> str:
        return normalize_tag_csv(str(v) if v is not None else "")

    @field_validator("url", mode="before")
    @classmethod
    def _u(cls, v: object) -> str:
        s = (str(v) if v is not None else "").strip()
        if not s:
            return ""
        return s

    @field_validator("html_dom", mode="before")
    @classmethod
    def _h(cls, v: object) -> str | None:
        t = (str(v) if v is not None else "").strip()
        return t or None


class CancelInF(BaseModel):
    all_in_suite: bool = False


class AutomationBrowserIn(BaseModel):
    browser: Literal["chromium", "chrome", "firefox", "msedge"]


class AutomationEnvOptionsIn(BaseModel):
    automation_headless: bool
    automation_screenshot_on_pass: bool
    automation_trace_file_generation: bool
    automation_default_timeout_ms: int = Field(..., ge=1000, le=600_000)
    automation_parallel_execution: int = Field(1, ge=1, le=4)


def _automation_env_payload() -> dict[str, Any]:
    locked = settings.automation_headless is not None
    return {
        "automation_browser": get_effective_automation_browser(),
        "automation_headless": get_effective_automation_headless(),
        "automation_headless_locked": locked,
        "automation_screenshot_on_pass": get_effective_automation_screenshot_on_pass(),
        "automation_trace_file_generation": get_effective_automation_trace_file_generation(),
        "automation_post_analysis": get_effective_automation_post_analysis(),
        "automation_default_timeout_ms": get_effective_automation_default_timeout_ms(),
        "automation_parallel_execution": get_effective_automation_parallel_execution(),
    }


@router.get("/env")
def automation_env():
    return _automation_env_payload()


@router.post("/browser")
def automation_set_browser(body: AutomationBrowserIn) -> dict[str, Any]:
    set_automation_kv("browser", body.browser)
    return _automation_env_payload()


@router.post("/env-options")
def automation_set_env_options(body: AutomationEnvOptionsIn) -> dict[str, Any]:
    if settings.automation_headless is None:
        set_automation_kv("headless", "1" if body.automation_headless else "0")
    set_automation_kv("screenshot_on_pass", "1" if body.automation_screenshot_on_pass else "0")
    set_automation_kv("trace_file_generation", "1" if body.automation_trace_file_generation else "0")
    set_automation_kv("default_timeout_ms", str(int(body.automation_default_timeout_ms)))
    set_automation_kv("parallel_execution", str(int(body.automation_parallel_execution)))
    return _automation_env_payload()


@router.post("/cancel")
def automation_cancel_fn(body: CancelInF) -> dict[str, object]:
    if body.all_in_suite:
        cancel.request_stop_all_suite()
    else:
        cancel.request_stop_one_spike()
    return {"ok": True}


@router.post("/spike-run")
async def automation_spike_run(body: SpikeRunIn) -> dict[str, Any]:
    cancel.clear_for_isolated_spike_run()
    try:
        st = (body.spike_type or "ui").strip().lower()
        if st not in ("ui", "api"):
            st = "ui"
        return await run_automation_spike_async(
            (body.title or "").strip() or "Untitled",
            body.bdd,
            body.url.strip(),
            body.html_dom,
            body.jira_id,
            body.tag,
            requirement_ticket_id=body.requirement_ticket_id,
            spike_type=st,
        )
    except SpikeUserError as e:
        d = e.logs
        if not d and hasattr(e, "args"):
            d = [str(e)]
        raise HTTPException(
            status_code=400,
            detail={"message": str(e), "logs": d or [str(e)]},
        ) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"message": str(e), "logs": [str(e)]}
        ) from e


@router.get("/runs/{run_id}")
def automation_run_detail(run_id: str) -> dict[str, Any]:
    g = get_run(_parse_run_id(run_id))
    if not g:
        raise HTTPException(status_code=404, detail="not found")
    return _run_detail(g["row"], g["steps"])


@router.get("/results/{run_id}")
def automation_results_alias(run_id: str) -> dict[str, Any]:
    return automation_run_detail(run_id)


@router.get("/artifacts/{run_id}/{name:path}")
def automation_artifact_file(run_id: str, name: str) -> FileResponse:
    r = _parse_run_id(run_id)
    n = (name or "").replace("\\", "/").lstrip("/")
    if n.startswith("..") or "/../" in n or "/.." in n:
        raise HTTPException(status_code=400, detail="invalid path")
    art = Path(settings.automation_artifacts_dir) / r / n
    if not art.is_file() or ".." in art.resolve().parts:
        raise HTTPException(status_code=404, detail="not found")
    root = Path(settings.automation_artifacts_dir).resolve()
    if not str(art.resolve()).startswith(str(root)):
        raise HTTPException(status_code=400, detail="invalid path")
    if n.endswith(".zip"):
        return FileResponse(
            art, media_type="application/zip", filename="trace.zip"
        )
    if n.lower().endswith(".png"):
        return FileResponse(art, media_type="image/png")
    return FileResponse(art)


@router.get("/selectors")
def automation_list_selectors(limit: int = 80) -> dict[str, Any]:
    return {"rows": list_selector_cache_rows(min(max(limit, 1), 500))}


@router.delete("/selectors/all")
def automation_delete_all_selectors(kc: Kc) -> dict[str, Any]:
    n = delete_all_selector_cache()
    _maybe_automation_audit(
        kc,
        _AUDIT_TICKET_SAVED_SELECTORS,
        "Deleted all Selectors",
    )
    return {"ok": "true", "deleted_cache_rows": n}


@router.delete("/selectors/{rowid}")
def automation_delete_selector(rowid: int, kc: Kc) -> dict[str, str]:
    if not delete_selector_cache_by_rowid(int(rowid)):
        raise HTTPException(status_code=404, detail="not found")
    _maybe_automation_audit(
        kc,
        _AUDIT_TICKET_SAVED_SELECTORS,
        "Deleted Selector",
    )
    return {"ok": "true"}


class SuiteCaseIn(BaseModel):
    title: str = Field(default="Suite case", max_length=500)
    bdd: str = Field(..., min_length=1)
    url: str = Field(default="", max_length=4000)
    html_dom: str = ""
    jira_id: str = Field(default="", max_length=200)
    requirement_ticket_id: str = Field(default="", max_length=200)
    tag: str = Field(default="", max_length=200)
    spike_type: str = Field(
        default="ui",
        description='Stored run mode: "ui" (browser) or "api" (HTTP only)',
    )

    @field_validator("jira_id", mode="before")
    @classmethod
    def _jira_id_strip(cls, v: object) -> str:
        s = (str(v) if v is not None else "").strip()[:200]
        return s

    @field_validator("requirement_ticket_id", mode="before")
    @classmethod
    def _suite_req_ticket_strip(cls, v: object) -> str:
        return (str(v) if v is not None else "").strip()[:200]

    @field_validator("tag", mode="before")
    @classmethod
    def _suite_tag_strip(cls, v: object) -> str:
        return normalize_tag_csv(str(v) if v is not None else "")

    @field_validator("spike_type", mode="before")
    @classmethod
    def _suite_spike_type(cls, v: object) -> str:
        s = (str(v) if v is not None else "ui").strip().lower()
        return s if s in ("ui", "api") else "ui"


def _automation_suite_audit_ticket_id(
    jira_id: str, requirement_ticket_id: str, fallback: str
) -> str:
    j = (jira_id or "").strip()
    if j:
        return j
    r = (requirement_ticket_id or "").strip()
    if r:
        return r
    return (fallback or "").strip()


def _automation_suite_audit_action(suite_save: bool, body: SuiteCaseIn) -> str:
    tid = (body.jira_id or "").strip()
    if suite_save:
        if tid:
            return f"Saved {tid} to Auto Test suite"
        return "Saved to Auto Test suite"
    if tid:
        return f"Updated {tid} to Auto Test suite"
    return "Updated to Auto Test suite"


def _automation_suite_delete_audit_action(row: dict) -> str:
    tid = (str(row.get("jira_id") or "")).strip()
    if tid:
        return f"Deleted {tid} from Auto Test suite"
    return "Deleted from Auto Test suite"


@router.get("/suite")
def automation_suite_list() -> dict[str, Any]:
    return {"cases": list_suite_cases()}


@router.get("/suite/{case_id}/run-history")
def automation_suite_case_run_history(case_id: str) -> dict[str, Any]:
    t = _parse_suite_case_id(case_id)
    if get_suite_case(t) is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"rows": list_suite_case_run_history(t)}


@router.post("/suite")
def automation_suite_add(body: SuiteCaseIn, kc: Kc) -> dict[str, str]:
    dup = would_duplicate_suite_case(
        (body.title or "").strip(), body.jira_id
    )
    if dup:
        raise HTTPException(status_code=409, detail=dup)
    cid = add_suite_case(
        (body.title or "").strip(),
        body.bdd,
        body.url.strip(),
        (body.html_dom or "").strip(),
        jira_id=body.jira_id,
        tag=body.tag,
        requirement_ticket_id=body.requirement_ticket_id,
        spike_type=body.spike_type,
    )
    _maybe_automation_audit(
        kc,
        _automation_suite_audit_ticket_id(
            body.jira_id, body.requirement_ticket_id, cid
        ),
        _automation_suite_audit_action(True, body),
    )
    return {"id": cid, "ok": "true"}


@router.put("/suite/{case_id}")
def automation_suite_update(case_id: str, body: SuiteCaseIn, kc: Kc) -> dict[str, str]:
    t = _parse_suite_case_id(case_id)
    old = get_suite_case(t)
    if old is None:
        raise HTTPException(status_code=404, detail="not found")
    dup = would_duplicate_suite_case(
        (body.title or "").strip(),
        body.jira_id,
        exclude_case_id=t,
    )
    if dup:
        raise HTTPException(status_code=409, detail=dup)
    in_html = (body.html_dom or "").strip()
    if in_html:
        html_f = in_html
    else:
        html_f = (str(old.get("html_dom") or "").strip()) or ""
    if not update_suite_case(
        t,
        (body.title or "").strip(),
        body.bdd,
        body.url.strip(),
        html_f,
        jira_id=body.jira_id,
        tag=body.tag,
        requirement_ticket_id=body.requirement_ticket_id,
        spike_type=body.spike_type,
    ):
        raise HTTPException(status_code=404, detail="not found")
    _maybe_automation_audit(
        kc,
        _automation_suite_audit_ticket_id(body.jira_id, body.requirement_ticket_id, t),
        _automation_suite_audit_action(False, body),
    )
    return {"id": t, "ok": "true"}


@router.delete("/suite/all")
def automation_suite_delete_all(kc: Kc) -> dict[str, Any]:
    if suite_state.get_running_case_ids():
        raise HTTPException(status_code=409, detail="suite run in progress")
    n_cases, n_hist = delete_all_suite_cases()
    _maybe_automation_audit(
        kc,
        _AUDIT_TICKET_SAVED_SUITE,
        "Deleted all tests from Saved Suite",
    )
    return {"ok": "true", "deleted_cases": n_cases, "deleted_history_rows": n_hist}


@router.delete("/suite/{case_id}")
def automation_suite_delete(case_id: str, kc: Kc) -> dict[str, str]:
    t = _parse_suite_case_id(case_id)
    old = get_suite_case(t)
    if old is None:
        raise HTTPException(status_code=404, detail="not found")
    if not delete_suite_case(t):
        raise HTTPException(status_code=404, detail="not found")
    _maybe_automation_audit(
        kc,
        _automation_suite_audit_ticket_id(
            str(old.get("jira_id") or ""),
            str(old.get("requirement_ticket_id") or ""),
            t,
        ),
        _automation_suite_delete_audit_action(old),
    )
    return {"ok": "true"}


class SuiteRunInF(BaseModel):
    case_ids: list[str] | None = None
    default_url: str = Field(default="", max_length=4000)
    use_tag_filter: bool = False
    filter_tags: str = Field(default="", max_length=200)
    use_jira_filter: bool = False
    filter_jira_ids: str = Field(default="", max_length=800)

    @field_validator("filter_tags", mode="before")
    @classmethod
    def _strip_filter_tags_csv(cls, v: object) -> str:
        return (str(v) if v is not None else "").strip()[:200]

    @field_validator("filter_jira_ids", mode="before")
    @classmethod
    def _strip_filter_jira_csv(cls, v: object) -> str:
        return (str(v) if v is not None else "").strip()[:800]


@router.get("/suite-run-status")
def automation_suite_run_status() -> dict[str, Any]:
    ids = suite_state.get_running_case_ids()
    return {
        "current_case_id": ids[0] if ids else None,
        "current_case_ids": ids,
    }


@router.post("/suite-run")
async def automation_suite_run(body: SuiteRunInF) -> dict[str, Any]:
    du = (body.default_url or "").strip()[:4000]
    ft = (body.filter_tags or "").strip()[:200]
    fj = (body.filter_jira_ids or "").strip()[:800]
    return await asyncio.to_thread(
        lambda: run_suite_sequential(
            body.case_ids,
            default_url=du,
            clear_cancel=True,
            use_tag_filter=body.use_tag_filter,
            filter_tags=ft,
            use_jira_filter=body.use_jira_filter,
            filter_jira_ids=fj,
        )
    )


@router.get("/reports/{name}")
def automation_run_report_file(name: str) -> FileResponse:
    n = (name or "").strip()
    if not _RE_PER_RUN_HTML.match(n):
        raise HTTPException(status_code=400, detail="invalid report name")
    return _html_report_file_response(Path(settings.automation_reports_dir) / n)


_MAX_SUITE_REPORTS_LIST = 2000

@router.get("/suite-reports-recent")
def automation_suite_reports_recent() -> dict[str, Any]:
    rep = Path(settings.automation_reports_dir)
    days = int(getattr(settings, "automation_retention_days", 20) or 0)
    now = datetime.now(timezone.utc)
    if days > 0:
        cutoff_ts = (now - timedelta(days=days)).timestamp()
    else:
        cutoff_ts = 0.0
    max_items = _MAX_SUITE_REPORTS_LIST
    rows: list[tuple[float, str]] = []
    if rep.is_dir():
        for p in rep.glob("*.html"):
            if p.name.startswith("."):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m < cutoff_ts:
                continue
            rows.append((m, p.name))
    rows.sort(key=lambda x: -x[0])
    rows = rows[:max_items]
    out: list[dict[str, str]] = []
    for m, name in rows:
        out.append(
            {
                "name": name,
                "report_url": f"/api/automation/suite-reports/{name}",
                "modified_at": datetime.fromtimestamp(m, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    return {
        "reports": out,
        "retention_days": days,
        "max_listed": max_items,
    }


@router.get("/suite-reports/{name}")
def automation_suite_report_file(name: str) -> FileResponse:
    n = (name or "").strip()
    if not (_RE_SUITE_PREFIX.match(n) or _RE_SUITE_UUID_HTML.match(n)):
        raise HTTPException(status_code=400, detail="invalid report name")
    return _html_report_file_response(Path(settings.automation_reports_dir) / n)
