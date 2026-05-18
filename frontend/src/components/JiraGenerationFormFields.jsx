import { AgenticPipelineOptions } from "./AgenticPipelineOptions";
import { FieldInfo } from "./common";
import { MinMaxTestCaseFields } from "./MinMaxTestCaseFields";

export function JiraGenerationFormFields({
  jiraTestProject,
  setJiraTestProject,
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
            <FieldInfo text="Project key where new test cases are created" />
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
        <MinMaxTestCaseFields
          idPrefix="jira"
          layout="bare"
          minTestCases={minTestCases}
          maxTestCases={maxTestCases}
          onMinChange={setMinTestCases}
          onMaxChange={setMaxTestCases}
          parseMinTc={parseMinTc}
          parseMaxTc={parseMaxTc}
        />
      </div>
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
