# Environment variables (aligns with `.env.example`)

Copy `.env.example` to `.env` in the **repository root** (one file for backend and UI defaults from `GET /api/config`).

**Loading:** `backend/settings.py` (Pydantic BaseSettings) reads the root `.env`. Unknown variable names are ignored.
Env keys use UPPER_SNAKE; in code they map to the same names in `lower_snake` (e.g. `SHOW_MEMORY_UI` →
`show_memory_ui`).

**Booleans:** `true` / `false`, `1` / `0`, `yes` / `no`, `on` / `off` (where validated).

**Order and example values** below follow `.env.example` closely. Anything configurable only in `settings.py` (and not
in `.env.example`) is not listed—see `backend/settings.py` (e.g. default automation DB paths, timeout fallback). Some
variables accept **legacy aliases** (see LLM table).

---

## UI Settings

| Variable                          | Example | Description                                                                       |
|-----------------------------------|---------|-----------------------------------------------------------------------------------|
| `SHOW_MEMORY_UI`                  | `true`  | Exposed via `GET /api/config`: show or hide **History** (saved memory) UI.        |
| `SHOW_AUDIT_UI`                   | `true`  | Exposed via `GET /api/config`: show or hide **Audit** UI.                         |
| `SHOW_JIRA_MODE_UI`               | `true`  | Exposed via `GET /api/config`: show or hide the **JIRA** requirement mode tab.    |
| `SHOW_PASTE_REQUIREMENTS_MODE_UI` | `true`  | Exposed via `GET /api/config`: show or hide **Paste Requirements** mode.          |
| `SHOW_AUTO_TESTS_UI`              | `true`  | Exposed via `GET /api/config`: show or hide **Auto Tests** (BDD/Playwright) mode. |

If all three of `SHOW_JIRA_MODE_UI`, `SHOW_PASTE_REQUIREMENTS_MODE_UI`, and `SHOW_AUTO_TESTS_UI` are off, the server sets `SHOW_JIRA_MODE_UI` back to `true` so at least one mode stays available.

---

## JIRA Settings

| Variable                              | Example                     | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
|---------------------------------------|-----------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `JIRA_URL`                            | *(empty)*                   | Jira site base URL (e.g. `https://your-domain.atlassian.net`).                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `JIRA_USERNAME`                       | *(empty)*                   | Jira user (often email) for API auth.                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `JIRA_PASSWORD`                       | *(empty)*                   | API token or password (Atlassian Cloud: prefer API token). If set, JIRA calls work with an empty UI password; the secret is never exposed via `/api/config`.                                                                                                                                                                                                                                                                                                                    |
| `JIRA_TEST_PROJECT_KEY`               | *(empty)*                   | Project key for creating test issues (e.g. `QA`).                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `JIRA_TEST_ISSUE_CREATION_TYPE`       | `Test`                      | Exact issue **type name** for issues **created** as test cases in the test project (must exist in that project). **Server-side only** (no UI field). Still exposed as `default_jira_test_issue_creation_type` on `GET /api/config` for the linked-tests panel heading.                                                                                                                                                                                                          |
| `JIRA_ISSUE_RELATION_TYPE`            | `Test`                      | Exact Jira **issue link type name** (from Project settings → Issue linking) used in `POST /rest/api/2/issueLink` when linking a **new** test issue to the requirement. **Server-side only** (no UI field); must exist on your Jira instance. Restart the API after changes.                                                                                                                                                                                                     |
| `JIRA_LINK_INWARD_IS_REQUIREMENT`     | `true`                      | Guides `POST /rest/api/2/issueLink`: when `true`, `inwardIssue` is the requirement key and `outwardIssue` is the new test issue; when `false`, the mapping is swapped. Matches Atlassian’s usual model where the outward end shows the outward phrase (e.g. “tests”) on the tester issue—see Atlassian issue linking docs. Effective value exposed on `GET /api/config`.                                                                                                        |
| `JIRA_ISSUE_LINK_SWAP_INWARD_OUTWARD` | `false`                     | After applying `JIRA_LINK_INWARD_IS_REQUIREMENT`, if `true` **swap** the two keys once more before issuing the issue link POST. Try `true` on some Jira Cloud projects if **with** inward=requirement Cloud still renders the wrong direction on one side (e.g. the Test issue shows inward phrasing toward the requirement). Restart the API after changing it; existing wrong links stay wrong until removed in Jira and recreated by pushing. Exposed via `GET /api/config`. |
| `JIRA_VERIFY_SSL`                     | `false`                     | If `true`, verify TLS for Jira HTTPS. Use `false` only for self-signed / dev.                                                                                                                                                                                                                                                                                                                                                                                                   |
| `JIRA_LINKED_WORK_ISSUE_TYPES`        | `Story,Improvement,Feature` | Comma-separated types for **Linked work**-style lists in the UI.                                                                                                                                                                                                                                                                                                                                                                                                                |
| `JIRA_CREATEMETA_TEST_TTL_SECONDS`    | `3600`                      | TTL in seconds for cached JIRA **createmeta** used when pushing **test** issues (`data/jira_createmeta_cache.json`). `0` disables disk cache (always queries JIRA). Updated when TTL expires combined with relevant JIRA interactions; not during **Fetch Requirements** alone.                                                                                                                                                                                                 |
| `JIRA_TEST_SEVERITY_FIELD_ID`         | *(empty)*                   | Optional custom field id for **Severity** when create metadata does not expose a field named `Severity`.                                                                                                                                                                                                                                                                                                                                                                        |

