from __future__ import annotations

import asyncio
import logging
import difflib
import hashlib
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from requests.exceptions import HTTPError, RequestException

from jira_client import (
    build_ai_to_jira_priority_map,
    build_ai_to_jira_severity_name_map,
    download_attachment_for_ticket,
    fetch_issue,
    fetch_issue_attachment_meta,
    fetch_linked_test_issues,
    fetch_linked_work_issues,
    fetch_priorities,
    find_severity_field_id,
    format_jira_http_error,
    get_issue_create_meta_fields_cached,
    project_key_from_issue_key,
    push_test_case_to_jira,
    severity_allowed_display_names,
    update_test_case_in_jira,
)
from agentic import run_agentic_pipeline_async
from ai_client import (
    disambiguate_duplicate_test_case_descriptions,
    generate_automation_skeleton,
    generate_test_cases,
    merge_ai_cases_with_jira_existing,
    merge_test_cases_with_previous,
    reconcile_jira_linked_test_cases,
    resolve_priority_allowed_for_generation,
    resolve_severity_allowed_for_generation,
    score_merged_test_cases,
    strip_test_case_diff_meta,
)
from audit_store import append_audit, init_audit_db, list_audit
from memory_store import (
    find_jira_history_key_for_same_requirements,
    find_latest_memory_by_title,
    find_similar_memory,
    get_latest,
    init_db,
    list_saved,
    merge_test_case_into_memory,
    normalized_paste_key_material,
    save,
)
from key_norm import norm_issue_key
from keycloak_auth import claims_username, get_keycloak_claims
from requirement_images import merge_and_validate
from automation import routes as automation_routes
from automation.prefs import (
    get_effective_automation_browser,
    get_effective_automation_default_timeout_ms,
    get_effective_automation_headless,
    get_effective_automation_parallel_execution,
    get_effective_automation_post_analysis,
    get_effective_automation_screenshot_on_pass,
    get_effective_automation_trace_file_generation,
)
from automation.retention import prune_automation_artifacts
from automation.store import init_automation_db
from settings import settings

_LOG = logging.getLogger(__name__)


def _strip(s: str) -> str:
    return (s or "").strip()


def _effective_jira_password(sent: str) -> str:
    return (sent or "").strip() or _strip(settings.jira_password)


def _require_jira_password(sent: str) -> str:
    pw = _effective_jira_password(sent)
    if settings.mock:
        return pw
    if not pw:
        raise HTTPException(
            status_code=400,
            detail="JIRA password or API token is required (enter it in the UI or set JIRA_PASSWORD in the server .env).",
        )
    return pw


def _validate_tc_bounds(min_test_cases: int, max_test_cases: int) -> None:
    if max_test_cases < min_test_cases:
        raise ValueError("Maximum Test Cases must be greater than or equal to Minimum Test Cases.")


class TicketIn(BaseModel):
    jira_url: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = ""
    ticket_id: str = Field(..., min_length=1)
    jira_test_issue_type: str = ""


class AttachmentDownloadIn(TicketIn):
    attachment_id: str = Field(..., min_length=1)


def _jira_test_issue_type_from_body(body: TicketIn) -> str:
    return (body.jira_test_issue_type or "").strip() or settings.jira_test_issue_type or "Test"


def _linked_jira_issue_rows(entries: list, *, work: bool) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        row = {
            "issue_key": e.get("issue_key"),
            "summary": e.get("summary"),
            "status_name": e.get("status_name"),
            "browse_url": e.get("browse_url"),
        }
        if work:
            row["issue_type_name"] = e.get("issue_type_name") or ""
        else:
            pri = str(e.get("jira_priority_name") or e.get("priority") or "").strip()
            icon = str(e.get("jira_priority_icon_url") or e.get("priority_icon_url") or "").strip()
            row["priority"] = pri
            row["priority_icon_url"] = icon or None
        out.append(row)
    return out


def _linked_work_type_labels_display(env_str: str, requirement_type: str) -> str:
    parts = [x.strip() for x in (env_str or "").split(",") if x.strip()]
    rt = (requirement_type or "").strip()
    if rt and rt.casefold() not in {p.casefold() for p in parts}:
        parts.append(rt)
    if not parts:
        return rt or "—"
    return ", ".join(sorted(parts, key=lambda s: s.casefold()))


def _jira_request_http_exception(e: RequestException) -> HTTPException:
    if isinstance(e, HTTPError) and e.response is not None:
        detail = format_jira_http_error(e.response)
    else:
        msg = str(e).strip() or "connection failed"
        detail = f"Could not reach JIRA. Check the site URL and your network.\n{msg}"
    return HTTPException(status_code=502, detail=detail)


