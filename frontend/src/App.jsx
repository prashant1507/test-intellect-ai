import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clearOidcSessionStorageKeys, initKeycloakSession, postAuthAuditEvent } from "./auth/keycloak";
import {
  AuthBrandIcon,
  AuthPageShell,
  Copy,
  FieldInfo,
  FloatingTooltip,
  PasteRequirementsPreview,
  Spinner,
  ThemeToggle,
} from "./components/common";
import { AuditActionCell } from "./components/AuditActionCell";
import { JiraTestPushButton } from "./components/JiraTestPushButton";
import { PriorityTag } from "./components/PriorityTag";
import { MemoryDetailContent } from "./components/Memory";
import { TestCaseEditModal } from "./components/TestCaseEditModal";
import { TestCaseBody } from "./components/TestCaseBody";
import {
  AUDIT_TICKET_EMPTY,
  AUDIT_USER_EMPTY,
  auditActionLabel,
  downloadAuditPdf,
} from "./utils/audit";
import { changeStatusLabel, fmtReqMarkdown, fmtTestsMarkdown, formatTime, readTheme } from "./utils/format";
import { parseApiError } from "./utils/parseApiError";
import {
  jiraPushFingerprint,
  jiraPushedTitleKey,
  normDescForJira,
  resolvePushedJiraKey,
} from "./utils/jiraPushFingerprint";
import { loadJiraPushedMap, persistJiraPushedMap } from "./utils/jiraPushedStorage";
import { remapTestCasePriority } from "./utils/jiraPriorityRemap";
import { parseMinTc, parseMaxTc, testCaseBounds } from "./utils/testCase";

function readStoredJiraUrl() {
  try {
    return localStorage.getItem("jira-ai-jira-url") ?? "";
  } catch {
    return "";
  }
}

function readStoredJiraTestIssueType() {
  try {
    const v = localStorage.getItem("jira-ai-jira-test-issue-type");
    if (v !== null && String(v).trim()) return String(v).trim();
  } catch {}
  return "Test";
}

function readStoredJiraLinkType() {
  try {
    const v = localStorage.getItem("jira-ai-jira-link-type");
    if (v !== null && String(v).trim()) {
      const t = String(v).trim();
      if (t === "Relates to") return "Relates";
      return t;
    }
  } catch {}
  return "Relates";
}

