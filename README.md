# Test Intellect AI

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org/) [![Jira](https://img.shields.io/badge/Jira-REST%20API-0052CC?style=flat-square&logo=jira&logoColor=white)](https://www.atlassian.com/software/jira)
[![LLM](https://img.shields.io/badge/LLM-OpenAI%20compatible-8B5CF6?style=flat-square&logo=openai&logoColor=white)](https://platform.openai.com/docs/api-reference)
[![Keycloak](https://img.shields.io/badge/Keycloak-OIDC-5C6BC0?style=flat-square&logo=keycloak&logoColor=white)](https://www.keycloak.org/)

Web app that pulls JIRA requirements (or paste text), uses OpenAI-compatible APIs to generate Gherkin-style test cases,
push to JIRA, and run UI/API automation.

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
<img src="resources/product-sample/images/img-3.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-4.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-5.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-6.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-7.png" alt="UI" width="200" />
<img src="resources/product-sample/images/img-8.png" alt="UI" width="200" />
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

## Functionality Flowcharts

<details>
<summary><strong>JIRA Mode</strong></summary>

```mermaid
flowchart TB

  subgraph ui[JIRA tab]
    A[Enter Jira URL, username, password, ticket ID, test project]
    B[Fetch Requirements]
    C[Generate Test Cases]
    A --> B
    A --> C
  end

  B -->|fetch ticket| F[Backend Jira REST]
  F --> R[Prepare requirements and metadata]
  R --> M{Optional memory or diff}
  M --> UI2[Show requirements and diff]

  C -->|generate tests| G[LLM creates BDD test cases]
  G --> T[Test Cases panel]

  T -->|run auto test| SW[Switch to Auto Tests tab]
```

</details>

<details>
<summary><strong>Paste Requirements</strong></summary>

```mermaid
flowchart TB

  subgraph ui[Paste Requirements]
    P[Enter title, requirement text, optional attachments]
    G2[Generate Test Cases]
    P --> G2
  end

  G2 -->|generate from paste| LLM[LLM creates BDD test cases JSON]
  LLM --> TC[Test Cases panel same as Jira]

  TC -->|run auto test| SW2[Auto Tests tab with prefilled data]
```

</details>

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
  PR2 -->|yes| ERR[Fail with prerun error]
  PR2 -->|no| BROWSER
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

---

## Features

### Modes (toggle via `.env`)

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

- Logged actions (fetch, generate, JIRA push, **Auto Test suite** save/update/delete, etc.); filter; **export as PDF**
  (UI). **Ticket ID** in the list can link to JIRA when a site URL is set and the value looks like an issue key.

### Auth & dev

- **Keycloak** OIDC optional for UI/API; idle timeout hint in UI.
- **Mock (`MOCK=true`):** no real JIRA HTTP, fixture text; no audit on generate or on suite save/update/delete; no memory
  save on generate.

### UX

- Light/dark theme, copy as Markdown, tooltips, skip links and live regions for accessibility.

---

<details>
<summary><strong>Environment</strong></summary>

1. `cp .env.example .env` (repo root). See [resources/env-variables.md](resources/env-variables.md) for a full list.

2. **Minimum (non-mock):** `LLM_TEXT_URL` + `LLM_TEXT_MODEL` (+ `LLM_TEXT_ACCESS_TOKEN` if your provider needs it). Add
   `LLM_VISION_*` only if you want image/PDF in the model and the upload UI. **Mock:** `MOCK=true` for JIRA-free dev
   (JIRA can be dummy values).

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

Containers often set `LLM_TEXT_URL` → `http://host.docker.internal:...` to reach the host’s LM Studio. `USE_KEYCLOAK` (
not a
lone `KEYCLOAK=` flag) must be `true` to enable Keycloak. See [docker-compose.yml](docker-compose.yml) for
`KEYCLOAK_INTERNAL_URL` defaults.

</details>

---

<details>
<summary><strong>API overview</strong></summary>

| Method   | Path                                | Purpose                                                                                                                           |
|----------|-------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `GET`    | `/api/config`                       | UI defaults: JIRA defaults, `mock`, feature flags, Keycloak client fields, idle timeout (no secrets).                             |
| `GET`    | `/api/memory/list`                  | Saved tickets list (Keycloak: `Authorization: Bearer`).                                                                           |
| `GET`    | `/api/memory/item/{ticket_id}`      | Saved `requirements` + `test_cases`.                                                                                              |
| `POST`   | `/api/memory/update-test-cases`     | Persist test case list updates.                                                                                                   |
| `POST`   | `/api/memory/save-after-edit`       | Save after edit.                                                                                                                  |
| `GET`    | `/api/audit/list`                   | Audit rows.                                                                                                                       |
| `POST`   | `/api/audit/auth`                   | Login/logout (Keycloak).                                                                                                          |
| `POST`   | `/api/fetch-ticket`                 | JIRA issue → `requirements`.                                                                                                      |
| `POST`   | `/api/generate-tests`               | JIRA path: generate, optional memory diff, save flags, min/max cases.                                                             |
| `POST`   | `/api/generate-from-paste`          | Paste path: `description`, optional `title`, `memory_key`.                                                                        |
| `POST`   | `/api/jira/priorities`              | JIRA priorities (names + icon URLs).                                                                                              |
| `POST`   | `/api/jira/push-test-case`          | Create/update test + link.                                                                                                        |
| `POST`   | `/api/generate-automation-skeleton` | LLM automation code skeleton for a test case.                                                                                     |
| `POST`   | `/api/automation/suite`             | Add a saved Auto Test case. With Keycloak, requires `Authorization: Bearer`; on success, writes **audit** (not when `MOCK=true`). |
| `PUT`    | `/api/automation/suite/{case_id}`   | Update a saved case. Same auth and **audit** rules as `POST` suite.                                                               |
| `DELETE` | `/api/automation/suite/{case_id}`   | Remove a saved case. Same auth and **audit** rules as `POST` suite.                                                               |

**Automation** (other paths): list suite, run spike, stop, suite batch run, reports, artifacts, selectors, etc. — see
`backend/automation/routes.py` (all under `/api/automation/...`).

</details>

---

## Notes

- **Mock Mode:** No audit writes from generate or from suite save/update/delete; no history saves from generate. Audit
  user column is empty without Keycloak
- **JIRA Test Project:** After generating tests, configuring the test project and using **+** can pull priorities from
  JIRA depending on setup
- Make sure to use model that supports vision in order to use feature to pass mockups to LLM
- Analysis for each test case will have details of last execution only if executed from 'Saved Suite'
- Green dot will appear for the currently running test case
- View Report will show the report from 'Start Test' as well
- 'Run Test Case' button will be enabled when `SHOW_AUTO_TESTS_UI=true`
- System will keep automation artifacts for last 20 days
- If `LLM_VISION_URL` is not set, the **Upload mockups** UI and the **include attachment** checkboxes for generation are
  hidden; JIRA can still list ticket attachments. See [resources/env-variables.md](resources/env-variables.md) for
  details.
- If a step is passed using screenshot from Vision model then the record will not be saved in 'Saved Selectors'
- JIRA will fetch the template of Test Project each `JIRA_CREATEMETA_TEST_TTL_SECONDS`

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

- Use a linked issue to get knowledge of the Requirement ticket
- Choice to generate test cases based on BDD or something else
- RAG feature
- Link with QA test framework and DEV code

## Last

- Use TSX instead of JSX for frontend 
- Provide a dropdown to select models or type model ID
- Use a multi-model approach for Test Generation, coding, and vision
