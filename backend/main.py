from __future__ import annotations

import asyncio
import difflib
import hashlib
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from requests.exceptions import HTTPError, RequestException

from jira_client import (
    build_ai_to_jira_priority_map,
    fetch_issue,
    fetch_linked_test_issues,
    fetch_linked_work_issues,
    fetch_priorities,
    format_jira_http_error,
    push_test_case_to_jira,
    update_test_case_in_jira,
)
from ai_client import (
    generate_automation_skeleton,
    generate_test_cases,
    merge_ai_cases_with_jira_existing,
    merge_test_cases_with_previous,
    resolve_priority_allowed_for_generation,
)
from audit_store import append_audit, init_audit_db, list_audit
from memory_store import (
    find_latest_memory_by_title,
    find_similar_memory,
    get_latest,
    init_db,
    list_saved,
    merge_test_case_into_memory,
    normalized_paste_key_material,
    save,
)
from keycloak_auth import claims_username, verify_keycloak_token
from settings import settings


def _strip(s: str) -> str:
    return (s or "").strip()


def _validate_tc_bounds(min_test_cases: int, max_test_cases: int) -> None:
    if 0 < max_test_cases < min_test_cases:
        raise ValueError("max_test_cases must be >= min_test_cases, or 0 for no maximum")


class TicketIn(BaseModel):
    jira_url: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    ticket_id: str = Field(..., min_length=1)
    jira_test_issue_type: str = ""


def _jira_test_issue_type_from_body(body: TicketIn) -> str:
    return (body.jira_test_issue_type or "").strip() or settings.jira_test_issue_type or "Test"


def _linked_jira_tests_light(entries: list) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        pri = str(e.get("jira_priority_name") or e.get("priority") or "").strip()
        icon = str(e.get("jira_priority_icon_url") or e.get("priority_icon_url") or "").strip()
        out.append(
            {
                "issue_key": e.get("issue_key"),
                "summary": e.get("summary"),
                "status_name": e.get("status_name"),
                "browse_url": e.get("browse_url"),
                "priority": pri,
                "priority_icon_url": icon or None,
            }
        )
    return out


def _linked_jira_work_light(entries: list) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        out.append(
            {
                "issue_key": e.get("issue_key"),
                "summary": e.get("summary"),
                "status_name": e.get("status_name"),
                "browse_url": e.get("browse_url"),
                "issue_type_name": e.get("issue_type_name") or "",
            }
        )
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


async def _load_ticket_linked_jira(body: TicketIn, key: str) -> tuple[list, list, str]:
    empty = _linked_work_type_labels_display(settings.jira_linked_work_issue_types, "")
    if settings.mock:
        return [], [], empty
    ju = body.jira_url.strip()
    user = body.username
    pw = body.password
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
        linked_work = []
        work_labels = empty
    return linked, linked_work, work_labels


class GenerateIn(TicketIn):
    test_project_key: str = ""
    save_memory: bool = True
    min_test_cases: int = Field(1, ge=1)
    max_test_cases: int = Field(10, ge=0)

    @model_validator(mode="after")
    def _test_case_bounds(self) -> "GenerateIn":
        _validate_tc_bounds(self.min_test_cases, self.max_test_cases)
        return self


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


class PastedGenerateIn(BaseModel):
    title: str = Field(default="", max_length=10000)
    description: str = Field(..., min_length=1)
    memory_key: str = Field(default="", max_length=64)
    save_memory: bool = True
    min_test_cases: int = Field(1, ge=1)
    max_test_cases: int = Field(10, ge=0)

    @model_validator(mode="after")
    def _paste_bounds(self) -> "PastedGenerateIn":
        _validate_tc_bounds(self.min_test_cases, self.max_test_cases)
        return self


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
    password: str = Field(..., min_length=1)
    requirement_key: str = Field(..., min_length=1)
    test_project_key: str = ""
    jira_test_issue_type: str = ""
    jira_link_type: str = ""
    test_case: dict = Field(default_factory=dict)
    existing_issue_key: str = Field(
        default="",
        description="When set, PUT this issue instead of creating a new one (no new link).",
    )


class JiraPrioritiesIn(BaseModel):
    jira_url: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    test_project_key: str = ""


class ConfigResponse(BaseModel):
    default_jira_url: str = ""
    default_username: str = ""
    default_jira_test_project_key: str = ""
    default_jira_test_issue_type: str = "Test"
    default_jira_link_type: str = "Relates"
    mock: bool = False
    show_memory_ui: bool = True
    show_audit_ui: bool = True
    use_keycloak: bool = False
    keycloak_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_idle_timeout_minutes: int = 5