export default function App() {
  const [theme, setTheme] = useState(readTheme);
  const [jiraUrl, setJiraUrl] = useState(readStoredJiraUrl);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [ticketId, setTicketId] = useState("");
  const [jiraTestProject, setJiraTestProject] = useState("");
  const [jiraTestIssueType, setJiraTestIssueType] = useState(readStoredJiraTestIssueType);
  const [jiraLinkType, setJiraLinkType] = useState(readStoredJiraLinkType);
  const [pushingKey, setPushingKey] = useState(null);
  const [jiraPushed, setJiraPushed] = useState(loadJiraPushedMap);
  const [jiraUpdateSucceededKeys, setJiraUpdateSucceededKeys] = useState({});
  const [jiraHideUpdateAfterCreate, setJiraHideUpdateAfterCreate] = useState({});
  const [bulkJiraSync, setBulkJiraSync] = useState(null);
  const [req, setReq] = useState(null);
  const [key, setKey] = useState("");
  const [tests, setTests] = useState(null);
  const [diff, setDiff] = useState(null);
  const [reqFetchMeta, setReqFetchMeta] = useState({ hadSavedMemory: false });
  const [diffExpanded, setDiffExpanded] = useState(false);
  const [hadPriorMemory, setHadPriorMemory] = useState(false);
  const [memoryMatch, setMemoryMatch] = useState(null);
  const [saveToMemory, setSaveToMemory] = useState(true);
  const [minTestCases, setMinTestCases] = useState("1");
  const [maxTestCases, setMaxTestCases] = useState("10");
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState("");
  const [lastFetchAt, setLastFetchAt] = useState(null);
  const [linkedJiraTests, setLinkedJiraTests] = useState([]);
  const [linkedJiraWork, setLinkedJiraWork] = useState([]);
  const [lastGenerateAt, setLastGenerateAt] = useState(null);
  const [mock, setMock] = useState(false);
  const [announce, setAnnounce] = useState("");
  const [tcFilter, setTcFilter] = useState("all");
  const [tcOpen, setTcOpen] = useState({});
  const [memoryEntries, setMemoryEntries] = useState([]);
  const [memoryFilter, setMemoryFilter] = useState("");
  const [auditEntries, setAuditEntries] = useState([]);
  const [auditModalOpen, setAuditModalOpen] = useState(false);
  const [editTcIdx, setEditTcIdx] = useState(null);
  const [auditFilters, setAuditFilters] = useState({ user: "", ticket: "", action: "" });
  const [showMemoryUi, setShowMemoryUi] = useState(true);
  const [showAuditUi, setShowAuditUi] = useState(true);
  const [bootPhase, setBootPhase] = useState("loading");
  const [bootError, setBootError] = useState("");
  const [useKeycloak, setUseKeycloak] = useState(false);
  const [oidcMgr, setOidcMgr] = useState(null);
  const [oidcUser, setOidcUser] = useState(null);
  const [idleTimeoutNotice, setIdleTimeoutNotice] = useState(false);
  const [idleMinutes, setIdleMinutes] = useState(5);
  const [inputMode, setInputMode] = useState("jira");
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [pasteMemoryKey, setPasteMemoryKey] = useState("");

  const [memoryPanel, setMemoryPanel] = useState(null);

  const testsRef = useRef(null);
  const jiraPushedRef = useRef(jiraPushed);
  const jiraHideUpdateAfterCreateRef = useRef(jiraHideUpdateAfterCreate);
  useEffect(() => {
    testsRef.current = tests;
  }, [tests]);
  useEffect(() => {
    jiraPushedRef.current = jiraPushed;
  }, [jiraPushed]);
  useEffect(() => {
    jiraHideUpdateAfterCreateRef.current = jiraHideUpdateAfterCreate;
  }, [jiraHideUpdateAfterCreate]);

  const generationInFlightRef = useRef(false);
  const redirectingToLoginRef = useRef(false);
  const jiraPriorityCacheRef = useRef(null);
  const jiraPriorityCacheKeyRef = useRef("");

  const redirectToKeycloakLogin = useCallback(async () => {
    if (!oidcMgr || redirectingToLoginRef.current) return;
    redirectingToLoginRef.current = true;
    try {
      try {
        sessionStorage.setItem("idle_timeout_notice", "1");
      } catch (_) {}
      try {
        const u = await oidcMgr.getUser();
        await postAuthAuditEvent(u?.access_token, "logout");
      } catch (_) {}
      try {
        await oidcMgr.removeUser();
      } catch (_) {}
      setOidcUser(null);
      await oidcMgr.signinRedirect();
    } catch (_) {
      redirectingToLoginRef.current = false;
    }
  }, [oidcMgr]);

  const applyGeneratePayload = (d) => {
    setReq(d.requirements);
    setKey(d.ticket_id);
    setTests(d.test_cases || []);
    setLinkedJiraTests(Array.isArray(d.linked_jira_tests) ? d.linked_jira_tests : []);
    setLinkedJiraWork(Array.isArray(d.linked_jira_work) ? d.linked_jira_work : []);
    setReqFetchMeta({ hadSavedMemory: false });
    setJiraUpdateSucceededKeys({});
    setJiraHideUpdateAfterCreate({});
    setDiff(d.requirements_diff || null);
    setDiffExpanded(false);
    setHadPriorMemory(!!d.had_previous_memory);
    setMemoryMatch(d.memory_match ?? null);
  };

  const auditUserOptions = useMemo(() => {
    const s = new Set(auditEntries.map((r) => r.username || ""));
    return [...s].sort((a, b) => (a || "\uFFFF").localeCompare(b || "\uFFFF"));
  }, [auditEntries]);

  const auditTicketOptions = useMemo(() => {
    const s = new Set(auditEntries.map((r) => String(r.ticket_id ?? "")));
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [auditEntries]);

  const auditActionOptions = useMemo(() => {
    const s = new Set(auditEntries.map((r) => r.action || ""));
    return [...s].filter(Boolean).sort((a, b) => auditActionLabel(a).localeCompare(auditActionLabel(b)));
  }, [auditEntries]);

  const filteredAuditEntries = useMemo(() => {
    return auditEntries.filter((row) => {
      if (auditFilters.user !== "") {
        const want = auditFilters.user === AUDIT_USER_EMPTY ? "" : auditFilters.user;
        if ((row.username || "") !== want) return false;
      }
      if (auditFilters.ticket !== "") {
        const want =
          auditFilters.ticket === AUDIT_TICKET_EMPTY ? "" : auditFilters.ticket;
        if (String(row.ticket_id ?? "") !== want) return false;
      }
      if (auditFilters.action !== "" && (row.action || "") !== auditFilters.action) return false;
      return true;
    });
  }, [auditEntries, auditFilters]);

  const cred = () => ({
    jira_url: jiraUrl,
    username,
    password,
    ticket_id: ticketId,
    jira_test_issue_type: jiraTestIssueType.trim(),
  });

  const api = useCallback(
    async (path, method = "GET", body, afterRefresh = false) => {
      const headers = {};
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (useKeycloak && oidcMgr) {
        const fresh = await oidcMgr.getUser();
        if (fresh?.access_token && fresh.access_token !== oidcUser?.access_token) {
          setOidcUser(fresh);
        }
        if (fresh?.access_token) headers.Authorization = `Bearer ${fresh.access_token}`;
      } else if (oidcUser?.access_token) {
        headers.Authorization = `Bearer ${oidcUser.access_token}`;
      }
      const r = await fetch(`/api${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      let d = {};
      try {
        d = await r.json();
      } catch {
        throw new Error(r.statusText || "Network error");
      }
      if (!r.ok) {
        if (r.status === 401 && useKeycloak && oidcMgr && !afterRefresh) {
          try {
            await oidcMgr.signinSilent();
            const u2 = await oidcMgr.getUser();
            if (u2?.access_token) {
              setOidcUser(u2);
              return api(path, method, body, true);
            }
          } catch (_) {}
          if (generationInFlightRef.current) {
            throw new Error(
              `${parseApiError(d)} — generation was not interrupted; sign in again in another tab if needed.`,
            );
          }
          await redirectToKeycloakLogin();
        }
        throw new Error(parseApiError(d));
      }
      return d;
    },
    [oidcUser, useKeycloak, oidcMgr, redirectToKeycloakLogin],
  );

  const syncLists = useCallback(async () => {
    try {
      if (showMemoryUi) {
        const m = await api("/memory/list");
        setMemoryEntries(Array.isArray(m.entries) ? m.entries : []);
      }
      if (showAuditUi) {
        const a = await api("/audit/list");
        setAuditEntries(Array.isArray(a.entries) ? a.entries : []);
      }
    } catch {
      setMemoryEntries([]);
      setAuditEntries([]);
    }
  }, [api, showMemoryUi, showAuditUi]);

  const openMemoryDetail = useCallback(
    async (tid) => {
      const key = (tid || "").trim();
      if (!key) return;
      setAuditModalOpen(false);
      setMemoryPanel({ phase: "loading", ticket_id: key });
      try {
        const d = await api(`/memory/item/${encodeURIComponent(key)}`);
        setMemoryPanel({
          phase: "ok",
          ticket_id: d.ticket_id,
          requirements: d.requirements,
          test_cases: d.test_cases,
        });
        setTicketId(d.ticket_id);
        setAnnounce(`History opened for ${d.ticket_id}.`);
      } catch (e) {
        setMemoryPanel({
          phase: "error",
          ticket_id: key,
          message: e.message || "Failed to load history.",
        });
      }
    },
    [api],
  );

  useEffect(() => {
    jiraPriorityCacheRef.current = null;
    jiraPriorityCacheKeyRef.current = "";
  }, [jiraUrl, username, password, jiraTestProject]);

  const ensureJiraPrioritiesMeta = useCallback(async () => {
    if (mock) return null;
    const key = `${jiraUrl.trim()}|${username}|${password}`;
    if (jiraPriorityCacheRef.current && jiraPriorityCacheKeyRef.current === key) {
      return jiraPriorityCacheRef.current;
    }
    const d = await api("/jira/priorities", "POST", {
      jira_url: jiraUrl.trim(),
      username,
      password,
      test_project_key: jiraTestProject.trim(),
    });
    jiraPriorityCacheRef.current = d;
    jiraPriorityCacheKeyRef.current = key;
    return d;
  }, [api, jiraUrl, username, password, jiraTestProject, mock]);

  const refreshMemoryPanelIfOpen = useCallback(
    async (ticketUpper) => {
      const key = String(ticketUpper || "").trim().toUpperCase();
      if (!key) return;
      try {
        const d = await api(`/memory/item/${encodeURIComponent(key)}`);
        setMemoryPanel((p) => {
          if (!p || p.phase !== "ok") return p;
          if (String(p.ticket_id || "").trim().toUpperCase() !== key) return p;
          return {
            phase: "ok",
            ticket_id: d.ticket_id,
            requirements: d.requirements,
            test_cases: d.test_cases,
          };
        });
      } catch {}
    },
    [api],
  );

  const pushTestToJira = useCallback(
    async (
      tc,
      idx,
      { scope = "main", memoryTicketId, updateExisting = false, bulkQuiet = false } = {},
    ) => {
      if (!bulkQuiet) setErr("");
      const tidForResolve =
        scope === "memory" && memoryTicketId
          ? String(memoryTicketId).trim().toUpperCase()
          : ticketId.trim().toUpperCase();
      if (!updateExisting && !jiraTestProject.trim()) {
        const msg = "JIRA Test Project is required to add a test case in JIRA.";
        if (!bulkQuiet) setErr(msg);
        return false;
      }
      if (scope !== "memory" && inputMode !== "jira") {
        const msg = "Use JIRA mode with a requirement ticket to push test cases.";
        if (!bulkQuiet) setErr(msg);
        return false;
      }
      if (mock) {
        const msg = "Cannot push to JIRA in mock mode.";
        if (!bulkQuiet) setErr(msg);
        return false;
      }
      const rk =
        scope === "memory" && memoryTicketId
          ? String(memoryTicketId).trim().toUpperCase()
          : ticketId.trim().toUpperCase();
      if (!rk) {
        const msg =
          scope === "memory"
            ? "This history entry has no requirement ticket id."
            : "Fill JIRA URL, requirement ticket, username, and password.";
        if (!bulkQuiet) setErr(msg);
        return false;
      }
      if (!jiraUrl.trim() || !username || !password) {
        const msg = "Fill JIRA URL, username, and password.";
        if (!bulkQuiet) setErr(msg);
        return false;
      }
      const fp = jiraPushFingerprint(tc);
      const tid = scope === "memory" && memoryTicketId ? String(memoryTicketId).trim().toUpperCase() : rk;
      const prefix = scope === "memory" ? "mem" : "main";
      const pushKey = `${prefix}:${tid}:${fp}`;
      const descKey = `${prefix}:${tid}:d:${normDescForJira(tc)}`;
      const titleKey = jiraPushedTitleKey(rk, tc);
      const otherPrefix = scope === "memory" ? "main" : "mem";
      const mirrorPush = `${otherPrefix}:${rk}:${fp}`;
      const mirrorDesc = `${otherPrefix}:${rk}:d:${normDescForJira(tc)}`;
      const scopeTag = scope === "memory" ? "mem" : "main";
      const existingKey = resolvePushedJiraKey(tc, tidForResolve, jiraPushedRef.current, scopeTag);
      if (updateExisting) {
        if (!existingKey) {
          const msg = "This scenario is not linked to a JIRA issue. Add it first with +.";
          if (!bulkQuiet) setErr(msg);
          return false;
        }
      }
      const pushKeyOp = updateExisting ? `${pushKey}:u` : pushKey;
      setPushingKey(pushKeyOp);
      if (updateExisting) {
        setJiraUpdateSucceededKeys((prev) => {
          const next = { ...prev };
          delete next[pushKey];
          return next;
        });
      }
      let remappedForMemory = null;
      try {
        let tcToSend = tc;
        const testsSnapshot = testsRef.current;
        try {
          jiraPriorityCacheRef.current = null;
          jiraPriorityCacheKeyRef.current = "";
          const meta = await ensureJiraPrioritiesMeta();
          if (meta?.priorities?.length) {
            if (scope === "main" && Array.isArray(testsSnapshot) && testsSnapshot.length > 0) {
              const remapped = testsSnapshot.map((t) => remapTestCasePriority(t, meta));
              remappedForMemory = remapped;
              setTests(remapped);
              testsRef.current = remapped;
              tcToSend = remapped[idx] ?? remapTestCasePriority(tc, meta);
            } else {
              tcToSend = remapTestCasePriority(tc, meta);
            }
          }
        } catch {}
        const res = await api("/jira/push-test-case", "POST", {
          jira_url: jiraUrl,
          username,
          password,
          requirement_key: rk,
          test_project_key: updateExisting ? "" : jiraTestProject.trim(),
          jira_test_issue_type: jiraTestIssueType.trim() || "Test",
          jira_link_type: jiraLinkType.trim() || "Relates",
          test_case: tcToSend,
          existing_issue_key: updateExisting ? existingKey : "",
        });
        const createdKey = res.created_key;
        if (!bulkQuiet) {
          setAnnounce(
            res.updated ? `Updated JIRA issue ${createdKey}` : `Created JIRA issue ${createdKey}`,
          );
        }
        if (!updateExisting) {
          setJiraPushed((prev) => {
            const next = {
              ...prev,
              [pushKey]: createdKey,
              [descKey]: createdKey,
              [mirrorPush]: createdKey,
              [mirrorDesc]: createdKey,
            };
            if (titleKey) next[titleKey] = createdKey;
            jiraPushedRef.current = next;
            return next;
          });
          setJiraHideUpdateAfterCreate((prev) => {
            const next = {
              ...prev,
              [pushKey]: true,
              [mirrorPush]: true,
            };
            jiraHideUpdateAfterCreateRef.current = next;
            return next;
          });
        }
        const baseList =
          remappedForMemory && remappedForMemory.length ? remappedForMemory : testsRef.current;
        const withKey = (baseList || []).map((t, i) =>
          i === idx ? { ...t, jira_issue_key: createdKey } : t,
        );
        setTests(withKey);
        testsRef.current = withKey;
        if (updateExisting) {
          setJiraUpdateSucceededKeys((prev) => ({ ...prev, [pushKey]: true }));
          setJiraHideUpdateAfterCreate((prev) => {
            const next = { ...prev };
            delete next[pushKey];
            delete next[mirrorPush];
            jiraHideUpdateAfterCreateRef.current = next;
            return next;
          });
        }
        if (!updateExisting && scope === "main" && !mock) {
          try {
            if (bulkQuiet) {
              await api("/memory/update-test-cases", "POST", {
                ticket_id: rk,
                test_cases: withKey,
                requirements: req ?? {},
              });
            } else {
              await api("/memory/merge-test-case", "POST", {
                ticket_id: rk,
                requirements: req ?? {},
                test_case: withKey[idx] ?? tcToSend,
              });
            }
          } catch {}
        }
        await syncLists();
        await refreshMemoryPanelIfOpen(rk);
        return true;
      } catch (e) {
        const msg = e.message || "Failed to push test case to JIRA.";
        if (!bulkQuiet) setErr(msg);
        return false;
      } finally {
        setPushingKey(null);
      }
    },
    [
      api,
      ensureJiraPrioritiesMeta,
      jiraUrl,
      username,
      password,
      ticketId,
      jiraTestProject,
      jiraTestIssueType,
      jiraLinkType,
      inputMode,
      mock,
      req,
      syncLists,
      refreshMemoryPanelIfOpen,
    ],
  );

  const filterTestsByChip = useCallback(
    (list) => {
      if (!list?.length) return [];
      if (tcFilter === "all") return list;
      if (tcFilter === "existing") return list.filter((t) => t.jira_existing);
      return list.filter((t) => (t.change_status || "new").toLowerCase() === tcFilter);
    },
    [tcFilter],
  );

  const syncAllJiraBulk = useCallback(async () => {
    const shown = filterTestsByChip(tests);
    if (mock || inputMode !== "jira" || !ticketId.trim() || !jiraUrl.trim() || !username || !password) {
      setErr("Use JIRA mode and fill URL, ticket, username, and password.");
      return;
    }
    if (!jiraTestProject.trim()) {
      setErr("JIRA Test Project is required to sync test cases.");
      return;
    }
    if (!shown.length) {
      setErr("No test cases in the current filter to sync.");
      return;
    }
    setErr("");
    let created = 0;
    let updated = 0;
    let skipped = 0;
    let failed = 0;
    try {
      setBulkJiraSync({
        running: true,
        current: 0,
        total: shown.length,
        created: 0,
        updated: 0,
        skipped: 0,
        failed: 0,
      });
      const tidU = ticketId.trim().toUpperCase();
      for (let i = 0; i < shown.length; i++) {
      const tcRow = shown[i];
      const rowFp = jiraPushFingerprint(tcRow);
      const idx = testsRef.current.findIndex((t) => jiraPushFingerprint(t) === rowFp);
      if (idx < 0) {
        skipped += 1;
        setBulkJiraSync((s) =>
          s ? { ...s, current: i + 1, skipped } : s,
        );
        continue;
      }
      const tc = testsRef.current[idx];
      const st = (tc.change_status || "new").toLowerCase().replace(/_/g, "-");
      const mainPushKey = `main:${tidU}:${jiraPushFingerprint(tc)}`;
      const pushedKey = resolvePushedJiraKey(tc, ticketId, jiraPushedRef.current, "main");
      const hideUpd = jiraHideUpdateAfterCreateRef.current[mainPushKey];
      let updateExisting = false;
      if (pushedKey && st === "unchanged") {
        skipped += 1;
        setBulkJiraSync((s) => (s ? { ...s, current: i + 1, skipped } : s));
        continue;
      }
      if (pushedKey && st === "updated" && hideUpd) {
        skipped += 1;
        setBulkJiraSync((s) => (s ? { ...s, current: i + 1, skipped } : s));
        continue;
      }
      if (pushedKey && st === "updated" && !hideUpd) {
        updateExisting = true;
      } else if (!pushedKey) {
        updateExisting = false;
      } else {
        skipped += 1;
        setBulkJiraSync((s) => (s ? { ...s, current: i + 1, skipped } : s));
        continue;
      }
      setBulkJiraSync((s) => (s ? { ...s, current: i + 1 } : s));
      const ok = await pushTestToJira(tc, idx, { updateExisting, bulkQuiet: true });
      if (ok) {
        if (updateExisting) {
          updated += 1;
        } else {
          created += 1;
        }
        setBulkJiraSync((s) =>
          s ? { ...s, created, updated, skipped, failed } : s,
        );
      } else {
        failed += 1;
        setBulkJiraSync((s) =>
          s ? { ...s, created, updated, skipped, failed } : s,
        );
      }
      }
      const parts = [];
      if (created) parts.push(`${created} created`);
      if (updated) parts.push(`${updated} updated`);
      if (skipped) parts.push(`${skipped} skipped`);
      if (failed) parts.push(`${failed} failed`);
      setAnnounce(parts.length ? `JIRA sync: ${parts.join(", ")}.` : "JIRA sync finished.");
      if (failed) {
        setErr(
          `${failed} test case(s) could not be synced. Fix the issue or retry those rows individually.`,
        );
      }
    } finally {
      setBulkJiraSync(null);
    }
  }, [
    tests,
    tcFilter,
    mock,
    inputMode,
    ticketId,
    jiraUrl,
    username,
    password,
    jiraTestProject,
    pushTestToJira,
    filterTestsByChip,
  ]);

  const persistEditedTestCase = useCallback(
    async (idx, updatedTc) => {
      const oldTc = tests?.[idx];
      const tidU = (key || ticketId).trim().toUpperCase();
      const nextTc = { ...updatedTc, change_status: "updated" };
      const nextList = (tests || []).map((t, i) => (i === idx ? nextTc : t));
      setTests(nextList);
      setEditTcIdx(null);
      setAnnounce("Test case updated.");
      const jiraTestId = String(nextTc.jira_issue_key || "").trim();
      if (jiraTestId && oldTc && tidU) {
        const ofp = jiraPushFingerprint(oldTc);
        const nfp = jiraPushFingerprint(nextTc);
        const keysToClear = [
          `main:${tidU}:${ofp}`,
          `main:${tidU}:${nfp}`,
          `mem:${tidU}:${ofp}`,
          `mem:${tidU}:${nfp}`,
        ];
        setJiraHideUpdateAfterCreate((prev) => {
          const n = { ...prev };
          for (const k of keysToClear) delete n[k];
          return n;
        });
        setJiraUpdateSucceededKeys((prev) => {
          const n = { ...prev };
          for (const k of keysToClear) delete n[k];
          return n;
        });
      }
      if (!tidU || mock || !req) return;
      try {
        await api("/memory/save-after-edit", "POST", {
          ticket_id: tidU,
          requirements: req,
          test_cases: nextList,
          edited_jira_issue_key: jiraTestId,
        });
        setAnnounce("Test case saved.");
        await syncLists();
        await refreshMemoryPanelIfOpen(tidU);
      } catch (e) {
        setErr(e.message || "Failed to save.");
      }
    },
    [tests, key, ticketId, mock, req, api, syncLists, refreshMemoryPanelIfOpen],
  );

  const startBulkSync = useCallback(() => {
    if (mock || inputMode !== "jira" || !ticketId.trim() || !jiraUrl.trim() || !String(username || "").trim() || !password) {
      setErr("Use JIRA mode and fill URL, ticket, username, and password.");
      return;
    }
    if (!jiraTestProject.trim()) {
      setErr("JIRA Test Project is required to sync test cases.");
      return;
    }
    const shown = filterTestsByChip(tests);
    if (!shown.length) {
      setErr("No test cases in the current filter to sync.");
      return;
    }
    setErr("");
    void syncAllJiraBulk();
  }, [
    mock,
    inputMode,
    ticketId,
    jiraUrl,
    username,
    password,
    jiraTestProject,
    tests,
    tcFilter,
    syncAllJiraBulk,
    filterTestsByChip,
  ]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("theme", theme);
    } catch (_) {}
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const c = await fetch("/api/config").then((r) => r.json());
        if (cancelled) return;
        if (typeof c.default_jira_url === "string" && c.default_jira_url.trim())
          setJiraUrl(c.default_jira_url.trim());
        if (c.default_username) setUsername(c.default_username);
        if (typeof c.default_jira_test_project_key === "string") setJiraTestProject(c.default_jira_test_project_key);
        try {
          if (
            typeof c.default_jira_test_issue_type === "string" &&
            c.default_jira_test_issue_type &&
            !localStorage.getItem("jira-ai-jira-test-issue-type")
          ) {
            setJiraTestIssueType(c.default_jira_test_issue_type);
          }
        } catch {}
        try {
          if (
            typeof c.default_jira_link_type === "string" &&
            c.default_jira_link_type &&
            !localStorage.getItem("jira-ai-jira-link-type")
          ) {
            setJiraLinkType(c.default_jira_link_type);
          }
        } catch {}
        setMock(!!c.mock);
        if (typeof c.show_memory_ui === "boolean") setShowMemoryUi(c.show_memory_ui);
        if (typeof c.show_audit_ui === "boolean") setShowAuditUi(c.show_audit_ui);
        if (typeof c.keycloak_idle_timeout_minutes === "number") setIdleMinutes(c.keycloak_idle_timeout_minutes);
        if (c.use_keycloak) {
          setUseKeycloak(true);
          const { mgr, user } = await initKeycloakSession(c);
          if (cancelled) return;
          setOidcMgr(mgr);
          setOidcUser(user);
        } else {
          setUseKeycloak(false);
        }
        setBootPhase("ready");
      } catch (e) {
        if (!cancelled) {
          setBootError(e?.message || "Failed to start");
          setBootPhase("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (bootPhase !== "ready" || (useKeycloak && !oidcUser)) return;
    syncLists();
  }, [bootPhase, useKeycloak, oidcUser, syncLists]);

  useEffect(() => {
    if (!showMemoryUi) setMemoryPanel(null);
    if (!showAuditUi) setAuditModalOpen(false);
  }, [showMemoryUi, showAuditUi]);

  useEffect(() => {
    if (!auditModalOpen) setAuditFilters({ user: "", ticket: "", action: "" });
  }, [auditModalOpen]);

  useEffect(() => {
    if (mock) setSaveToMemory(false);
  }, [mock]);

  useEffect(() => {
    setTcOpen(tests?.length ? Object.fromEntries(tests.map((_, i) => [String(i), true])) : {});
  }, [tests]);

  useEffect(() => {
    persistJiraPushedMap(jiraPushed);
  }, [jiraPushed]);

  useEffect(() => {
    const tid = ticketId.trim().toUpperCase();
    if (!tid || !tests?.length) return;
    const fpSet = new Set(tests.map((tc) => jiraPushFingerprint(tc)));
    setJiraPushed((prev) => {
      const next = { ...prev };
      const prefix = `main:${tid}:`;
      for (const k of Object.keys(next)) {
        if (!k.startsWith(prefix)) continue;
        if (k.startsWith(`main:${tid}:d:`)) continue;
        const rest = k.slice(prefix.length);
        if (rest.startsWith("d:")) continue;
        if (!fpSet.has(rest)) delete next[k];
      }
      return next;
    });
  }, [tests, ticketId]);

  useEffect(() => {
    try {
      localStorage.setItem("jira-ai-jira-url", jiraUrl);
    } catch {}
  }, [jiraUrl]);

  useEffect(() => {
    try {
      localStorage.setItem("jira-ai-jira-test-issue-type", jiraTestIssueType);
    } catch {}
  }, [jiraTestIssueType]);

  useEffect(() => {
    try {
      localStorage.setItem("jira-ai-jira-link-type", jiraLinkType);
    } catch {}
  }, [jiraLinkType]);

  useEffect(() => {
    if (memoryPanel?.phase !== "ok") return;
    const tid = String(memoryPanel.ticket_id || "").trim().toUpperCase();
    if (!tid || !Array.isArray(memoryPanel.test_cases)) return;
    const fpSet = new Set(memoryPanel.test_cases.map((tc) => jiraPushFingerprint(tc)));
    setJiraPushed((prev) => {
      const next = { ...prev };
      const prefix = `mem:${tid}:`;
      for (const k of Object.keys(next)) {
        if (!k.startsWith(prefix)) continue;
        if (k.startsWith(`mem:${tid}:d:`)) continue;
        const rest = k.slice(prefix.length);
        if (rest.startsWith("d:")) continue;
        if (!fpSet.has(rest)) delete next[k];
      }
      return next;
    });
  }, [memoryPanel?.phase, memoryPanel?.ticket_id, memoryPanel?.test_cases]);

  useEffect(() => {
    const anyOpen = auditModalOpen || !!memoryPanel || editTcIdx != null;
    if (!anyOpen) return;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (editTcIdx != null) setEditTcIdx(null);
      else if (memoryPanel) setMemoryPanel(null);
      else setAuditModalOpen(false);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onDocPointerDown = (e) => {
      const auditDialog = document.getElementById("audit-dialog");
      const memoryDialog = document.getElementById("memory-dialog");
      const tcEditDialog = document.getElementById("tc-edit-dialog");
      if (editTcIdx != null && tcEditDialog && !tcEditDialog.contains(e.target)) {
        setEditTcIdx(null);
      }
      if (auditModalOpen && auditDialog && !auditDialog.contains(e.target)) {
        setAuditModalOpen(false);
      }
      if (memoryPanel && memoryDialog && !memoryDialog.contains(e.target)) {
        setMemoryPanel(null);
      }
    };
    const t = window.setTimeout(() => {
      document.addEventListener("pointerdown", onDocPointerDown, true);
    }, 0);

    return () => {
      window.clearTimeout(t);
      document.removeEventListener("pointerdown", onDocPointerDown, true);
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [auditModalOpen, memoryPanel, editTcIdx]);

  useEffect(() => {
    if (!oidcMgr || !useKeycloak) return undefined;
    const unsubSilent = oidcMgr.events.addSilentRenewError(() => {
      void redirectToKeycloakLogin();
    });
    const unsubExpired = oidcMgr.events.addAccessTokenExpired(async () => {
      try {
        await oidcMgr.signinSilent();
        const u = await oidcMgr.getUser();
        if (u?.access_token) {
          setOidcUser(u);
          return;
        }
      } catch (_) {}
      void redirectToKeycloakLogin();
    });
    return () => {
      unsubSilent();
      unsubExpired();
    };
  }, [oidcMgr, useKeycloak, redirectToKeycloakLogin]);

  useEffect(() => {
    if (!useKeycloak || !oidcUser) return undefined;
    if (busy === "/generate-tests" || busy === "/generate-from-paste") return undefined;
    const idleMs = idleMinutes * 60 * 1000;
    let last = Date.now();
    const bump = () => {
      last = Date.now();
    };
    const events = ["mousedown", "keydown", "scroll", "touchstart", "pointerdown"];
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }));
    const iv = window.setInterval(() => {
      if (Date.now() - last > idleMs) {
        void redirectToKeycloakLogin();
      }
    }, 5000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, bump));
      window.clearInterval(iv);
    };
  }, [useKeycloak, oidcUser, idleMinutes, busy, redirectToKeycloakLogin]);

  useEffect(() => {
    if (bootPhase !== "ready" || !oidcUser || !useKeycloak) return;
    try {
      if (sessionStorage.getItem("idle_timeout_notice") === "1") {
        sessionStorage.removeItem("idle_timeout_notice");
        setIdleTimeoutNotice(true);
      }
    } catch (_) {}
  }, [bootPhase, oidcUser, useKeycloak]);

  useEffect(() => {
    if (!idleTimeoutNotice) return undefined;
    const t = window.setTimeout(() => setIdleTimeoutNotice(false), 12000);
    return () => window.clearTimeout(t);
  }, [idleTimeoutNotice]);

  useEffect(() => {
    if (!auditModalOpen) return undefined;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [auditModalOpen]);

  useEffect(() => {
    if (!memoryPanel) return undefined;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [memoryPanel]);

  useEffect(() => {
    if (editTcIdx == null) return undefined;
    const id = requestAnimationFrame(() => {
      document.getElementById("app-theme-toggle")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(id);
  }, [editTcIdx]);

  const runPasteGenerate = async () => {
    const desc = pasteText.trim();
    if (!desc) return;
    setErr("");
    generationInFlightRef.current = true;
    setBusy("/generate-from-paste");
    setReq(null);
    setTests(null);
    setDiff(null);
    setHadPriorMemory(false);
    setMemoryMatch(null);
    setAnnounce("Generating test cases…");
    try {
      const d = await api("/generate-from-paste", "POST", {
        title: pasteTitle.trim(),
        description: desc,
        memory_key: pasteMemoryKey.trim(),
        save_memory: saveToMemory && !mock,
        ...testCaseBounds(minTestCases, maxTestCases),
      });
      applyGeneratePayload(d);
      setPasteMemoryKey(d.ticket_id);
      const now = new Date().toISOString();
      setLastGenerateAt(now);
      setLastFetchAt(now);
      setAnnounce("Test cases generated.");
      await syncLists();
      await refreshMemoryPanelIfOpen(String(d.ticket_id || "").trim().toUpperCase());
    } catch (e) {
      setErr(e.message || "Something went wrong.");
      setAnnounce("");
    } finally {
      generationInFlightRef.current = false;
      setBusy(null);
    }
  };

  const run = async (path) => {
    setErr("");
    setBusy(path);
    if (path === "/generate-tests") {
      generationInFlightRef.current = true;
    }
    try {
      if (path === "/generate-tests") {
        const credBody = cred();
        setReq(null);
        setTests(null);
        setDiff(null);
        setReqFetchMeta({ hadSavedMemory: false });
        setHadPriorMemory(false);
        setMemoryMatch(null);
        setAnnounce("Fetching requirements…");

        const fd = await api("/fetch-ticket", "POST", credBody);
        setReq(fd.requirements);
        setKey(fd.ticket_id);
        setLinkedJiraTests(Array.isArray(fd.linked_jira_tests) ? fd.linked_jira_tests : []);
        setLinkedJiraWork(Array.isArray(fd.linked_jira_work) ? fd.linked_jira_work : []);
        setLastFetchAt(new Date().toISOString());
        setAnnounce("Requirements loaded. Generating test cases…");

        const d = await api("/generate-tests", "POST", {
          ...credBody,
          test_project_key: jiraTestProject.trim(),
          save_memory: saveToMemory && !mock,
          ...testCaseBounds(minTestCases, maxTestCases),
        });
        applyGeneratePayload(d);
        setLastGenerateAt(new Date().toISOString());
        setAnnounce("Test cases generated.");
        await syncLists();
        await refreshMemoryPanelIfOpen(String(d.ticket_id || "").trim().toUpperCase());
        return;
      }

      if (path === "/fetch-ticket") {
        const d = await api("/fetch-ticket", "POST", cred());
        setReq(d.requirements);
        setKey(d.ticket_id);
        setLinkedJiraTests(Array.isArray(d.linked_jira_tests) ? d.linked_jira_tests : []);
        setLinkedJiraWork(Array.isArray(d.linked_jira_work) ? d.linked_jira_work : []);
        setReqFetchMeta({ hadSavedMemory: !!d.had_saved_memory });
        setDiff(d.requirements_diff != null && d.requirements_diff !== "" ? d.requirements_diff : null);
        setDiffExpanded(false);
        setLastFetchAt(new Date().toISOString());
        if (d.had_saved_memory && d.requirements_diff) {
          setAnnounce("Requirements loaded. Diff vs saved history is shown below.");
        } else if (d.had_saved_memory) {
          setAnnounce("Requirements loaded. No text changes vs saved history.");
        } else {
          setAnnounce("Requirements loaded.");
        }
        await syncLists();
        return;
      }
    } catch (e) {
      setErr(e.message || "Something went wrong.");
      setAnnounce("");
    } finally {
      if (path === "/generate-tests") {
        generationInFlightRef.current = false;
      }
      setBusy(null);
    }
  };

  const canSubmit = jiraUrl.trim() && ticketId.trim() && username.trim() && password;
  const canSubmitPaste = pasteText.trim().length > 0;
  const mf = memoryFilter.trim().toLowerCase();
  const memItems = mf ? memoryEntries.filter((e) => (e.ticket_id || "").toLowerCase().includes(mf)) : memoryEntries;
  const testsShown = filterTestsByChip(tests);
  const linkedWorkHeadingTypes = useMemo(() => {
    const set = new Set();
    for (const row of linkedJiraWork || []) {
      const t = String(row.issue_type_name || "").trim();
      if (t) set.add(t);
    }
    return [...set].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" })).join(", ");
  }, [linkedJiraWork]);
  const diffLong = diff && diff.length > 600;
  const diffShown = diffLong && !diffExpanded ? `${diff.slice(0, 600)}…` : diff;
  const setAllTc = (v) => () => tests?.length && setTcOpen(Object.fromEntries(tests.map((_, i) => [String(i), v])));

  const loadingRequirements =
    busy === "/fetch-ticket" || (busy === "/generate-tests" && !req) || busy === "/generate-from-paste";
  const loadingTestCases = (busy === "/generate-tests" && !!req) || busy === "/generate-from-paste";
  const generatingTestCases = busy === "/generate-tests" || busy === "/generate-from-paste";

  const jiraPushConfigIncomplete =
    !jiraUrl.trim() ||
    !String(username || "").trim() ||
    !password ||
    !jiraTestProject.trim();
  const memoryPushTicketId =
    memoryPanel?.phase === "ok" ? String(memoryPanel.ticket_id || "").trim().toUpperCase() || null : null;

  if (bootPhase === "loading") {
    return (
      <AuthPageShell theme={theme} setTheme={setTheme}>
        <div className="auth-panel card auth-panel--loading" role="status">
          <Spinner />
          <p className="auth-loading-text">Loading…</p>
        </div>
      </AuthPageShell>
    );
  }
  if (bootPhase === "error") {
    return (
      <AuthPageShell theme={theme} setTheme={setTheme}>
        <div className="auth-panel card auth-panel--error" role="alert">
          <h1 className="auth-panel-title">Something went wrong</h1>
          <p className="auth-error-detail">{bootError}</p>
          <p className="auth-error-hint">
            If Keycloak showed an internal error, check Keycloak and Postgres logs. Stale browser sign-in data can also break the next attempt — try clearing it and reloading.
          </p>
          <button
            type="button"
            className="primary auth-signin-btn"
            onClick={() => {
              clearOidcSessionStorageKeys();
              window.location.reload();
            }}
          >
            Clear sign-in state and retry
          </button>
        </div>
      </AuthPageShell>
    );
  }
  if (useKeycloak && !oidcUser) {
    return (
      <AuthPageShell theme={theme} setTheme={setTheme}>
        <div className="auth-panel card auth-panel--login">
          <AuthBrandIcon />
          <h1 className="auth-panel-title">Test Intellect AI</h1>
          <p className="auth-subtitle">Sign in using Keycloak to access the panel</p>
          <button type="button" className="primary auth-signin-btn" onClick={() => oidcMgr.signinRedirect()}>
            Continue to sign in
          </button>
        </div>
      </AuthPageShell>
    );
  }

  return (
    <div className="app">
      <a
        href="#main"
        className="skip-link"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
          window.history.replaceState(null, "", "#main");
        }}
      >
        Skip to content
      </a>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announce}
      </div>

      <header className="app-header">
        <h1>Test Intellect AI</h1>
        <div className="app-header-actions">
          {useKeycloak && oidcUser ? (
            <>
              <span className="auth-user-label">
                {oidcUser.profile?.preferred_username || oidcUser.profile?.name || oidcUser.profile?.email || "Signed in"}
              </span>
              <button
                type="button"
                className="logout-icon-btn"
                onClick={() => {
                  postAuthAuditEvent(oidcUser?.access_token, "logout").finally(() => {
                    oidcMgr?.signoutRedirect();
                  });
                }}
                title="Log out"
                aria-label="Log out"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
              </button>
            </>
          ) : null}
          <ThemeToggle id="app-theme-toggle" theme={theme} setTheme={setTheme} />
        </div>
      </header>

      {mock ? (
        <div className="mock-banner" role="status">
          <strong>Mock JIRA mode.</strong> Fetch uses built-in sample requirements (no JIRA). Set <code>MOCK=false</code> in <code>.env</code> for a real server.
        </div>
      ) : null}

      {useKeycloak && idleTimeoutNotice ? (
        <div className="session-timeout-banner" role="status" aria-live="polite">
          Session timeout. Login again.
        </div>
      ) : null}

      <div
        className={`layout-shell${showMemoryUi || showAuditUi ? "" : " layout-shell--no-sidebar"}`}
      >
        {showMemoryUi || showAuditUi ? (
          <aside
            className="sidebar"
            aria-label={
              showMemoryUi && showAuditUi
                ? "Audit records and history"
                : showMemoryUi
                  ? "History"
                  : "Audit records"
            }
          >
            {showAuditUi ? (
              <details
                className="sidebar-audit-details"
                onToggle={(e) => {
                  if (e.currentTarget.open) {
                    e.currentTarget.open = false;
                    syncLists();
                    setMemoryPanel(null);
                    setAuditModalOpen(true);
                  }
                }}
              >
                <summary className="sidebar-audit-summary">Audit Records</summary>
              </details>
            ) : null}

            {showMemoryUi ? (
              <div className={showAuditUi ? "sidebar-memory-section" : undefined}>
                <h2 className="sidebar-title">History</h2>
                {memoryEntries.length === 0 ? (
                  <p className="sidebar-empty">No saved history yet. Generate with save enabled.</p>
                ) : (
                  <>
                    <div className="memory-filter">
                      <label htmlFor="memoryFilter" className="label-with-info">
                        <span>Filter by Ticket</span>
                        <FieldInfo text="Narrows the saved history list by requirement ticket id." />
                      </label>
                      <input
                        id="memoryFilter"
                        type="search"
                        value={memoryFilter}
                        onChange={(e) => setMemoryFilter(e.target.value)}
                        placeholder="Requirement Ticket ID"
                        autoComplete="off"
                        spellCheck={false}
                        aria-describedby="hint-memory-filter"
                      />
                      <span id="hint-memory-filter" className="sr-only">
                        Narrows the saved history list by requirement ticket id.
                      </span>
                    </div>
                    <div className="memory-list-scroll">
                      {memItems.length === 0 ? (
                        <p className="sidebar-empty memory-list-empty">No entries match this filter.</p>
                      ) : (
                        <ul className="memory-list">
                          {memItems.map((e) => {
                            const cur = ticketId.trim().toUpperCase() === (e.ticket_id || "").toUpperCase();
                            return (
                              <li key={e.ticket_id}>
                                <button
                                  type="button"
                                  className={`memory-item ${cur ? "current" : ""}`}
                                  onClick={() => {
                                    setTicketId(e.ticket_id);
                                    openMemoryDetail(e.ticket_id);
                                  }}
                                  title="Open saved history (requirements and test cases)"
                                >
                                  <div className="memory-item-top">
                                    <span className="memory-ticket-line">{e.ticket_id}</span>
                                    <span className="memory-title-line">{e.title || "—"}</span>
                                  </div>
                                  <span className="memory-meta">
                                    {e.test_case_count} case{e.test_case_count === 1 ? "" : "s"} ·{" "}
                                    {formatTime(e.updated_at)}
                                  </span>
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  </>
                )}
              </div>
            ) : null}
          </aside>
        ) : null}

        <div className="layout-main">
          <main id="main" className="main-area" tabIndex={-1}>
          {showAuditUi && auditModalOpen ? (
            <div
              className="modal-backdrop modal-backdrop--main-area"
              role="presentation"
              onClick={() => setAuditModalOpen(false)}
            >
              <div
                id="audit-dialog"
                className="modal-dialog modal-dialog-audit"
                role="dialog"
                aria-modal="true"
                aria-labelledby="audit-dialog-title"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="modal-dialog-head">
                  <h2 id="audit-dialog-title" className="modal-dialog-title">
                    Audit Records
                  </h2>
                  <div className="modal-dialog-head-actions">
                    <button
                      type="button"
                      className="modal-dialog-icon-btn"
                      onClick={() => downloadAuditPdf(filteredAuditEntries)}
                      disabled={filteredAuditEntries.length === 0}
                      title="Download as PDF"
                      aria-label="Download filtered audit records as PDF"
                    >
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      className="modal-dialog-close"
                      onClick={() => setAuditModalOpen(false)}
                      aria-label="Close audit records"
                    >
                      ×
                    </button>
                  </div>
                </div>
                {auditEntries.length > 0 ? (
                  <div className="audit-filters" role="group" aria-label="Filter audit records">
                    <div className="audit-filter-field">
                      <label htmlFor="audit-filter-user" className="label-with-info">
                        <span>User</span>
                        <FieldInfo text="Filter rows by who performed the action." />
                      </label>
                      <select
                        id="audit-filter-user"
                        className="audit-filter-select"
                        value={auditFilters.user}
                        onChange={(e) => setAuditFilters((f) => ({ ...f, user: e.target.value }))}
                      >
                        <option value="">All users</option>
                        {auditUserOptions.map((u) => (
                          <option key={u === "" ? AUDIT_USER_EMPTY : u} value={u === "" ? AUDIT_USER_EMPTY : u}>
                            {u || "—"}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="audit-filter-field">
                      <label htmlFor="audit-filter-ticket" className="label-with-info">
                        <span>Ticket ID</span>
                        <FieldInfo text="Filter by requirement or JIRA ticket key." />
                      </label>
                      <select
                        id="audit-filter-ticket"
                        className="audit-filter-select"
                        value={auditFilters.ticket}
                        onChange={(e) => setAuditFilters((f) => ({ ...f, ticket: e.target.value }))}
                      >
                        <option value="">All tickets</option>
                        {auditTicketOptions.map((tid) => (
                          <option
                            key={tid === "" ? "tid-empty" : tid}
                            value={tid === "" ? AUDIT_TICKET_EMPTY : tid}
                          >
                            {tid === "AUTH" ? "—" : tid || "—"}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="audit-filter-field">
                      <label htmlFor="audit-filter-action" className="label-with-info">
                        <span>Action</span>
                        <FieldInfo text="Filter by the type of audit event." />
                      </label>
                      <select
                        id="audit-filter-action"
                        className="audit-filter-select"
                        value={auditFilters.action}
                        onChange={(e) => setAuditFilters((f) => ({ ...f, action: e.target.value }))}
                      >
                        <option value="">All actions</option>
                        {auditActionOptions.map((act) => (
                          <option key={act} value={act}>
                            {auditActionLabel(act)}
                          </option>
                        ))}
                      </select>
                    </div>
                    {(auditFilters.user || auditFilters.ticket || auditFilters.action) ? (
                      <button
                        type="button"
                        className="audit-filters-clear"
                        onClick={() => setAuditFilters({ user: "", ticket: "", action: "" })}
                      >
                        Clear filters
                      </button>
                    ) : null}
                  </div>
                ) : null}
                <div className="audit-table-wrap">
                  {auditEntries.length === 0 ? (
                    <p className="audit-empty">
                      No audit entries yet.
                    </p>
                  ) : filteredAuditEntries.length === 0 ? (
                    <p className="audit-empty">No audit entries match the selected filters.</p>
                  ) : (
                    <table className="audit-table">
                      <thead>
                        <tr>
                          <th scope="col">Date &amp; time</th>
                          <th scope="col">User</th>
                          <th scope="col">Ticket ID</th>
                          <th scope="col">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredAuditEntries.map((row, i) => (
                          <tr key={`${row.created_at}-${row.ticket_id}-${row.action}-${i}`}>
                            <td>{formatTime(row.created_at)}</td>
                            <td>{row.username || "—"}</td>
                            <td>
                              {row.ticket_id === "AUTH" ? (
                                <span className="audit-context-muted">—</span>
                              ) : (
                                <code className="audit-ticket">{row.ticket_id}</code>
                              )}
                            </td>
                            <td>
                              <AuditActionCell action={row.action} jiraBaseUrl={jiraUrl} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            </div>
          ) : null}

          {editTcIdx != null && tests?.[editTcIdx] ? (
            <div
              className="modal-backdrop modal-backdrop--main-area"
              role="presentation"
              onClick={() => setEditTcIdx(null)}
            >
              <div
                id="tc-edit-dialog"
                className="modal-dialog modal-dialog-tc-edit"
                role="dialog"
                aria-modal="true"
                aria-labelledby="tc-edit-title"
                onClick={(e) => e.stopPropagation()}
              >
                <TestCaseEditModal
                  tc={tests[editTcIdx]}
                  onClose={() => setEditTcIdx(null)}
                  onSave={(next) => void persistEditedTestCase(editTcIdx, next)}
                />
              </div>
            </div>
          ) : null}

          {showMemoryUi && memoryPanel ? (
            <div
              className="modal-backdrop modal-backdrop--main-area"
              role="presentation"
              onClick={() => setMemoryPanel(null)}
            >
              <div
                id="memory-dialog"
                className="modal-dialog modal-dialog-memory"
                role="dialog"
                aria-modal="true"
                aria-labelledby="memory-dialog-title"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="modal-dialog-head">
                  <h2 id="memory-dialog-title" className="modal-dialog-title">
                    Saved History · {memoryPanel.ticket_id}
                    {memoryPanel.phase === "loading" ? " (loading…)" : ""}
                  </h2>
                  <button
                    type="button"
                    className="modal-dialog-close"
                    onClick={() => setMemoryPanel(null)}
                    aria-label="Close saved history"
                  >
                    ×
                  </button>
                </div>
                <div className="modal-dialog-memory-body">
                  <MemoryDetailContent
                    memoryPanel={memoryPanel}
                    onAnnounce={setAnnounce}
                    memoryTicketId={memoryPushTicketId}
                    jiraUrl={jiraUrl}
                    jiraPushed={jiraPushed}
                  />
                </div>
              </div>
            </div>
          ) : null}

          <div className="card form-card">
            <div className="mode-switch" role="tablist" aria-label="Requirement source">
              <button
                type="button"
                role="tab"
                aria-selected={inputMode === "jira"}
                className={`mode-tab${inputMode === "jira" ? " active" : ""}`}
                onClick={() => {
                  setInputMode("jira");
                  setErr("");
                }}
              >
                JIRA
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={inputMode === "paste"}
                className={`mode-tab${inputMode === "paste" ? " active" : ""}`}
                onClick={() => {
                  setInputMode("paste");
                  setErr("");
                  setEditTcIdx(null);
                  setLinkedJiraTests([]);
                  setLinkedJiraWork([]);
                }}
              >
                Paste Requirements
              </button>
            </div>
            <fieldset
              disabled={generatingTestCases}
              className="form-card-fieldset"
              aria-busy={generatingTestCases}
            >
            {inputMode === "paste" ? (
              <>
                <div className="row cols-2">
                  <div>
                    <label htmlFor="pasteTitle" className="label-with-info">
                      <span>Title (optional)</span>
                      <FieldInfo text="Optional short label for this pasted requirement in history." />
                    </label>
                    <input
                      id="pasteTitle"
                      value={pasteTitle}
                      onChange={(e) => setPasteTitle(e.target.value)}
                      placeholder=""
                      autoComplete="off"
                    />
                  </div>
                  <div>
                    <label htmlFor="pasteMemoryKey" className="label-with-info">
                      <span>Save as Key (Optional)</span>
                      <FieldInfo text="Stable key for history and diffs; leave empty to auto-generate." />
                    </label>
                    <input
                      id="pasteMemoryKey"
                      value={pasteMemoryKey}
                      onChange={(e) => setPasteMemoryKey(e.target.value)}
                      placeholder=""
                      autoComplete="off"
                      aria-describedby="hint-paste-key"
                    />
                    <span id="hint-paste-key" className="sr-only">
                      Stable key for history and diffs; leave empty to auto-generate.
                    </span>
                  </div>
                </div>
                <div className="row">
                  <label htmlFor="pasteText" className="label-with-info">
                    <span>Requirements</span>
                    <FieldInfo text="Text the model uses to generate tests; Markdown is supported." />
                  </label>
                  <textarea
                    id="pasteText"
                    className="paste-requirements-textarea"
                    value={pasteText}
                    onChange={(e) => setPasteText(e.target.value)}
                    placeholder="Paste plain text or Markdown (headings, lists, tables, code)…"
                    rows={2}
                    aria-required="true"
                    aria-describedby="hint-paste-preview"
                  />
                  <span id="hint-paste-preview" className="sr-only">
                    Text the model uses to generate tests; Markdown is supported.
                  </span>
                  <PasteRequirementsPreview text={pasteText} />
                </div>
                <div className="row cols-2">
                  <div>
                    <label htmlFor="minTc" className="label-with-info">
                      <span>Minimum Test Cases</span>
                      <FieldInfo text="Lower bound on how many scenarios the model returns." />
                    </label>
                    <input
                      id="minTc"
                      type="text"
                      inputMode="numeric"
                      autoComplete="off"
                      value={minTestCases}
                      onChange={(e) => setMinTestCases(e.target.value)}
                      onBlur={() => setMinTestCases(String(parseMinTc(minTestCases)))}
                    />
                  </div>
                  <div>
                    <label htmlFor="maxTc" className="label-with-info">
                      <span>Maximum Test Cases</span>
                      <FieldInfo text="Upper cap on scenarios; 0 means no limit." />
                    </label>
                    <input
                      id="maxTc"
                      type="text"
                      inputMode="numeric"
                      autoComplete="off"
                      value={maxTestCases}
                      onChange={(e) => setMaxTestCases(e.target.value)}
                      onBlur={() => setMaxTestCases(String(parseMaxTc(maxTestCases)))}
                      aria-describedby="hint-max-tc"
                    />
                    <span id="hint-max-tc" className="sr-only">
                      Upper cap on scenarios; 0 means no limit.
                    </span>
                  </div>
                </div>
              </>
            ) : (
              <>
            <div className="row cols-2 jira-form-split">
              <div className="jira-form-col-stack">
                <div>
                  <label htmlFor="jiraUrl" className="label-with-info">
                    <span>JIRA URL</span>
                    <FieldInfo text="Your JIRA site base URL (e.g. https://company.atlassian.net)." />
                  </label>
                  <input
                    id="jiraUrl"
                    value={jiraUrl}
                    onChange={(e) => setJiraUrl(e.target.value)}
                    placeholder=""
                    autoComplete="url"
                    required
                    aria-required="true"
                    aria-describedby="hint-jira"
                  />
                  <span id="hint-jira" className="sr-only">
                    Your JIRA site base URL (e.g. https://company.atlassian.net).
                  </span>
                </div>
                <div>
                  <label htmlFor="username" className="label-with-info">
                    <span>JIRA Username</span>
                    <FieldInfo text="Login name or email for JIRA API access." />
                  </label>
                  <input
                    id="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    required
                    aria-required="true"
                    aria-describedby="hint-user"
                  />
                  <span id="hint-user" className="sr-only">
                    Login name or email for JIRA API access.
                  </span>
                </div>
                <div>
                  <label htmlFor="password" className="label-with-info">
                    <span>JIRA Password / Token</span>
                    <FieldInfo text="Account password or API token." />
                  </label>
                  <div className="input-with-toggle">
                    <input
                      id="password"
                      type={showPw ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoComplete="current-password"
                      required
                      aria-required="true"
                      aria-describedby="hint-pw"
                    />
                    <span id="hint-pw" className="sr-only">
                      Account password or API token.
                    </span>
                    <button
                      type="button"
                      className="pw-toggle"
                      onClick={() => setShowPw((v) => !v)}
                      aria-pressed={showPw}
                      aria-label={showPw ? "Hide password" : "Show password"}
                      title={showPw ? "Hide" : "Show"}
                    >
                      {showPw ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                          <line x1="1" y1="1" x2="23" y2="23" />
                        </svg>
                      ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                          <circle cx="12" cy="12" r="3" />
                        </svg>
                      )}
                    </button>
                  </div>
                </div>
                <div>
                  <label htmlFor="minTc" className="label-with-info">
                    <span>Minimum Test Cases</span>
                    <FieldInfo text="Lower bound on how many scenarios the model returns." />
                  </label>
                  <input
                    id="minTc"
                    type="text"
                    inputMode="numeric"
                    autoComplete="off"
                    value={minTestCases}
                    onChange={(e) => setMinTestCases(e.target.value)}
                    onBlur={() => setMinTestCases(String(parseMinTc(minTestCases)))}
                  />
                </div>
                <div>
                  <label htmlFor="maxTc" className="label-with-info">
                    <span>Maximum Test Cases</span>
                    <FieldInfo text="Upper cap on scenarios; 0 means no limit." />
                  </label>
                  <input
                    id="maxTc"
                    type="text"
                    inputMode="numeric"
                    autoComplete="off"
                    value={maxTestCases}
                    onChange={(e) => setMaxTestCases(e.target.value)}
                    onBlur={() => setMaxTestCases(String(parseMaxTc(maxTestCases)))}
                    aria-describedby="hint-max-tc"
                  />
                  <span id="hint-max-tc" className="sr-only">
                    Upper cap on scenarios; 0 means no limit.
                  </span>
                </div>
              </div>
              <div className="jira-form-col-stack">
                <div>
                  <label htmlFor="ticketId" className="label-with-info">
                    <span>Requirement Ticket ID</span>
                    <FieldInfo text="Requirement / Story ticket ID." />
                  </label>
                  <input
                    id="ticketId"
                    value={ticketId}
                    onChange={(e) => setTicketId(e.target.value)}
                    placeholder=""
                    required
                    aria-required="true"
                    aria-describedby="hint-ticket"
                  />
                  <span id="hint-ticket" className="sr-only">
                    Requirement / Story ticket ID.
                  </span>
                </div>
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
            </div>
              </>
            )}
            <label className={`check check-save-memory${mock ? " check-disabled" : ""}`}>
              <input
                type="checkbox"
                checked={saveToMemory}
                disabled={mock}
                onChange={(e) => setSaveToMemory(e.target.checked)}
              />
              <span className="check-save-memory-text" role="note">
                Save generated tests to history. 'Test Intellect AI' is an AI tool and can make mistakes.
              </span>
              {mock ? <span className="check-hint"> (disabled in mock mode)</span> : null}
            </label>
            <div className="actions">
              {inputMode === "jira" ? (
                <>
                  <button
                    type="button"
                    className="secondary has-icon"
                    disabled={busy === "/fetch-ticket" || !canSubmit}
                    onClick={() => run("/fetch-ticket")}
                    title={!canSubmit ? "Fill all fields first" : undefined}
                  >
                    {busy === "/fetch-ticket" ? <Spinner /> : null}
                    {busy === "/fetch-ticket" ? "Fetching…" : "Fetch Requirements"}
                  </button>
                  <button
                    type="button"
                    className="primary has-icon"
                    disabled={busy === "/generate-tests" || !canSubmit}
                    onClick={() => run("/generate-tests")}
                    title={!canSubmit ? "Fill all fields first" : undefined}
                  >
                    {busy === "/generate-tests" ? <Spinner /> : null}
                    {busy === "/generate-tests" ? "Generating…" : "Generate Test Cases"}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="primary has-icon"
                  disabled={busy === "/generate-from-paste" || !canSubmitPaste}
                  onClick={() => runPasteGenerate()}
                  title={!canSubmitPaste ? "Paste requirements first" : undefined}
                >
                  {busy === "/generate-from-paste" ? <Spinner /> : null}
                  {busy === "/generate-from-paste" ? "Generating…" : "Generate Test Cases"}
                </button>
              )}
            </div>
            {inputMode === "jira" && !canSubmit ? (
              <p className="form-hint-warn">Complete every field above to enable actions.</p>
            ) : null}
            {inputMode === "paste" && !canSubmitPaste ? (
              <p className="form-hint-warn">Paste requirement text to enable generation.</p>
            ) : null}
            {err ? (
              <div className="err" role="alert">
                <strong>Error.</strong> {err}
              </div>
            ) : null}
            </fieldset>
          </div>

          {inputMode !== "paste" ? (
            <div className="card section-card section-requirements">
              <div className="head">
                <div>
                  <h2>Requirements {key ? `(${key})` : ""}</h2>
                  {lastFetchAt ? <p className="last-run">Last loaded {formatTime(lastFetchAt)}</p> : null}
                </div>
                <Copy text={fmtReqMarkdown(req)} label="Copy as Markdown" onAnnounce={setAnnounce} />
              </div>
              {loadingRequirements ? (
                <div className="section-loading" role="status" aria-live="polite">
                  <Spinner />
                  <span>Loading requirements…</span>
                </div>
              ) : req ? (
                <>
                  <PasteRequirementsPreview text={fmtReqMarkdown(req)} />
                  {inputMode === "jira" && linkedJiraTests?.length ? (
                    <div className="linked-jira-tests" role="region" aria-label="Linked JIRA test issues">
                      <h3 className="linked-jira-tests-title">
                        Linked {jiraTestIssueType.trim() || "Test"}
                      </h3>
                      <ul className="linked-jira-tests-list">
                        {linkedJiraTests.map((row) => {
                          const title = String(row.summary || "").trim() || "—";
                          const st = String(row.status_name || "").trim();
                          const p = String(row.priority || "").trim();
                          const pUrl = row.priority_icon_url ? String(row.priority_icon_url).trim() : "";
                          return (
                            <li key={row.issue_key} className="linked-jira-tests-line">
                              <div className="linked-jira-tests-item">
                                <div className="linked-jira-tests-head">
                                  <a
                                    className="linked-jira-tests-key"
                                    href={row.browse_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {row.issue_key}
                                  </a>
                                  {p || pUrl ? (
                                    <PriorityTag priority={p} iconUrl={pUrl || undefined} />
                                  ) : null}
                                  {st ? (
                                    <span className="linked-jira-tests-status">{st}</span>
                                  ) : null}
                                </div>
                                <p className="linked-jira-tests-summary">{title}</p>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null}
                  {inputMode === "jira" && linkedJiraWork?.length ? (
                    <div className="linked-jira-tests" role="region" aria-label="Linked JIRA work items">
                      <h3 className="linked-jira-tests-title">
                        Linked Issues ({linkedWorkHeadingTypes || "—"})
                      </h3>
                      <ul className="linked-jira-tests-list">
                        {linkedJiraWork.map((row) => {
                          const title = String(row.summary || "").trim() || "—";
                          const it = String(row.issue_type_name || "").trim();
                          const st = String(row.status_name || "").trim();
                          return (
                            <li key={row.issue_key} className="linked-jira-tests-line">
                              <div className="linked-jira-tests-item">
                                <div className="linked-jira-tests-head">
                                  <a
                                    className="linked-jira-tests-key"
                                    href={row.browse_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {row.issue_key}
                                  </a>
                                  {it ? (
                                    <span className="linked-jira-work-type">{it}</span>
                                  ) : null}
                                  {st ? (
                                    <span className="linked-jira-tests-status">{st}</span>
                                  ) : null}
                                </div>
                                <p className="linked-jira-tests-summary">{title}</p>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null}
                  {inputMode === "jira" && reqFetchMeta.hadSavedMemory && !diff ? (
                    <p className="meta req-fetch-hint" role="status">
                      No text changes vs last saved history for this ticket.
                    </p>
                  ) : null}
                </>
              ) : (
                <p className="empty-state">
                  <strong>No requirements yet.</strong>
                </p>
              )}
            </div>
          ) : null}

          {diff ? (
            <div className="card">
              <div className="head">
                <h2>Requirements Diff</h2>
                <Copy text={diff} label="Copy diff" onAnnounce={setAnnounce} />
              </div>
              <p className="meta">Changes compared to the last saved requirements in history for this ticket.</p>
              <pre className="block mono diff-block" tabIndex={0}>
                {diffShown}
              </pre>
              {diffLong ? (
                <button type="button" className="linkish" onClick={() => setDiffExpanded((e) => !e)}>
                  {diffExpanded ? "Show less" : "Show full diff"}
                </button>
              ) : null}
            </div>
          ) : null}

          <div className="card section-card section-test-cases">
            <div className="head">
              <div>
                <h2>Test Cases</h2>
                {lastGenerateAt ? <p className="last-run">Last Generated {formatTime(lastGenerateAt)}</p> : null}
              </div>
              <Copy text={fmtTestsMarkdown(tests)} label="Copy as Markdown" onAnnounce={setAnnounce} />
            </div>
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
                        onClick={() => setTcFilter(f)}
                        aria-pressed={tcFilter === f}
                      >
                        {f === "all"
                          ? "All"
                          : f === "existing"
                            ? "Existing"
                            : changeStatusLabel(f)}
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
                          onClick={() => startBulkSync()}
                          aria-label="Add all to JIRA"
                        >
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
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
                    <span className="bulk-sync-progress-count">{bulkJiraSync.current}/{bulkJiraSync.total}</span>
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
                    const st = (tc.change_status || "new").replace("_", "-");
                    const jiraPushDisabled =
                      mock ||
                      inputMode !== "jira" ||
                      pushingKey !== null ||
                      jiraPushConfigIncomplete ||
                      bulkJiraSync?.running;
                    const mainPushKey = `main:${ticketId.trim().toUpperCase()}:${jiraPushFingerprint(tc)}`;
                    const pushedKey = resolvePushedJiraKey(tc, ticketId, jiraPushed, "main");
                    const isUpdatingJira = pushingKey === `${mainPushKey}:u`;
                    const isPushing = pushingKey === mainPushKey || isUpdatingJira;
                    const jiraPushTitle = pushedKey
                      ? `Added to JIRA as ${pushedKey}`
                      : mock
                        ? "JIRA push is disabled in mock mode"
                        : inputMode !== "jira"
                          ? "Use JIRA mode with a requirement ticket to push test cases"
                          : jiraPushConfigIncomplete
                            ? "Provide JIRA URL, username, password, and Test Project to add to JIRA"
                            : "Create this test as a JIRA issue and link to the requirement";
                    const jiraPushLabel = isUpdatingJira
                      ? "Updating JIRA…"
                      : isPushing
                        ? "Adding to JIRA…"
                        : pushedKey
                          ? `Added to JIRA as ${pushedKey}`
                          : "Add test case to JIRA";
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
                            <span className={`badge badge--tc-${st}`}>{changeStatusLabel(tc.change_status)}</span>
                            {tc.jira_existing ? (
                              <FloatingTooltip text="Already in JIRA">
                                <span className="badge badge--jira-existing">EXISTING</span>
                              </FloatingTooltip>
                            ) : null}
                            {tc.jira_status ? (
                              <FloatingTooltip text="Workflow Status">
                                <span className="tc-jira-status">{tc.jira_status}</span>
                              </FloatingTooltip>
                            ) : null}
                            <PriorityTag priority={tc.priority} iconUrl={tc.priority_icon_url} />
                            <span className="tc-desc">{tc.description}</span>
                          </button>
                          {inputMode !== "paste" ? (
                            <div className="tc-summary-actions">
                              <FloatingTooltip text="Edit this test case">
                                <button
                                  type="button"
                                  className="tc-edit-icon-btn"
                                  disabled={generatingTestCases || bulkJiraSync?.running}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setEditTcIdx(idx);
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
                          <JiraTestPushButton
                            displayMode="default"
                            disabled={jiraPushDisabled}
                            isPushing={isPushing}
                            isUpdating={isUpdatingJira}
                            pushedKey={pushedKey}
                            showUpdateButton={
                              st === "updated" && !jiraHideUpdateAfterCreate[mainPushKey]
                            }
                            jiraBaseUrl={jiraUrl}
                            title={jiraPushTitle}
                            ariaLabel={jiraPushLabel}
                            updateTitle={
                              jiraUpdateSucceededKeys[mainPushKey]
                                ? `JIRA issue ${pushedKey || ""} was updated`
                                : `Update JIRA issue ${pushedKey || ""}`
                            }
                            updateAriaLabel="Update existing JIRA test issue"
                            updateSucceeded={!!jiraUpdateSucceededKeys[mainPushKey]}
                            onClick={(e) => {
                              e.stopPropagation();
                              pushTestToJira(tc, idx);
                            }}
                            onUpdate={
                              inputMode === "jira" && pushedKey
                                ? (e) => {
                                    e.stopPropagation();
                                    pushTestToJira(tc, idx, { updateExisting: true });
                                  }
                                : undefined
                            }
                          />
                            </div>
                          ) : (
                          <JiraTestPushButton
                            displayMode="linkOnly"
                            disabled={jiraPushDisabled}
                            isPushing={isPushing}
                            isUpdating={isUpdatingJira}
                            pushedKey={pushedKey}
                            showUpdateButton={false}
                            jiraBaseUrl={jiraUrl}
                            title={jiraPushTitle}
                            ariaLabel={jiraPushLabel}
                            onClick={(e) => {
                              e.stopPropagation();
                              pushTestToJira(tc, idx);
                            }}
                            onUpdate={undefined}
                          />
                          )}
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
                  <p className="empty-state">No cases match this filter. Try <strong>All</strong>.</p>
                )}
              </>
            ) : (
              <p className="empty-state">
                <strong>No test cases yet.</strong>
              </p>
            )}
          </div>
          </main>
        </div>
      </div>
    </div>
  );
}
