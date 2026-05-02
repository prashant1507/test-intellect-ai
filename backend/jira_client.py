from __future__ import annotations

import html as html_module
import json
import logging
import re
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

import requests
import urllib3

from key_norm import norm_issue_key
from settings import settings

_LOG = logging.getLogger(__name__)
_createmeta_cache_lock = threading.Lock()
_CREATEMETA_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "jira_createmeta_cache.json"


def _requests_verify() -> bool:
    v = settings.jira_verify_ssl
    if not v:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return v


def _semantic_tier_labels_for_jira_mapping() -> list[str]:
    return ["Highest", "High", "Medium", "Low", "Lowest"]


def fetch_priorities(base_url: str, user: str, password: str) -> list[dict]:
    verify = _requests_verify()
    base = base_url.rstrip("/")
    auth = (user, password)
    headers = {"Accept": "application/json"}
    r = requests.get(
        f"{base}/rest/api/2/priority",
        auth=auth,
        headers=headers,
        timeout=60,
        verify=verify,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []

    def sort_key(p: dict) -> float:
        s = p.get("sequence")
        if s is not None:
            try:
                return float(s)
            except (TypeError, ValueError):
                pass
        try:
            return float(p.get("id", 0))
        except (TypeError, ValueError):
            return 0.0

    return sorted(data, key=sort_key)


def build_ai_to_jira_priority_map(jira_priorities: list[dict]) -> dict[str, str]:
    labels = _semantic_tier_labels_for_jira_mapping()
    if not labels or not jira_priorities:
        return {}
    n = len(jira_priorities)
    out: dict[str, str] = {}
    denom = max(len(labels) - 1, 1)
    for i, lab in enumerate(labels):
        j = min(n - 1, round(i * (n - 1) / denom)) if n > 1 else 0
        name = str(jira_priorities[j].get("name") or "").strip()
        if name:
            out[lab] = name
    return out


def map_test_priority_to_jira(
    ai_or_name: str | None,
    jira_priorities: list[dict],
) -> dict | None:
    if not jira_priorities:
        return None
    raw = str(ai_or_name or "").strip()
    if not raw:
        labs = _semantic_tier_labels_for_jira_mapping()
        raw = labs[len(labs) // 2] if labs else "Medium"
    by_name = {str(p.get("name") or "").lower(): p for p in jira_priorities}
    if raw.lower() in by_name:
        return by_name[raw.lower()]
    ai_map = build_ai_to_jira_priority_map(jira_priorities)
    labels = _semantic_tier_labels_for_jira_mapping()
    for lab in labels:
        if lab.lower() == raw.lower():
            jname = ai_map.get(lab)
            if jname and jname.lower() in by_name:
                return by_name[jname.lower()]
            break
    for lab, jname in ai_map.items():
        if lab.lower() == raw.lower() and jname and jname.lower() in by_name:
            return by_name[jname.lower()]
    for lab in labels:
        if lab.lower() in raw.lower() or raw.lower() in lab.lower():
            jname = ai_map.get(lab)
            if jname and jname.lower() in by_name:
                return by_name[jname.lower()]
    return jira_priorities[len(jira_priorities) // 2]


def _priority_payload_for_issue(pick: dict) -> dict:
    pid = pick.get("id")
    if pid is not None and str(pid).strip() != "":
        return {"id": str(pid)}
    name = str(pick.get("name") or "").strip()
    return {"name": name} if name else {}


def _severity_semantic_labels() -> list[str]:
    raw = (settings.paste_mode_severities or "").strip()
    if not raw:
        return ["Blocker", "Critical", "Major", "Minor"]
    return [x.strip() for x in raw.split(",") if x.strip()]


def severity_display_from_issue_field(val: object) -> str:
    if isinstance(val, dict):
        for k in ("value", "name"):
            x = val.get(k)
            if isinstance(x, str) and x.strip():
                return x.strip()
        if val.get("id") is not None:
            return str(val.get("id")).strip()
    return str(val or "").strip()


def severity_allowed_display_names(meta_field: dict | None) -> list[str]:
    if not isinstance(meta_field, dict):
        return []
    av = meta_field.get("allowedValues")
    if not isinstance(av, list):
        return []
    out: list[str] = []
    for o in av:
        if not isinstance(o, dict):
            continue
        d = severity_display_from_issue_field(o)
        if d:
            out.append(d)
    return out


def find_severity_field_id(meta_fields: dict[str, dict]) -> str | None:
    ov = (settings.jira_test_severity_field_id or "").strip()
    if ov:
        return ov if ov in meta_fields else None
    for fid, fm in meta_fields.items():
        if isinstance(fm, dict) and str(fm.get("name") or "").strip().casefold() == "severity":
            return str(fid)
    return None


def build_ai_to_jira_severity_map(allowed_options: list[dict]) -> dict[str, str]:
    labels = _severity_semantic_labels()
    if not labels or not allowed_options:
        return {}
    n = len(allowed_options)
    out: dict[str, str] = {}
    denom = max(len(labels) - 1, 1)
    for i, lab in enumerate(labels):
        j = min(n - 1, round(i * (n - 1) / denom)) if n > 1 else 0
        dn = severity_display_from_issue_field(allowed_options[j])
        if dn:
            out[lab] = dn
    return out


def build_ai_to_jira_severity_name_map(sorted_names: list[str]) -> dict[str, str]:
    labels = _severity_semantic_labels()
    if not labels or not sorted_names:
        return {}
    n = len(sorted_names)
    out: dict[str, str] = {}
    denom = max(len(labels) - 1, 1)
    for i, lab in enumerate(labels):
        j = min(n - 1, round(i * (n - 1) / denom)) if n > 1 else 0
        out[lab] = sorted_names[j]
    return out


def map_test_severity_to_jira(
    ai_or_name: str | None,
    meta_field: dict,
) -> dict | None:
    av = meta_field.get("allowedValues") if isinstance(meta_field, dict) else None
    opts = [x for x in av if isinstance(x, dict)] if isinstance(av, list) else []
    if not opts:
        return None
    raw = str(ai_or_name or "").strip()
    labs = _severity_semantic_labels()
    if not raw:
        raw = labs[len(labs) // 2] if labs else severity_display_from_issue_field(opts[len(opts) // 2])
    def _dk(o: dict) -> str:
        return severity_display_from_issue_field(o).lower()

    by_name = {_dk(o): o for o in opts}
    ai_map = build_ai_to_jira_severity_map(opts)
    if raw.lower() in by_name:
        return by_name[raw.lower()]
    for lab in labs:
        if lab.lower() == raw.lower():
            jnm = ai_map.get(lab)
            if jnm and str(jnm).strip().lower() in by_name:
                return by_name[str(jnm).strip().lower()]
            break
    for lab, jnm in ai_map.items():
        if lab.lower() == raw.lower() and jnm and str(jnm).strip().lower() in by_name:
            return by_name[str(jnm).strip().lower()]
    for lab in labs:
        lj = lab.lower()
        if lj in raw.lower() or raw.lower() in lj:
            jnm = ai_map.get(lab)
            if jnm and str(jnm).strip().lower() in by_name:
                return by_name[str(jnm).strip().lower()]
            break
    return opts[len(opts) // 2]


def severity_option_payload_for_issue(pick: dict) -> dict:
    pid = pick.get("id")
    if pid is not None and str(pid).strip() != "":
        return {"id": str(pid)}
    v = pick.get("value")
    if isinstance(v, str) and v.strip():
        return {"value": v.strip()}
    n = pick.get("name")
    if isinstance(n, str) and n.strip():
        return {"name": n.strip()}
    return dict(pick)


def apply_test_severity_to_issue_fields(fields: dict, test_case: dict, meta_fields: dict[str, dict]) -> None:
    fid = find_severity_field_id(meta_fields or {})
    if not fid:
        return
    fm = meta_fields.get(fid) if isinstance(meta_fields, dict) else None
    if not isinstance(fm, dict):
        return
    opt = map_test_severity_to_jira((test_case or {}).get("severity"), fm)
    if opt is None:
        return
    fields[fid] = severity_option_payload_for_issue(opt)


def _adf(
    node: object,
    *,
    list_kind: str | None = None,
    index: int = 0,
    depth: int = 0,
) -> str:
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf(x, depth=depth) for x in node)
    if not isinstance(node, dict):
        return str(node)

    t = node.get("type", "")
    content = node.get("content") or []

    def render_children(**kwargs: object) -> str:
        return "".join(_adf(c, **kwargs) for c in content)

    if t == "text":
        return str(node.get("text", ""))
    if t == "hardBreak":
        return "\n"
    if t == "heading":
        level = max(1, min(6, int((node.get("attrs") or {}).get("level") or 1)))
        return f"{'#' * level} {render_children(depth=depth).strip()}\n"
    if t in {"bulletList", "orderedList"}:
        kind = "bullet" if t == "bulletList" else "ordered"
        lines = (_adf(c, list_kind=kind, index=i, depth=depth) for i, c in enumerate(content))
        return "".join(lines) + "\n"
    if t == "listItem":
        body = render_children(depth=depth + 1).strip()
        pad = "  " * depth
        marker = {"bullet": "-", "ordered": f"{index + 1}."}.get(list_kind, "•")
        return f"{pad}{marker} {body}\n"

    inner = render_children(depth=depth)
    return inner + "\n" if t == "paragraph" else inner


def _html_to_plain(html: str) -> str:
    t = html_module.unescape(html)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    for n in range(1, 7):
        t = re.sub(rf"<h{n}[^>]*>(.*?)</h{n}>", rf"\n\n{'#' * n} \1\n\n", t, flags=re.I | re.S)
    t = re.sub(r"</p>\s*<p[^>]*>", "\n\n", t, flags=re.I)
    t = re.sub(r"<p[^>]*>", "", t, flags=re.I)
    t = re.sub(r"</p>", "\n\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n- ", t, flags=re.I)
    t = re.sub(r"</li>", "", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _desc(fields: dict) -> str:
    html = (fields.get("renderedFields") or {}).get("description")
    if isinstance(html, str) and html.strip():
        return _html_to_plain(html)
    d = fields.get("description")
    if isinstance(d, str):
        return d.strip()
    if isinstance(d, dict) and d.get("type") == "doc":
        return _adf(d).strip()
    return str(d or "").strip()


def _mock_issue(issue_key: str) -> dict[str, str]:
    k = norm_issue_key(issue_key)
    title = f"Login Page Implementation | {k}"
    desc = """
Develop a secure and user-friendly login page that allows registered users to access the application using their credentials. The page should follow UI/UX guidelines and ensure proper validation, authentication, and error handling.

User Story:
As a registered user, I want to log in to the application using my email/username and password so that I can securely access my account.

## Acceptance Criteria

1. UI Elements

* Login form should include:

    * Email/Username field
    * Password field
    * Login button
    * "Forgot Password" link
* Password field should have show/hide toggle option

2. Validation

* Email/Username field should not be empty
* Password field should not be empty
* Email format should be validated (if email is used)
* Display proper validation messages

3. Authentication

* On valid input, system should authenticate user credentials via backend API
* On successful login, redirect user to dashboard/home page
* Store authentication token/session securely

4. Error Handling

* Display error message for:

    * Invalid credentials
    * User not found
    * Server/API errors
* Error messages should be user-friendly

5. Security

* Password should be masked by default
* Implement secure API communication (HTTPS)
* Protect against common vulnerabilities (e.g., brute force, injection)

6. Performance

* Login response time should be within acceptable limits (<2 seconds ideally)

7. Accessibility & UX

* Form should be accessible (keyboard navigation, labels)
* Responsive design for mobile, tablet, and desktop
    """
    return {"title": title.strip(), "description": desc.strip()}


def format_jira_http_error(response: requests.Response) -> str:
    status = response.status_code

    def extract_body() -> str:
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError, TypeError):
            text = (response.text or "").strip()
            return text[:500] if text else ""

        if not isinstance(data, dict):
            return ""

        msgs = data.get("errorMessages")
        if isinstance(msgs, list):
            text = " ".join(m.strip() for m in msgs if isinstance(m, str) and m.strip())
            if text:
                return text

        errs = data.get("errors")
        if isinstance(errs, dict):
            text = "; ".join(f"{k}: {v}" for k, v in errs.items() if v)
            if text:
                return text

        text = (response.text or "").strip()
        return text[:500] if text else ""

    body = extract_body() or (response.reason or "Unknown error").strip()
    status_hints = {
        401: "Check your email and password. For Atlassian Cloud, use an API token as the password if required.",
        403: "Your account may not have permission to view this project or issue.",
        404: "The ticket may not exist, or you may not have access. Confirm the ticket key and site URL.",
    }
    lines = [f"JIRA returned HTTP {status}.", body]
    if status in status_hints:
        lines.append(status_hints[status])
    elif status >= 500:
        lines.append("The JIRA service reported an error. Try again in a moment.")
    return "\n".join(lines)


def fetch_issue(base_url: str, user: str, password: str, issue_key: str) -> dict[str, str]:
    if settings.mock:
        return _mock_issue(issue_key)
    verify = _requests_verify()
    response = requests.get(
        f"{base_url.rstrip('/')}/rest/api/2/issue/{issue_key}",
        auth=(user, password),
        headers={"Accept": "application/json"},
        params={"expand": "renderedFields"},
        timeout=60,
        verify=verify,
    )
    response.raise_for_status()
    data = response.json()
    fields = data.get("fields") or {}
    title = (fields.get("summary") or "").strip()
    description = _desc(fields)
    return {"title": title, "description": description}


def fetch_issue_attachment_meta(base_url: str, user: str, password: str, issue_key: str) -> list[dict]:
    if settings.mock:
        return []
    data = _get_issue_json(base_url, user, password, issue_key, fields="attachment")
    fields = data.get("fields") or {}
    raw = fields.get("attachment")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or "").strip()
        if not aid:
            continue
        fn = str(a.get("filename") or "attachment").strip() or "attachment"
        sz = a.get("size")
        try:
            size_i = int(sz) if sz is not None else None
        except (TypeError, ValueError):
            size_i = None
        mime = str(a.get("mimeType") or "").strip()
        out.append(
            {
                "id": aid,
                "filename": fn,
                "size": size_i,
                "mime_type": mime or None,
            }
        )
    return out


def download_attachment_for_ticket(
    base_url: str,
    user: str,
    password: str,
    attachment_id: str,
    expected_issue_key: str,
) -> tuple[bytes, str, str]:
    if settings.mock:
        return b"", "attachment", "application/octet-stream"
    exp = norm_issue_key(expected_issue_key)
    meta_list = fetch_issue_attachment_meta(base_url, user, password, exp)
    aid = str(attachment_id or "").strip()
    if not aid or not any(str(x.get("id")) == aid for x in meta_list if isinstance(x, dict)):
        raise ValueError("Attachment not found on this ticket")
    filename = "attachment"
    for x in meta_list:
        if isinstance(x, dict) and str(x.get("id")) == aid:
            filename = str(x.get("filename") or "attachment").strip() or "attachment"
            break
    verify = _requests_verify()
    base = base_url.rstrip("/")
    r = requests.get(
        f"{base}/rest/api/2/attachment/content/{aid}",
        auth=(user, password),
        headers={"Accept": "*/*"},
        timeout=120,
        verify=verify,
    )
    r.raise_for_status()
    ct = (r.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
    return r.content, filename, ct


def jira_browse_url(base_url: str, issue_key: str) -> str:
    return f"{base_url.rstrip('/')}/browse/{norm_issue_key(issue_key)}"


def _get_issue_json(
    base_url: str,
    user: str,
    password: str,
    issue_key: str,
    *,
    fields: str,
    expand: str | None = None,
) -> dict:
    verify = _requests_verify()
    params: dict[str, str] = {"fields": fields}
    if expand:
        params["expand"] = expand
    r = requests.get(
        f"{base_url.rstrip('/')}/rest/api/2/issue/{norm_issue_key(issue_key)}",
        auth=(user, password),
        headers={"Accept": "application/json"},
        params=params,
        timeout=60,
        verify=verify,
    )
    r.raise_for_status()
    return r.json()


def _parse_issue_type_names(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def fetch_requirement_issue_type_name(
    base_url: str,
    user: str,
    password: str,
    requirement_key: str,
) -> str:
    if settings.mock:
        return ""
    data = _get_issue_json(base_url, user, password, requirement_key, fields="issuetype")
    it = (data.get("fields") or {}).get("issuetype") or {}
    return str(it.get("name") or "").strip()


def fetch_linked_work_issues(
    base_url: str,
    user: str,
    password: str,
    requirement_key: str,
    *,
    extra_issue_types_from_env: str,
    test_issue_type_name: str,
) -> tuple[list[dict], str]:
    if settings.mock:
        return [], ""
    req_type = fetch_requirement_issue_type_name(base_url, user, password, requirement_key)
    want_cf: set[str] = {t.casefold() for t in _parse_issue_type_names(extra_issue_types_from_env)}
    if req_type:
        want_cf.add(req_type.casefold())
    if not want_cf:
        return [], req_type
    test_cf = (test_issue_type_name or "").strip().casefold() or (settings.jira_test_issue_type or "Test").casefold()
    keys = list_linked_issue_keys(base_url, user, password, requirement_key)
    out: list[dict] = []
    for ik in keys:
        try:
            data = _get_issue_json(
                base_url,
                user,
                password,
                ik,
                fields="summary,issuetype,status,description,renderedFields",
                expand="renderedFields",
            )
        except Exception:
            _LOG.debug("fetch_linked_work_issues: skip issue %s", ik, exc_info=True)
            continue
        fields = data.get("fields") or {}
        it = fields.get("issuetype") or {}
        it_name = str(it.get("name") or "").strip()
        it_cf = it_name.casefold()
        if it_cf == test_cf:
            continue
        if it_cf not in want_cf:
            continue
        summary = str(fields.get("summary") or "").strip() or ik
        desc_plain = _desc(fields)
        st = fields.get("status") or {}
        status_name = str(st.get("name") or "").strip() or "—"
        key = norm_issue_key(str(data.get("key") or ik))
        browse = jira_browse_url(base_url, key)
        out.append(
            {
                "issue_key": key,
                "summary": summary,
                "status_name": status_name,
                "browse_url": browse,
                "issue_type_name": it_name,
                "description": desc_plain,
            }
        )
    return out, req_type


def list_linked_issue_keys(
    base_url: str,
    user: str,
    password: str,
    requirement_key: str,
) -> list[str]:
    data = _get_issue_json(base_url, user, password, requirement_key, fields="issuelinks")
    req_u = norm_issue_key(requirement_key)
    keys: list[str] = []
    for link in (data.get("fields") or {}).get("issuelinks") or []:
        for side in ("inwardIssue", "outwardIssue"):
            iss = link.get(side)
            if isinstance(iss, dict):
                k = norm_issue_key(str(iss.get("key") or ""))
                if k and k != req_u:
                    keys.append(k)
    return list(dict.fromkeys(keys))


def _description_lines_to_steps(body: str) -> list[str]:
    raw = (body or "").strip()
    if not raw:
        return ["Given Preconditions are met."]
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    steps: list[str] = []
    for ln in lines:
        if re.match(r"^(Given|When|Then|And)\s+", ln, re.I):
            steps.append(ln)
    if steps:
        return steps
    return [f"Given {lines[0]}"] if lines else ["Given Preconditions are met."]


def fetch_linked_test_issues(
    base_url: str,
    user: str,
    password: str,
    requirement_key: str,
    test_issue_type_name: str,
) -> list[dict]:
    if settings.mock:
        return []
    want = (test_issue_type_name or "").strip() or "Test"
    want_l = want.casefold()
    keys = list_linked_issue_keys(base_url, user, password, requirement_key)
    uniq_pj: list[str] = []
    for ik in keys:
        pj = project_key_from_issue_key(ik)
        if pj and pj not in uniq_pj:
            uniq_pj.append(pj)
    meta_by_pj: dict[str, dict[str, dict]] = {}
    for pj in uniq_pj:
        try:
            meta_by_pj[pj] = get_issue_create_meta_fields_cached(base_url, user, password, pj, want)
        except Exception:
            _LOG.debug("createmeta unavailable for project %s", pj, exc_info=True)
            meta_by_pj[pj] = {}
    out: list[dict] = []
    for ik in keys:
        pj_link = project_key_from_issue_key(ik)
        meta_l = meta_by_pj.get(pj_link) or {}
        sev_fid = find_severity_field_id(meta_l)
        fld = "summary,description,issuetype,status,priority,renderedFields"
        if sev_fid:
            fld += f",{sev_fid}"
        try:
            data = _get_issue_json(base_url, user, password, ik, fields=fld, expand="renderedFields")
        except Exception:
            _LOG.debug("fetch_linked_test_issues: skip issue %s", ik, exc_info=True)
            continue
        fields = data.get("fields") or {}
        it = fields.get("issuetype") or {}
        it_name = str(it.get("name") or "").strip()
        if it_name.casefold() != want_l:
            continue
        summary = str(fields.get("summary") or "").strip() or ik
        desc_plain = _desc(fields)
        steps = _description_lines_to_steps(desc_plain)
        st = fields.get("status") or {}
        status_name = str(st.get("name") or "").strip() or "—"
        key = norm_issue_key(str(data.get("key") or ik))
        browse = jira_browse_url(base_url, key)
        pri = fields.get("priority") if isinstance(fields.get("priority"), dict) else {}
        jira_priority_name = str(pri.get("name") or "").strip()
        jira_priority_icon_url = str(pri.get("iconUrl") or "").strip()
        se_raw = fields.get(sev_fid) if sev_fid else None
        jira_severity_name = severity_display_from_issue_field(se_raw) if se_raw is not None else ""
        tc = {
            "description": summary[:10000],
            "preconditions": "",
            "steps": steps,
            "expected_result": "",
            "severity": jira_severity_name,
        }
        out.append(
            {
                "issue_key": key,
                "summary": summary,
                "status_name": status_name,
                "browse_url": browse,
                "jira_priority_name": jira_priority_name,
                "jira_priority_icon_url": jira_priority_icon_url,
                "jira_severity_name": jira_severity_name,
                "test_case": tc,
            }
        )
    return out


def _issue_fields_summary_desc_priority(
    base_url: str,
    user: str,
    password: str,
    test_case: dict,
) -> dict:
    summary = str((test_case or {}).get("description") or "Test case").strip() or "Test case"
    summary = summary[:254]
    desc = _test_case_description_text(test_case)
    fields: dict = {"summary": summary, "description": desc}
    try:
        prior_list = fetch_priorities(base_url, user, password)
        pick = map_test_priority_to_jira((test_case or {}).get("priority"), prior_list)
        if pick:
            fields["priority"] = _priority_payload_for_issue(pick)
    except Exception:
        _LOG.debug("Could not map test case priority to JIRA", exc_info=True)
    return fields


def fetch_issue_create_meta_fields(
    base_url: str,
    user: str,
    password: str,
    project_key: str,
    issue_type_name: str,
) -> dict[str, dict]:
    verify = _requests_verify()
    base = base_url.rstrip("/")
    pj = quote(norm_issue_key(project_key), safe="")
    itn = quote(issue_type_name.strip(), safe="")
    url = (
        f"{base}/rest/api/2/issue/createmeta"
        f"?projectKeys={pj}&issuetypeNames={itn}&expand=projects.issuetypes.fields"
    )
    r = requests.get(
        url,
        auth=(user, password),
        headers={"Accept": "application/json"},
        timeout=60,
        verify=verify,
    )
    r.raise_for_status()
    data = r.json()
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, list):
        raise ValueError("JIRA createmeta response has no projects")
    target = issue_type_name.strip().casefold()
    for pr in projects:
        if not isinstance(pr, dict):
            continue
        for ipt in pr.get("issuetypes") or []:
            if not isinstance(ipt, dict):
                continue
            if str(ipt.get("name") or "").strip().casefold() != target:
                continue
            fd = ipt.get("fields")
            return fd if isinstance(fd, dict) else {}
    raise ValueError(f"Issue type {issue_type_name!r} not found in createmeta for project {project_key!r}")


def project_key_from_issue_key(issue_key: str) -> str:
    k = norm_issue_key(issue_key)
    if "-" not in k:
        return ""
    return k.split("-", 1)[0]


def _createmeta_cache_blob_key(base_url: str, project_key: str, issue_type_name: str) -> str:
    b = base_url.rstrip("/").casefold()
    pk = norm_issue_key(project_key).casefold()
    it = issue_type_name.strip().casefold()
    return f"{b}|{pk}|{it}"


def _load_createmeta_cache_blob() -> dict:
    path = _CREATEMETA_CACHE_PATH
    if not path.is_file():
        return {"v": 1, "entries": {}}
    try:
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
        if isinstance(blob, dict) and isinstance(blob.get("entries"), dict):
            return blob
    except Exception:
        _LOG.warning("Ignoring invalid JIRA createmeta cache file at %s", path, exc_info=True)
    return {"v": 1, "entries": {}}


def _save_createmeta_cache_blob(blob: dict) -> None:
    path = _CREATEMETA_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False)
    tmp.replace(path)


def get_issue_create_meta_fields_cached(
    base_url: str,
    user: str,
    password: str,
    project_key: str,
    issue_type_name: str,
) -> dict[str, dict]:
    ttl = int(settings.jira_createmeta_test_ttl_seconds or 0)
    if ttl <= 0:
        return fetch_issue_create_meta_fields(
            base_url, user, password, project_key, issue_type_name
        )
    ck = _createmeta_cache_blob_key(base_url, project_key, issue_type_name)
    now = time.time()
    with _createmeta_cache_lock:
        blob = _load_createmeta_cache_blob()
        entries = blob.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            blob["entries"] = entries
        ent = entries.get(ck)
        if isinstance(ent, dict):
            at = ent.get("fetched_at_unix")
            fields = ent.get("fields")
            if isinstance(at, (int, float)) and isinstance(fields, dict) and (now - float(at)) < ttl:
                return fields
        fields = fetch_issue_create_meta_fields(
            base_url, user, password, project_key, issue_type_name
        )
        entries[ck] = {"fetched_at_unix": now, "fields": fields}
        _save_createmeta_cache_blob(blob)
        return fields


def _fetch_myself(base_url: str, user: str, password: str) -> dict | None:
    verify = _requests_verify()
    base = base_url.rstrip("/")
    r = requests.get(
        f"{base}/rest/api/2/myself",
        auth=(user, password),
        headers={"Accept": "application/json"},
        timeout=30,
        verify=verify,
    )
    if not r.ok:
        return None
    d = r.json()
    return d if isinstance(d, dict) else None


def _assignee_candidate_from_myself(me: dict) -> dict[str, str] | None:
    aid = me.get("accountId")
    if isinstance(aid, str) and aid.strip():
        return {"accountId": aid.strip()}
    name = me.get("name") or me.get("displayName") or me.get("key")
    if isinstance(name, str) and name.strip():
        return {"name": name.strip()}
    email = me.get("emailAddress")
    if isinstance(email, str) and email.strip():
        return {"emailAddress": email.strip()}
    return None


def _schema_type(meta: dict) -> str:
    sc = meta.get("schema") if isinstance(meta.get("schema"), dict) else {}
    return str(sc.get("type") or "").strip().lower()


def _first_allowed_issue_value(av: object) -> object | None:
    if not isinstance(av, list) or not av:
        return None
    first = av[0]
    if not isinstance(first, dict):
        return first
    if first.get("id") is not None and str(first.get("id")).strip() != "":
        return {"id": str(first.get("id"))}
    nm = first.get("name") or first.get("value")
    if nm is not None and str(nm).strip() != "":
        return {"name": str(nm).strip()}
    return dict(first)


def _default_value_for_createmeta_field(
    field_id: str,
    meta: dict,
    *,
    base_url: str,
    user: str,
    password: str,
    myself_cached: dict | None,
) -> tuple[object | None, dict | None]:
    if not isinstance(meta, dict):
        return None, myself_cached

    dv = meta.get("defaultValue")
    if dv is not None:
        sch = meta.get("schema") if isinstance(meta.get("schema"), dict) else {}
        st = str(sch.get("type") or "").lower()
        if st == "array" and not isinstance(dv, list):
            return [dv] if dv not in ({}, [], None) else None, myself_cached
        if st != "array" or isinstance(dv, list):
            return dv, myself_cached

    av = meta.get("allowedValues")
    fv = _first_allowed_issue_value(av)
    if fv is not None:
        styp = _schema_type(meta)
        if styp == "array":
            items = meta.get("schema") if isinstance(meta.get("schema"), dict) else {}
            it = str((items.get("items") if isinstance(items.get("items"), str) else "") or "").strip()
            if it == "string":
                if isinstance(av, list) and av:
                    x0 = av[0]
                    if isinstance(x0, dict) and isinstance(x0.get("value"), str):
                        return [x0.get("value")], myself_cached
                return ([] if fv == [] else [fv]), myself_cached
        return fv, myself_cached

    styp = _schema_type(meta)

    sys_name = ""
    scm = meta.get("schema") if isinstance(meta.get("schema"), dict) else {}
    if isinstance(scm.get("system"), str):
        sys_name = scm["system"].strip().lower()

    if styp == "user" or field_id.casefold() in ("assignee", "reporter") or sys_name in ("assignee", "reporter"):
        myself_cached = myself_cached or _fetch_myself(base_url, user, password)
        if isinstance(myself_cached, dict):
            pl = _assignee_candidate_from_myself(myself_cached)
            if pl:
                return pl, myself_cached
        return None, myself_cached

    if styp in ("string", "text") or scm.get("type") == "string":
        return " ", myself_cached

    if styp == "number" or scm.get("type") in ("integer", "long", "double"):
        return 0, myself_cached

    if "date" in styp:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d"), myself_cached

    if styp == "datetime":
        try:
            return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        except Exception:
            _LOG.debug("datetime field default microsecond format failed", exc_info=True)
            return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000") + "+0000", myself_cached

    if styp == "array":
        inner = scm.get("items")
        if inner == "string":
            return [], myself_cached
        iv = _first_allowed_issue_value(av)
        if iv is not None:
            return [iv] if not isinstance(iv, list) else iv, myself_cached
        return None, myself_cached

    return None, myself_cached


def _normalize_description_for_jira(fields_out: dict, meta_fields: dict[str, dict]) -> None:
    desc_m = meta_fields.get("description")
    if isinstance(desc_m, dict) and str((desc_m.get("schema") or {}).get("type") or "").lower() == "doc":
        blob = fields_out.pop("description", None)
        if blob is None:
            return
        if isinstance(blob, str):
            stripped = blob.strip()
            if stripped:
                fields_out["description"] = {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": stripped}]},
                ]}


def merge_createmeta_defaults_for_issue_create(
    base_url: str,
    user: str,
    password: str,
    fields_out: dict,
    *,
    meta_fields: dict[str, dict],
    error_prefix: str = "Issue create failed",
) -> None:
    def _field_value_nonempty(v: object) -> bool:
        if v is None or v == "":
            return False
        if isinstance(v, (list, dict)) and len(v) == 0:
            return False
        return True

    myself: dict | None = None
    missing: list[str] = []
    skipped_keys = frozenset({"project", "issuetype"})
    fd_out = dict(fields_out)

    for fid, fm in sorted(meta_fields.items(), key=lambda x: x[0]):
        if not isinstance(fm, dict) or not fm.get("required"):
            continue
        if fid in skipped_keys:
            continue
        if _field_value_nonempty(fd_out.get(fid)):
            continue
        dv, myself = _default_value_for_createmeta_field(
            fid,
            fm,
            base_url=base_url,
            user=user,
            password=password,
            myself_cached=myself,
        )
        if dv is not None:
            fd_out[fid] = dv
        else:
            missing.append(fid)

    if missing:
        show = missing[:24]
        extra = len(missing) - len(show)
        msg = ", ".join(show)
        if extra > 0:
            msg = f"{msg} (+{extra} more)"
        raise ValueError(
            f"{error_prefix}: JIRA marks these fields required but no default exists in metadata: {msg}. "
            "Configure the project's create screen or add mappings."
        )

    fields_out.clear()
    fields_out.update(fd_out)
    _normalize_description_for_jira(fields_out, meta_fields)


def _test_case_description_text(tc: dict) -> str:
    lines: list[str] = []
    steps = tc.get("steps")
    if isinstance(steps, list):
        lines.extend(str(x) for x in steps)
    pre = str(tc.get("preconditions") or "").strip()
    exp = str(tc.get("expected_result") or "").strip()
    if pre or exp:
        if lines:
            lines.append("")
        if pre:
            lines.extend(["Preconditions:", pre, ""])
        if exp:
            lines.extend(["Expected:", exp])
    return "\n".join(lines).strip()


def push_test_case_to_jira(
    base_url: str,
    user: str,
    password: str,
    requirement_key: str,
    test_project_key: str,
    test_case: dict,
    issue_type_override: str | None = None,
    link_type_override: str | None = None,
) -> dict[str, str]:
    verify = _requests_verify()
    base = base_url.rstrip("/")
    auth = (user, password)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    raw_type = (issue_type_override or "").strip() or None
    issue_type = (raw_type or settings.jira_test_issue_type or "Test").strip() or "Test"
    proj = norm_issue_key(test_project_key)
    fld = _issue_fields_summary_desc_priority(base_url, user, password, test_case)
    meta_fields = get_issue_create_meta_fields_cached(
        base_url, user, password, proj, issue_type
    )
    merge_createmeta_defaults_for_issue_create(
        base_url,
        user,
        password,
        fld,
        meta_fields=meta_fields,
        error_prefix="Create test issue",
    )
    apply_test_severity_to_issue_fields(fld, test_case, meta_fields)
    payload = {
        "fields": {
            "project": {"key": proj},
            "issuetype": {"name": issue_type},
            **fld,
        }
    }
    r = requests.post(
        f"{base}/rest/api/2/issue",
        json=payload,
        auth=auth,
        headers=headers,
        timeout=60,
        verify=verify,
    )
    r.raise_for_status()
    created = r.json()
    new_key = created.get("key") or ""
    if not new_key:
        raise ValueError("JIRA did not return an issue key")
    raw_link = (link_type_override or "").strip() or None
    link_type = (raw_link or settings.jira_test_link_type or "Relates").strip() or "Relates"
    req_k = norm_issue_key(requirement_key)
    if settings.jira_link_inward_is_requirement:
        inward_key, outward_key = req_k, new_key
    else:
        inward_key, outward_key = new_key, req_k
    link_payload = {
        "type": {"name": link_type},
        "inwardIssue": {"key": inward_key},
        "outwardIssue": {"key": outward_key},
    }
    r2 = requests.post(
        f"{base}/rest/api/2/issueLink",
        json=link_payload,
        auth=auth,
        headers=headers,
        timeout=60,
        verify=verify,
    )
    r2.raise_for_status()
    self_url = (created.get("self") or "").strip()
    return {"key": new_key, "self": self_url}


def update_test_case_in_jira(
    base_url: str,
    user: str,
    password: str,
    issue_key: str,
    test_case: dict,
) -> dict[str, str]:
    verify = _requests_verify()
    base = base_url.rstrip("/")
    auth = (user, password)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    ik = norm_issue_key(issue_key)
    proj_data = _get_issue_json(base_url, user, password, ik, fields="project,issuetype")
    fproj = proj_data.get("fields") or {}
    pj = norm_issue_key(str((fproj.get("project") or {}).get("key") or ""))
    itn = str((fproj.get("issuetype") or {}).get("name") or "").strip() or (
        settings.jira_test_issue_type or "Test"
    ).strip()
    meta_fields = get_issue_create_meta_fields_cached(base_url, user, password, pj, itn)
    fld = _issue_fields_summary_desc_priority(base_url, user, password, test_case)
    apply_test_severity_to_issue_fields(fld, test_case, meta_fields)
    r = requests.put(
        f"{base}/rest/api/2/issue/{ik}",
        json={"fields": fld},
        auth=auth,
        headers=headers,
        timeout=60,
        verify=verify,
    )
    r.raise_for_status()
    self_url = f"{base}/rest/api/2/issue/{ik}"
    return {"key": ik, "self": self_url}
