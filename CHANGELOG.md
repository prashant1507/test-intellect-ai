# Changelog

All notable changes to **Test Intellect AI** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0]

### Added

- **JIRA mode:** Fetch requirement tickets, normalize ADF/wiki/HTML to plain text, generate Gherkin-style test cases via an OpenAI-compatible LLM (`LLM_URL`, optional `LLM_ACCESS_TOKEN`).
- **Paste mode:** Generate tests from pasted requirements without JIRA; optional save key and history.
- **SQLite history:** Per-ticket storage of requirements and generated tests (when saving is enabled); history list, filters, and detail view.
- **Similar-ticket matching:** Optional fuzzy match via `MEMORY_SIMILARITY_THRESHOLD` when no exact saved row exists.
- **JIRA push:** Create or update test issues, link to the requirement, configurable test project, issue type, and link type; per-row and bulk push with filters.
- **Audit log:** Records fetch, generate, and related actions; optional PDF export; filters by user, ticket, and action.
- **Keycloak (optional):** OIDC sign-in; usernames on audit entries when enabled.
- **Mock mode:** Local development without real JIRA (`MOCK=true`); sample data, no generate-time history or audit writes from generation.
- **UI:** Light/dark theme, requirements diffs and test change status on regenerate, accessibility helpers (skip link, live regions), tooltips.

---
## [1.0.1]

### Added

- Fetch linked issues from JIRA for the requirement (configured test issue type); show priority and workflow status; rows matched to a linked issue are marked **EXISTING** and include the issue link.
- Automation skeleton generation
- 2 AI agents verifying the generated tet cases
- LLM now shows the scoring of test cases out of /10

---
## [1.0.2]

### Added

- Copy icon for individual test cases
- Copy icon will be enabled after the Requirements or Test Cases data is loaded
- Now for UPDATED test cases, new changes will be displayed in red and old ones in red
- Added Expand All and Collapse All for Test Cases in Saved History
- Filter by JIRA User in Audit Records

### Changed
- Minor bug fixes

---
## [1.0.3]

### Added
- Supports passing Mockups to AI Model (can be enabled or disabled in .env file)

### Changed
- Minor bug fixes

---
## [1.0.4]

### Added
- Added delete option per test case for 'Generate Test Cases'

### Changed
- Increase the tile spacing
- Minor bug fixes

---
## [1.0.5]

### Added
- Added 'Count' for Generated test Cases
- Reset the fetched Requirements and Generated Test Cases on switching modes

### Changed
- Updated README.md
- Minor bug fixes
- Removed 'Add all to JIRA' button from 'Paste Requirements' mode

---
## [1.0.6]

### Changed
- Now copy to clip board for Test Cases will copy Status, Priority, Gherkin Steps, Score 
- Improved BDD LLM prompt

---
## [2.0.0]

### Added
- Added additional mode for 'Auto Tests'
- The user can run the newly generated test case

### Changed
- Minor Improvements
- Minor bug fixes

---
## [2.0.1]

### Changed
- Improved HTML reporting

---
## [2.1.0]

### Added
- Added support for API tests

---
## [2.1.1]

### Added
- Added 'Stop Test Generation' button
- Added possibility to use same or different model for Text and Vision

### Changed
- Minor bug fixes