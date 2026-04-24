from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from settings import settings

from . import cancel
from .tag_csv import normalize_tag_csv
from .errors import SpikeUserError
from .spike import run_automation_spike_async
from .prefs import (
    get_effective_automation_browser,
    get_effective_automation_default_timeout_ms,
    get_effective_automation_headless,
    get_effective_automation_post_analysis,
    get_effective_automation_screenshot_on_pass,
    get_effective_automation_trace_file_generation,
)
from .store import (
    add_suite_case,
    delete_selector_cache_by_rowid,
    delete_suite_case,
    get_run,
    get_suite_case,
    list_selector_cache_rows,
    list_suite_case_run_history,
    list_suite_cases,
    set_automation_kv,
    would_duplicate_suite_case,
)
from . import suite_state
from .suite import run_suite_sequential

router = APIRouter(prefix="/automation", tags=["automation"])

_UUID_36 = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


def _parse_run_id(s: str) -> str:
    t = s.strip()
    if not t or not _UUID_36.match(t):
        raise HTTPException(status_code=400, detail="invalid run id")
    return t


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
    url: str = Field(..., min_length=1, description="Page URL to open in Playwright")
    html_dom: str | None = Field(default=None, max_length=2_000_000)
    jira_id: str = Field(default="", max_length=200)
    tag: str = Field(default="", max_length=200)

    @field_validator("jira_id", mode="before")
    @classmethod
    def _spike_jira_strip(cls, v: object) -> str:
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


def _automation_env_payload() -> dict[str, Any]:
    return {
        "automation_browser": get_effective_automation_browser(),
        "automation_headless": get_effective_automation_headless(),
        "automation_screenshot_on_pass": get_effective_automation_screenshot_on_pass(),
        "automation_trace_file_generation": get_effective_automation_trace_file_generation(),
        "automation_post_analysis": get_effective_automation_post_analysis(),
        "automation_default_timeout_ms": get_effective_automation_default_timeout_ms(),
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
    set_automation_kv("headless", "1" if body.automation_headless else "0")
    set_automation_kv("screenshot_on_pass", "1" if body.automation_screenshot_on_pass else "0")
    set_automation_kv("trace_file_generation", "1" if body.automation_trace_file_generation else "0")
    set_automation_kv("default_timeout_ms", str(int(body.automation_default_timeout_ms)))
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
        return await run_automation_spike_async(
            (body.title or "").strip() or "Untitled",
            body.bdd,
            body.url.strip(),
            body.html_dom,
            body.jira_id,
            body.tag,
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


@router.delete("/selectors/{rowid}")
def automation_delete_selector(rowid: int) -> dict[str, str]:
    if not delete_selector_cache_by_rowid(int(rowid)):
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": "true"}


class SuiteCaseIn(BaseModel):
    title: str = Field(default="Suite case", max_length=500)
    bdd: str = Field(..., min_length=1)
    url: str = Field(default="", max_length=4000)
    html_dom: str = ""
    jira_id: str = Field(default="", max_length=200)
    tag: str = Field(default="", max_length=200)

    @field_validator("jira_id", mode="before")
    @classmethod
    def _jira_id_strip(cls, v: object) -> str:
        s = (str(v) if v is not None else "").strip()[:200]
        return s

    @field_validator("tag", mode="before")
    @classmethod
    def _suite_tag_strip(cls, v: object) -> str:
        return normalize_tag_csv(str(v) if v is not None else "")


@router.get("/suite")
def automation_suite_list() -> dict[str, Any]:
    return {"cases": list_suite_cases()}


@router.get("/suite/{case_id}/run-history")
def automation_suite_case_run_history(case_id: str) -> dict[str, Any]:
    t = (case_id or "").strip()
    if not t or not re.match(r"^[\w.-]{1,200}$", t):
        raise HTTPException(status_code=400, detail="invalid case id")
    if get_suite_case(t) is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"rows": list_suite_case_run_history(t)}


@router.post("/suite")
def automation_suite_add(body: SuiteCaseIn) -> dict[str, str]:
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
    )
    return {"id": cid, "ok": "true"}


@router.delete("/suite/{case_id}")
def automation_suite_delete(case_id: str) -> dict[str, str]:
    t = (case_id or "").strip()
    if not t or not re.match(r"^[\w.-]{1,200}$", t):
        raise HTTPException(status_code=400, detail="invalid case id")
    if not delete_suite_case(t):
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": "true"}


class SuiteRunInF(BaseModel):
    case_ids: list[str] | None = None
    default_url: str = Field(default="")


@router.get("/suite-run-status")
def automation_suite_run_status() -> dict[str, Any]:
    return {"current_case_id": suite_state.get_running_case()}


@router.post("/suite-run")
async def automation_suite_run(body: SuiteRunInF) -> dict[str, Any]:
    du = (body.default_url or "").strip()[:4000]
    return await asyncio.to_thread(
        lambda: run_suite_sequential(
            body.case_ids, default_url=du, clear_cancel=True
        )
    )


@router.get("/reports/{name}")
def automation_run_report_file(name: str) -> FileResponse:
    n = (name or "").strip()
    if not re.match(r"^[0-9a-fA-F-]{10,200}\.html$", n):
        raise HTTPException(status_code=400, detail="invalid report name")
    p = Path(settings.automation_reports_dir) / n
    if not p.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p, media_type="text/html; charset=utf-8")


_MAX_SUITE_REPORTS_LIST = 2000

@router.get("/suite-reports-recent")
def automation_suite_reports_recent() -> dict[str, Any]:
    """HTML reports under ``automation_reports_dir``, newest first.

    When :env:`AUTOMATION_RETENTION_DAYS` > 0, only files modified after the cutoff
    (now minus that many days) are included. Listing is capped at
    :data:`_MAX_SUITE_REPORTS_LIST` for API safety, not by retention day count.
    """
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
    if not re.match(r"^suite_[0-9a-fA-F-]{10,200}\.html$", n) and not re.match(
        r"^[0-9a-fA-F-]{8}-[0-9a-fA-F-]{4}-[0-9a-fA-F-]{4}-[0-9a-fA-F-]{4}-[0-9a-fA-F-]{12}\.html$",
        n,
    ):
        raise HTTPException(status_code=400, detail="invalid report name")
    p = Path(settings.automation_reports_dir) / n
    if not p.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p, media_type="text/html; charset=utf-8")
