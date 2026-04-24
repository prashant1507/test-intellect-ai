# Environment variables (`.env.example`)

Copy `.env.example` to `.env` in the project root. The backend loads it via `backend/settings.py` (Pydantic Settings).
Variable names are case-insensitive for most keys; use the names below to match the example file.

Boolean values accept `true` / `false`, `1` / `0`, `yes` / `no`, `on` / `off` (string forms are coerced where validators
apply).

---

## JIRA

| Variable                          | Default in example          | Description                                                                                                                                                                                                                                                                  |
|-----------------------------------|-----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `JIRA_URL`                        | *(empty)*                   | Base URL of your Jira site (e.g. `https://your-domain.atlassian.net`). Required for live Jira API calls when `MOCK` is false.                                                                                                                                                |
| `JIRA_USERNAME`                   | *(empty)*                   | Jira user email or username for Basic auth.                                                                                                                                                                                                                                  |
| `JIRA_PASSWORD`                   | *(empty)*                   | Jira API token or password (prefer API tokens for Atlassian Cloud).                                                                                                                                                                                                          |
| `JIRA_TEST_PROJECT_KEY`           | *(empty)*                   | Project key where new test issues are created (e.g. `QA`).                                                                                                                                                                                                                   |
| `JIRA_TEST_ISSUE_TYPE`            | `Test`                      | Issue type name for created/linked test issues.                                                                                                                                                                                                                              |
| `JIRA_TEST_LINK_TYPE`             | `Relates`                   | Link type name used when linking tests to the requirement.                                                                                                                                                                                                                   |
| `JIRA_LINK_INWARD_IS_REQUIREMENT` | `true`                      | Directional semantics for issue links: treat the inward side as the requirement when resolving links.                                                                                                                                                                        |
| `JIRA_VERIFY_SSL`                 | `false`                     | If `true`, verify TLS certificates for Jira HTTPS requests. Set `false` only for dev/self-signed.                                                                                                                                                                            |
| `JIRA_LINKED_WORK_ISSUE_TYPES`    | `Story,Improvement,Feature` | Comma-separated issue type names. Linked issues of these types (plus the requirement’s own type) are listed under **Linked Issues** in the Requirements section. Issues of `JIRA_TEST_ISSUE_TYPE` appear under linked tests, not here. Not passed to the LLM for generation. |

---

## Application behavior

| Variable             | Default in example | Description                                                                                                          |
|----------------------|--------------------|----------------------------------------------------------------------------------------------------------------------|
| `MOCK`               | `false`            | If `true`, skips real Jira calls (fixture data), does not write audit logs, and does not persist memory on generate. |
| `SHOW_MEMORY_UI`     | `true`             | Exposed via `GET /config` so the frontend can show or hide the History / memory sidebar.                             |
| `SHOW_AUDIT_UI`      | `true`             | Exposed via `GET /config` so the frontend can show or hide the audit log UI.                                         |
| `SHOW_AUTOMATION_UI` | `true`             | Exposed via `GET /config` so the frontend can show or hide the automation spike / BDD + Playwright UI.               |

---

## Automation (BDD + Playwright, `/api/automation/*`)

The LLM is used to map BDD steps to selectors when the selector cache has no entry.

Browser, headless mode, screenshots-on-pass, and trace file generation are **not** set in `.env`. First-run defaults
(Chrome, headless off, screenshots off, trace off) are applied by the app; the **Environment** panel persists changes to
the database via `GET/POST /api/automation/*`.

| Variable                        | Default in example | Description                                                                                                                                                                      |
|---------------------------------|--------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `AUTOMATION_POST_ANALYSIS`      | `true`             | Run post-run analysis (LLM) on automation results when enabled.                                                                                                                  |
| `AUTOMATION_WRITE_RUN_HTML`     | `true`             | Write per-run HTML reports under the reports directory.                                                                                                                          |
| `AUTOMATION_DEFAULT_TIMEOUT_MS` | `30000`            | Default Playwright timeout in ms (clamped in settings, typically 1000–600000).                                                                                                   |
| `AUTOMATION_RETENTION_DAYS`     | `20`               | On startup, prune data older than this many days: run DB rows, per-run artifacts, HTML reports, suite run history. `0` disables pruning.                                         |
| `AUTOMATION_SPIKE_PRERUN`       | `false`            | If `true`, after the LLM builds a selector plan (non-cached path), run a Playwright locator pre-check and optional repair before step execution. If `false`, skip the pre-check. |

**Not in `.env.example` (defaults in `settings.py`):** `AUTOMATION_DB_PATH`, `AUTOMATION_ARTIFACTS_DIR`,
`AUTOMATION_REPORTS_DIR` — paths for the selector store, run artifacts, and HTML reports.

---

## Keycloak (OIDC)

| Variable                        | Default in example | Description                                                                                                                                                                          |
|---------------------------------|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `USE_KEYCLOAK`                  | `false`            | Enable Keycloak/OpenID Connect authentication for the API.                                                                                                                           |
| `KEYCLOAK_URL`                  | *(empty)*          | Public Keycloak base URL (browser redirects, issuer).                                                                                                                                |
| `KEYCLOAK_REALM`                | *(empty)*          | Realm name.                                                                                                                                                                          |
| `KEYCLOAK_CLIENT_ID`            | *(empty)*          | OIDC client id.                                                                                                                                                                      |
| `KEYCLOAK_CLIENT_SECRET`        | *(empty)*          | Client secret (if required by the client type).                                                                                                                                      |
| `KEYCLOAK_IDLE_TIMEOUT_MINUTES` | `60`               | Session idle timeout used by the app configuration (minutes).                                                                                                                        |
| `KEYCLOAK_INTERNAL_URL`         | *(empty)*          | Optional base URL for server-side JWKS/token validation when it differs from `KEYCLOAK_URL` (e.g. Docker network hostname). Leave empty for local dev when JWKS uses `KEYCLOAK_URL`. |

