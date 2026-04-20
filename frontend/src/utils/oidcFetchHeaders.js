export async function withOidcAuthorization(headers, { useKeycloak, oidcMgr, oidcUser, setOidcUser }) {
  const h = { ...headers };
  if (useKeycloak && oidcMgr) {
    const fresh = await oidcMgr.getUser();
    if (fresh?.access_token && fresh.access_token !== oidcUser?.access_token) {
      setOidcUser(fresh);
    }
    if (fresh?.access_token) h.Authorization = `Bearer ${fresh.access_token}`;
  } else if (oidcUser?.access_token) {
    h.Authorization = `Bearer ${oidcUser.access_token}`;
  }
  return h;
}
