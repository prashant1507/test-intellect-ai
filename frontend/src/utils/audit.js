import { formatTime } from "./format";

const AUDIT_ACTION = {
  fetch_requirements: "Fetched Requirements",
  generate_test_cases: "Generated Test Cases",
  memory_update_test_cases: "Update saved history (priorities)",
  logged_in: "Logged In",
  logged_out: "Logged Out",
};

function normalizeTestCreateKey(a) {
  const s = String(a).trim();
  let m = /^Created Test (.+)$/.exec(s);
  if (m) return m[1].trim() || null;
  m = /^Test Created \| (.+)$/.exec(s);
  if (m) return m[1].trim() || null;
  m = /^Test Create \| (.+)$/.exec(s);
  if (m) return m[1].trim() || null;
  m = /^push_test_to_jira\s+(.+)$/.exec(s);
  if (m) return m[1].trim() || null;
  m = /^Test Created\s+(.+)$/.exec(s);
  if (m) return m[1].trim() || null;
  m = /^Test Create\s+(.+)$/.exec(s);
  if (m) return m[1].trim() || null;
  return null;
}

export function auditActionParts(a) {
  if (!a) return { type: "plain", text: "—" };
  if (AUDIT_ACTION[a]) return { type: "plain", text: AUDIT_ACTION[a] };
  const raw = String(a).trim();
  const updatedNew = /^Updated ([A-Z][A-Z0-9]*-\d+)$/i.exec(raw);
  if (updatedNew) {
    const k = updatedNew[1].trim().toUpperCase();
    if (k) return { type: "test_update", key: k };
  }
  const updatedLegacy = /^Updated Test\s+(.+)$/i.exec(raw);
  if (updatedLegacy) {
    const k = updatedLegacy[1].trim().toUpperCase();
    if (k) return { type: "test_update", key: k };
  }
  const editedNew = /^Edited ([A-Z][A-Z0-9]*-\d+)$/i.exec(raw);
  if (editedNew) {
    const k = editedNew[1].trim().toUpperCase();
    if (k) return { type: "test_edit", key: k };
  }
  const editedLegacy = /^Edited QA-(.+)$/i.exec(raw);
  if (editedLegacy) {
    const k = editedLegacy[1].trim().toUpperCase();
    if (k) return { type: "test_edit", key: k };
  }
  const createdNew = /^Created ([A-Z][A-Z0-9]*-\d+)$/i.exec(raw);
  if (createdNew) {
    const k = createdNew[1].trim().toUpperCase();
    if (k) return { type: "test_create", key: k };
  }
  const key = normalizeTestCreateKey(a);
  if (key) return { type: "test_create", key: key.toUpperCase() };
  return { type: "plain", text: a };
}

export const auditActionLabel = (a) => {
  const p = auditActionParts(a);
  if (p.type === "test_create") return `Created ${p.key}`;
  if (p.type === "test_update") return `Updated ${p.key}`;
  if (p.type === "test_edit") return `Edited ${p.key}`;
  return p.text;
};

export function jiraBrowseHref(baseUrl, key) {
  if (!baseUrl?.trim() || !key?.trim()) return null;
  try {
    const raw = baseUrl.trim();
    const u = new URL(raw.startsWith("http") ? raw : `https://${raw}`);
    const path = u.pathname.replace(/\/$/, "");
    u.pathname = `${path}/browse/${encodeURIComponent(key.trim())}`;
    return u.toString();
  } catch {
    return null;
  }
}

export const AUDIT_USER_EMPTY = "__empty__";
export const AUDIT_TICKET_EMPTY = "__empty_ticket__";

export async function downloadAuditPdf(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return;
  const [{ jsPDF }, { default: autoTable }] = await Promise.all([import("jspdf"), import("jspdf-autotable")]);
  const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
  doc.setFontSize(16);
  doc.text("Audit Records", 14, 16);
  doc.setFontSize(9);
  doc.setTextColor(80, 80, 80);
  doc.text(`Generated ${new Date().toLocaleString()}`, 14, 22);
  doc.setTextColor(0, 0, 0);
  autoTable(doc, {
    startY: 26,
    head: [["Date & time", "User", "Ticket ID", "Action"]],
    body: entries.map((row) => [
      formatTime(row.created_at),
      String(row.username || "—"),
      row.ticket_id === "AUTH" ? "—" : String(row.ticket_id || "—"),
      auditActionLabel(row.action),
    ]),
    styles: { fontSize: 8, cellPadding: 2 },
    headStyles: { fillColor: [55, 65, 81], fontStyle: "bold" },
    margin: { left: 14, right: 14 },
  });
  const safe = new Date().toISOString().slice(0, 10);
  doc.save(`audit-records-${safe}.pdf`);
}
