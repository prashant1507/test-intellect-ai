export function stripTestCaseDiffMeta(tc) {
  if (!tc || typeof tc !== "object") return tc;
  const out = { ...tc };
  for (const k of Object.keys(out)) {
    if (k.startsWith("previous_")) delete out[k];
  }
  return out;
}

export function settleUpdatedRowAfterPersist(tc) {
  return stripTestCaseDiffMeta(tc);
}

export function lineDiff(a, b) {
  const m = a.length;
  const n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j] ? 1 + dp[i + 1][j + 1] : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out = [];
  let i = 0;
  let j = 0;
  while (i < m || j < n) {
    if (i < m && j < n && a[i] === b[j]) {
      out.push({ t: "same", text: a[i] });
      i++;
      j++;
    } else if (j < n && (i === m || dp[i][j + 1] >= dp[i + 1][j])) {
      out.push({ t: "add", text: b[j] });
      j++;
    } else if (i < m) {
      out.push({ t: "remove", text: a[i] });
      i++;
    }
  }
  return out;
}

export function linesFromText(s) {
  return String(s ?? "").split(/\r?\n/);
}

export function normStepsArr(steps) {
  return Array.isArray(steps) ? steps.map((x) => String(x)) : [];
}

function textFieldDiffers(tc, pk, ck) {
  if (!(pk in tc)) return false;
  return String(tc[pk] ?? "").trim() !== String(tc[ck] ?? "").trim();
}

function stepsSnapshotDiffers(tc) {
  if (!("previous_steps" in tc)) return false;
  const o = normStepsArr(tc.previous_steps);
  const n = normStepsArr(tc.steps);
  return o.length !== n.length || o.some((v, idx) => v !== n[idx]);
}

export function hasRenderableUpdatedDiff(tc) {
  if (!tc || typeof tc !== "object") return false;
  if (String(tc.change_status || "").toLowerCase() !== "updated") return false;
  return (
    textFieldDiffers(tc, "previous_description", "description") ||
    textFieldDiffers(tc, "previous_preconditions", "preconditions") ||
    stepsSnapshotDiffers(tc) ||
    textFieldDiffers(tc, "previous_expected_result", "expected_result")
  );
}

export function hasDiffSnapshots(tc) {
  return hasRenderableUpdatedDiff(tc);
}
