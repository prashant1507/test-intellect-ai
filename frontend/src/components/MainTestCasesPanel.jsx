import { AutomationSkeletonIconButton } from "./AutomationSkeletonModal";
import { Copy, FloatingTooltip, Spinner } from "./common";
import { JiraTestPushButton } from "./JiraTestPushButton";
import { TestCaseBody } from "./TestCaseBody";
import { TestCaseSummaryBadges } from "./TestCaseSummaryBadges";
import { changeStatusLabel, fmtTestsMarkdown, tcStatusSlug } from "../utils/format";
import { jiraPushFingerprint, resolvePushedJiraKey } from "../utils/jiraPushFingerprint";

function mainJiraPushCopy({
  pushedKey,
  mock,
  inputMode,
  jiraPushConfigIncomplete,
  isUpdatingJira,
  isPushing,
}) {
  const title = pushedKey
    ? `Added to JIRA as ${pushedKey}`
    : mock
      ? "JIRA push is disabled in mock mode"
      : inputMode !== "jira"
        ? "Use JIRA mode with a requirement ticket to push test cases"
        : jiraPushConfigIncomplete
          ? "Provide JIRA URL, username, password, and Test Project to add to JIRA"
          : "Create this test as a JIRA issue and link to the requirement";
  const ariaLabel = isUpdatingJira
    ? "Updating JIRA…"
    : isPushing
      ? "Adding to JIRA…"
      : pushedKey
        ? `Added to JIRA as ${pushedKey}`
        : "Add test case to JIRA";
  return { title, ariaLabel };
}

