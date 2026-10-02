import { EmptyState, LoadingState, OverviewView, InboxView, BrainView, SourcesView, AskView, StudioView, ActivateView, AnalyticsPreview, AuditView, AgentsView, GraphView, ConnectorsView, CaptureDialog } from "./LivePages";
import { FormEvent, KeyboardEvent as ReactKeyboardEvent, ReactNode, RefObject, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Archive, BarChart3, BookOpen, Boxes, Brain, Check, ChevronRight, CircleDot, Download, FileText, History, Home, Inbox, GitBranch, KeyRound, Layers3, Menu, MessageSquareText, Mic2, Plus, Search, ShieldCheck, Sparkles, TriangleAlert, X } from "lucide-react";
import { BrainClientContext } from "./client";
import { createDemoClient } from "./demo";
import LandingPage from "./LandingPage";
import { PreviewPage } from "./PreviewPages";
import { goTo, openSiteHome, readRoute, SHOW_LANDING, type View } from "./routes";
import { api, Draft, Integrity, InterviewSession, Knowledge, McpConnection, Overview, Proposal, Source, clearToken, getToken, hasToken, setToken, Unauthorized } from "./api";

type NavItem = { id: View; label: string; icon: typeof Home; future?: boolean };

const workspaceNav: NavItem[] = [
  { id: "overview", label: "Overview", icon: Home },
  { id: "workspaces", label: "Workspaces", icon: Boxes, future: true },
  { id: "inbox", label: "Inbox", icon: Inbox },
  { id: "ask", label: "Playground", icon: MessageSquareText },
];
const knowledgeNav: NavItem[] = [
  { id: "brain", label: "Brain", icon: Brain },
  { id: "working-memory", label: "Working Memory", icon: Layers3, future: true },
  { id: "graph", label: "Brain Graph", icon: GitBranch },
  { id: "sources", label: "Sources", icon: Archive },
  { id: "import", label: "Import", icon: Plus },
];
const operationsNav: NavItem[] = [
  { id: "studio", label: "Studio", icon: Mic2 },
  { id: "activate", label: "Activate", icon: Sparkles },
  { id: "turns", label: "Turns", icon: History, future: true },
  { id: "proactivity", label: "Proactivity", icon: CircleDot, future: true },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "insights", label: "Insights", icon: Activity, future: true },
];
const developerNav: NavItem[] = [
  { id: "connectors", label: "Connectors", icon: Boxes },
  { id: "api-keys", label: "API Keys", icon: KeyRound, future: true },
  { id: "agents", label: "Agents & MCP", icon: Brain },
  { id: "requests", label: "Requests", icon: Activity, future: true },
  { id: "audit", label: "Audit", icon: Activity },
];
const settingsNav: NavItem[] = [{ id: "settings", label: "Settings", icon: ShieldCheck, future: true }];
const navGroups = [{ label: "Workspace", items: workspaceNav }, { label: "Knowledge", items: knowledgeNav }, { label: "Operations", items: operationsNav }, { label: "Developer", items: developerNav }, { label: "Settings", items: settingsNav }];

const navLabel = Object.fromEntries(
  navGroups.flatMap(group => group.items).map((item) => [item.id, item.label]),
) as Record<View, string>;

