import { FieldInfo } from "./common";

const AGENT_STEP_LABEL = {
  planner: "Coverage Planner",
  generator: "Generator",
  parser: "Parser",
  validator: "Validator",
  suggestion_merge: "Suggestion Merge",
  auto_extend: "Auto Extend",
  finalize: "Finalize",
};

function pipelineStepStatus(agent, detail) {
  const d = String(detail || "").toLowerCase();
  const a = String(agent || "");
  if (a === "finalize") {
    if (d.includes("validation passed")) return "ok";
    if (d.includes("incomplete") || d.includes("no scenarios")) return "warn";
    return "neutral";
  }
  if (d.includes("parse failed after max") || d.includes("scoring json invalid")) return "err";
  if (d.includes("deterministic quality failed") || d.includes("retry scheduled")) return "warn";
  if (d.includes("parse error;")) return "warn";
  if (d.includes("validation incomplete")) return "warn";
  if (d.includes("parsed ") && d.includes("test case")) return "ok";
  if (d.includes("validation passed")) return "ok";
  if (a === "validator" && d.includes("passed (")) return "ok";
  if (a === "planner" && d.includes("fallback")) return "warn";
  if (a === "planner") return "ok";
  if (d.includes("skipped")) return "warn";
  return "neutral";
}

function statusGlyph(status) {
  if (status === "ok") return "✓";
  if (status === "err") return "✕";
  if (status === "warn") return "⚠";
  return "·";
}

function statusAria(status) {
  if (status === "ok") return "Success";
  if (status === "err") return "Failed";
  if (status === "warn") return "Warning";
  return "Info";
}

function buildPipelineTraceEntries(trace) {
  const entries = [];
  const seenGen = new Set();
  let stepNum = 0;
  for (let i = 0; i < trace.length; i++) {
    const row = trace[i];
    if (!row || typeof row !== "object") continue;
    const gen =
      row.generation != null && Number.isFinite(Number(row.generation)) ? Number(row.generation) : null;
    if (gen != null && !seenGen.has(gen)) {
      seenGen.add(gen);
      entries.push({ kind: "round", gen, key: `round-${gen}-${i}` });
    }
    stepNum += 1;
    entries.push({ kind: "step", row, index: i, key: `step-${i}`, stepNum });
  }
  return entries;
}

function formatDim(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return String(v);
}

function normalizeValidatorLine(raw) {
  if (raw == null) return "";
  const s = String(raw).trim();
  if (s.startsWith("{") && s.includes('"')) {
    try {
      const d = JSON.parse(s);
      if (d && typeof d === "object") {
        if (d.reason != null && (d.scenario_index != null || d.scenarioIndex != null)) {
          const idx = d.scenario_index != null ? d.scenario_index : d.scenarioIndex;
          const r = String(d.reason).trim();
          if (r) return `Scenario ${idx}: ${r}`;
        }
        if (d.suggestion != null) {
          const b = String(d.suggestion).trim();
          const r = d.requirement_ref != null ? String(d.requirement_ref).trim() : "";
          return r ? `${b} — ${r}` : b;
        }
        if (d.issue != null) {
          const b = String(d.issue).trim();
          const r = d.requirement_ref != null ? String(d.requirement_ref).trim() : "";
          const sev = d.severity != null ? String(d.severity).trim() : "";
          const lead = sev ? `[${sev}] ` : "";
          const tail = r ? ` (${r})` : "";
          return `${lead}${b}${tail}`;
        }
      }
    } catch {
      /* keep string */
    }
  }
  return s;
}

function capitalizeBulletLead(text) {
  const s = String(text ?? "").trim();
  if (!s) return s;
  let i = 0;
  while (i < s.length && !/[a-zA-Z]/.test(s[i])) i += 1;
  if (i >= s.length) return s;
  const ch = s[i];
  if (ch >= "a" && ch <= "z") {
    return s.slice(0, i) + ch.toUpperCase() + s.slice(i + 1);
  }
  return s;
}

