import { AgenticPipelineOptions } from "./AgenticPipelineOptions";
import { FieldInfo } from "./common";
import { MinMaxTestCaseFields } from "./MinMaxTestCaseFields";

export function JiraGenerationFormFields({
  jiraTestProject,
  setJiraTestProject,
  jiraTestIssueType,
  setJiraTestIssueType,
  jiraLinkType,
  setJiraLinkType,
  minTestCases,
  maxTestCases,
  setMinTestCases,
  setMaxTestCases,
  parseMinTc,
  parseMaxTc,
  useAgenticGen,
  setUseAgenticGen,
  agenticMaxRounds,
  setAgenticMaxRounds,
}) {
  return (
    <>
      <div className="row cols-3 jira-credentials-row-equal">
        <div>
          <label htmlFor="jiraTestProject" className="label-with-info">
            <span>JIRA Test Project</span>
            <FieldInfo text="Project key where new test cases are created." />
          </label>
          <input
            id="jiraTestProject"
            value={jiraTestProject}
            onChange={(e) => setJiraTestProject(e.target.value)}
            placeholder=""
            autoComplete="off"
            aria-describedby="hint-jira-test-project"
          />
          <span id="hint-jira-test-project" className="sr-only">
            Project key where new test cases are created as JIRA issues.
          </span>
        </div>
        <div>
          <label htmlFor="jiraTestIssueType" className="label-with-info">
            <span>Test Issue Type</span>
            <FieldInfo text="Exact name of an issue type in your test project (e.g. Test, Task, or a custom type)." />
          </label>
          <input
            id="jiraTestIssueType"
            value={jiraTestIssueType}
            onChange={(e) => setJiraTestIssueType(e.target.value)}
            placeholder="Test"
            autoComplete="off"
            aria-describedby="hint-jira-test-issue-type"
          />
          <span id="hint-jira-test-issue-type" className="sr-only">
            Issue type name for created test issues; must exist in the JIRA test project.
          </span>
        </div>
        <div>
          <label htmlFor="jiraLinkType" className="label-with-info">
            <span>Issue Link Type</span>
            <FieldInfo text="Exact link type name from JIRA (Project settings → Issue linking). Often Relates — not the UI sentence “relates to”." />
          </label>
          <input
            id="jiraLinkType"
            value={jiraLinkType}
            onChange={(e) => setJiraLinkType(e.target.value)}
            placeholder="Relates"
            autoComplete="off"
            aria-describedby="hint-jira-link-type"
          />
          <span id="hint-jira-link-type" className="sr-only">
            JIRA issue link type name used when linking the new test issue to the requirement ticket.
          </span>
        </div>
      </div>
      <MinMaxTestCaseFields
        idPrefix="jira"
        layout="jiraCols3"
        minTestCases={minTestCases}
        maxTestCases={maxTestCases}
        onMinChange={setMinTestCases}
        onMaxChange={setMaxTestCases}
        parseMinTc={parseMinTc}
        parseMaxTc={parseMaxTc}
      />
      <AgenticPipelineOptions
        checked={useAgenticGen}
        onCheckedChange={setUseAgenticGen}
        maxRounds={agenticMaxRounds}
        onMaxRoundsChange={setAgenticMaxRounds}
        roundsInputId="agenticRoundsJira"
      />
    </>
  );
}