const titleMap: Record<View, { title: string; description: string }> = {
  overview: {
    title: "Overview",
    description: "Your sources, review queue, and approved knowledge at a glance.",
  },
  inbox: {
    title: "Review inbox",
    description: "Inspect every proposal beside its original evidence before it becomes part of the Brain.",
  },
  brain: {
    title: "Your Brain",
    description: "Search the positions, lessons, decisions, and language your organisation has explicitly approved.",
  },
  studio: {
    title: "Intelligence Studio",
    description: "Capture expert knowledge through guided interviews and assemble drafts from approved intelligence.",
  },
  activate: {
    title: "Activate intelligence",
    description: "Assemble approved knowledge and its citations into context for briefs, articles, and agents.",
  },
  analytics: {
    title: "Intelligence analytics",
    description: "Inspect current knowledge counts, review status, and evidence health. Usage and business outcomes are not measured yet.",
  },
  sources: {
    title: "Source library",
    description: "Keep interviews, research, notes, and decisions separate from the interpretations built from them.",
  },
  audit: {
    title: "Audit trail",
    description: "See why the system believes what it believes, what changed, and which items need attention.",
  },
  ask: {
    title: "Playground",
    description: "Ask a question across approved knowledge and inspect the original evidence behind the response.",
  },
  import: { title: "Import", description: "Add original material to your Brain. Text capture is available now." },
  workspaces: { title: "Workspaces", description: "Browse spaces for different teams and projects." },
  "working-memory": { title: "Working Memory", description: "Explore interpretations and their links to original sources and approved knowledge." },
  graph: { title: "Brain Graph", description: "Explore the relationships between evidence, proposals, memory, and approved knowledge." },
  connectors: { title: "Connectors", description: "See providers that may bring content into the Brain." },
  "api-keys": { title: "API Keys", description: "Inspect how scoped, expiring access will be managed." },
  agents: { title: "Agents & MCP", description: "Connect coding tools to your own Brain deployment." },
  requests: { title: "Requests", description: "Inspect API operations and latency separately from domain events." },
  insights: { title: "Insights", description: "Preview how usage patterns could be reported." },
  turns: { title: "Turns", description: "Review individual agent interactions and their context." },
  proactivity: { title: "Proactivity", description: "Define when the Brain should suggest the next step." },
  settings: { title: "Settings", description: "Manage appearance and preview future administration controls." },
};

function readTheme(): "light" | "dark" {
  try { return localStorage.getItem("brain.theme") === "light" ? "light" : "dark"; } catch { return "dark"; }
}

