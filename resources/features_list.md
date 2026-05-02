# Features

### General

- Agents:
  - Agent 1: Planner, Agent 2: Generator, Agent 3: Validator
  - Iteration will be as per `effective_max = min(max_rounds_from_ui + (AGENTIC_AUTO_EXTEND_PHASES × AGENTIC_AUTO_EXTEND_ADDITIONAL_GENERATIONS, AGENTIC_ROUND_CAP_CEILING))`
  - Agent 1 will run only 1 time but Agent 2 and 3 as per `effective_max`
  - Notes:
    - Traceability – How well scenarios line up with the written requirements (and coverage plan ids, when a plan exists). 
    - Coverage – How well the set of scenarios covers the important behaviors, edge cases, and plan intents—not just “more tests.” 
    - Gherkin – Structure and clarity of Given / When / Then style flow (order, completeness, consistency). 
    - Concrete – Specific, testable wording (real UI text, URLs, outcomes) vs vague steps. 
    - Non-redundant – How much overlap or duplicate coverage exists across scenarios.\
    - 5 is the top of the scale for that dimension; 4 and 3 mean “good but not strongest” on Gherkin and Concrete. 
    - Weighted 4.50 is the overall rubric score from combining the five; it’s what you use to compare runs at a glance.

- Fetched and Generated content will rest if switch between JIRA MODE and PASTE REQUIREMENT MODE
- Fetched and Generated content will not rest if switch between 
  - JIRA MODE and AUTO TEST MODE
  - PASTE REQUIREMENT MODE and AUTO TEST MODE
- If JIRA_PASSWORD is set in `.env`, then still in UI nothing will dispalye as its password

---

### Mock Mode
- No audit records
- No JIRA
- Only for development purpose

---

### Audit Records
- Login and Logout
- Fetch Requirements
- Generate Test Cases
- Filters
- Download audit records as PDF
- Edited
- Updated
- Created
- Auto test - edit, save, delete, delete all suite, delete all sectors

---

### JIRA MODE

- Fetch requirements, attachments and linked issues using 'Requirement Ticket ID'
- Optional: Agentic Validation and Scoring.
    - Checked (Default): Test cases will go through Agents
    - Unchecked: Test cases will not go through Agents
- Optional: Save generated tests to history.
    - Checked (Default): Tests and requirements will be save in 'History'
    - Unchecked: Tests and requirements will not be save in 'History'
- 'Upload Mockups and Attachments' to provide additional mockups.
    - The option is hidden if LLM_VISION_URL is not set
- Select fetched attachments
    - The option is hidden if LLM_VISION_URL is not set
- Requirement Different if there is difference between saved and newely fetched requirements
- Filtering using 'All, Existing, Unchanged, Updated, New'
- Expand and Collapse all generated test cases
- Edit test case
    - If a test case is edited then it will be marked as UPDATED
    - If the test has JIRA ID then user can update from the application
- Run automation for the test case
    - This will be available if `SHOW_AUTO_TESTS_UI=true`
- Generate Automation skeleton
- Add test case in JIRA
    - Test case will be linked with Requirement Ticket
    - The icon will change to check in green
    - JIRA ID will be displayed for the test case
- Copy to clipboard available for
    - Requirements
    - Requirements Diff
    - All generated test cases
    - Copy specific test case
- Delete test case which is not in JIRA
- Add all test cases in bulk
    - If an existed test case is present with UPDATE status, will be updated in JIRA
- Test Cases will have
    - Scoring
    - Priority from `PASTE_MODE_PRIORITIES`
    - Priority from JIRA if test case has JIRA ID
- Type: 'All, Existing, Unchanged, Updated, New'
- Stop test Generation will stop and make the app ready (but LLM will continue to run if it received the prompt)
- Clicking on run auto test will navigate to Auto Test mode and auto fill
    - Scenario
    - Test Steps
    - Requirement Ticket if present
    - Test Case ID if present
- If an exiting test case is regenerated and is marked as UPDATED, then the new change will be displayed in GREEN and old one in RED
- Test case section will reset if user re fetch the requirements

---

### Automation Skeleton Generation

- Generate skeleton using Language and Test Framework
- Copy to clip board is available
- Copy to clipboard available for
    - Requirements
    - Requirements Diff
    - All generated test cases
    - Copy specific test case
- Expand and Collapse all generated test cases

---

### Saved History

- 'Generated Test Cases' if 'Save generated tests to history' is checked before generating test cases
- Has: Run auto test, generate skeleton code
- Filter by Requirement ID

---

### Paste Requirements MODE

- Paste Requirements and generate test cases
- No possibility to interact to JIRA
- If requirement is already in Saved History the the Title and key will be auto filled
- If Title and key is not provided then key will be auto filed as `TEST-`
- Reset everything will work as JIRA mode

---

### Auto Test MODE

- 'Start Test'
    - Will not save the test case in suite
    - the report will be available in 'View test report'
    - Stop test will stop the running test (may take some time to stop)
    - TAG accepts csv values
- Test Type will be used as a TAG
- Saved Suite
    - Test can be saved from the 'Start test' form
    - The save test will have pattern: `TEST_TYEP (dot) TAG_1 (dot) TAG_2 (dot) REQUIREMENT_ID (dot) TEST_ID (dot) SCENARIO_TITLE`
    - View test case
    - run single test 
    - check analytics. will save analytic from last run only
    - If a test is skipped then in history it will show skipped but run and analystics will show status of last run (fail or pass)
    - execution history
    - delete test from saved list
    - running test will have a green dot and will come in focus automatically
    - Run filters supports `OR Match`
    - Run all test case
    - No record in Audit record
    - Run per test button will show color based on last run status
    - Stop current test
    - Stop all test in suite
    - Download report
    - View last report
    - Edit test case - will allow user to edit existing test case in 'Start Test' form
- Supports both UI and API 
- Environment changes will be save din DB
- Artifacts will be deleted after `AUTOMATION_RETENTION_DAYS` days
- Delete all button for Save Selectors and Saved Suite

---

### Saved Selectors

- Selectors will be saved only after successful run
- Delete selector

---

### HTML Report

- Filter by Status and TAG
- Dashboard
- Sharable PDF file

---

### docker-compose

- Headless will be enabled all the time