def _warm_jira_createmeta_cache(
    jira_url: str,
    username: str,
    password: str,
    test_project_key: str,
    issue_type_name: str,
) -> None:
    tpk = (test_project_key or "").strip()
    if not tpk:
        return
    it = (issue_type_name or "").strip() or settings.jira_test_issue_type or "Test"
    it = it or "Test"
    try:
        get_issue_create_meta_fields_cached(
            jira_url.strip(),
            username,
            password,
            norm_issue_key(tpk),
            it,
        )
    except Exception:
        _LOG.debug("JIRA createmeta warm-up failed", exc_info=True)


async def _load_ticket_linked_jira(body: TicketIn, key: str) -> tuple[list, list, str]:
    empty = _linked_work_type_labels_display(settings.jira_linked_work_issue_types, "")
    if settings.mock:
        return [], [], empty
    ju = body.jira_url.strip()
    user = body.username
    pw = _require_jira_password(body.password)
    tt = _jira_test_issue_type_from_body(body)
    linked: list = []
    try:
        linked = await asyncio.to_thread(
            fetch_linked_test_issues,
            ju,
            user,
            pw,
            key,
            tt,
        )
    except Exception:
        _LOG.warning("fetch_linked_test_issues failed for %s", key, exc_info=True)
        linked = []
    linked_work: list = []
    work_labels = empty
    try:
        linked_work, req_t = await asyncio.to_thread(
            fetch_linked_work_issues,
            ju,
            user,
            pw,
            key,
            extra_issue_types_from_env=settings.jira_linked_work_issue_types,
            test_issue_type_name=tt,
        )
        work_labels = _linked_work_type_labels_display(settings.jira_linked_work_issue_types, req_t)
    except Exception:
        _LOG.warning("fetch_linked_work_issues failed for %s", key, exc_info=True)
        linked_work = []
        work_labels = empty
    return linked, linked_work, work_labels


def _ascii_filename(name: str) -> str:
    s = (name or "file").strip() or "file"
    return "".join(c if 32 <= ord(c) < 127 and c not in '";\\' else "_" for c in s)[:200]


async def _fetch_issue_attachments(body: TicketIn, key: str) -> list:
    if settings.mock:
        return []
    try:
        return await asyncio.to_thread(
            fetch_issue_attachment_meta,
            body.jira_url.strip(),
            body.username,
            _require_jira_password(body.password),
            key,
        )
    except Exception:
        _LOG.warning("fetch_issue_attachment_meta failed for %s", key, exc_info=True)
        return []


async def _enrich_out_with_attachments(body: TicketIn, out: dict) -> None:
    tk = norm_issue_key(str(out.get("ticket_id") or ""))
    if tk:
        out["requirement_attachments"] = await _fetch_issue_attachments(body, tk)


class _TestCaseBounds(BaseModel):
    min_test_cases: int = Field(1, ge=1)
    max_test_cases: int = Field(10, ge=1)

    @model_validator(mode="after")
    def _bounds(self) -> "_TestCaseBounds":
        _validate_tc_bounds(self.min_test_cases, self.max_test_cases)
        return self


class GenerateIn(TicketIn, _TestCaseBounds):
    test_project_key: str = ""
    save_memory: bool = True
    attachment_ids: list[str] = Field(default_factory=list)