---

## LLM (OpenAI-compatible)

| Variable                              | Default in example         | Description                                                                                                                                                                                                                                                                 |
|---------------------------------------|----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `LLM_URL`                             | `http://127.0.0.1:1234/v1` | Base URL for OpenAI-compatible chat completions (must include `/v1` if your server expects it). Local LM Studio / similar, or cloud API base.                                                                                                                               |
| `LLM_MODEL`                           | `qwen/qwen3-vl-30b`        | Model id passed to the provider (vision-capable if using requirement images).                                                                                                                                                                                               |
| `LLM_ACCESS_TOKEN`                    | *(empty)*                  | Bearer token for cloud APIs. Leave empty for local servers with no auth.                                                                                                                                                                                                    |
| `LLM_REQUIREMENT_IMAGES_ENABLED`      | `false`                    | When `true`, the UI can attach PNG/JPEG/GIF/WebP images and PDF mockups (uploads and selected JIRA ticket attachments). Images are sent as vision inputs; PDFs are sent as chat `file` parts (OpenAI-style). Requires a model/server that supports those modalities.        |
| `LLM_REQUIREMENT_IMAGES_MAX_COUNT`    | `5`                        | Maximum number of files combined (uploaded files + selected ticket attachments) per generate request.                                                                                                                                                                       |
| `LLM_REQUIREMENT_IMAGES_MAX_TOTAL_MB` | `200`                      | Maximum combined size of all attachments in MB (binary megabytes, 1024² bytes per MB).                                                                                                                                                                                      |
| `DOCKER_LLM_URL`                      | *(empty)*                  | **Not read by the backend.** Reserved for Docker/Compose or deployment docs: set the URL the **container** should use to reach the host LLM (e.g. `http://host.docker.internal:1234/v1`). The sample `docker-compose.yml` sets `LLM_URL` directly in `environment` instead. |

---

## Memory and priorities

| Variable                      | Default in example                     | Description                                                                                                                                              |
|-------------------------------|----------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `MEMORY_SIMILARITY_THRESHOLD` | `0.92`                                 | When the exact memory key is missing, match saved entries by similar title+description. `0` disables fuzzy matching; typical range about `0.88`–`0.95`.  |
| `PASTE_MODE_PRIORITIES`       | `'Highest, High, Medium, Low, Lowest'` | Comma-separated priority labels for paste mode and as fallback when Jira priority names are not fetched. Maps to settings field `paste_mode_priorities`. |

---

## Backend mapping (reference)

| `.env` name                           | `settings` attribute                  |
|---------------------------------------|---------------------------------------|
| `JIRA_*`                              | `jira_*`                              |
| `MOCK`                                | `mock`                                |
| `SHOW_MEMORY_UI`                      | `show_memory_ui`                      |
| `SHOW_AUDIT_UI`                       | `show_audit_ui`                       |
| `SHOW_AUTOMATION_UI`                  | `show_automation_ui`                  |
| `AUTOMATION_POST_ANALYSIS`            | `automation_post_analysis`            |
| `AUTOMATION_WRITE_RUN_HTML`           | `automation_write_run_html`           |
| `AUTOMATION_DEFAULT_TIMEOUT_MS`       | `automation_default_timeout_ms`       |
| `AUTOMATION_RETENTION_DAYS`           | `automation_retention_days`           |
| `AUTOMATION_SPIKE_PRERUN`             | `automation_spike_prerun`             |
| `USE_KEYCLOAK`                        | `use_keycloak`                        |
| `KEYCLOAK_*`                          | `keycloak_*`                          |
| `LLM_URL`                             | `llm_url`                             |
| `LLM_MODEL`                           | `llm_model`                           |
| `LLM_ACCESS_TOKEN`                    | `llm_access_token`                    |
| `LLM_REQUIREMENT_IMAGES_ENABLED`      | `llm_requirement_images_enabled`      |
| `LLM_REQUIREMENT_IMAGES_MAX_COUNT`    | `llm_requirement_images_max_count`    |
| `LLM_REQUIREMENT_IMAGES_MAX_TOTAL_MB` | `llm_requirement_images_max_total_mb` |
| `MEMORY_SIMILARITY_THRESHOLD`         | `memory_similarity_threshold`         |
| `PASTE_MODE_PRIORITIES`               | `paste_mode_priorities`               |

`DOCKER_LLM_URL` has no entry in `settings.py`; it is documentation-only unless your compose or scripts substitute it
into `LLM_URL`.

---

## Docker Compose (`docker-compose.yml`)

The sample service does **not** load the project `.env` file; it sets `environment` inline. Defaults align with
`.env.example` for `JIRA_*` (including `JIRA_LINKED_WORK_ISSUE_TYPES`), `LLM_REQUIREMENT_IMAGES_*`,
`MEMORY_SIMILARITY_THRESHOLD`, and `PASTE_MODE_PRIORITIES`. `LLM_URL` is `http://host.docker.internal:1234/v1` so the
container can reach an LLM on the host; `LLM_MODEL` matches `.env.example`. `USE_KEYCLOAK`, `KEYCLOAK_URL`,
`KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, and `KEYCLOAK_INTERNAL_URL` are set for Keycloak-in-Docker testing and differ
from `.env.example` (which uses `USE_KEYCLOAK=false` for local API-only runs).

`SHOW_AUTOMATION_UI` and the `AUTOMATION_*` keys are **not** set in the sample `docker-compose.yml`; the image uses
Pydantic defaults from `settings.py` for those.
