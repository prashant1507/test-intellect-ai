import { UserManager, WebStorageStateStore } from "oidc-client-ts";

export function clearOidcSessionStorageKeys() {
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const k = sessionStorage.key(i);
      if (k && k.startsWith("oidc.")) sessionStorage.removeItem(k);
    }
  } catch (_) {}
}

export async function postAuthAuditEvent(accessToken, event) {
  if (!accessToken || !["login", "logout"].includes(event)) return;
  try {
    await fetch("/api/audit/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ event }),
    });
  } catch (_) {}
}

export async function initKeycloakSession(cfg) {
  const base = (cfg.keycloak_url || "").replace(/\/$/, "");
  const r = `${window.location.origin}${window.location.pathname || "/"}`;
  const mgr = new UserManager({
    authority: `${base}/realms/${cfg.keycloak_realm || ""}`,
    client_id: cfg.keycloak_client_id || "",
    redirect_uri: r,
    post_logout_redirect_uri: r,
    response_type: "code",
    scope: "openid profile email",
    extraQueryParams: { prompt: "login" },
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: true,
    accessTokenExpiringNotificationTimeInSeconds: 60,
    silentRequestTimeoutInSeconds: 30,
  });

  const params = new URLSearchParams(window.location.search);
  const oauthErr = params.get("error");
  if (oauthErr) {
    let desc = params.get("error_description") || oauthErr;
    try {
      desc = decodeURIComponent(String(desc).replace(/\+/g, " "));
    } catch (_) {
      desc = String(desc);
    }
    window.history.replaceState({}, document.title, window.location.pathname);
    try {
      await mgr.removeUser();
      await mgr.clearStaleState();
    } catch (_) {}
    clearOidcSessionStorageKeys();
    throw new Error(`Sign-in was rejected: ${desc}`);
  }

  const isOAuthReturn = params.has("code") && params.has("state");
  if (isOAuthReturn) {
    try {
      const user = await mgr.signinRedirectCallback();
      window.history.replaceState({}, document.title, window.location.pathname);
      if (user?.access_token) {
        await postAuthAuditEvent(user.access_token, "login");
      }
      return { mgr, user };
    } catch (e) {
      window.history.replaceState({}, document.title, window.location.pathname);
      try {
        await mgr.removeUser();
        await mgr.clearStaleState();
      } catch (_) {}
      clearOidcSessionStorageKeys();
      const msg = e?.error_description || e?.message || String(e);
      throw new Error(
        `Keycloak login did not finish (token exchange). ${msg} — use “Clear sign-in state and retry” below, or confirm Keycloak uses a public client and this app’s URL is in Valid redirect URIs.`,
      );
    }
  }
  return { mgr, user: await mgr.getUser() };
}