---

## Mock Mode

| Variable | Example | Description                                                                                |
|----------|---------|--------------------------------------------------------------------------------------------|
| `MOCK`   | `false` | `true`: no real Jira HTTP; fixture text; no audit on generate; no memory save on generate. |

---

## Auto Tests Settings

| Variable                        | Example  | Description                                                                                                                                                                                                                                                                               |
|---------------------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `AUTOMATION_POST_ANALYSIS`      | `true`   | If `true`, run post-run LLM analysis on automation results.                                                                                                                                                                                                                               |
| `AUTOMATION_WRITE_RUN_HTML`     | `true`   | Write per-run HTML reports under the reports directory.                                                                                                                                                                                                                                   |
| `AUTOMATION_RETENTION_DAYS`     | `20`     | Prune data older than this many days (runs, artifacts, reports, history). `0` disables.                                                                                                                                                                                                   |
| `AUTOMATION_PARALLEL_EXECUTION` | `1`      | Saved-suite **Run all**: max parallel workers **1–5** (hard cap **5**; higher values clamp). Sets how many **Parallel Execution** radios appear in Auto Tests env options (`GET/POST /api/automation/env*`). The chosen value is also stored in the automation DB (`parallel_execution`). |
| `AUTOMATION_HEADLESS`           | *(omit)* | If **set** (`true` / `false`), forces Playwright headless and locks the “Headless” control in the Auto Tests env panel. **Docker:** set `true` (no display in the container). **Local dev:** **omit** to use the in-app on/off value (stored in the automation database).                 |

---

## Keycloak Settings

| Variable                        | Example   | Description                                                                                                                |
|---------------------------------|-----------|----------------------------------------------------------------------------------------------------------------------------|
| `USE_KEYCLOAK`                  | `false`   | Enable Keycloak / OIDC for the app.                                                                                        |
| `KEYCLOAK_URL`                  | *(empty)* | Public Keycloak base URL.                                                                                                  |
| `KEYCLOAK_REALM`                | *(empty)* | Realm.                                                                                                                     |
| `KEYCLOAK_CLIENT_ID`            | *(empty)* | OIDC client id.                                                                                                            |
| `KEYCLOAK_CLIENT_SECRET`        | *(empty)* | Client secret (if the client type requires it).                                                                            |
| `KEYCLOAK_IDLE_TIMEOUT_MINUTES` | `60`      | Idle timeout (minutes) exposed to the UI.                                                                                  |
| `KEYCLOAK_INTERNAL_URL`         | *(empty)* | For token/JWKS from the server when it differs from `KEYCLOAK_URL` (e.g. Docker). Empty uses `KEYCLOAK_URL` for local API. |

---

## Text LLM (OpenAI-compatible)

Used for BDD generation, batch scoring, agentic graph (when not using a separate vision call), Playwright automation
planning, and other text endpoints.

| Variable                | Example                    | Description                                                                                                                                     |
|-------------------------|----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| `LLM_TEXT_URL`          | `http://127.0.0.1:1234/v1` | OpenAI-compatible API base; include `/v1` if the server uses that path. **Required** when `MOCK=false` (see validation in `settings.py`).       |
| `LLM_TEXT_MODEL`        | `qwen/qwen3-coder-next`    | Model id for text. **Required** when `MOCK=false`.                                                                                              |
| `LLM_TEXT_ACCESS_TOKEN` | *(empty)*                  | Bearer for the text API; leave empty for local servers.                                                                                         |
| *Aliases (same fields)* |                            | `LLM_URL` → `LLM_TEXT_URL`, `LLM_MODEL` → `LLM_TEXT_MODEL`, `LLM_ACCESS_TOKEN` → `LLM_TEXT_ACCESS_TOKEN` (Pydantic `AliasChoices` in settings). |

Non-secret hint: `GET /api/config` does not expose LLM URLs, models, or tokens.

