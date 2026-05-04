# Test Intellect AI

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org/) [![Jira](https://img.shields.io/badge/Jira-REST%20API-0052CC?style=flat-square&logo=jira&logoColor=white)](https://www.atlassian.com/software/jira)
[![LLM](https://img.shields.io/badge/LLM-OpenAI%20compatible-8B5CF6?style=flat-square&logo=openai&logoColor=white)](https://platform.openai.com/docs/api-reference)
[![Keycloak](https://img.shields.io/badge/Keycloak-OIDC-5C6BC0?style=flat-square&logo=keycloak&logoColor=white)](https://www.keycloak.org/)

Web app that ingests requirements from Jira or free-form text, generates Gherkin-style test cases via OpenAI-compatible
APIs, writes them back to Jira, and runs UI and API automation.

Optionally:

- Save runs per ticket in SQLite
- Track actions in an audit log
- Use Keycloak to associate users with activity

---

### Product Sample Video

<p align="center">
  <a href="https://youtu.be/MCDQR60AEiE">
    <img src="https://img.youtube.com/vi/MCDQR60AEiE/hqdefault.jpg" width="450" alt="Watch product sample video on YouTube" />
  </a>
</p>

---

### Product Sample Images and Report

<details>
<summary><strong>Images</strong></summary>

<img src="resources/product-sample/images/img-1.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-2.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-2a.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-2b.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-3.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-4.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-5.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-6.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-7.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-9.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-10.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-11.png" alt="UI" width="200" />


</details>

[Sample Automation Test Report](resources/product-sample/sample-automation-report.html)

[Sample Audit Records](resources/product-sample/sample-audit-records.pdf)

---

### Architecture

```mermaid
flowchart LR
  UI["React UI"] -->|HTTP /api| API["FastAPI main"]
  API --> JIRA["jira_client"]
  API --> LLM["ai_client"]
  API --> AG["agentic"]
  API --> IMG["requirement_images"]
  API --> MEM["memory_store SQLite"]
  API --> AUD["audit_store SQLite"]
  API --> ATU["automation UI"]
  API --> ATA["automation API"]
  API --> KC["keycloak_auth"]
  AG -.->|uses| LLM
  ATA -.->|plans API steps| LLM
```

---

## Functionality Flowcharts

<details>
<summary><strong>Auto Test (Suite Run)</strong></summary>

```mermaid
flowchart TB

  subgraph client2[Client]
    S0[Select suite and filters]
    S1[Run suite]
    S0 --> S1
  end

  S1 -->|start run| SR[Run suite sequential or threaded]

  SR --> CANCEL[Clear cancel flag]
  CANCEL --> LIST[Load suite cases from DB]
  LIST --> FILTER[Apply filters]
  FILTER --> REP[Create report id and file]
  FILTER --> PARM{Parallel execution enabled?}

  PARM -->|no| LOOP[Run cases one by one]
  PARM -->|yes| POOL[Thread pool workers]
  POOL --> WORK[Run case in worker]

  LOOP --> ONE[Run single case]
  WORK --> ONE

  ONE --> STOP{Cancel suite?}
  STOP -->|yes| END1[Stop execution]
  STOP -->|no| RASP[Run automation spike per case]

  subgraph repair[UI spike: two-LLM repair optional]
    RASP --> SPIKE[Plan steps from BDD + DOM; optional pre-run check]
    SPIKE --> STEPS[Execute Playwright step]
    STEPS --> OK{Step passed?}
    OK -->|yes| NXT2{More steps?}
    OK -->|no| T1[Text LLM: repair from fresh DOM + error]
    T1 --> STEPS2[Retry same step]
    STEPS2 --> OK2{Passed?}
    OK2 -->|yes| NXT2
    OK2 -->|no| VCFG{LLM_VISION_URL set?}
    VCFG -->|no| FAIL[Step fails; continue / abort as configured]
    VCFG -->|yes| V1[Capture screenshot; Vision LLM repair]
    V1 --> STEPS3[Retry same step]
    STEPS3 --> OK3{Passed?}
    OK3 -->|yes| NXT2
    OK3 -->|no| FAIL
    NXT2 -->|yes| STEPS
    NXT2 -->|no| CACHE{Vision repair passed on any step?}
    CACHE -->|yes| NOC[Skip Saved Selectors cache for this run]
    CACHE -->|no| UPS[Upsert Saved Selectors on success]
    NOC --> DONE1[Spike result]
    UPS --> DONE1
    FAIL --> DONE1
  end

  RASP -.-> repair

  DONE1 --> HIST[Save run history]
  HIST --> BATCH[Collect results]

  LOOP --> NEX{More cases?}
  NEX -->|yes| LOOP
  NEX -->|no| REND

  END1 --> REND[Render HTML report]
  WORK -->|done| REND
  REND --> OUT[Return report id and results]

  subgraph percase[Per case reuse]
    RASP -.-> SAME[Same as standalone spike: run_automation_spike]
  end
```

</details>


<details>
<summary><strong>Auto Test (Single Run)</strong></summary>

```mermaid
flowchart TB

  subgraph client[Client]
    A[Enter BDD, base URL, mode UI or API]
    B[Start Test]
    A --> B
  end

  B -->|start run| API[API receives request]

  API --> ASYNC[Run async in background thread]

  ASYNC --> CL[Clear cancel flag for isolated run]
  CL --> BEGIN[Create run id and store in DB]
  BEGIN --> EXEC[Execute test flow]

  EXEC --> PARSE[Parse BDD steps]
  PARSE --> ST{Mode}

  ST -->|api| APIPATH[Validate API base URL]
  APIPATH --> APILLM[Text LLM: plan HTTP steps]
  APILLM --> APIHTTP[Execute requests and checks]
  APIHTTP --> FIN[Finalize run]

  ST -->|ui| UIPATH[Validate page URL]
  UIPATH --> FP[Build fingerprint from title, BDD, URL, optional pasted HTML]
  FP --> CACHE{Selector cache hit?}

  CACHE -->|yes| LOAD[Load cached selectors]
  CACHE -->|no| UILLM[Text LLM: BDD to Playwright steps from DOM]
  UILLM --> VAL[Optional: validate or refine against DOM]
  VAL --> PRERUN{Prerun: early steps match page?}
  PRERUN -->|fail once| ZFIX[Text LLM: repair zero-match locators]
  ZFIX --> PR2{Still bad?}
  PR2 -->|yes| BYP[Log + continue: run without prerun guard]
  PR2 -->|no| BROWSER
  BYP --> BROWSER
  PRERUN -->|ok| BROWSER[Launch browser, goto page]
  LOAD --> BROWSER

  BROWSER --> STEPPW[For each step: run Playwright action]
  STEPPW --> POK{Step passed?}
  POK -->|yes| MRD{More steps?}
  POK -->|no| R1[Text LLM: repair with fresh DOM, no image]
  R1 --> RET1[Retry same step]
  RET1 --> P2{Passed?}
  P2 -->|yes| MRD
  P2 -->|no| VSET{LLM_VISION_URL set?}
  VSET -->|no| STEPF[Step / run fails as configured]
  VSET -->|yes| R2[Vision LLM: screenshot + repair]
  R2 --> RET2[Retry same step]
  RET2 --> P3{Passed?}
  P3 -->|yes| MRD
  P3 -->|no| STEPF
  MRD -->|yes| STEPPW
  MRD -->|no| PANA[Optional: post-run analysis text LLM]
  PANA --> SC{Any passed step source llm-vision?}
  SC -->|yes| NOCA[Omit upsert to Saved Selectors]
  SC -->|no| UPSV[Upsert Saved Selectors on success]
  NOCA --> FIN
  UPSV --> FIN
  STEPF --> FIN2[Finalize run]
  ERR --> FIN2

  FIN --> UPD[Save results and artifacts in DB]
  UPD --> RESP[Return status and run id to client]
  FIN2 --> UPD2[Save results and artifacts in DB]
  UPD2 --> RESP

```

</details>

<details>
<summary><strong>JIRA Mode</strong></summary>

```mermaid
flowchart TB

  subgraph ui[JIRA tab]
    A[Enter Jira URL, username, password, ticket ID, test project]
    B[Fetch Requirements]
    C[Generate Test Cases — classic or agentic]
    A --> B
    A --> C
  end

  B -->|fetch ticket| F[Backend Jira REST]
  F --> R[Prepare requirements and metadata]
  R --> M{Optional memory or diff}
  M --> UI2[Show requirements and diff]

  subgraph agentic[Agentic pipeline — backend LangGraph]
    direction TB
    PL[Coverage planner LLM]
    GN[Generator LLM]
    PS[Parse JSON envelope]
    VL[Validator rubric LLM]
    SU[Suggestion merge optional]
    FZ[Finalize — cases + trace]
    AX[Auto-extend rounds optional]
    PL --> GN --> PS
    PS -->|valid envelope| VL
    PS -.->|retry with feedback| GN
    VL -->|pass / budget exhausted| FZ
    VL -.->|refine with feedback| GN
    VL --> SU
    SU --> VL
    VL -.->|extend generation budget| AX
    AX --> GN
  end

  C -->|POST /api/generate-tests| GC[LLM single-shot BDD JSON]
  C -->|POST /api/generate-tests-agentic| PL

  GC --> MERGE[Merge linked JIRA tests, memory, reconcile, score]
  FZ --> MERGE

  MERGE --> T[Test Cases panel — Agentic Pipeline panel when agentic]
  T -->|run auto test| SW[Switch to Auto Tests tab]
```

</details>


<details>
<summary><strong>Paste Requirements</strong></summary>

```mermaid
flowchart TB

  subgraph ui[Paste Requirements]
    P[Enter title, requirement text, optional attachments]
    G2[Generate Test Cases — classic or agentic]
    P --> G2
  end

  G2 --> PREP[Requirements from paste — optional memory / similarity]

  subgraph agenticPaste[Agentic pipeline — backend LangGraph]
    direction TB
    PL[Coverage planner LLM]
    GN[Generator LLM]
    PS[Parse JSON envelope]
    VL[Validator rubric LLM]
    SU[Suggestion merge optional]
    FZ[Finalize — cases + trace]
    AX[Auto-extend rounds optional]
    PL --> GN --> PS
    PS -->|valid envelope| VL
    PS -.->|retry with feedback| GN
    VL -->|pass / budget exhausted| FZ
    VL -.->|refine with feedback| GN
    VL --> SU
    SU --> VL
    VL -.->|extend generation budget| AX
    AX --> GN
  end

  PREP -->|POST /api/generate-from-paste| GC[LLM single-shot BDD JSON]
  PREP -->|POST /api/generate-from-paste-agentic| PL

  GC --> MERGE[Paste path: merge memory, reconcile keys, score]
  FZ --> MERGE

  MERGE --> TC[Test Cases panel — Agentic Pipeline panel when agentic]

  TC -->|run auto test| SW2[Auto Tests tab with prefilled data]
```

</details>



---

## Features

### Modes (toggle via `.env`)

- **Auto Tests**: Run BDD-style browser and API automation, persist suites, and produce reports.
- **Jira**: Load a ticket and convert ADF/wiki/HTML to plain text for generation.
- **Paste Requirements**: Generate from pasted text or Markdown without Jira.

### AI Test Generation

- **LLM backend**: Any OpenAI-compatible /v1/chat/completions endpoint (local, e.g. LM Studio, or cloud).
- **Vision (optional)**: Send requirement mockups or images when enabled in .env; use a vision-capable model.
- **Output**: Structured Gherkin scenarios with configurable min/max case counts in [App.jsx](frontend/src/App.jsx).
- **Priorities**: Jira project priority list in Jira mode, or PASTE_MODE_PRIORITIES in paste mode.
- **Scoring**: The model assigns a score (/10) per case. Edit or delete generated cases; deletes are restricted when a
  case is linked to Jira (see UI).
- **Automation Skeleton**: Per-case code-style automation skeleton generation.
- **Agentic**: LangGraph flow — coverage planning → generation → parsing → validator scoring → optional suggestion
  merge — with retries and auto-extend rounds. Exposed as /api/generate-tests-agentic (mirrored for paste mode).

### Auto Test Execution (UI and API)

- **Saved Suite**: Persist scenarios; run one or run all. Optional filters by tags or Jira. Parallel run count is
  configurable. Environment: browser profile, headless, timeouts, traces, screenshots on pass, HTML reports, and
  artifact/report retention.
- **Run History**: Per saved case; HTML reports for individual runs and full suite runs. `AUTOMATION_RETENTION_DAYS`
  prunes old runs/data (default 20).
- **Saved History (memory)**: Open a ticket snapshot; Run routes a case into the Auto Tests form with requirement + test
  issue ids prefilled.
- **UI Feedback**: Shows which case is executing. Suite analysis text uses the last run of the saved suite when that
  applies.

### History & Comparison

- **Persistence**: With saving enabled, SQLite keeps the latest requirements and linked tests per ticket.
- **Similar Match**: If there is no exact key, optionally match a prior row using MEMORY_SIMILARITY_THRESHOLD (fuzzy on
  title/description); set to 0 to disable.
- **History Sidebar**: Browse and filter by requirement id; open Saved History for the full stored snapshot.
- **Regenerate with Memory**: Reload prior context so the UI can show a requirements diff and per-case change status (
  e.g. new, updated, unchanged, existing).

### JIRA Integration

- **Read:** Fetch the requirement issue, **linked work** and **linked tests**, and attachments.
- **Write:** Create or update **test** issues and **link** them to the requirement (**`JIRA_TEST_LINK_TYPE`**, e.g.
  `Relates`; inward/outward semantics via **`JIRA_LINK_INWARD_IS_REQUIREMENT`**).
- **Bulk push:** e.g. push by **change/status filter** (new/updated); **priorities** use Jira priority names/icons.
- **`JIRA_LINKED_WORK_ISSUE_TYPES`:** Limits which linked-work types show in the UI (comma-separated list in `.env`).

### Audit

- **Events:** Logs operations such as fetch, generation, **Jira** push, and **saved Auto Test suite**
  create/update/delete (and similar actions).
- **Use:** Filter in-app; **export to PDF** from the UI.
- **Issue keys:** Rows show a **ticket/issue id**; when **Jira site URL** is configured and the value looks like a *
  *Jira key**, it links out to the issue.

### Auth & development

- **Keycloak:** Optional **OIDC** for the UI and API. The UI shows an **idle timeout** hint from config.
- **Mock mode (`MOCK=true`):** Skips real **Jira** HTTP and uses fixture data. Skips audit for **generation** and for *
  *suite** create/update/delete, and skips **memory persistence on generate**.

### UX

- Light/dark theme, copy as Markdown, tooltips, skip links and live regions for accessibility.

---

<details>
<summary><strong>Environment</strong></summary>

1. `cp .env.example .env`. See [resources/env-variables.md](resources/env-variables.md) for a full list.

2. **Minimum (non-mock):** `LLM_TEXT_URL` + `LLM_TEXT_MODEL` (+ `LLM_TEXT_ACCESS_TOKEN` if your provider needs it). Add
   `LLM_VISION_*` only if you want image/PDF in the model and the upload UI.
3. **Mock:** `MOCK=true` for JIRA-free DEV (JIRA can be dummy values).

4. **UI flags:** Set at-least one
    - `SHOW_MEMORY_UI`
    - `SHOW_AUDIT_UI`
    - `SHOW_AUTO_TESTS_UI`
    - `SHOW_JIRA_MODE_UI`
    - `SHOW_PASTE_REQUIREMENTS_MODE_UI`

5. **Keycloak (optional):** `USE_KEYCLOAK=true` and realm/client/URLs; for Docker, browser-reachable `KEYCLOAK_URL` and
   often `KEYCLOAK_INTERNAL_URL` for the API. Redirect URIs in Keycloak must match the app origin/port.

</details>

---

<details>
<summary><strong>Run Locally</strong></summary>

**Backend (Python 3.10+):**

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
playwright install firefox
playwright install msedge
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

**Frontend (Node 18+):**

```bash
cd frontend
npm install
npm run dev
```

- Open **http://127.0.0.1:5173**
- Proxies `/api` → `http://127.0.0.1:8001` (see `frontend/vite.config.js`).

</details>

---

<details>
<summary><strong>Docker Compose</strong></summary>

1. `docker compose up`
2. UI is typically at `http://127.0.0.1:8001`

Containers often set `LLM_TEXT_URL` → `http://host.docker.internal:...` to reach the host’s LM Studio. `USE_KEYCLOAK` (
not a
lone `KEYCLOAK=` flag) must be `true` to enable Keycloak. See [docker-compose.yml](docker-compose.yml) for
`KEYCLOAK_INTERNAL_URL` defaults.

</details>

---

<details>
<summary><strong>API Overview</strong></summary>

| Method   | Path                                          | Purpose                                                                                                                                    |
|----------|-----------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| `GET`    | `/api/config`                                 | UI defaults: Jira defaults, `mock`, feature flags, Keycloak client fields, idle timeout, automation env hints, vision limits (no secrets). |
| `GET`    | `/api/memory/list`                            | Saved tickets list (Keycloak: `Authorization: Bearer`).                                                                                    |
| `GET`    | `/api/memory/item/{ticket_id}`                | Saved `requirements` + `test_cases`.                                                                                                       |
| `POST`   | `/api/memory/update-test-cases`               | Persist test case list updates.                                                                                                            |
| `POST`   | `/api/memory/merge-test-case`                 | Merge a single edited test case into saved memory for a ticket.                                                                            |
| `POST`   | `/api/memory/save-after-edit`                 | Save after edit.                                                                                                                           |
| `GET`    | `/api/audit/list`                             | Audit rows.                                                                                                                                |
| `POST`   | `/api/audit/auth`                             | Login/logout (Keycloak).                                                                                                                   |
| `POST`   | `/api/fetch-ticket`                           | Jira issue → `requirements`, linked tests/work, attachments meta, optional memory diff.                                                    |
| `POST`   | `/api/generate-tests`                         | Jira path: single-shot generate (multipart/form or JSON); optional images, memory diff, save flags, min/max cases.                         |
| `POST`   | `/api/generate-tests-agentic`                 | Same as `generate-tests` with LangGraph agentic pipeline (`max_rounds`, retries, auto-extend via server env where configured).             |
| `POST`   | `/api/generate-from-paste`                    | Paste path: `description`, optional `title`, `memory_key`; single-shot generation.                                                         |
| `POST`   | `/api/generate-from-paste-agentic`            | Paste path agentic counterpart of `generate-from-paste`.                                                                                   |
| `POST`   | `/api/jira/priorities`                        | Jira priorities (names + icon URLs); optionally severities when a test project key is supplied.                                            |
| `POST`   | `/api/jira/push-test-case`                    | Create/update test + link to requirement.                                                                                                  |
| `POST`   | `/api/jira/attachment-download`               | Stream a Jira attachment by id (ticket + attachment id); not available in mock mode.                                                       |
| `POST`   | `/api/generate-automation-skeleton`           | LLM automation code skeleton for a test case.                                                                                              |
| `GET`    | `/api/automation/env`                         | Current automation env (browser, headless lock, timeouts, trace, parallel, etc.).                                                          |
| `POST`   | `/api/automation/browser`                     | Set stored browser; returns payload like `GET /api/automation/env`.                                                                        |
| `POST`   | `/api/automation/env-options`                 | Set headless (if not server-locked), screenshot-on-pass, trace, default timeout, parallel execution.                                       |
| `POST`   | `/api/automation/cancel`                      | Request stop for current spike or all suite runs (`all_in_suite`).                                                                         |
| `POST`   | `/api/automation/spike-run`                   | Start a single UI or API BDD run (async); Keycloak may set report author.                                                                  |
| `GET`    | `/api/automation/runs/{run_id}`               | Run metadata and step results.                                                                                                             |
| `GET`    | `/api/automation/results/{run_id}`            | Same response as `GET /api/automation/runs/{run_id}`.                                                                                      |
| `GET`    | `/api/automation/artifacts/{run_id}/{name}`   | Serve a run artifact file (images, trace zip, etc.).                                                                                       |
| `GET`    | `/api/automation/selectors`                   | List cached selector rows (optional `limit`).                                                                                              |
| `DELETE` | `/api/automation/selectors/all`               | Clear selector cache; may audit under Keycloak.                                                                                            |
| `DELETE` | `/api/automation/selectors/{rowid}`           | Delete one selector cache row; may audit under Keycloak.                                                                                   |
| `GET`    | `/api/automation/suite`                       | List saved suite cases.                                                                                                                    |
| `GET`    | `/api/automation/suite/{case_id}/run-history` | Per-case execution history rows.                                                                                                           |
| `POST`   | `/api/automation/suite`                       | Add a saved Auto Test case. With Keycloak, `Authorization: Bearer`; audit on success unless `MOCK=true`.                                   |
| `PUT`    | `/api/automation/suite/{case_id}`             | Update a saved case. Same auth and audit rules as `POST /suite`.                                                                           |
| `DELETE` | `/api/automation/suite/all`                   | Delete all suite cases and history (409 if suite run in progress); may audit under Keycloak.                                               |
| `DELETE` | `/api/automation/suite/{case_id}`             | Remove one saved case. Same auth and audit rules as `POST /suite`.                                                                         |
| `GET`    | `/api/automation/suite-run-status`            | Currently running suite case id(s).                                                                                                        |
| `POST`   | `/api/automation/suite-run`                   | Run suite (optional case id subset, tag/Jira filters, default URL); Keycloak may set report author.                                        |
| `GET`    | `/api/automation/reports/{name}`              | HTML report file for a single run (validated filename).                                                                                    |
| `GET`    | `/api/automation/suite-reports-recent`        | List recent suite HTML reports within retention.                                                                                           |
| `GET`    | `/api/automation/suite-reports/{name}`        | HTML suite report file (validated filename).                                                                                               |

Refer: [backend/automation/routes.py](backend/automation/routes.py).

</details>

---

## Notes

- **Mock Mode:** No audit writes from generate or from suite save/update/delete; no history saves from generate. Audit user column is empty without Keycloak
- **JIRA Test Project:** After generating tests, configuring the test project and can pull priorities from JIRA depending on setup
- Make sure to use model that supports vision in order to use feature to pass mockups to LLM
- Analysis for each test case will have details of last execution only if executed from 'Saved Suite'
- Green dot will appear for the currently running test case
- View Report will show the report from 'Start Test' as well
- 'Run Test Case' button will be enabled when `SHOW_AUTO_TESTS_UI=true`
- System will keep automation artifacts for last 20 days
- If `LLM_VISION_URL` is not set, the **Upload mockups** UI and the **include attachment** checkboxes for generation are hidden; JIRA can still list ticket attachments. See [resources/env-variables.md](resources/env-variables.md) for details.
- If a step is passed using screenshot from Vision model then the record will not be saved in 'Saved Selectors'
- JIRA will fetch the template of Test Project each `JIRA_CREATEMETA_TEST_TTL_SECONDS`

---

## Tested with a local model

Development testing has used a local OpenAI-compatible endpoint (e.g. LM Studio on `http://127.0.0.1:1234/v1`) with:

- qwen/qwen3-vl-30b (model with vision support)
- qwen/qwen3-coder-next
- qwen/qwen3-coder-30b
- openai/gpt-oss-20b
- openai/gpt-oss-120b

---

## Future Improvements & Features

- Use a linked issue to get knowledge of the Requirement ticket
- Choice to generate test cases based on BDD or something else
- RAG feature
- Link with QA test framework and DEV code

---

## Known Issue
- Keyclock integration with docker-compose is not working