export function MainTestCasesPanel({
  loadingTestCases,
  tests,
  testsShown,
  hadPriorMemory,
  memoryMatch,
  tcFilter,
  onTcFilter,
  bulkJiraSync,
  onStartBulkSync,
  mock,
  inputMode,
  pushingKey,
  jiraPushConfigIncomplete,
  tcOpen,
  setTcOpen,
  mainRequirementKey,
  jiraUrl,
  jiraPushed,
  jiraHideUpdateAfterCreate,
  jiraUpdateSucceededKeys,
  pushTestToJira,
  onEditTestCase,
  onOpenMainAutomationSkeleton,
  setAnnounce,
  genOrBulkBusy,
}) {
  const setAllTc = (v) => () => tests?.length && setTcOpen(Object.fromEntries(tests.map((_, i) => [String(i), v])));

  return (
    <>
      {hadPriorMemory ? (
        <p className="meta">
          {memoryMatch === "similar"
            ? "Prior history was matched by similar requirements (not only the exact saved key). Tags reflect changes vs that saved snapshot."
            : "Prior history was used for this run"}
        </p>
      ) : null}

      {loadingTestCases ? (
        <div className="section-loading" role="status" aria-live="polite">
          <Spinner />
          <span>Generating test cases…</span>
        </div>
      ) : tests?.length ? (
        <>
          <div className="filter-bar filter-bar--with-sync" role="toolbar" aria-label="Filter by change status">
            <div className="filter-bar-chips">
              {["all", "existing", "unchanged", "updated", "new"].map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`chip ${tcFilter === f ? "active" : ""}`}
                  onClick={() => onTcFilter(f)}
                  aria-pressed={tcFilter === f}
                >
                  {f === "all" ? "All" : f === "existing" ? "Existing" : changeStatusLabel(f)}
                </button>
              ))}
            </div>
            <div className="filter-bar-sync-slot">
              {!bulkJiraSync?.running ? (
                <FloatingTooltip text="Add all to JIRA">
                  <button
                    type="button"
                    className="bulk-sync-icon-btn"
                    disabled={
                      mock ||
                      inputMode !== "jira" ||
                      pushingKey !== null ||
                      jiraPushConfigIncomplete ||
                      !testsShown.length
                    }
                    onClick={() => onStartBulkSync()}
                    aria-label="Add all to JIRA"
                  >
                    <svg
                      width="20"
                      height="20"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <path d="M12 15V3" />
                      <path d="m7 8 5-5 5 5" />
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    </svg>
                  </button>
                </FloatingTooltip>
              ) : null}
            </div>
          </div>
          {bulkJiraSync?.running ? (
            <div className="bulk-sync-progress-row" aria-live="polite">
              <div
                className="bulk-sync-progress-track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={bulkJiraSync.total}
                aria-valuenow={bulkJiraSync.current}
                aria-label={`${bulkJiraSync.current} of ${bulkJiraSync.total}`}
              >
                <div
                  className="bulk-sync-progress-fill"
                  style={{
                    width: `${bulkJiraSync.total ? Math.min(100, (bulkJiraSync.current / bulkJiraSync.total) * 100) : 0}%`,
                  }}
                />
              </div>
              <span className="bulk-sync-progress-count">
                {bulkJiraSync.current}/{bulkJiraSync.total}
              </span>
            </div>
          ) : null}
          <div className="expand-bar">
            <button type="button" className="linkish" onClick={setAllTc(true)}>
              Expand All
            </button>
            <button type="button" className="linkish" onClick={setAllTc(false)}>
              Collapse All
            </button>
          </div>
          {testsShown.length ? (
            testsShown.map((tc) => {
              const idx = tests.indexOf(tc);
              const tcKey = String(idx);
              const open = tcOpen[tcKey] !== false;
              const st = tcStatusSlug(tc.change_status);
              const jiraPushDisabled =
                mock ||
                inputMode !== "jira" ||
                pushingKey !== null ||
                jiraPushConfigIncomplete ||
                bulkJiraSync?.running;
              const mainPushKey = `main:${mainRequirementKey}:${jiraPushFingerprint(tc)}`;
              const pushedKey = resolvePushedJiraKey(tc, mainRequirementKey, jiraPushed, "main");
              const isUpdatingJira = pushingKey === `${mainPushKey}:u`;
              const isPushing = pushingKey === mainPushKey || isUpdatingJira;
              const { title: jiraPushTitle, ariaLabel: jiraPushLabel } = mainJiraPushCopy({
                pushedKey,
                mock,
                inputMode,
                jiraPushConfigIncomplete,
                isUpdatingJira,
                isPushing,
              });
              const jiraPushCommon = {
                disabled: jiraPushDisabled,
                isPushing,
                isUpdating: isUpdatingJira,
                pushedKey,
                jiraBaseUrl: jiraUrl,
                title: jiraPushTitle,
                ariaLabel: jiraPushLabel,
                onClick: (e) => {
                  e.stopPropagation();
                  pushTestToJira(tc, idx);
                },
              };
              return (
                <section key={tcKey} className={`tc status-${st}`}>
                  <div className="tc-summary-row">
                    <button
                      type="button"
                      className="tc-summary"
                      aria-expanded={open}
                      onClick={() => setTcOpen((prev) => ({ ...prev, [tcKey]: !open }))}
                    >
                      <span className="tc-chevron" aria-hidden>
                        {open ? "▼" : "▶"}
                      </span>
                      <TestCaseSummaryBadges tc={tc} statusSlug={st} />
                      <span className="tc-desc">{tc.description}</span>
                    </button>
                    <div className="tc-summary-actions">
                      {inputMode !== "paste" ? (
                        <FloatingTooltip text="Edit this test case">
                          <button
                            type="button"
                            className="tc-edit-icon-btn"
                            disabled={genOrBulkBusy}
                            onClick={(e) => {
                              e.stopPropagation();
                              onEditTestCase(idx);
                            }}
                            aria-label="Edit test case"
                          >
                            <svg
                              width="18"
                              height="18"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              aria-hidden
                            >
                              <path d="M12 20h9" />
                              <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
                            </svg>
                          </button>
                        </FloatingTooltip>
                      ) : null}
                      <AutomationSkeletonIconButton
                        disabled={genOrBulkBusy}
                        onClick={() => onOpenMainAutomationSkeleton(idx)}
                      />
                      {inputMode === "paste" ? (
                        <JiraTestPushButton
                          {...jiraPushCommon}
                          displayMode="linkOnly"
                          showUpdateButton={false}
                          onUpdate={undefined}
                        />
                      ) : (
                        <JiraTestPushButton
                          {...jiraPushCommon}
                          displayMode="default"
                          showUpdateButton={st === "updated" && !jiraHideUpdateAfterCreate[mainPushKey]}
                          updateTitle={
                            jiraUpdateSucceededKeys[mainPushKey]
                              ? `JIRA issue ${pushedKey || ""} was updated`
                              : `Update JIRA issue ${pushedKey || ""}`
                          }
                          updateAriaLabel="Update existing JIRA test issue"
                          updateSucceeded={!!jiraUpdateSucceededKeys[mainPushKey]}
                          onUpdate={
                            inputMode === "jira" && pushedKey
                              ? (e) => {
                                  e.stopPropagation();
                                  pushTestToJira(tc, idx, { updateExisting: true });
                                }
                              : undefined
                          }
                        />
                      )}
                      <FloatingTooltip text="Copy this test case as Markdown">
                        <Copy
                          text={fmtTestsMarkdown([tc])}
                          label="Copy this test case as Markdown"
                          onAnnounce={setAnnounce}
                          disabled={genOrBulkBusy}
                          omitTitle
                        />
                      </FloatingTooltip>
                    </div>
                  </div>
                  {open ? (
                    <div className="tc-body">
                      <TestCaseBody tc={tc} />
                    </div>
                  ) : null}
                </section>
              );
            })
          ) : (
            <p className="empty-state">
              No cases match this filter. Try <strong>All</strong>.
            </p>
          )}
        </>
      ) : (
        <p className="empty-state">
          <strong>No test cases yet.</strong>
        </p>
      )}
    </>
  );
}
