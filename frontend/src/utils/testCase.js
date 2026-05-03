export function isUnifiedGherkin(tc) {
  const first = tc?.steps?.[0]?.trim?.();
  return (
    first?.startsWith("Given ") &&
    !String(tc?.preconditions || "").trim() &&
    !String(tc?.expected_result || "").trim()
  );
}

export function testCaseToSpikeBdd(tc) {
  if (!tc) return "";
  if (isUnifiedGherkin(tc)) return (tc.steps || []).join("\n");
  const parts = [];
  if (tc.preconditions) parts.push(tc.preconditions);
  (tc.steps || []).forEach((s) => parts.push(s));
  if (tc.expected_result) parts.push(tc.expected_result);
  return parts.join("\n");
}

function parseIntTc(s, fallback) {
  const n = parseInt(String(s ?? "").trim(), 10);
  return Number.isFinite(n) ? n : fallback;
}

export function parseMinTc(s) {
  return Math.max(1, parseIntTc(s, 1));
}

export function parseMaxTc(s) {
  const n = parseIntTc(String(s ?? "").trim(), NaN);
  return Number.isFinite(n) ? Math.max(1, n) : NaN;
}

export function validateTcBounds(minStr, maxStr) {
  const min_test_cases = parseIntTc(String(minStr ?? "").trim(), NaN);
  const max_test_cases = parseIntTc(String(maxStr ?? "").trim(), NaN);
  if (!Number.isFinite(min_test_cases) || min_test_cases < 1) {
    return {
      ok: false,
      message: "Minimum Test Cases must be a whole number of at least 1.",
    };
  }
  if (!Number.isFinite(max_test_cases) || max_test_cases < 1) {
    return {
      ok: false,
      message: "Maximum Test Cases must be a whole number of at least 1.",
    };
  }
  if (max_test_cases < min_test_cases) {
    return {
      ok: false,
      message: "Maximum Test Cases must be greater than or equal to Minimum Test Cases.",
    };
  }
  return { ok: true, min_test_cases, max_test_cases };
}

export function clampAgenticMaxRounds(s) {
  const n = parseInt(String(s ?? "").trim(), 10);
  const v = Number.isFinite(n) ? n : 3;
  return Math.min(10, Math.max(1, v));
}