function splitRunSummary(err) {
  const s = String(err || "").trim();
  if (!s) return [];
  const parts = s.split(/;\s+/).map((x) => x.trim()).filter(Boolean);
  return parts.length ? parts : [s];
}

function groupScenarioFollowUps(lines) {
  const groups = [];
  for (const raw of lines) {
    const line = String(raw ?? "").trim();
    if (!line) continue;
    if (/^scenario\s+\d+\s*:/i.test(line)) {
      groups.push({ lead: line, nested: [] });
    } else if (groups.length > 0) {
      groups[groups.length - 1].nested.push(line);
    } else {
      groups.push({ lead: line, nested: [] });
    }
  }
  return groups;
}

function calloutHeadingAndBullets(err) {
  const parts = splitRunSummary(err);
  if (
    parts.length >= 2 &&
    parts[0].toLowerCase() === "validation did not fully pass" &&
    parts[1].toLowerCase() === "returning best attempt"
  ) {
    return {
      heading: "Validation did not fully pass. Returning best attempt.",
      bullets: parts.slice(2).map(capitalizeBulletLead),
    };
  }
  return { heading: null, bullets: parts };
}

function formatPlannerCategory(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return "";
  return s
    .split(/_+|\s+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function validatorLineClass(text) {
  const t = String(text || "");
  return t.startsWith("Deterministic check:") ? "agentic-coverage-panel__issue--deterministic" : "";
}

export function AgenticCoveragePanel({ agentic }) {
  if (!agentic || typeof agentic !== "object") return null;

  const plan = agentic.coverage_plan;
  const items = Array.isArray(plan?.items) ? plan.items : [];
  const outOfScope = Array.isArray(plan?.out_of_scope) ? plan.out_of_scope.filter(Boolean) : [];
  const assumptions = Array.isArray(plan?.assumptions) ? plan.assumptions.filter(Boolean) : [];
  const v = agentic.validator;
  const dims = v?.dimensions;
  const gaps = Array.isArray(v?.coverage_gaps) ? v.coverage_gaps.filter((x) => String(x || "").trim()) : [];
  const passed = agentic.validation_passed === true;
  const rounds = agentic.generations;
  const err = agentic.error && String(agentic.error).trim();
  const trace = Array.isArray(agentic.agent_trace) ? agentic.agent_trace.filter(Boolean) : [];

  const showPlan = items.length > 0 || outOfScope.length > 0 || assumptions.length > 0;
  const showValidator = v && typeof v === "object";
  const pipelineEntries = trace.length ? buildPipelineTraceEntries(trace) : [];
  const calloutHB = err ? calloutHeadingAndBullets(err) : { heading: null, bullets: [] };
  const calloutGroups =
    calloutHB.heading && calloutHB.bullets.length ? groupScenarioFollowUps(calloutHB.bullets) : null;

  return (
    <details className="agentic-coverage-panel">
      <summary className="agentic-coverage-panel__summary">
        <span className="label-with-info">
          <span>Agentic Pipeline</span>
          <FieldInfo text="Planner coverage intent, ordered steps (who did what), validator scores, and coverage gaps vs the plan. Only when agentic generation is enabled." />
        </span>
        {agentic.validation_passed != null && (
          <span
            className={`agentic-coverage-panel__badge ${passed ? "agentic-coverage-panel__badge--ok" : "agentic-coverage-panel__badge--warn"}`}
          >
            {passed ? "Validation Passed" : "Validation Incomplete"}
          </span>
        )}
        {agentic.validation_passed == null && rounds != null ? (
          <span className="agentic-coverage-panel__badge agentic-coverage-panel__badge--muted">
            Rounds: {rounds}
          </span>
        ) : null}
      </summary>

      <div className="agentic-coverage-panel__body">
        {err ? (
          <div className="agentic-coverage-panel__callout" role="status">
            {calloutHB.heading ? (
              <p className="agentic-coverage-panel__callout-heading">{calloutHB.heading}</p>
            ) : null}
            {calloutHB.bullets.length ? (
              <ul
                className={
                  calloutHB.heading
                    ? "agentic-coverage-panel__callout-list agentic-coverage-panel__callout-list--below-heading"
                    : "agentic-coverage-panel__callout-list"
                }
              >
                {calloutGroups
                  ? calloutGroups.map((g, i) => (
                      <li key={i}>
                        {normalizeValidatorLine(g.lead)}
                        {g.nested.length ? (
                          <ul className="agentic-coverage-panel__callout-sublist">
                            {g.nested.map((line, j) => (
                              <li key={j}>{normalizeValidatorLine(line)}</li>
                            ))}
                          </ul>
                        ) : null}
                      </li>
                    ))
                  : calloutHB.bullets.map((line, i) => (
                      <li key={i}>{normalizeValidatorLine(line)}</li>
                    ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {trace.length ? (
          <details className="agentic-coverage-panel__block agentic-coverage-panel__trace-details">
            <summary className="agentic-coverage-panel__trace-summary">
              Pipeline Steps
              <span className="agentic-coverage-panel__trace-count">{trace.length}</span>
            </summary>
            <div className="agentic-coverage-trace" role="list">
              {pipelineEntries.map((entry) => {
                if (entry.kind === "round") {
                  return (
                    <div
                      key={entry.key}
                      className="agentic-coverage-trace__round"
                      role="presentation"
                    >
                      <span className="agentic-coverage-trace__round-label">Round {entry.gen}</span>
                    </div>
                  );
                }
                const row = entry.row;
                const id = row && typeof row === "object" ? String(row.agent || "").trim() : "";
                const label = AGENT_STEP_LABEL[id] || id || "Step";
                const detail =
                  row && typeof row === "object" && row.detail != null
                    ? String(row.detail).trim()
                    : "";
                const status = pipelineStepStatus(id, detail);
                const agentMod = id.replace(/[^a-z0-9_]/gi, "_") || "other";
                return (
                  <div
                    key={entry.key}
                    className={`agentic-coverage-trace__step agentic-coverage-trace__step--${status}`}
                    role="listitem"
                  >
                    <span className="agentic-coverage-trace__idx">{entry.stepNum}</span>
                    <span
                      className={`agentic-coverage-trace__glyph agentic-coverage-trace__glyph--${status}`}
                      aria-label={statusAria(status)}
                    >
                      {statusGlyph(status)}
                    </span>
                    <div className="agentic-coverage-trace__main">
                      <span
                        className={`agentic-coverage-trace__agent agentic-coverage-trace__agent--${agentMod}`}
                      >
                        {label}
                      </span>
                      {detail ? (
                        <span className="agentic-coverage-trace__what">{detail}</span>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </details>
        ) : null}

        {showPlan ? (
          <div className="agentic-coverage-panel__block">
            <h3 className="agentic-coverage-panel__h">Coverage Plan</h3>
            {items.length ? (
              <table className="agentic-coverage-table">
                <thead>
                  <tr>
                    <th scope="col">Id</th>
                    <th scope="col">Category</th>
                    <th scope="col">Intent</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row, i) => {
                    const id = row && typeof row === "object" ? String(row.id ?? "").trim() : "";
                    const cat =
                      row && typeof row === "object" ? String(row.category ?? "").trim() : "";
                    const catDisp = formatPlannerCategory(cat);
                    const intent =
                      row && typeof row === "object" ? String(row.intent ?? "").trim() : "";
                    return (
                      <tr key={id || `row-${i}`}>
                        <td className="mono">{id || "—"}</td>
                        <td>{catDisp || "—"}</td>
                        <td>{intent || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="meta">No planner items (requirements-only run or planner fallback).</p>
            )}
            {outOfScope.length ? (
              <>
                <h4 className="agentic-coverage-panel__subh">Out of scope</h4>
                <ul className="agentic-coverage-panel__list">
                  {outOfScope.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </>
            ) : null}
            {assumptions.length ? (
              <>
                <h4 className="agentic-coverage-panel__subh">Assumptions</h4>
                <ul className="agentic-coverage-panel__list">
                  {assumptions.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        ) : null}

        {gaps.length ? (
          <div className="agentic-coverage-panel__block agentic-coverage-panel__gaps">
            <h3 className="agentic-coverage-panel__h">Coverage gaps</h3>
            <p className="meta">Planner ids not fully reflected in the suite:</p>
            <ul className="agentic-coverage-panel__list agentic-coverage-panel__gap-ids">
              {gaps.map((id, i) => (
                <li key={i} className="mono">
                  {id}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {showValidator ? (
          <div className="agentic-coverage-panel__block">
            <h3 className="agentic-coverage-panel__h">Validator</h3>
            {dims && typeof dims === "object" ? (
              <dl className="agentic-coverage-dims">
                <div>
                  <dt>Traceability</dt>
                  <dd>{formatDim(dims.traceability)}</dd>
                </div>
                <div>
                  <dt>Coverage</dt>
                  <dd>{formatDim(dims.coverage)}</dd>
                </div>
                <div>
                  <dt>Gherkin</dt>
                  <dd>{formatDim(dims.gherkin_structure)}</dd>
                </div>
                <div>
                  <dt>Concrete</dt>
                  <dd>{formatDim(dims.concreteness)}</dd>
                </div>
                <div>
                  <dt>Non-redundant</dt>
                  <dd>{formatDim(dims.non_redundancy)}</dd>
                </div>
                {v.aggregate != null ? (
                  <div>
                    <dt>Weighted</dt>
                    <dd>{typeof v.aggregate === "number" ? v.aggregate.toFixed(2) : formatDim(v.aggregate)}</dd>
                  </div>
                ) : null}
              </dl>
            ) : null}
            {Array.isArray(v.must_fix) && v.must_fix.some((x) => String(x || "").trim()) ? (
              <>
                <h4 className="agentic-coverage-panel__subh">Must Fix</h4>
                <ul className="agentic-coverage-panel__issue-list agentic-coverage-panel__issue-list--bullets-plain">
                  {v.must_fix
                    .filter(Boolean)
                    .map((t, i) => {
                      const line = capitalizeBulletLead(normalizeValidatorLine(t));
                      return (
                        <li key={i} className={validatorLineClass(line)}>
                          {line}
                        </li>
                      );
                    })}
                </ul>
              </>
            ) : null}
            {Array.isArray(v.issues) && v.issues.some((x) => String(x || "").trim()) ? (
              <>
                <h4 className="agentic-coverage-panel__subh">Issues</h4>
                <ul className="agentic-coverage-panel__issue-list">
                  {v.issues
                    .filter(Boolean)
                    .map((t, i) => {
                      const line = normalizeValidatorLine(t);
                      return (
                        <li key={i} className={validatorLineClass(line)}>
                          {line}
                        </li>
                      );
                    })}
                </ul>
              </>
            ) : null}
            {Array.isArray(v.suggestions) && v.suggestions.some((x) => String(x || "").trim()) ? (
              <>
                <h4 className="agentic-coverage-panel__subh">Suggestions</h4>
                <ul className="agentic-coverage-panel__issue-list agentic-coverage-panel__issue-list--bullets-plain">
                  {v.suggestions
                    .filter(Boolean)
                    .map((t, i) => {
                      const line = normalizeValidatorLine(t);
                      return (
                        <li key={i} className={validatorLineClass(line)}>
                          {line}
                        </li>
                      );
                    })}
                </ul>
              </>
            ) : null}
          </div>
        ) : null}

        {agentic.suggestion_swap && typeof agentic.suggestion_swap === "object" && agentic.suggestion_swap.done ? (
          <p className="meta agentic-coverage-panel__swap">Suggestion swap applied to the suite.</p>
        ) : null}
      </div>
    </details>
  );
}