---

## Agentic test generation

Read by **`backend/agentic/graph.py`** (not `settings.py`). Controls automatic extra **generate** attempts when
agentic validation has not passed after the UI **max rounds** limit.

| Variable                                     | Example | Description                                                                                                                                                                                                                                                                     |
|----------------------------------------------|---------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `AGENTIC_AUTO_EXTEND_PHASES`                 | `1`     | How many times the run may **auto-extend** after the UI **max rounds** cap is hit while validation still fails. **`0`** = off; then the two vars below are unused.                                                                                                              |
| `AGENTIC_AUTO_EXTEND_ADDITIONAL_GENERATIONS` | `3`     | **Per extension:** extra **full generator attempts** allowed (each = `generate` → `parse` → `score` when applicable). The effective round cap increases by this amount. Not “tokens” or inner-LLM steps. Clamped in code (1–8). **Legacy alias:** `AGENTIC_AUTO_EXTEND_ROUNDS`. |
| `AGENTIC_ROUND_CAP_CEILING`                  | `10`    | Hard cap on **effective** generator attempts in one HTTP request: `min(UI max_rounds + total extension bump, ceiling)` (clamped in code, max 24).                                                                                                                               |

# effective_max = min(max_rounds_from_ui + AGENTIC_AUTO_EXTEND_PHASES × AGENTIC_AUTO_EXTEND_ADDITIONAL_GENERATIONS, AGENTIC_ROUND_CAP_CEILING)
---

## Vision LLM (optional, OpenAI-compatible)

When **`LLM_VISION_URL` is set** (non-empty), the app treats a vision endpoint as available: multimodal **image/PDF**
requests
for test generation and the agentic pipeline use this URL and model, with **`LLM_VISION_ACCESS_TOKEN`** as Bearer (or
the
text token if the vision token is empty). The UI shows mockup upload and JIRA attachment **selection** when
`LLM_VISION_URL` is configured (`GET /api/config` includes `llm_vision_configured: true`).

If **both** `LLM_VISION_URL` and `LLM_VISION_MODEL` are empty, the deployment is text-only: JIRA **still fetches**
ticket
attachments for display, but the user cannot select them for the LLM and cannot upload mockups for generation.

| Variable                  | Example   | Description                                                                                 |
|---------------------------|-----------|---------------------------------------------------------------------------------------------|
| `LLM_VISION_URL`          | *(empty)* | OpenAI-compatible base for vision/multimodal calls. If set, `LLM_VISION_MODEL` must be set. |
| `LLM_VISION_MODEL`        | *(empty)* | Vision model id. If set, `LLM_VISION_URL` must be set.                                      |
| `LLM_VISION_ACCESS_TOKEN` | *(empty)* | Bearer for the vision API; if empty, `LLM_TEXT_ACCESS_TOKEN` is used.                       |

---

## Requirement mockups / screenshots (LLM)

Uploads and JIRA attachment selection for generation require **`LLM_VISION_URL`** (and `LLM_VISION_MODEL`). Limits below
apply whenever vision is configured.

| Variable                              | Example | Description                                                            |
|---------------------------------------|---------|------------------------------------------------------------------------|
| `LLM_REQUIREMENT_IMAGES_MAX_COUNT`    | `10`    | Max number of files (uploads + selected JIRA attachments) per request. |
| `LLM_REQUIREMENT_IMAGES_MAX_TOTAL_MB` | `200`   | Max combined size of those files in MB.                                |

**UI:** The paste/JIRA **upload** row and JIRA **checkboxes** for the LLM are shown when `llm_vision_configured` is
true. JIRA can still list attachments without vision; they are not selectable for generation until vision is configured.

**Backend:** If `LLM_VISION_URL` is unset, generate routes merge **no** image bytes for the LLM.

---

## Memory

| Variable                      | Example | Description                                                                                               |
|-------------------------------|---------|-----------------------------------------------------------------------------------------------------------|
| `MEMORY_SIMILARITY_THRESHOLD` | `0.92`  | If no exact memory key, match saved rows by similar title+description. `0` = off; try e.g. `0.88`–`0.95`. |

---

## Priorities

| Variable                | Example                                      | Description                                                                                   |
|-------------------------|----------------------------------------------|-----------------------------------------------------------------------------------------------|
| `PASTE_MODE_PRIORITIES` | `'Highest, High, Medium, Low, Lowest'`       | Comma-separated priority labels for **paste** mode (and fallbacks as implemented in code).    |
| `PASTE_MODE_SEVERITIES` | `'Blocker, Critical, Major, Minor, Trivial'` | Comma-separated severity labels for **paste** mode and semantic mapping to JIRA **Severity**. |