function AppNav({
  label, items, view, proposalCount, onNavigate,
}: {
  label: string; items: NavItem[]; view: View; proposalCount: number; onNavigate: (view: View) => void;
}) {
  return (
    <div className="nav-group">
      <span className="nav-label">{label}</span>
      <ul>
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <button
                className={view === item.id ? "active" : ""}
                onClick={() => onNavigate(item.id)}
                aria-current={view === item.id ? "page" : undefined}
                aria-label={`${item.label}${item.id === "inbox" && proposalCount > 0 ? ` ${proposalCount}` : ""}${item.future ? " Preview" : ""}`}
              >
                <Icon size={17} aria-hidden="true" />
                <span>{item.label}</span>
                {item.id === "inbox" && proposalCount > 0 && <span className="nav-count">{proposalCount}</span>}
                {item.future && view !== item.id && <span className="nav-preview">Preview</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

type PaletteItem = {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: ReactNode;
  run: () => void;
};

function CommandPalette({ knowledge, sources, onNavigate, onClose, focusFallbackRef }: {
  knowledge: Knowledge[]; sources: Source[]; onNavigate: (view: View, record?: string) => void; onClose: () => void; focusFallbackRef: RefObject<HTMLButtonElement | null>;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const fallback = focusFallbackRef.current;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    inputRef.current?.focus();
    return () => {
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      if (previous?.isConnected && !previous.closest("[inert],[aria-hidden=true]")) previous.focus();
      else fallback?.focus();
    };
  }, [focusFallbackRef]);

  const items = useMemo<PaletteItem[]>(() => {
    const needle = query.toLowerCase().trim();
    const hit = (value: string) => !needle || value.toLowerCase().includes(needle);
    const navRows = navGroups.flatMap(({label,items}) => items.map(item => ({ item, group: label })));
    const nav: PaletteItem[] = navRows.map(({ item, group }) => {
      const Icon = item.icon;
      return {
        id: `nav-${item.id}`,
        label: item.label,
        hint: item.future ? "Preview" : undefined,
        group,
        icon: <Icon size={16} aria-hidden="true" />,
        run: () => onNavigate(item.id),
      };
    });
    const canon: PaletteItem[] = knowledge
      .filter((item) => hit(`${item.statement} ${item.type} ${item.source_title}`))
      .slice(0, 5)
      .map((item) => ({
        id: `knowledge-${item.id}`,
        label: item.statement,
        hint: `${item.type} · v${item.version}`,
        group: "Approved knowledge",
        icon: <BookOpen size={16} aria-hidden="true" />,
        run: () => onNavigate("brain", item.id),
      }));
    const library: PaletteItem[] = sources
      .filter((item) => hit(`${item.title} ${item.kind}`))
      .slice(0, 4)
      .map((item) => ({
        id: `source-${item.id}`,
        label: item.title,
        hint: `${item.kind} · v${item.current_version}`,
        group: "Source library",
        icon: <FileText size={16} aria-hidden="true" />,
        run: () => onNavigate("sources", item.id),
      }));
    const filteredNav = nav.filter((item) => hit(item.label));
    return [...filteredNav, ...canon, ...library];
  }, [query, knowledge, sources, onNavigate]);

  function handleKey(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((prev) => (items.length ? (prev + 1) % items.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((prev) => (items.length ? (prev - 1 + items.length) % items.length : 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = items[active];
      if (item) { onClose(); item.run(); }
    }
  }

  const groups = items.reduce<Record<string, PaletteItem[]>>((acc, item) => {
    (acc[item.group] ??= []).push(item);
    return acc;
  }, {});
  const flatIndex = (item: PaletteItem) => items.indexOf(item);

  return (
    <dialog ref={dialogRef} className="palette" aria-label="Search and jump to" onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <div className="palette-field">
        <Search size={18} aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(event) => { setQuery(event.target.value); setActive(0); }}
          onKeyDown={handleKey}
          placeholder="Search knowledge, sources, or jump to a view…"
          aria-label="Search knowledge, sources, or jump to a view"
          aria-controls="palette-results"
        />
        <kbd>esc</kbd>
      </div>
      <div className="palette-results" id="palette-results" role="listbox" aria-label="Results">
        {items.length === 0 && <p className="palette-empty">Nothing matches “{query}”. Try a shorter phrase.</p>}
        {Object.entries(groups).map(([group, groupItems]) => (
          <div className="palette-group" key={group}>
            <span className="palette-group-label">{group}</span>
            {groupItems.map((item) => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={flatIndex(item) === active}
                className={`palette-item ${flatIndex(item) === active ? "palette-item--active" : ""}`}
                onMouseEnter={() => setActive(flatIndex(item))}
                onClick={() => { onClose(); item.run(); }}
              >
                <span className="palette-item-icon">{item.icon}</span>
                <span className="palette-item-label">{item.label}</span>
                <span className="palette-item-hint">{item.hint}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="palette-foot">
        <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
        <span><kbd>↵</kbd> open</span>
        <span>{items.length} result{items.length === 1 ? "" : "s"}</span>
      </div>
    </dialog>
  );
}

/* The access credential is deliberately not part of the bundle. An unauthenticated
   browser is met with a gate: machine token paste always works; human sign-in
   appears when the deployment has an identity provider configured. */
function AccessGate({ refused, onUnlock }: { refused: boolean; onUnlock: () => void }) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<"token" | "signin">("token");
  const [signInAvailable, setSignInAvailable] = useState(false);
  const [provider, setProvider] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState("");
  const googleBtnRef = useRef<HTMLDivElement | null>(null);
  const onUnlockRef = useRef(onUnlock);
  onUnlockRef.current = onUnlock;
  const googleClientId = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) ?? "";
  const wantsGoogle =
    signInAvailable && mode === "signin" && (provider === "google" || provider === "firebase") && !!googleClientId;

  useEffect(() => {
    let cancelled = false;
    api.authStatus().then((status) => {
      if (cancelled) return;
      setSignInAvailable(status.sign_in_available);
      setProvider(status.provider);
      if (status.sign_in_available) setMode("signin");
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  /* Real Google sign-in (Google Identity Services). The button hands us a Google
     ID token, which is posted to /auth/login as the provider credential; the
     session comes back and is stored like any other sign-in. */
  useEffect(() => {
    if (!wantsGoogle || !googleBtnRef.current) return;
    const win = window as any;
    const start = () => {
      if (!win.google?.accounts?.id || !googleBtnRef.current) return;
      win.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: (response: { credential: string }) => {
          setLocalError("");
          setBusy(true);
          api.login(response.credential)
            .then(() => onUnlockRef.current())
            .catch((err) => setLocalError(err instanceof Error ? err.message : "Sign-in failed."))
            .finally(() => setBusy(false));
        },
      });
      win.google.accounts.id.renderButton(googleBtnRef.current, { theme: "outline", size: "large", width: 320 });
    };
    if (win.google?.accounts?.id) {
      start();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = start;
    document.head.appendChild(script);
  }, [wantsGoogle, googleClientId]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!value.trim() || busy) return;
    setLocalError("");
    setBusy(true);
    try {
      if (mode === "signin") {
        await api.login(value.trim());
      } else {
        setToken(value.trim());
      }
      onUnlock();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  const title =
    mode === "signin"
      ? provider === "firebase"
        ? "Sign in to your Brain."
        : "Sign in with your identity credential."
      : "Welcome to your Brain.";
  const copy =
    mode === "signin"
      ? provider === "firebase"
        ? "Use the ID token from Google sign-in. Your membership still decides what you can reach."
        : "Enter the development identity credential provisioned for this Brain."
      : "Enter the access token from your Brain administrator to open the workspace.";
  const label = mode === "signin" ? "Sign-in credential" : "Access token";
  const placeholder =
    mode === "signin"
      ? provider === "firebase"
        ? "Paste Firebase ID token"
        : "e.g. dev-alice"
      : "Paste the token you were given";

  return (
    <div className="access-gate">
      <form className="access-card panel-card" onSubmit={submit}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><Brain size={20} strokeWidth={2.2} /></span>
          <span className="eyebrow">Open Brain</span>
        </div>
        <h1 className="access-title">{title}</h1>
        <p className="access-copy">{copy}</p>
        {signInAvailable && (
          <div className="access-mode-tabs" role="tablist" aria-label="Sign-in method">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "signin"}
              className={mode === "signin" ? "access-mode is-active" : "access-mode"}
              onClick={() => { setMode("signin"); setLocalError(""); }}
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "token"}
              className={mode === "token" ? "access-mode is-active" : "access-mode"}
              onClick={() => { setMode("token"); setLocalError(""); }}
            >
              Access token
            </button>
          </div>
        )}
        {(refused || localError) && (
          <div className="alert alert--error" role="alert">
            <TriangleAlert size={18} strokeWidth={2.1} />
            <span>{localError || "That credential was refused. Check it and try again."}</span>
          </div>
        )}
        {wantsGoogle && (
          <>
            <div ref={googleBtnRef} className="google-signin" />
            <div className="access-divider"><span>or use a credential below</span></div>
          </>
        )}
        <div className="form-field">
          <label htmlFor="brain-token">{label}</label>
          <input
            id="brain-token"
            className="input"
            type="password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={placeholder}
            autoComplete="off"
            spellCheck={false}
            autoFocus
          />
          <span className="field-help">Stored for this browser tab only. Close the tab to clear access.</span>
        </div>
        <div className="access-actions">
          <button className="primary-button" type="submit" disabled={!value.trim() || busy}>
            {busy ? "Opening…" : mode === "signin" ? "Sign in" : "Open the Brain"}
          </button>
          <span className="access-hint">
            {mode === "signin"
              ? "No membership yet? Ask an owner to invite you."
              : "No token? Ask whoever runs this Brain."}
          </span>
        </div>
        {SHOW_LANDING ? (
          <a className="access-back" href="#/">← Back to home</a>
        ) : (
          <button className="access-back" type="button" onClick={() => openSiteHome()}>
            ← Back to home
          </button>
        )}
      </form>
    </div>
  );
}

export default function App() {
  const [route, setRoute] = useState(readRoute);
  const view = route.view;
  const demoClient = useMemo(createDemoClient, []);
  const client = route.screen === "demo" ? demoClient : api;
  const [theme, setTheme] = useState<"light" | "dark">(() => readTheme());
  const [overview, setOverview] = useState<Overview | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [integrity, setIntegrity] = useState<Integrity | null>(null);
  const [interviews, setInterviews] = useState<InterviewSession[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [mcpConnections, setMcpConnections] = useState<McpConnection[]>([]);
  const [loadedClient, setLoadedClient] = useState<typeof api | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showCapture, setShowCapture] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState("General");
  const [compact, setCompact] = useState(() => typeof window.matchMedia === "function" && window.matchMedia("(max-width: 880px)").matches);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 880px)");
    const change = (event: MediaQueryListEvent) => setCompact(event.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    if (!compact || !menuOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const opener = menuButtonRef.current;
    const sidebar = sidebarRef.current;
    const targets = () => Array.from(sidebar?.querySelectorAll<HTMLElement>('button:not([disabled]),a[href]') ?? []);
    targets()[0]?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setMenuOpen(false); }
      if (event.key !== "Tab") return;
      const items = targets(); const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", trap);
    return () => { document.removeEventListener("keydown", trap); (opener ?? previous)?.focus(); };
  }, [compact, menuOpen]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // The token is not in the bundle, so the page starts locked until this browser
  // presents one. `tokenRefused` only distinguishes a wrong token from none.
  const [tokenRequired, setTokenRequired] = useState(!hasToken());
  const [tokenRefused, setTokenRefused] = useState(false);

  useEffect(() => {
    const sync = () => {
      const next = readRoute();
      if (next.screen !== route.screen) { setLoading(true); setError(""); setLoadedClient(null); setOverview(null); setSources([]); setProposals([]); setKnowledge([]); setIntegrity(null); setInterviews([]); setDrafts([]); setMcpConnections([]); }
      setRoute(next);
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [route.screen]);

  useEffect(() => {
    document.documentElement.dataset.theme = route.screen === "landing" || route.screen === "login" ? "light" : theme;
    document.documentElement.dataset.surface = route.screen === "landing" || route.screen === "login" ? "public" : "console";
  }, [route.screen, theme]);

  function changeTheme(next: "light" | "dark") {
    try { localStorage.setItem("brain.theme", next); } catch { /* Preference remains in memory. */ }
    setTheme(next);
  }

  async function refresh() {
    try {
      setError("");
      const [overviewData, sourceData, proposalData, knowledgeData, integrityData, interviewData, draftData, mcpConnectionData] = await Promise.all([
        client.overview(), client.sources(), client.proposals(), client.knowledge(), client.integrity(), client.interviews(), client.drafts(), client.mcpConnections(),
      ]);
      setOverview(overviewData);
      setSources(sourceData);
      setProposals(proposalData);
      setKnowledge(knowledgeData);
      setIntegrity(integrityData);
      setInterviews(interviewData);
      setDrafts(draftData);
      setMcpConnections(mcpConnectionData);
      setLoadedClient(client);
    } catch (requestError) {
      recordRequestError(requestError);
    } finally {
      setLoading(false);
    }
  }

  // A refused token reopens the access screen; anything else is a real failure
  // of the Brain and belongs in the error banner.
  function recordRequestError(requestError: unknown) {
    if (requestError instanceof Unauthorized) {
      clearToken();
      setTokenRefused(true);
      setTokenRequired(true);
      setLoading(false);
      return;
    }
    setError(requestError instanceof Error ? requestError.message : "Could not load the workspace.");
  }

  function unlock() {
    setTokenRefused(false);
    setLoading(true);
    setTokenRequired(false);
    setRoute({ screen: "console", view: "overview" });
    goTo("console", "overview");
  }

  useEffect(() => {
    // Nothing is requested before a token is present: an unauthenticated page
    // load must not reach the API at all.
    if ((tokenRequired && route.screen !== "demo") || !["console", "demo"].includes(route.screen)) return;
    let active = true;
    Promise.all([client.overview(), client.sources(), client.proposals(), client.knowledge(), client.integrity(), client.interviews(), client.drafts(), client.mcpConnections()])
      .then(([overviewData, sourceData, proposalData, knowledgeData, integrityData, interviewData, draftData, mcpConnectionData]) => {
        if (!active) return;
        setOverview(overviewData);
        setSources(sourceData);
        setProposals(proposalData);
        setKnowledge(knowledgeData);
        setIntegrity(integrityData);
        setInterviews(interviewData);
        setDrafts(draftData);
        setMcpConnections(mcpConnectionData);
        setLoadedClient(client);
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        recordRequestError(requestError);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [tokenRequired, route.screen, client]);

  useEffect(() => {
    function handleCommandSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
        setMenuOpen(false);
      }
    }
    document.addEventListener("keydown", handleCommandSearch);
    return () => document.removeEventListener("keydown", handleCommandSearch);
  }, []);

  function navigate(next: View, record?: string) {
    setRoute({ ...route, view: next, record });
    goTo(route.screen === "demo" ? "demo" : "console", next, record);
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleExport() {
    try {
      const response = await fetch(api.exportUrl, { headers: { "X-Brain-Token": getToken() } });
      if (response.status === 401) throw new Unauthorized();
      if (!response.ok) throw new Error("Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `brain-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setNotice("Portable Brain export downloaded.");
    } catch (exportError) {
      if (exportError instanceof Unauthorized) recordRequestError(exportError);
      else setError("The workspace could not be exported.");
    }
  }

  const current = titleMap[view];

  // Console-first builds keep the public site off unless VITE_SHOW_LANDING=true.
  if (route.screen === "landing") return SHOW_LANDING ? <LandingPage /> : <AccessGate refused={tokenRefused} onUnlock={unlock} />;
  if (route.screen === "login" || (route.screen === "console" && tokenRequired)) return <AccessGate refused={tokenRefused} onUnlock={unlock} />;

  return (
    <BrainClientContext.Provider value={client}><div className="app-shell" data-view={view}>
      <a className="skip-link" href="#main-content" onClick={e => { e.preventDefault(); document.getElementById("main-content")?.focus(); }}>Skip to content</a>
      <aside ref={sidebarRef} id="workspace-navigation" className={`sidebar ${menuOpen ? "sidebar--open" : ""}`} aria-label="Workspace navigation" role={compact ? "dialog" : undefined} aria-modal={compact && menuOpen ? true : undefined} aria-hidden={compact && !menuOpen ? true : undefined} inert={compact && !menuOpen}>
        <button className="sidebar-close" aria-label="Close navigation drawer" onClick={() => setMenuOpen(false)}><X size={18}/></button>
        <div className="brand">
          <Brain size={22} strokeWidth={1.8} aria-hidden="true" />
          <strong>Open Brain</strong>
        </div>
        <button className="command-button rail-command" aria-label="Search or jump to… ⌘K" aria-keyshortcuts="Meta+k Control+k" onClick={() => { setMenuOpen(false); setPaletteOpen(true); }}>
          <Search size={15} aria-hidden="true" /><span>Search…</span><kbd>⌘K</kbd>
        </button>
        {view === "settings" ? <nav className="console-settings-nav" aria-label="Settings navigation">
          <button className="settings-back" onClick={() => navigate("overview")}><ChevronRight size={14} aria-hidden="true"/><strong>Settings</strong></button>
          <span className="nav-label">Organization</span>
          {["General", "Team", "Usage", "Advanced"].map(section => <button key={section} className={settingsSection === section ? "active" : ""} aria-current={settingsSection === section ? "page" : undefined} onClick={() => setSettingsSection(section)}><span>{section}</span>{section !== "General" && <> <small>Preview</small></>}</button>)}
          <span className="nav-label">Personal</span>
          <button className={settingsSection === "Account" ? "active" : ""} aria-current={settingsSection === "Account" ? "page" : undefined} onClick={() => setSettingsSection("Account")}><span>Account</span> <small>Preview</small></button>
        </nav> : <nav aria-label="Primary navigation">
          {navGroups.map(group => <AppNav key={group.label} label={group.label} items={group.items} view={view} proposalCount={loadedClient === client ? proposals.length : 0} onNavigate={navigate} />)}
        </nav>}
        <div className="sidebar-footer">
          <div className="rail-status">
            <span className="status-light" aria-hidden="true" />
            <span><strong>{route.screen === "demo" ? "Demo workspace" : ["localhost", "127.0.0.1"].includes(window.location.hostname) ? "Local host" : "Hosted interface"}</strong><small>Engine: {route.screen === "demo" ? "sample" : overview?.engine?.available ? "available" : overview ? "unavailable" : "unknown"}</small></span>
            <ShieldCheck size={15} aria-hidden="true" />
          </div>
          <div className="rail-account">
            <span className="workspace-avatar">L</span>
            <span><strong>{route.screen === "demo" ? "Sample workspace" : "Token access"}</strong><small>{route.screen === "demo" ? "No API connection" : loadedClient === client ? "Authenticated with token" : "Token supplied · status unknown"}</small></span>
            {route.screen !== "demo" && <button className="rail-action" aria-label="Change access token" title="Change access token" onClick={()=>goTo("login")}><KeyRound size={15}/></button>}
            {route.screen !== "demo" && <button className="rail-action" onClick={handleExport} title="Export workspace" aria-label="Export workspace"><Download size={15} /></button>}
          </div>
        </div>
      </aside>

      {menuOpen && <button className="scrim" tabIndex={-1} aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}

      <div className="main-column" inert={compact && menuOpen}>
        <header className="topbar">
          <div className="topbar-start">
            <button ref={menuButtonRef} className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Open navigation" aria-controls="workspace-navigation" aria-expanded={menuOpen}><Menu size={20} /></button>
            <button className="workspace-switcher" aria-label="Current workspace: Personal Brain" onClick={() => navigate("workspaces")}>
              <span className="workspace-avatar">P</span><strong>Personal Brain</strong><span className="workspace-mode">{route.screen === "demo" ? "Demo" : "Workspace"}</span><ChevronRight size={13} aria-hidden="true" />
            </button>
            <nav className="topbar-crumbs" aria-label="Breadcrumb"><ChevronRight size={12} aria-hidden="true"/><span>{view === "settings" ? settingsSection : navLabel[view]}</span></nav>
          </div>
          <div className="topbar-actions">
            {compact && <button className="mobile-search-button" aria-label="Open search" onClick={() => setPaletteOpen(true)}><Search size={16} aria-hidden="true"/></button>}
            <button className="theme-button" type="button" onClick={() => changeTheme(theme === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>{theme === "dark" ? "☀" : "☾"}</button>
            <button className="capture-button" onClick={() => route.screen === "demo" ? navigate("import") : setShowCapture(true)}><Plus size={17} /> Capture source</button>
          </div>
        </header>

        <main id="main-content" data-layout={["import", "connectors", "agents", "insights", "proactivity", "settings"].includes(view) ? "narrow" : "wide"} tabIndex={-1}>
          <header className="page-heading">
            <div><h1>{view === "settings" ? settingsSection : current.title}</h1><p>{current.description}</p></div>
            {view === "brain" && <button className="secondary-button btn--pill" onClick={() => navigate("ask")}><MessageSquareText size={17} /> Ask the Brain</button>}
            {view === "sources" && <button className="primary-button btn--pill" onClick={() => route.screen === "demo" ? navigate("import") : setShowCapture(true)}><Plus size={17} /> Add source</button>}
            {view === "audit" && route.screen !== "demo" && <button className="secondary-button btn--pill" onClick={handleExport}><Download size={17} /> Export audit data</button>}
          </header>

          {error && <div className="alert alert--error" role="alert"><X size={18} /><span>{error}</span><button onClick={refresh}>Retry loading</button><button onClick={() => setError("")}>Dismiss</button></div>}
          {notice && <div className="alert alert--success" role="status"><Check size={18} /><span>{notice}</span><button onClick={() => setNotice("")}>Dismiss</button></div>}

          {route.screen === "demo" && ["overview", "inbox", "brain", "sources", "ask", "studio", "activate", "analytics", "audit"].includes(view) && <div className="preview-banner"><Sparkles size={16}/><strong>Demo workspace</strong><span>Synthetic data. All interactions stay in this page; no production API or AI service is connected.</span></div>}
          {(loading || loadedClient !== client) && !["import", "workspaces", "working-memory", "graph", "connectors", "api-keys", "agents", "requests", "insights", "turns", "proactivity", "settings"].includes(view) ? error ? <EmptyState icon={<TriangleAlert />} title="Workspace unavailable">Loading failed. Use Retry loading above to try again. No sample data has replaced your workspace.</EmptyState> : <LoadingState /> : (
            <>
              {view === "overview" && overview && <OverviewView overview={overview} proposals={proposals} knowledge={knowledge} integrity={integrity} onNavigate={navigate} />}
              {view === "inbox" && <InboxView proposals={proposals} onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {view === "brain" && <BrainView recordId={route.record} onSelect={id=>navigate("brain", id ?? undefined)} initial={knowledge} onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {view === "sources" && <SourcesView recordId={route.record} onSelect={id=>navigate("sources", id ?? undefined)} sources={sources} onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {view === "ask" && <AskView />}
              {view === "studio" && <StudioView interviews={interviews} drafts={drafts} knowledge={knowledge} onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {view === "activate" && <ActivateView knowledge={knowledge} onNavigate={navigate} onNotice={setNotice} />}
              {view === "analytics" && <AnalyticsPreview overview={overview} knowledge={knowledge} integrity={integrity} />}
              {view === "audit" && overview && <AuditView overview={overview} integrity={integrity} />}
              {view === "agents" && <AgentsView connections={mcpConnections} />}
              {view === "graph" && <GraphView />}
              {view === "connectors" && <ConnectorsView onChanged={refresh} onNotice={setNotice} onError={setError} />}
              {(["import", "workspaces", "working-memory", "api-keys", "requests", "insights", "turns", "proactivity", "settings"] as View[]).includes(view) && <PreviewPage key={view} view={view} demo={route.screen === "demo"} onNavigate={navigate} onImported={refresh} theme={theme} onTheme={changeTheme} settingsSection={settingsSection} />}
            </>
          )}
        </main>
      </div>

      {showCapture && route.screen === "console" && (
        <CaptureDialog
          onClose={() => setShowCapture(false)}
          onCreated={async () => {
            setShowCapture(false);
            setNotice("Source captured and proposals added to your inbox.");
            await refresh();
            navigate("inbox");
          }}
          onError={setError}
        />
      )}
      {paletteOpen && (
        <CommandPalette
          knowledge={loadedClient === client ? knowledge : []}
          sources={loadedClient === client ? sources : []}
          onNavigate={navigate}
          focusFallbackRef={menuButtonRef}
          onClose={() => setPaletteOpen(false)}
        />
      )}
    </div></BrainClientContext.Provider>
  );
}
