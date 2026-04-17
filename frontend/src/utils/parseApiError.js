export function parseApiError(d) {
  const x = d?.detail;
  if (typeof x === "string") return x;
  if (Array.isArray(x)) return x.map((e) => e.msg || e.message || JSON.stringify(e)).join("; ");
  if (x && typeof x === "object") return x.message || JSON.stringify(x);
  return "Request failed";
}
