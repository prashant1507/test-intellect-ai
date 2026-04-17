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

## [1.0.1]

### Changed

- Fetch linked issues from JIRA for the requirement (configured test issue type); show priority and workflow status; rows matched to a linked issue are marked **EXISTING** and include the issue link.