def _req_snapshot(d: dict) -> str:
    return f"Title: {d.get('title', '')}\n\nDescription:\n{d.get('description', '')}"


def _ticket_key_from_paste(memory_key: str, title: str, description: str) -> str:
    raw = (memory_key or "").strip().upper()
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
    key = body.ticket_id.strip().upper()
    try:
        raw = await asyncio.to_thread(
            fetch_issue,
            body.jira_url.strip(),
            body.username,
            body.password,
            key,
        )
    except RequestException as e:
        raise _jira_request_http_exception(e) from e
    return key, raw


async def _maybe_fetch_jira_priority_names_for_generate(body: GenerateIn) -> list[str] | None:
    if not body.test_project_key.strip() or settings.mock:
        return None
    try:
        pri = await asyncio.to_thread(
            fetch_priorities,
            body.jira_url.strip(),
            body.username,
            body.password,
        )
        names = [str(p.get("name") or "").strip() for p in pri if str(p.get("name") or "").strip()]
        return names if names else None
    except Exception:
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
    jira_entries: list | None = None,
    linked_jira_work_entries: list | None = None,
    linked_jira_work_type_labels: str = "",
) -> dict:
    req_diff = _diff(prev["requirements"], req) if prev else None
    allowed = resolve_priority_allowed_for_generation(paste_mode, priority_labels)
    ej_llm = _existing_jira_tests_for_llm(jira_entries)
    try:
        cases = await generate_test_cases(
            req,
            prev,
            allowed_priorities=allowed,
            min_test_cases=min_test_cases,
            max_test_cases=max_test_cases,
            paste_mode=paste_mode,
            existing_jira_tests=ej_llm,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e
    if jira_entries:
        cases = merge_ai_cases_with_jira_existing(cases, jira_entries, allowed_priorities=allowed)
    prior_union = _prior_cases_union_for_merge(key, prev)
    if prior_union:
        cases = merge_test_cases_with_previous(prior_union, cases, allowed_priorities=allowed)
    if not settings.mock:
        if save_memory:
            save(key, req, cases)
        _maybe_audit(kc, key, "generate_test_cases")
    return {
        "ticket_id": key,
        "requirements": req,
        "test_cases": cases,
        "requirements_diff": req_diff,
        "had_previous_memory": prev is not None,
        "memory_match": ("similar" if similar_used else "exact") if prev else None,
        "linked_jira_tests": _linked_jira_tests_light(jira_entries or []),
        "linked_jira_work": _linked_jira_work_light(linked_jira_work_entries or []),
        "linked_jira_work_type_labels": linked_jira_work_type_labels,
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.use_keycloak and not all(
        x.strip() for x in (settings.keycloak_url, settings.keycloak_realm, settings.keycloak_client_id)
    ):
        raise RuntimeError("USE_KEYCLOAK=true requires KEYCLOAK_URL, KEYCLOAK_REALM, and KEYCLOAK_CLIENT_ID in .env")
    init_db()
    init_audit_db()
    yield


def get_keycloak_claims(authorization: str | None = Header(None)) -> dict | None:
    if not settings.use_keycloak:
        return None
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization[7:].strip()
    try:
        return verify_keycloak_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


Kc = Annotated[dict | None, Depends(get_keycloak_claims)]


def _maybe_audit(kc: dict | None, key: str, action: str) -> None:
    if settings.mock:
        return
    u = claims_username(kc) if settings.use_keycloak and kc else ""
    append_audit(u, key, action)


app = FastAPI(title="Test Intellect AI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
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
    data = get_latest(ticket_id.strip())
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "ticket_id": ticket_id.strip().upper(),
        "requirements": data["requirements"],
        "test_cases": data["test_cases"],
    }


@api.post("/memory/update-test-cases")
def memory_update_test_cases(body: MemoryUpdateTestCasesIn, kc: Kc):
    _require_memory_not_mock()
    key = body.ticket_id.strip().upper()
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
    key = body.ticket_id.strip().upper()
    tc = body.test_case if isinstance(body.test_case, dict) else {}
    req = body.requirements if isinstance(body.requirements, dict) else {}
    merge_test_case_into_memory(key, req, tc)
    return {"ok": True}


@api.post("/memory/save-after-edit")
def memory_save_after_edit(body: MemorySaveAfterEditIn, kc: Kc):
    _require_memory_not_mock()
    key = body.ticket_id.strip().upper()
    req = body.requirements if isinstance(body.requirements, dict) else {}
    tc = body.test_cases if isinstance(body.test_cases, list) else []
    save(key, req, tc)
    jk = (body.edited_jira_issue_key or "").strip()
    if jk:
        _maybe_audit(kc, key, f"Edited {jk}")
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
        default_jira_test_project_key=_strip(s.jira_test_project_key),
        default_jira_test_issue_type=_strip(s.jira_test_issue_type) or "Test",
        default_jira_link_type=_strip(s.jira_test_link_type) or "Relates",
        mock=s.mock,
        show_memory_ui=s.show_memory_ui,
        show_audit_ui=s.show_audit_ui,
        use_keycloak=s.use_keycloak,
        keycloak_url=_strip(s.keycloak_url),
        keycloak_realm=_strip(s.keycloak_realm),
        keycloak_client_id=_strip(s.keycloak_client_id),
        keycloak_idle_timeout_minutes=s.keycloak_idle_timeout_minutes,
    )


@api.post("/jira/priorities")
async def jira_priorities(body: JiraPrioritiesIn, kc: Kc):
    if settings.mock:
        return {"priorities": [], "ai_to_jira_name": {}}
    try:
        pri = await asyncio.to_thread(
            fetch_priorities,
            body.jira_url.strip(),
            body.username,
            body.password,
        )
    except RequestException as e:
        raise _jira_request_http_exception(e) from e
    ai_map = build_ai_to_jira_priority_map(pri)
    client_pri = [
        {"id": p.get("id"), "name": p.get("name"), "iconUrl": p.get("iconUrl")}
        for p in pri
    ]
    return {"priorities": client_pri, "ai_to_jira_name": ai_map}


@api.post("/jira/push-test-case")
async def jira_push_test_case(body: PushTestToJiraIn, kc: Kc):
    if settings.mock:
        raise HTTPException(status_code=400, detail="Cannot push to JIRA in mock mode.")
    rk = body.requirement_key.strip().upper()
    existing = (body.existing_issue_key or "").strip().upper()
    if existing:
        try:
            result = await asyncio.to_thread(
                update_test_case_in_jira,
                body.jira_url.strip(),
                body.username,
                body.password,
                existing,
                body.test_case,
            )
        except RequestException as e:
            raise _jira_request_http_exception(e) from e
        except ValueError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        _maybe_audit(kc, rk, f"Updated {result['key']}")
        return {"created_key": result["key"], "self": result.get("self", ""), "updated": True}
    if not body.test_project_key.strip():
        raise HTTPException(
            status_code=400,
            detail="JIRA Test Project is required to add a test case in JIRA.",
        )
    tpk = body.test_project_key.strip().upper()
    try:
        result = await asyncio.to_thread(
            push_test_case_to_jira,
            body.jira_url.strip(),
            body.username,
            body.password,
            rk,
            tpk,
            body.test_case,
            body.jira_test_issue_type.strip() or None,
            body.jira_link_type.strip() or None,
        )
    except RequestException as e:
        raise _jira_request_http_exception(e) from e
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    _maybe_audit(kc, rk, f"Created {result['key']}")
    return {"created_key": result["key"], "self": result.get("self", ""), "updated": False}


@api.post("/fetch-ticket")
async def fetch_ticket(body: TicketIn, kc: Kc):
    key, raw = await _fetch_jira(body)
    _maybe_audit(kc, key, "fetch_requirements")
    prev = get_latest(key)
    linked, linked_work, work_labels = await _load_ticket_linked_jira(body, key)
    out: dict = {
        "ticket_id": key,
        "requirements": raw,
        "linked_jira_tests": _linked_jira_tests_light(linked),
        "linked_jira_work": _linked_jira_work_light(linked_work),
        "linked_jira_work_type_labels": work_labels,
    }
    if prev and isinstance(prev.get("requirements"), dict):
        out["had_saved_memory"] = True
        out["requirements_diff"] = _diff(prev["requirements"], raw)
    else:
        out["had_saved_memory"] = False
        out["requirements_diff"] = None
    return out


@api.post("/generate-tests")
async def generate_tests(body: GenerateIn, kc: Kc):
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
    return await _generate_and_persist(
        key,
        req,
        prev,
        similar_used,
        body.min_test_cases,
        body.max_test_cases,
        body.save_memory,
        kc,
        paste_mode=False,
        priority_labels=jira_names,
        jira_entries=jira_entries,
        linked_jira_work_entries=linked_work_raw,
        linked_jira_work_type_labels=work_labels,
    )


@api.post("/generate-automation-skeleton")
async def generate_automation_skeleton_route(body: AutomationSkeletonIn, kc: Kc):
    try:
        code = await generate_automation_skeleton(body.test_case, body.language, body.framework)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e
    return {"code": code}


@api.post("/generate-from-paste")
async def generate_from_paste(body: PastedGenerateIn, kc: Kc):
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
    )


app.include_router(api)

_static = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
