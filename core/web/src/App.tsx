/**
 * The shell (checkpoint B-2, ruling D-103.1; extended at B-1).
 *
 * It does four things: ask the server who the session is, ask the server
 * which modules that identity sees, ask the server what has come back to
 * this person (the F-10 inbox), and render whichever screen the URL
 * names. It decides nothing. There is no role name in this file, no
 * comparison against one, and no module list of its own — the sidebar is
 * whatever `/v1/dashboard/modules` returned, and a module the server did
 * not return has no route here to reach.
 *
 * If someone types a module path anyway, the module's own API answers —
 * with data or with a 403, which renders as the server's own words. The
 * client is never the thing that says no (UI-1).
 *
 * The inbox badge is the one number in the chrome, and it is the
 * server's: `unread` from `/v1/dashboard/inbox`, scoped to the session's
 * own subject server-side (UI-D / D-103.2). It is not computed here and
 * it could not be — nothing about who filed what is in this file.
 */

import React, { useCallback, useEffect, useState } from "react";
import { api, type ApiError, type Inbox as InboxData, type Module, type ModuleMap, type Session } from "./api";
import { Connections } from "./Connections";
import { GapTriage } from "./GapTriage";
import { Inbox } from "./Inbox";
import { KbHealth } from "./KbHealth";
import { Ops } from "./Ops";
import { Publish } from "./Publish";
import { Dark, ServerSays, Spinner, Text } from "./ui";

const BASE = "/app";

function currentPath(): string {
  const path = window.location.pathname;
  return path.startsWith(BASE) ? path.slice(BASE.length) || "/" : "/";
}

interface ScreenProps {
  csrf: string | null;
  inbox: InboxData | null;
  reloadInbox: () => void;
}

/** The registry of screens that exist in this bundle. A module the
 * server sends that has no entry here renders its own dark state — that
 * is the honest shape while Track B is mid-build. */
const SCREENS: Record<string, (props: ScreenProps) => React.ReactNode> = {
  connections: ({ csrf }) => <Connections csrf={csrf} />,
  kb_health: () => <KbHealth />,
  gap_triage: ({ csrf }) => <GapTriage csrf={csrf} />,
  publish: () => <Publish />,
  ops: ({ csrf }) => <Ops csrf={csrf} />,
};

/** The inbox is not a `dashboard.yaml` module — it is the reply path
 * every identity has, whatever modules their roles show them. */
const INBOX_ROUTE = "/inbox";

function SignedOut({ error }: { error: ApiError }) {
  const login = `/v1/auth/login?redirect=${encodeURIComponent(window.location.pathname)}`;
  return (
    <div className="signed-out">
      <h1>Context Layer</h1>
      <p>
        {error.status === 401
          ? "You are not signed in."
          : "The core could not confirm your session."}
      </p>
      <ServerSays error={error} />
      <p>
        <a className="button" href={login}>
          Sign in
        </a>
      </p>
    </div>
  );
}

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [map, setMap] = useState<ModuleMap | null>(null);
  const [inbox, setInbox] = useState<InboxData | null>(null);
  const [authError, setAuthError] = useState<ApiError | null>(null);
  const [route, setRoute] = useState(currentPath());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const onPop = () => setRoute(currentPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const loadInbox = useCallback(async () => {
    const res = await api.get<InboxData>("/v1/dashboard/inbox");
    // An inbox that cannot be read is not an error worth blocking the
    // shell for: the badge simply does not appear, and the modules the
    // person came for still render.
    if (res.ok) setInbox(res.data);
  }, []);

  const boot = useCallback(async () => {
    const s = await api.get<Session>("/v1/auth/session");
    if (!s.ok) {
      setAuthError(s.error);
      setLoading(false);
      return;
    }
    setSession(s.data);
    const m = await api.get<ModuleMap>("/v1/dashboard/modules");
    if (m.ok) setMap(m.data);
    else setAuthError(m.error);
    await loadInbox();
    setLoading(false);
  }, [loadInbox]);

  useEffect(() => {
    void boot();
  }, [boot]);

  const navigate = (to: string) => {
    window.history.pushState({}, "", `${BASE}${to}`);
    setRoute(to);
  };

  const logout = async () => {
    await api.post("/v1/auth/logout", {}, session?.csrf_token ?? null);
    window.location.href = `${BASE}/`;
  };

  if (loading) return <Spinner label="signing in…" />;
  if (authError) return <SignedOut error={authError} />;
  if (!session || !map) return null;

  const modules = map.modules;
  const onInbox = route === INBOX_ROUTE;
  const active: Module | undefined = onInbox
    ? undefined
    : modules.find((m) => m.path === route) ?? modules.find((m) => m.built);
  const Screen = active ? SCREENS[active.id] : undefined;
  const unread = inbox?.unread ?? 0;
  const csrf = session.csrf_token ?? null;

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">
          <Text value={map.branding ?? "Context Layer"} />
        </span>
        <span className="who">
          <Text value={map.display ?? map.subject} />
          <button className="link" onClick={logout}>
            sign out
          </button>
        </span>
      </header>

      <div className="body">
        <nav className="sidebar">
          {modules.map((m) => (
            <button
              key={m.id}
              className={`nav-item${active?.id === m.id ? " active" : ""}${m.built ? "" : " unbuilt"}`}
              onClick={() => navigate(m.path)}
            >
              <Text value={m.title} />
            </button>
          ))}
          {modules.length === 0 && (
            <p className="muted">
              This deployment&apos;s <code>dashboard.yaml</code> shows your roles no modules.
            </p>
          )}

          <button
            className={`nav-item nav-inbox${onInbox ? " active" : ""}`}
            onClick={() => navigate(INBOX_ROUTE)}
          >
            What came back
            {unread > 0 && <span className="badge">{unread}</span>}
          </button>
        </nav>

        <main>
          <h2>
            <Text value={onInbox ? "What came back" : (active?.title ?? "Dashboard")} />
          </h2>
          {onInbox ? (
            <Inbox data={inbox} csrf={csrf} onAcked={loadInbox} />
          ) : active && Screen ? (
            Screen({ csrf, inbox, reloadInbox: loadInbox })
          ) : active ? (
            <Dark title={`${active.title} is not built yet`} why={active.description} />
          ) : (
            <Dark
              title="Nothing to show"
              why="No module in this deployment's configuration is visible to your identity."
            />
          )}
        </main>
      </div>

      <footer>
        <span className="muted">
          module map from <Text value={map.config_source} /> · signed in as{" "}
          <Text value={map.subject} />
        </span>
      </footer>
    </div>
  );
}