class MemoryUpdateTestCasesIn(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    test_cases: list = Field(default_factory=list)
    requirements: dict = Field(default_factory=dict)


class MemoryMergeTestCaseIn(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    requirements: dict = Field(default_factory=dict)
    test_case: dict = Field(default_factory=dict)


class MemorySaveAfterEditIn(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    requirements: dict = Field(default_factory=dict)
    test_cases: list = Field(default_factory=list)
    edited_jira_issue_key: str = ""
    jira_username: str = ""


class PastedGenerateIn(_TestCaseBounds):
    title: str = Field(default="", max_length=10000)
    description: str = Field(..., min_length=1)
    memory_key: str = Field(default="", max_length=64)
    save_memory: bool = True


class GenerateAgenticIn(GenerateIn):
    max_rounds: int = Field(3, ge=1, le=10)


class PastedAgenticIn(PastedGenerateIn):
    max_rounds: int = Field(3, ge=1, le=10)


class AuthAuditIn(BaseModel):
    event: Literal["login", "logout"]


class AutomationSkeletonIn(BaseModel):
    test_case: dict = Field(default_factory=dict)
    language: Literal["python", "java", "javascript", "typescript", "csharp"]
    framework: Literal["playwright", "selenium", "cypress"]
    ticket_id: str = ""

    @model_validator(mode="after")
    def _framework_lang_pair(self) -> "AutomationSkeletonIn":
        if self.framework == "cypress" and self.language not in ("javascript", "typescript"):
            raise ValueError("Cypress is only available with JavaScript or TypeScript.")
        return self


class PushTestToJiraIn(BaseModel):
    jira_url: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = ""
    requirement_key: str = Field(..., min_length=1)
    test_project_key: str = ""
    jira_test_issue_type: str = ""
    jira_link_type: str = ""
    test_case: dict = Field(default_factory=dict)
    existing_issue_key: str = ""


class JiraPrioritiesIn(BaseModel):
    jira_url: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = ""
    test_project_key: str = ""


class ConfigResponse(BaseModel):
    default_jira_url: str = ""
    default_username: str = ""
    jira_password_configured: bool = False
    default_jira_test_project_key: str = ""
    default_jira_test_issue_type: str = "Test"
    default_jira_link_type: str = "Relates"
    mock: bool = False
    show_memory_ui: bool = True
    show_audit_ui: bool = True
    show_jira_mode_ui: bool = True
    show_paste_requirements_mode_ui: bool = True
    show_auto_tests_ui: bool = True
    use_keycloak: bool = False
    keycloak_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_idle_timeout_minutes: int = 5
    llm_requirement_images_max_count: int = 5
    llm_requirement_images_max_total_mb: int = 200
    llm_vision_configured: bool = False
    automation_browser: str = "chromium"
    automation_headless: bool = True
    automation_screenshot_on_pass: bool = False
    automation_trace_file_generation: bool = False
    automation_post_analysis: bool = True
    automation_default_timeout_ms: int = 30_000
    automation_parallel_execution: int = 1
    automation_retention_days: int = 20


def _llm_vision_configured() -> bool:
    return bool((settings.llm_vision_url or "").strip())


def _req_snapshot(d: dict) -> str:
    return f"Title: {d.get('title', '')}\n\nDescription:\n{d.get('description', '')}"


def _ticket_key_from_paste(memory_key: str, title: str, description: str) -> str:
    raw = norm_issue_key(memory_key)
    if raw:
        cleaned = re.sub(r"[^A-Z0-9_.-]", "", raw)
        if cleaned:
            return cleaned[:64]
    mat = normalized_paste_key_material(title, description)
    h = hashlib.sha256(mat.encode("utf-8")).hexdigest()[:10].upper()
    return f"TEST-{h}"


def _prior_cases_union_for_merge(key: str, prev: dict | None) -> list:
    chunks: list = []
    latest = get_latest(key)
    if latest and isinstance(latest.get("test_cases"), list):
        chunks.extend(latest["test_cases"])
    if prev and isinstance(prev.get("test_cases"), list):
        chunks.extend(prev["test_cases"])
    return chunks


def _diff(a: dict, b: dict) -> str | None:
    x, y = _req_snapshot(a), _req_snapshot(b)
    if x == y:
        return None
    return "\n".join(difflib.unified_diff(x.splitlines(), y.splitlines(), "previous", "current", lineterm=""))


async def _fetch_jira(body: TicketIn) -> tuple[str, dict]:
    key = norm_issue_key(body.ticket_id)
    pw = _require_jira_password(body.password)
    try:
        raw = await asyncio.to_thread(
            fetch_issue,
            body.jira_url.strip(),
            body.username,
            pw,
            key,
        )
    except RequestException as e:
        raise _jira_request_http_exception(e) from e
    return key, raw


async def _maybe_fetch_jira_severity_names_for_generate(body: GenerateIn) -> list[str] | None:
    if not body.test_project_key.strip() or settings.mock:
        return None
    try:
        meta = await asyncio.to_thread(
            get_issue_create_meta_fields_cached,
            body.jira_url.strip(),
            body.username,
            _require_jira_password(body.password),
            norm_issue_key(body.test_project_key.strip()),
            _jira_test_issue_type_from_body(body),
        )
        fid = find_severity_field_id(meta or {})
        if not fid or not isinstance(meta, dict):
            return None
        fm = meta.get(fid)
        names = severity_allowed_display_names(fm if isinstance(fm, dict) else None)
        return names if names else None
    except Exception:
        _LOG.debug("JIRA severity names for generate unavailable", exc_info=True)
        return None


async def _jira_generate_context(
    body: GenerateIn,
) -> tuple[str, dict, dict | None, bool, list, list, str, list[str] | None, list[str] | None]:
    key, req = await _fetch_jira(body)
    jira_entries, linked_work_raw, work_labels = await _load_ticket_linked_jira(body, key)
    prev = get_latest(key)
    similar_used = False
    thr = settings.memory_similarity_threshold
    if prev is None and thr > 0:
        _, sp = find_similar_memory(req, thr)
        if sp is not None:
            prev = sp
            similar_used = True
    jira_names = await _maybe_fetch_jira_priority_names_for_generate(body)
    jira_sev = await _maybe_fetch_jira_severity_names_for_generate(body)
    return key, req, prev, similar_used, jira_entries, linked_work_raw, work_labels, jira_names, jira_sev


async def _maybe_fetch_jira_priority_names_for_generate(body: GenerateIn) -> list[str] | None:
    if not body.test_project_key.strip() or settings.mock:
        return None
    try:
        pri = await asyncio.to_thread(
            fetch_priorities,
            body.jira_url.strip(),
            body.username,
            _require_jira_password(body.password),
        )
        names = [str(p.get("name") or "").strip() for p in pri if str(p.get("name") or "").strip()]
        return names if names else None
    except Exception:
        _LOG.debug("JIRA priority names for generate unavailable", exc_info=True)
        return None


def _require_memory_not_mock() -> None:
    if settings.mock:
        raise HTTPException(status_code=400, detail="Memory is not persisted in mock mode.")


def _existing_jira_tests_for_llm(jira_entries: list | None) -> list[dict] | None:
    if not jira_entries:
        return None
    rows = [
        {"issue_key": e["issue_key"], "summary": e.get("summary"), "test_case": e.get("test_case")}
        for e in jira_entries
        if isinstance(e, dict) and e.get("issue_key")
    ]
    return rows or None


def _generate_response_base(
    key: str,
    req: dict,
    cases: list,
    req_diff: str | None,
    prev: dict | None,
    similar_used: bool,
    jira_entries: list | None,
    linked_jira_work_entries: list | None,
    linked_jira_work_type_labels: str,
    *,
    history_jira_ticket_id: str | None = None,
) -> dict:
    out: dict = {
        "ticket_id": key,
        "requirements": req,
        "test_cases": cases,
        "requirements_diff": req_diff,
        "had_previous_memory": prev is not None,
        "memory_match": ("similar" if similar_used else "exact") if prev else None,
        "linked_jira_tests": _linked_jira_issue_rows(jira_entries or [], work=False),
        "linked_jira_work": _linked_jira_issue_rows(linked_jira_work_entries or [], work=True),
        "linked_jira_work_type_labels": linked_jira_work_type_labels,
    }
    if history_jira_ticket_id:
        out["history_jira_ticket_id"] = norm_issue_key(history_jira_ticket_id)
    return out


async def _finalize_cases_after_llm(
    key: str,
    req: dict,
    cases: list,
    prev: dict | None,
    *,
    jira_entries: list | None,
    allowed_priorities: list[str],
    allowed_severities: list[str],
    save_memory: bool,
    kc: dict | None,
    jira_username: str | None,
    audit_action: str,
) -> list:
    if jira_entries:
        cases = merge_ai_cases_with_jira_existing(
            cases,
            jira_entries,
            allowed_priorities=allowed_priorities,
            allowed_severities=allowed_severities,
        )
    prior_union = _prior_cases_union_for_merge(key, prev)
    if prior_union:
        cases = merge_test_cases_with_previous(
            prior_union,
            cases,
            allowed_priorities=allowed_priorities,
            allowed_severities=allowed_severities,
        )
    reconcile_jira_linked_test_cases(
        cases,
        jira_entries,
        allowed_priorities=allowed_priorities,
        allowed_severities=allowed_severities,
    )
    disambiguate_duplicate_test_case_descriptions(cases)
    await asyncio.to_thread(score_merged_test_cases, req, cases)
    if not settings.mock:
        if save_memory:
            save(key, req, cases)
        _maybe_audit(kc, key, audit_action, jira_username)
    return cases


async def _generate_and_persist(
    key: str,
    req: dict,
    prev: dict | None,
    similar_used: bool,
    min_test_cases: int,
    max_test_cases: int,
    save_memory: bool,
    kc: dict | None,
    *,
    paste_mode: bool = False,
    priority_labels: list[str] | None = None,
    severity_labels: list[str] | None = None,
    jira_entries: list | None = None,
    linked_jira_work_entries: list | None = None,
    linked_jira_work_type_labels: str = "",
    jira_username: str | None = None,
    requirement_images: list[tuple[str, str, bytes]] | None = None,
    agentic: bool = False,
    max_rounds: int = 3,
) -> dict:
    req_diff = _diff(prev["requirements"], req) if prev else None
    allowed_p = resolve_priority_allowed_for_generation(paste_mode, priority_labels)
    allowed_s = resolve_severity_allowed_for_generation(paste_mode, severity_labels)
    ej_llm = _existing_jira_tests_for_llm(jira_entries)
    agentic_out: dict | None = None
    try:
        if agentic:
            agentic_out = await run_agentic_pipeline_async(
                requirements=req,
                allowed_priorities=allowed_p,
                allowed_severities=allowed_s,
                min_test_cases=min_test_cases,
                max_test_cases=max_test_cases,
                max_rounds=max_rounds,
                prev=prev,
                paste_mode=paste_mode,
                existing_jira_tests=ej_llm,
                requirement_images=requirement_images,
            )
            cases = agentic_out.get("test_cases") or []
        else:
            cases = await generate_test_cases(
                req,
                prev,
                allowed_priorities=allowed_p,
                allowed_severities=allowed_s,
                min_test_cases=min_test_cases,
                max_test_cases=max_test_cases,
                paste_mode=paste_mode,
                existing_jira_tests=ej_llm,
                requirement_images=requirement_images,
            )
    except Exception as e:
        _raise_llm_route_error(e)
    cases = await _finalize_cases_after_llm(
        key,
        req,
        cases,
        prev,
        jira_entries=jira_entries,
        allowed_priorities=allowed_p,
        allowed_severities=allowed_s,
        save_memory=save_memory,
        kc=kc,
        jira_username=jira_username,
        audit_action="generate_test_cases_agentic" if agentic else "generate_test_cases",
    )
    history_jira: str | None = None
    if paste_mode and save_memory and prev is not None and not settings.mock:
        hj = find_jira_history_key_for_same_requirements(req, exclude_key=key)
        if hj and norm_issue_key(hj) != norm_issue_key(key):
            history_jira = hj
    base = _generate_response_base(
        key,
        req,
        cases,
        req_diff,
        prev,
        similar_used,
        jira_entries,
        linked_jira_work_entries,
        linked_jira_work_type_labels,
        history_jira_ticket_id=history_jira,
    )
    if agentic and agentic_out is not None:
        base["agentic"] = {
            "validator": agentic_out.get("validator"),
            "validation_passed": agentic_out.get("validation_passed"),
            "error": agentic_out.get("error"),
            "generations": agentic_out.get("generations"),
            "suggestion_swap": agentic_out.get("suggestion_swap"),
            "coverage_plan": agentic_out.get("coverage_plan"),
            "agent_trace": agentic_out.get("agent_trace"),
        }
    return base


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.use_keycloak and not all(
        x.strip() for x in (settings.keycloak_url, settings.keycloak_realm, settings.keycloak_client_id)
    ):
        raise RuntimeError("USE_KEYCLOAK=true requires KEYCLOAK_URL, KEYCLOAK_REALM, and KEYCLOAK_CLIENT_ID in .env")
    init_db()
    init_audit_db()
    init_automation_db()
    try:
        prune_automation_artifacts()
    except Exception as e:
        _LOG.warning("Automation retention prune failed: %s", e)
    yield


Kc = Annotated[dict | None, Depends(get_keycloak_claims)]


def _maybe_audit(kc: dict | None, key: str, action: str, jira_username: str | None = None) -> None:
    if settings.mock:
        return
    u = claims_username(kc) if settings.use_keycloak and kc else ""
    append_audit(u, key, action, jira_username)


def _raise_llm_route_error(e: Exception) -> None:
    if isinstance(e, ValueError):
        raise HTTPException(status_code=500, detail=str(e)) from e
    raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e


async def _read_generate_body(request: Request, model_cls: type[BaseModel]) -> tuple[BaseModel, list[UploadFile]]:
    ct = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in ct:
        form = await request.form()
        raw = form.get("payload")
        if not isinstance(raw, str):
            raise HTTPException(
                status_code=400,
                detail="multipart requests must include a string form field 'payload' with JSON.",
            )
        body = model_cls.model_validate_json(raw)
        files: list[UploadFile] = []
        for key, v in form.multi_items():
            if key == "files" and hasattr(v, "read"):
                fn = getattr(v, "filename", None)
                if fn:
                    files.append(v)
        return body, files
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail="Body must be JSON or multipart/form-data with form field 'payload'.",
        ) from e
    return model_cls.model_validate(data), []


async def _upload_tuples(files: list[UploadFile]) -> list[tuple[str, bytes, str]]:
    out: list[tuple[str, bytes, str]] = []
    for uf in files:
        if not uf.filename:
            continue
        raw = await uf.read()
        ct = (uf.content_type or "").strip()
        out.append((uf.filename, raw, ct))
    return out


async def _jira_attachment_parts_for_generate(body: TicketIn, ids: list[str]) -> list[tuple[str, str, bytes]]:
    if settings.mock or not ids:
        return []
    ju = body.jira_url.strip()
    user = body.username
    pw = _require_jira_password(body.password)
    key = norm_issue_key(body.ticket_id)
    meta = await asyncio.to_thread(fetch_issue_attachment_meta, ju, user, pw, key)
    allowed = {str(x.get("id")) for x in meta if isinstance(x, dict)}
    out: list[tuple[str, str, bytes]] = []
    for aid in ids:
        s = str(aid).strip()
        if not s or s not in allowed:
            raise HTTPException(status_code=400, detail=f"Attachment is not on this ticket: {s!r}")
        content, fn, ct = await asyncio.to_thread(download_attachment_for_ticket, ju, user, pw, s, key)
        out.append((fn, ct, content))
    return out


def _merge_req_validated(
    uploads: list[tuple[str, bytes, str]],
    jira_parts: list[tuple[str, str, bytes]],
) -> list[tuple[str, str, bytes]]:
    return merge_and_validate(
        enabled=_llm_vision_configured(),
        max_count=settings.llm_requirement_images_max_count,
        max_total_bytes=settings.llm_requirement_images_max_total_mb * 1024 * 1024,
        uploads=uploads,
        jira_parts=jira_parts,
    )


def _require_vision_for_requirement_files(files: list, attachment_ids: list | None) -> None:
    if _llm_vision_configured():
        return
    if files or attachment_ids:
        raise HTTPException(
            status_code=400,
            detail="LLM_VISION_URL must be set to send requirement images or JIRA attachments to the model.",
        )


async def _merge_req_images_jira(body: GenerateIn, files: list[UploadFile]) -> list[tuple[str, str, bytes]]:
    _require_vision_for_requirement_files(files, list(body.attachment_ids or []))
    if not _llm_vision_configured():
        return []
    uploads = await _upload_tuples(files)
    jira_parts = await _jira_attachment_parts_for_generate(body, list(body.attachment_ids or []))
    return _merge_req_validated(uploads, jira_parts)


async def _merge_req_images_paste(files: list[UploadFile]) -> list[tuple[str, str, bytes]]:
    _require_vision_for_requirement_files(files, None)
    if not _llm_vision_configured():
        return []
    uploads = await _upload_tuples(files)
    return _merge_req_validated(uploads, [])


async def _jira_generate_route_kwargs(body: GenerateIn) -> tuple[str, dict, dict | None, bool, dict]:
    (
        key,
        req,
        prev,
        similar_used,
        jira_entries,
        linked_work_raw,
        work_labels,
        jira_names,
        jira_sev_names,
    ) = await _jira_generate_context(body)
    shared = dict(
        paste_mode=False,
        priority_labels=jira_names,
        severity_labels=jira_sev_names,
        jira_entries=jira_entries,
        linked_jira_work_entries=linked_work_raw,
        linked_jira_work_type_labels=work_labels,
        jira_username=body.username,
    )
    return key, req, prev, similar_used, shared


app = FastAPI(title="Test Intellect AI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


@api.get("/memory/list")
def memory_list(_: Kc):
    return {"entries": list_saved()}


@api.get("/memory/item/{ticket_id}")
def memory_item(ticket_id: str, _: Kc):
    data = get_latest(norm_issue_key(ticket_id))
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "ticket_id": norm_issue_key(ticket_id),
        "requirements": data["requirements"],
        "test_cases": data["test_cases"],
    }


@api.post("/memory/update-test-cases")
def memory_update_test_cases(body: MemoryUpdateTestCasesIn, kc: Kc):
    _require_memory_not_mock()
    key = norm_issue_key(body.ticket_id)
    tc = body.test_cases if isinstance(body.test_cases, list) else []
    req_in = body.requirements if isinstance(body.requirements, dict) else {}
    latest = get_latest(key)
    if not latest:
        save(key, req_in, tc)
        return {"ok": True}
    save(key, latest["requirements"], tc)
    return {"ok": True}


@api.post("/memory/merge-test-case")
def memory_merge_test_case(body: MemoryMergeTestCaseIn, kc: Kc):
    _require_memory_not_mock()
    key = norm_issue_key(body.ticket_id)
    tc = body.test_case if isinstance(body.test_case, dict) else {}
    req = body.requirements if isinstance(body.requirements, dict) else {}
    merge_test_case_into_memory(key, req, tc)
    return {"ok": True}


@api.post("/memory/save-after-edit")
def memory_save_after_edit(body: MemorySaveAfterEditIn, kc: Kc):
    _require_memory_not_mock()
    key = norm_issue_key(body.ticket_id)
    req = body.requirements if isinstance(body.requirements, dict) else {}
    tc = body.test_cases if isinstance(body.test_cases, list) else []
    save(key, req, tc)
    jk = (body.edited_jira_issue_key or "").strip()
    if jk:
        _maybe_audit(kc, key, f"Edited {jk}", (body.jira_username or "").strip() or None)
    return {"ok": True}


@api.get("/audit/list")
def audit_list(_: Kc):
    return {"entries": list_audit()}


@api.post("/audit/auth")
def audit_auth_event(body: AuthAuditIn, kc: Kc):
    if not settings.use_keycloak:
        raise HTTPException(status_code=400, detail="Keycloak is not enabled")
    if settings.mock:
        return {"ok": True}
    u = claims_username(kc)
    action = "logged_in" if body.event == "login" else "logged_out"
    append_audit(u, "AUTH", action)
    return {"ok": True}


@api.get("/config", response_model=ConfigResponse)
def get_config():
    s = settings
    return ConfigResponse(
        default_jira_url=_strip(s.jira_url),
        default_username=_strip(s.jira_username),
        jira_password_configured=bool(_strip(s.jira_password)),
        default_jira_test_project_key=_strip(s.jira_test_project_key),
        default_jira_test_issue_type=_strip(s.jira_test_issue_type) or "Test",
        default_jira_link_type=_strip(s.jira_test_link_type) or "Relates",
        mock=s.mock,
        show_memory_ui=s.show_memory_ui,
        show_audit_ui=s.show_audit_ui,
        show_jira_mode_ui=s.show_jira_mode_ui,
        show_paste_requirements_mode_ui=s.show_paste_requirements_mode_ui,
        show_auto_tests_ui=s.show_auto_tests_ui,
        use_keycloak=s.use_keycloak,
        keycloak_url=_strip(s.keycloak_url),
        keycloak_realm=_strip(s.keycloak_realm),
        keycloak_client_id=_strip(s.keycloak_client_id),
        keycloak_idle_timeout_minutes=s.keycloak_idle_timeout_minutes,
        llm_requirement_images_max_count=s.llm_requirement_images_max_count,
        llm_requirement_images_max_total_mb=s.llm_requirement_images_max_total_mb,
        llm_vision_configured=_llm_vision_configured(),
        automation_browser=get_effective_automation_browser(),
        automation_headless=get_effective_automation_headless(),
        automation_screenshot_on_pass=get_effective_automation_screenshot_on_pass(),
        automation_trace_file_generation=get_effective_automation_trace_file_generation(),
        automation_post_analysis=get_effective_automation_post_analysis(),
        automation_default_timeout_ms=get_effective_automation_default_timeout_ms(),
        automation_parallel_execution=get_effective_automation_parallel_execution(),
        automation_retention_days=s.automation_retention_days,
    )


@api.post("/jira/priorities")
async def jira_priorities(body: JiraPrioritiesIn, kc: Kc):
    if settings.mock:
        return {"priorities": [], "ai_to_jira_name": {}, "severities": [], "ai_to_jira_severity_name": {}}
    pw = _require_jira_password(body.password)
    tpk = (body.test_project_key or "").strip() or (settings.jira_test_project_key or "").strip()
    itt = (settings.jira_test_issue_type or "Test").strip() or "Test"
    if tpk:
        await asyncio.to_thread(
            _warm_jira_createmeta_cache,
            body.jira_url.strip(),
            body.username,
            pw,
            tpk,
            itt,
        )
    try:
        pri = await asyncio.to_thread(
            fetch_priorities,
            body.jira_url.strip(),
            body.username,
            pw,
        )
    except RequestException as e:
        raise _jira_request_http_exception(e) from e
    ai_map = build_ai_to_jira_priority_map(pri)
    client_pri = [
        {"id": p.get("id"), "name": p.get("name"), "iconUrl": p.get("iconUrl")}
        for p in pri
    ]
    out: dict = {
        "priorities": client_pri,
        "ai_to_jira_name": ai_map,
        "severities": [],
        "ai_to_jira_severity_name": {},
    }
    if tpk:
        try:
            meta = await asyncio.to_thread(
                get_issue_create_meta_fields_cached,
                body.jira_url.strip(),
                body.username,
                pw,
                norm_issue_key(tpk),
                itt,
            )
            fid = find_severity_field_id(meta or {})
            if fid and isinstance(meta, dict):
                fm = meta.get(fid)
                snames = severity_allowed_display_names(fm if isinstance(fm, dict) else None)
                if snames:
                    out["severities"] = [{"name": n} for n in snames]
                    out["ai_to_jira_severity_name"] = build_ai_to_jira_severity_name_map(snames)
        except Exception:
            _LOG.debug("JIRA severities meta for priorities endpoint failed", exc_info=True)
    return out


@api.post("/jira/push-test-case")
async def jira_push_test_case(body: PushTestToJiraIn, kc: Kc):
    if settings.mock:
        raise HTTPException(status_code=400, detail="Cannot push to JIRA in mock mode.")
    rk = norm_issue_key(body.requirement_key)
    existing = norm_issue_key(body.existing_issue_key)
    tc_jira = strip_test_case_diff_meta(body.test_case) if isinstance(body.test_case, dict) else body.test_case
    if existing:
        try:
            result = await asyncio.to_thread(
                update_test_case_in_jira,
                body.jira_url.strip(),
                body.username,
                _require_jira_password(body.password),
                existing,
                tc_jira,
            )
        except RequestException as e:
            raise _jira_request_http_exception(e) from e
        except ValueError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        _maybe_audit(kc, rk, f"Updated {result['key']}", body.username)
        return {"created_key": result["key"], "self": result.get("self", ""), "updated": True}
    if not body.test_project_key.strip():
        raise HTTPException(
            status_code=400,
            detail="JIRA Test Project is required to add a test case in JIRA.",
        )
    tpk = norm_issue_key(body.test_project_key)
    try:
        result = await asyncio.to_thread(
            push_test_case_to_jira,
            body.jira_url.strip(),
            body.username,
            _require_jira_password(body.password),
            rk,
            tpk,
            tc_jira,
            body.jira_test_issue_type.strip() or None,
            body.jira_link_type.strip() or None,
        )
    except RequestException as e:
        raise _jira_request_http_exception(e) from e
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    _maybe_audit(kc, rk, f"Created {result['key']}", body.username)
    return {"created_key": result["key"], "self": result.get("self", ""), "updated": False}


@api.post("/fetch-ticket")
async def fetch_ticket(body: TicketIn, kc: Kc):
    key, raw = await _fetch_jira(body)
    _maybe_audit(kc, key, "fetch_requirements", body.username)
    prev = get_latest(key)
    linked, linked_work, work_labels = await _load_ticket_linked_jira(body, key)
    attachments = await _fetch_issue_attachments(body, key)
    out: dict = {
        "ticket_id": key,
        "requirements": raw,
        "linked_jira_tests": _linked_jira_issue_rows(linked, work=False),
        "linked_jira_work": _linked_jira_issue_rows(linked_work, work=True),
        "linked_jira_work_type_labels": work_labels,
        "requirement_attachments": attachments,
    }
    if prev and isinstance(prev.get("requirements"), dict):
        out["had_saved_memory"] = True
        out["requirements_diff"] = _diff(prev["requirements"], raw)
    else:
        out["had_saved_memory"] = False
        out["requirements_diff"] = None
    return out


@api.post("/jira/attachment-download")
async def jira_attachment_download(body: AttachmentDownloadIn, _kc: Kc):
    if settings.mock:
        raise HTTPException(status_code=400, detail="Attachments are not available in mock mode.")
    key = norm_issue_key(body.ticket_id)
    pk = project_key_from_issue_key(key)
    if pk:
        await asyncio.to_thread(
            _warm_jira_createmeta_cache,
            body.jira_url.strip(),
            body.username,
            _require_jira_password(body.password),
            pk,
            _jira_test_issue_type_from_body(body),
        )
    try:
        content, filename, ctype = await asyncio.to_thread(
            download_attachment_for_ticket,
            body.jira_url.strip(),
            body.username,
            _require_jira_password(body.password),
            body.attachment_id.strip(),
            key,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RequestException as e:
        raise _jira_request_http_exception(e) from e
    disp = f'attachment; filename="{_ascii_filename(filename)}"'
    return Response(content=content, media_type=ctype, headers={"Content-Disposition": disp})


async def _run_jira_generate(request: Request, kc: Kc, *, agentic: bool) -> dict:
    cls = GenerateAgenticIn if agentic else GenerateIn
    body, files = await _read_generate_body(request, cls)
    imgs = await _merge_req_images_jira(body, files)
    key, req, prev, similar_used, shared = await _jira_generate_route_kwargs(body)
    max_rounds = body.max_rounds if agentic else 3
    out = await _generate_and_persist(
        key,
        req,
        prev,
        similar_used,
        body.min_test_cases,
        body.max_test_cases,
        body.save_memory,
        kc,
        requirement_images=imgs,
        agentic=agentic,
        max_rounds=max_rounds,
        **shared,
    )
    await _enrich_out_with_attachments(body, out)
    return out


@api.post("/generate-tests")
async def generate_tests(request: Request, kc: Kc):
    return await _run_jira_generate(request, kc, agentic=False)


@api.post("/generate-tests-agentic")
async def generate_tests_agentic(request: Request, kc: Kc):
    return await _run_jira_generate(request, kc, agentic=True)


@api.post("/generate-automation-skeleton")
async def generate_automation_skeleton_route(body: AutomationSkeletonIn, kc: Kc):
    try:
        code = await generate_automation_skeleton(body.test_case, body.language, body.framework)
    except Exception as e:
        _raise_llm_route_error(e)
    return {"code": code}


def _paste_generate_context(body: PastedGenerateIn) -> tuple[str, dict, dict | None, bool]:
    description = body.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="Description is required")
    title = _strip(body.title) or "Pasted requirements"
    memory_key_raw = (body.memory_key or "").strip()
    key = _ticket_key_from_paste(body.memory_key, title, description)
    req = {"title": title, "description": description}
    prev = get_latest(key)
    similar_used = False
    thr = settings.memory_similarity_threshold
    if prev is None and thr > 0 and not memory_key_raw:
        sk, sp = find_similar_memory(req, thr)
        if sp is not None:
            prev = sp
            key = sk
            similar_used = True
        else:
            sk, sp = find_latest_memory_by_title(req)
            if sp is not None:
                prev = sp
                key = sk
                similar_used = True
    return key, req, prev, similar_used


async def _run_paste_generate(request: Request, kc: Kc, *, agentic: bool) -> dict:
    cls = PastedAgenticIn if agentic else PastedGenerateIn
    body, files = await _read_generate_body(request, cls)
    imgs = await _merge_req_images_paste(files)
    key, req, prev, similar_used = _paste_generate_context(body)
    max_rounds = body.max_rounds if agentic else 3
    return await _generate_and_persist(
        key,
        req,
        prev,
        similar_used,
        body.min_test_cases,
        body.max_test_cases,
        body.save_memory,
        kc,
        paste_mode=True,
        requirement_images=imgs,
        agentic=agentic,
        max_rounds=max_rounds,
    )


@api.post("/generate-from-paste")
async def generate_from_paste(request: Request, kc: Kc):
    return await _run_paste_generate(request, kc, agentic=False)


@api.post("/generate-from-paste-agentic")
async def generate_from_paste_agentic(request: Request, kc: Kc):
    return await _run_paste_generate(request, kc, agentic=True)


app.include_router(api)
app.include_router(automation_routes.router, prefix="/api")

_static = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
