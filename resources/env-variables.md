# Environment variables (`.env.example`)

Copy `.env.example` to `.env` in the project root. The backend loads it via `backend/settings.py` (Pydantic Settings). Variable names are case-insensitive for most keys; use the names below to match the example file.

Boolean values accept `true` / `false`, `1` / `0`, `yes` / `no`, `on` / `off` (string forms are coerced where validators apply).

---

## JIRA

| Variable | Default in example | Description |
|----------|-------------------|-------------|
| `JIRA_URL` | *(empty)* | Base URL of your Jira site (e.g. `https://your-domain.atlassian.net`). Required for live Jira API calls when `MOCK` is false. |
| `JIRA_USERNAME` | *(empty)* | Jira user email or username for Basic auth. |
| `JIRA_PASSWORD` | *(empty)* | Jira API token or password (prefer API tokens for Atlassian Cloud). |
| `JIRA_TEST_PROJECT_KEY` | *(empty)* | Project key where new test issues are created (e.g. `QA`). |
| `JIRA_TEST_ISSUE_TYPE` | `Test` | Issue type name for created/linked test issues. |
| `JIRA_TEST_LINK_TYPE` | `Relates` | Link type name used when linking tests to the requirement. |
| `JIRA_LINK_INWARD_IS_REQUIREMENT` | `true` | Directional semantics for issue links: treat the inward side as the requirement when resolving links. |
| `JIRA_VERIFY_SSL` | `false` | If `true`, verify TLS certificates for Jira HTTPS requests. Set `false` only for dev/self-signed. |
| `JIRA_LINKED_WORK_ISSUE_TYPES` | `Story,Improvement,Feature` | Comma-separated issue type names. Linked issues of these types (plus the requirement’s own type) are listed under **Linked Issues** in the Requirements section. Issues of `JIRA_TEST_ISSUE_TYPE` appear under linked tests, not here. Not passed to the LLM for generation. |

---

## Application behavior

| Variable | Default in example | Description |
|----------|-------------------|-------------|
| `MOCK` | `false` | If `true`, skips real Jira calls (fixture data), does not write audit logs, and does not persist memory on generate. |
| `SHOW_MEMORY_UI` | `true` | Exposed via `GET /config` so the frontend can show or hide the History / memory sidebar. |
| `SHOW_AUDIT_UI` | `true` | Exposed via `GET /config` so the frontend can show or hide the audit log UI. |

---

## Keycloak (OIDC)

| Variable | Default in example | Description |
|----------|-------------------|-------------|
| `USE_KEYCLOAK` | `false` | Enable Keycloak/OpenID Connect authentication for the API. |
| `KEYCLOAK_URL` | *(empty)* | Public Keycloak base URL (browser redirects, issuer). |
| `KEYCLOAK_REALM` | *(empty)* | Realm name. |
| `KEYCLOAK_CLIENT_ID` | *(empty)* | OIDC client id. |
| `KEYCLOAK_CLIENT_SECRET` | *(empty)* | Client secret (if required by the client type). |
| `KEYCLOAK_IDLE_TIMEOUT_MINUTES` | `60` | Session idle timeout used by the app configuration (minutes). |
| `KEYCLOAK_INTERNAL_URL` | *(empty)* | Optional base URL for server-side JWKS/token validation when it differs from `KEYCLOAK_URL` (e.g. Docker network hostname). Leave empty for local dev when JWKS uses `KEYCLOAK_URL`. |

---

## LLM (OpenAI-compatible)

| Variable | Default in example | Description |
|----------|-------------------|-------------|
| `LLM_URL` | `http://127.0.0.1:1234/v1` | Base URL for OpenAI-compatible chat completions (must include `/v1` if your server expects it). Local LM Studio / similar, or cloud API base. |
| `LLM_MODEL` | `qwen/qwen3-coder-30b` | Model id passed to the provider. |
| `LLM_ACCESS_TOKEN` | *(empty)* | Bearer token for cloud APIs. Leave empty for local servers with no auth. |
| `DOCKER_LLM_URL` | *(empty)* | **Not read by the backend.** Reserved for Docker/Compose or deployment docs: set the URL the **container** should use to reach the host LLM (e.g. `http://host.docker.internal:1234/v1`). The sample `docker-compose.yml` sets `LLM_URL` directly in `environment` instead. |

---

## Memory and priorities

| Variable | Default in example | Description |
|----------|-------------------|-------------|
| `MEMORY_SIMILARITY_THRESHOLD` | `0.92` | When the exact memory key is missing, match saved entries by similar title+description. `0` disables fuzzy matching; typical range about `0.88`–`0.95`. |
| `PASTE_MODE_PRIORITIES` | `'Highest, High, Medium, Low, Lowest'` | Comma-separated priority labels for paste mode and as fallback when Jira priority names are not fetched. Maps to settings field `paste_mode_priorities`. |

---

## Backend mapping (reference)

| `.env` name | `settings` attribute |
|-------------|----------------------|
| `JIRA_*` | `jira_*` |
| `MOCK` | `mock` |
| `SHOW_MEMORY_UI` | `show_memory_ui` |
| `SHOW_AUDIT_UI` | `show_audit_ui` |
| `USE_KEYCLOAK` | `use_keycloak` |
| `KEYCLOAK_*` | `keycloak_*` |
| `LLM_URL` | `llm_url` |
| `LLM_MODEL` | `llm_model` |
| `LLM_ACCESS_TOKEN` | `llm_access_token` |
| `MEMORY_SIMILARITY_THRESHOLD` | `memory_similarity_threshold` |
| `PASTE_MODE_PRIORITIES` | `paste_mode_priorities` |

`DOCKER_LLM_URL` has no entry in `settings.py`; it is documentation-only unless your compose or scripts substitute it into `LLM_URL`.
