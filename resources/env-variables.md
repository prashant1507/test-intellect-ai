# Environment variables (aligns with `.env.example`)

Copy `.env.example` to `.env` in the **repository root** (one file for backend and UI defaults from `GET /api/config`).

**Loading:** `backend/settings.py` (Pydantic BaseSettings) reads the root `.env`. Unknown variable names are ignored.
Env keys use UPPER_SNAKE; in code they map to the same names in `lower_snake` (e.g. `SHOW_MEMORY_UI` →
`show_memory_ui`).

**Booleans:** `true` / `false`, `1` / `0`, `yes` / `no`, `on` / `off` (where validated).

**Order and example values** below follow `.env.example` exactly. Anything configurable only in `settings.py` (and not
in `.env.example`) is not listed—see `backend/settings.py` (e.g. default automation DB paths, timeout fallback).

---

## UI Settings

| Variable                          | Example | Description                                                                       |
|-----------------------------------|---------|-----------------------------------------------------------------------------------|
| `SHOW_MEMORY_UI`                  | `true`  | Exposed via `GET /api/config`: show or hide **History** (saved memory) UI.        |
| `SHOW_AUDIT_UI`                   | `true`  | Exposed via `GET /api/config`: show or hide **Audit** UI.                         |
| `SHOW_JIRA_MODE_UI`               | `true`  | Exposed via `GET /api/config`: show or hide the **JIRA** requirement mode tab.    |
| `SHOW_PASTE_REQUIREMENTS_MODE_UI` | `true`  | Exposed via `GET /api/config`: show or hide **Paste Requirements** mode.          |
| `SHOW_AUTO_TESTS_UI`              | `true`  | Exposed via `GET /api/config`: show or hide **Auto Tests** (BDD/Playwright) mode. |

If all three of `SHOW_JIRA_MODE_UI`, `SHOW_PASTE_REQUIREMENTS_MODE_UI`, and `SHOW_AUTO_TESTS_UI` are off, the server
sets `SHOW_JIRA_MODE_UI` back to `true` so at least one mode stays available.

---

## JIRA Settings

| Variable                          | Example                     | Description                                                                   |
|-----------------------------------|-----------------------------|-------------------------------------------------------------------------------|
| `JIRA_URL`                        | *(empty)*                   | Jira site base URL (e.g. `https://your-domain.atlassian.net`).                |
| `JIRA_USERNAME`                   | *(empty)*                   | Jira user (often email) for API auth.                                         |
| `JIRA_PASSWORD`                   | *(empty)*                   | API token or password (Atlassian Cloud: prefer API token).                    |
| `JIRA_TEST_PROJECT_KEY`           | *(empty)*                   | Project key for creating test issues (e.g. `QA`).                             |
| `JIRA_TEST_ISSUE_TYPE`            | `Test`                      | Issue type name for test issues.                                              |
| `JIRA_TEST_LINK_TYPE`             | `Relates`                   | Link type name when linking tests to the requirement.                         |
| `JIRA_LINK_INWARD_IS_REQUIREMENT` | `true`                      | Whether the inward end of the link is treated as the requirement.             |
| `JIRA_VERIFY_SSL`                 | `false`                     | If `true`, verify TLS for Jira HTTPS. Use `false` only for self-signed / dev. |
| `JIRA_LINKED_WORK_ISSUE_TYPES`    | `Story,Improvement,Feature` | Comma-separated types for **Linked work**-style lists in the UI.              |

---

## Mock Mode

| Variable | Example | Description                                                                                |
|----------|---------|--------------------------------------------------------------------------------------------|
| `MOCK`   | `false` | `true`: no real Jira HTTP; fixture text; no audit on generate; no memory save on generate. |

---

## Auto Tests Settings

| Variable                    | Example | Description                                                                                         |
|-----------------------------|---------|-----------------------------------------------------------------------------------------------------|
| `AUTOMATION_POST_ANALYSIS`  | `true`  | If `true`, run post-run LLM analysis on automation results.                                         |
| `AUTOMATION_WRITE_RUN_HTML` | `true`  | Write per-run HTML reports under the reports directory.                                             |
| `AUTOMATION_RETENTION_DAYS` | `20`    | Prune data older than this many days (runs, artifacts, reports, history). `0` disables.             |
| `AUTOMATION_SPIKE_PRERUN`   | `false` | If `true`, run Playwright locator pre-check (and optional repair) after a non-cached selector plan. |

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

## LLM Settings (OpenAI-compatible)

| Variable           | Example                    | Description                                                                                                                   |
|--------------------|----------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| `LLM_URL`          | `http://127.0.0.1:1234/v1` | OpenAI-compatible API base; must include `/v1` if your server expects that path.                                              |
| `LLM_MODEL`        | `qwen/qwen3-vl-30b`        | Model id. Use a **vision** model if you enable requirement images.                                                            |
| `LLM_ACCESS_TOKEN` | *(empty)*                  | Bearer token for cloud APIs; leave empty for local servers without auth.                                                      |
| `DOCKER_LLM_URL`   | *(empty)*                  | **Not read by the backend** (`settings` ignores it). For compose/docs: value you might map into `LLM_URL` inside a container. |

---

## Requirement mockups / screenshots (LLM)

| Variable                              | Example | Description                                                                                |
|---------------------------------------|---------|--------------------------------------------------------------------------------------------|
| `LLM_REQUIREMENT_IMAGES_ENABLED`      | `false` | Enable sending image attachments to the model (OpenAI-style vision: PNG, JPEG, GIF, WebP). |
| `LLM_REQUIREMENT_IMAGES_MAX_COUNT`    | `5`     | Max number of image files per request.                                                     |
| `LLM_REQUIREMENT_IMAGES_MAX_TOTAL_MB` | `300`   | Max combined size of those images in MB.                                                   |

---

## Memory

| Variable                      | Example | Description                                                                                               |
|-------------------------------|---------|-----------------------------------------------------------------------------------------------------------|
| `MEMORY_SIMILARITY_THRESHOLD` | `0.92`  | If no exact memory key, match saved rows by similar title+description. `0` = off; try e.g. `0.88`–`0.95`. |

---

## Priorities

| Variable                | Example                                | Description                                                                                |
|-------------------------|----------------------------------------|--------------------------------------------------------------------------------------------|
| `PASTE_MODE_PRIORITIES` | `'Highest, High, Medium, Low, Lowest'` | Comma-separated priority labels for **paste** mode (and fallbacks as implemented in code). |
