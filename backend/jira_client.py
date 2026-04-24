from __future__ import annotations

import html as html_module
import json
import re

import requests
import urllib3

from key_norm import norm_issue_key
from settings import settings


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
    out: list[dict] = []
    for ik in keys:
        try:
            data = _get_issue_json(
                base_url,
                user,
                password,
                ik,
                fields="summary,description,issuetype,status,priority,renderedFields",
                expand="renderedFields",
            )
        except Exception:
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
        tc = {
            "description": summary[:10000],
            "preconditions": "",
            "steps": steps,
            "expected_result": "",
        }
        out.append(
            {
                "issue_key": key,
                "summary": summary,
                "status_name": status_name,
                "browse_url": browse,
                "jira_priority_name": jira_priority_name,
                "jira_priority_icon_url": jira_priority_icon_url,
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
        pass
    return fields


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
    payload: dict = {"fields": _issue_fields_summary_desc_priority(base_url, user, password, test_case)}
    r = requests.put(
        f"{base}/rest/api/2/issue/{ik}",
        json=payload,
        auth=auth,
        headers=headers,
        timeout=60,
        verify=verify,
    )
    r.raise_for_status()
    self_url = f"{base}/rest/api/2/issue/{ik}"
    return {"key": ik, "self": self_url}
