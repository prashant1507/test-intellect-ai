export function isUnifiedGherkin(tc) {
  const first = tc?.steps?.[0]?.trim?.();
  return (
    first?.startsWith("Given ") &&
    !String(tc?.preconditions || "").trim() &&
    !String(tc?.expected_result || "").trim()
  );
}

export function parseMinTc(s) {
  const n = parseInt(String(s ?? "").trim(), 10);
  if (!Number.isFinite(n)) return 1;
  return Math.max(1, n);
}

export function parseMaxTc(s) {
  const n = parseInt(String(s ?? "").trim(), 10);
  if (!Number.isFinite(n)) return 10;
  return Math.max(0, n);
}

export function testCaseBounds(minStr, maxStr) {
  const min_test_cases = parseMinTc(minStr);
  let max_test_cases = parseMaxTc(maxStr);
  if (max_test_cases > 0 && max_test_cases < min_test_cases) {
    max_test_cases = min_test_cases;
  }
  return { min_test_cases, max_test_cases };
}

export function clampAgenticMaxRounds(s) {
  const n = parseInt(String(s ?? "").trim(), 10);
  const v = Number.isFinite(n) ? n : 5;
  return Math.min(10, Math.max(1, v));
}
