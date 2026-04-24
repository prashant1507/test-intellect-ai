# Test Intellect AI

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org/) [![Jira](https://img.shields.io/badge/Jira-REST%20API-0052CC?style=flat-square&logo=jira&logoColor=white)](https://www.atlassian.com/software/jira)
[![LLM](https://img.shields.io/badge/LLM-OpenAI%20compatible-8B5CF6?style=flat-square&logo=openai&logoColor=white)](https://platform.openai.com/docs/api-reference)
[![Keycloak](https://img.shields.io/badge/Keycloak-OIDC-5C6BC0?style=flat-square&logo=keycloak&logoColor=white)](https://www.keycloak.org/)

Web app that pull JIRA requirements (or paste text), use an OpenAI-compatible LLM or VLM (local or cloud) to generate
Gherkin-style test cases, push to JIRA, and run BDD in a browser (Playwright).
Set the model via `LLM_URL` (must include /v1) and optionally `LLM_ACCESS_TOKEN` for Bearer auth.

Optionally:

- Save runs per ticket in SQLite
- Track actions in an audit log
- Use Keycloak to associate users with activity

---

### Product Sample Video

[Check out the video on YouTube](https://www.youtube.com/watch?v=u5MYzPwuOGI)
<p align="center">
  <a href="https://youtu.be/u5MYzPwuOGI">
    <img src="https://img.youtube.com/vi/u5MYzPwuOGI/hqdefault.jpg" width="600" alt="Watch product sample video on YouTube" />
  </a>
</p>

---

### Product Sample Images

<img src="resources/product-images/img-1.png" alt="UI" width="200" /> <img src="resources/product-images/img-2.png" alt="UI" width="200" /> <img src="resources/product-images/img-2a.png" alt="UI" width="200" /> <img src="resources/product-images/img-3.png" alt="UI" width="200" /> <img src="resources/product-images/img-4.png" alt="UI" width="200" /> <img src="resources/product-images/img-5.png" alt="UI" width="200" /> <img src="resources/product-images/img-6.png" alt="UI" width="200" />

---

### Product Sample Images

[Sample Automation Test Report](resources/Sample-Automation-Report.html)

---

### Architecture

```mermaid
flowchart LR
  UI["React UI"] -->|api| API["FastAPI main"]
  API --> JIRA["jira_client"]
  API --> LLM["ai_client"]
  API --> AG["agentic"]
  API --> IMG["requirement images"]
  API --> MEM["memory_store SQLite"]
  API --> AUD["audit_store SQLite"]
  API --> ATU["automation UI"]
  API --> ATA["automation API"]
  API --> KC["keycloak_auth"]
  AG -.->|uses| LLM
  ATA -.->|plans API steps| LLM
```

---

## Features

### Modes (toggle via `.env` / `GET /api/config`)

- **JIRA:** Fetch ticket (ADF/wiki/HTML → text).
- **Paste Requirements:** Generate from text/Markdown, no JIRA.
- **Auto Tests:** BDD browser runs, saved suite, reports.

### AI test generation

- Any OpenAI-compatible `/v1/chat/completions` (local e.g. LM Studio, or cloud).
- **Vision:** optional requirement mockups/images to the model (enable in `.env`; use a vision-capable model).
- Structured Gherkin scenarios, configurable **min/max** test case count (`0` = no max).
- **Priorities:** JIRA project priorities, or `PASTE_MODE_PRIORITIES` for paste mode.
- **Scoring:** Model scores each case (/10). **Edit/delete** generated cases; delete is limited when a case has a JIRA
  id (see UI).
- **Automation Skeleton:** Generate code-style skeleton per case.
- **Agentic:** Two-step validate-and-refine pipeline.

### Auto test execution (UI and API)

- **Saved Suite:** Store cases; run one / run all; optional **tag** and **JIRA** filters; configurable **parallel**
  runs; env (browser, headless, timeout, trace, screenshot-on-pass, post-run analysis, HTML reports, retention of
  artifacts).
- **Execution history** per saved case; **HTML reports** for runs (start test and suite; retention prunes old data per
  `AUTOMATION_RETENTION_DAYS`, default 20).
- **Saved History** (memory dialog): open a ticket snapshot; **Run** a case into the Auto test form (prefills
  requirement + test ids).
- Running case indicated in the UI; suite analysis text refers to **last run** from the saved suite when applicable.

### History & comparison

- SQLite stores latest requirements + tests per ticket when saving is on.
- **Similar match:** if no exact key, optional fuzzy match via `MEMORY_SIMILARITY_THRESHOLD` (`0` = off).
- **History sidebar:** list/filter by requirement id; open **Saved History** for full snapshot.
- **Regenerate** with prior memory: **requirements diff** and **change status** on cases (new / updated / unchanged /
  existing).

### JIRA

- Fetch issue, **linked** work and **linked** tests, attachments.
- **Push** test issues (create/update), **link** to requirement (`JIRA_TEST_LINK_TYPE`, e.g. Relates; direction via
  `JIRA_LINK_INWARD_IS_REQUIREMENT`).
- **Bulk push** (e.g. by change filter), priority names/icons mapped from JIRA.
- `JIRA_LINKED_WORK_ISSUE_TYPES` filters which linked types appear (see `.env`).

### Audit

- Logged actions (fetch, generate, push, etc.); filter; **export as PDF** (UI).

### Auth & dev

- **Keycloak** OIDC optional for UI/API; idle timeout hint in UI.
- **Mock (`MOCK=true`):** no real JIRA HTTP, fixture text; no audit on generate; no memory save on generate.

### UX

- Light/dark theme, copy as Markdown, tooltips, skip links and live regions for accessibility.

---

<details>
<summary><strong>Environment</strong></summary>

1. `cp .env.example .env` (repo root). See [resources/env-variables.md](resources/env-variables.md) for a full list.

2. **Minimum to try:** JIRA connection fields if not mocking; `LLM_URL` + `LLM_MODEL` (+ token if needed). **Mock:** set
   `MOCK=true` for JIRA-free dev.

3. **UI flags:** `SHOW_MEMORY_UI`, `SHOW_AUDIT_UI`, `SHOW_JIRA_MODE_UI`, `SHOW_PASTE_REQUIREMENTS_MODE_UI`,
   `SHOW_AUTO_TESTS_UI` — at least one requirement-related mode must stay on (defaults ensure this).

4. **Keycloak (optional):** `USE_KEYCLOAK=true` and realm/client/URLs; for Docker, browser-reachable `KEYCLOAK_URL` and
   often `KEYCLOAK_INTERNAL_URL` for the API. Redirect URIs in Keycloak must match the app origin/port.

5. `GET /api/config` returns **safe defaults** for the UI (no passwords or LLM secrets).

</details>

---

<details>
<summary><strong>Run locally</strong></summary>

**Backend (Python 3.10+):**

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

**Frontend (Node 18+):**

```bash
cd frontend
npm install
npm run dev
```

Open **http://127.0.0.1:5173** (Vite). Proxies `/api` → `http://127.0.0.1:8001` (see `frontend/vite.config.js`). Use a
local LLM or cloud API; with **`MOCK=true`**, JIRA can be dummy values.

</details>

---

<details>
<summary><strong>Docker Compose</strong></summary>

1. `docker build -t test-intellect-ai:1.0 .`
2. Point [docker-compose.yml](docker-compose.yml) at the image, then `docker compose up`
3. UI is typically at `http://127.0.0.1:8001`

Containers often use `LLM_URL` → `http://host.docker.internal:...` to reach the host’s LM Studio. `USE_KEYCLOAK` (not a
lone `KEYCLOAK=` flag) must be `true` to enable Keycloak. See [docker-compose.yml](docker-compose.yml) for
`KEYCLOAK_INTERNAL_URL` defaults.

</details>

---

<details>
<summary><strong>API overview</strong></summary>

| Method | Path                                | Purpose                                                                                               |
|--------|-------------------------------------|-------------------------------------------------------------------------------------------------------|
| `GET`  | `/api/config`                       | UI defaults: JIRA defaults, `mock`, feature flags, Keycloak client fields, idle timeout (no secrets). |
| `GET`  | `/api/memory/list`                  | Saved tickets list (Keycloak: `Authorization: Bearer`).                                               |
| `GET`  | `/api/memory/item/{ticket_id}`      | Saved `requirements` + `test_cases`.                                                                  |
| `POST` | `/api/memory/update-test-cases`     | Persist test case list updates.                                                                       |
| `POST` | `/api/memory/save-after-edit`       | Save after edit.                                                                                      |
| `GET`  | `/api/audit/list`                   | Audit rows.                                                                                           |
| `POST` | `/api/audit/auth`                   | Login/logout (Keycloak).                                                                              |
| `POST` | `/api/fetch-ticket`                 | JIRA issue → `requirements`.                                                                          |
| `POST` | `/api/generate-tests`               | JIRA path: generate, optional memory diff, save flags, min/max cases.                                 |
| `POST` | `/api/generate-from-paste`          | Paste path: `description`, optional `title`, `memory_key`.                                            |
| `POST` | `/api/jira/priorities`              | JIRA priorities (names + icon URLs).                                                                  |
| `POST` | `/api/jira/push-test-case`          | Create/update test + link.                                                                            |
| `POST` | `/api/generate-automation-skeleton` | LLM automation code skeleton for a test case.                                                         |

**Automation** routes: suite CRUD, spike run, stop, reports, etc. — `backend/main.py` + `backend/automation/routes.py` (
all under `/api/...`).

</details>

---

## Notes

- **Mock Mode:** No audit writes from generate; no history saves from generate. Audit user column is empty without
  Keycloak
- **JIRA Test Project:** After generating tests, configuring the test project and using **+** can pull priorities from
  JIRA depending on setup
- Make sure to use model that supports vision in order to use feature to pass mockups to LLM
- Analysis for each test case will have details of last execution only if executed from 'Saved Suite'
- Green dot will appear for currently running test case
- View Report will show report from 'Start Test' as well
- 'Run Test Case' button will be enabled when `SHOW_AUTO_TESTS_UI=true`
- System will keep automation artifacts for last 20 days

---

## Tested with a local model

Development testing has used a local OpenAI-compatible endpoint (e.g. LM Studio on `http://127.0.0.1:1234/v1`) with:

- qwen/qwen3-coder-30b
- qwen/qwen3-coder-next
- openai/gpt-oss-20b
- openai/gpt-oss-120b
- qwen/qwen3-vl-30b (model with vision support)

---

## Future Improvements & Features

- Use linked issue to get knowledge of the Requirement ticket
- Choice to generate test cases based on BDD or something else
- RAG feature
- Link with QA test framework and DEV code

## Last

- Use TSX instead of JSX for frontend
- Provide dropdown to select models or type model id
- Use multi model approach for Test Generation, coding and vision