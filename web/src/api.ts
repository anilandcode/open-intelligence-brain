// A hosted build is served by the API itself, so the origin that delivered this
// page is the origin that answers the API. Only the dev server splits the two
// across ports, which is why the fallback is per-mode rather than a constant.
const API_URL =
  import.meta.env.VITE_API_URL ??
  (import.meta.env.DEV ? "http://localhost:8000" : window.location.origin);
/* The access token is deliberately NOT a build input. Vite inlines every
   `VITE_*` variable into the bundle at build time, so a `VITE_API_TOKEN` would
   hand the owner token of this Brain to anyone who opens the page and reads the
   JavaScript. The token arrives at runtime instead: pasted into the access
   screen, or carried in the `#token=` fragment, which browsers keep out of the
   request line and therefore out of server logs.

   Human sessions (`X-Brain-Session`) are a separate class: minted by
   `/api/v1/auth/login` after a verified identity provider assertion. A request
   may carry exactly one of the two headers. */
export const TOKEN_KEY = "brain.token";
export const SESSION_KEY = "brain.session";

/** Raised when the API refuses the token this browser is holding. */
export class Unauthorized extends Error {
  constructor(message = "That token was refused.") {
    super(message);
    this.name = "Unauthorized";
  }
}

// Storage can be unavailable (private mode, blocked storage), in which case the
// credential still works for the life of the page but is never persisted.
let memoryToken = "";
let memorySession = "";

function storeKey(key: string, value: string): void {
  try {
    if (value) window.sessionStorage.setItem(key, value);
    else window.sessionStorage.removeItem(key);
  } catch {
    // No storage: the in-memory copy above is all we have.
  }
}

function readKey(key: string, memory: string): string {
  try {
    return window.sessionStorage.getItem(key) ?? memory;
  } catch {
    return memory;
  }
}

/** The machine token this browser is holding, if any. Never a compiled-in default. */
export function getToken(): string {
  return readKey(TOKEN_KEY, memoryToken);
}

export function getSession(): string {
  return readKey(SESSION_KEY, memorySession);
}

export function hasToken(): boolean {
  return getToken().length > 0 || getSession().length > 0;
}

export function setToken(value: string): void {
  memoryToken = value.trim();
  storeKey(TOKEN_KEY, memoryToken);
  // A request may carry exactly one credential class.
  if (memoryToken) {
    memorySession = "";
    storeKey(SESSION_KEY, "");
  }
}

export function setSession(value: string): void {
  memorySession = value.trim();
  storeKey(SESSION_KEY, memorySession);
  if (memorySession) {
    memoryToken = "";
    storeKey(TOKEN_KEY, "");
  }
}

export function clearToken(): void {
  memoryToken = "";
  memorySession = "";
  storeKey(TOKEN_KEY, "");
  storeKey(SESSION_KEY, "");
}

// A link may hand the token over in the fragment: read it once, then strip it
// from the address bar so it does not linger in history or get passed on.
if (typeof window !== "undefined" && window.location.hash.startsWith("#token=")) {
  setToken(decodeURIComponent(window.location.hash.slice("#token=".length)));
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}

/** Which extraction engine answered, and why not a better one. */
export type Engine = {
  name: string;
  available: boolean;
  detail: string;
  container_tag: string;
  degraded: boolean;
};

export type Overview = {
  sources: number;
  proposals: number;
  canonical: number;
  pending_reviews: number;
  recent_activity: Array<{ id: string; action: string; detail: string; created_at: string }>;
  engine: Engine;
};

export type Source = {
  id: string;
  title: string;
  kind: string;
  sensitivity: string;
  content: string;
  created_at: string;
  proposal_count: number;
  current_version: number;
  content_hash: string;
};

export type SourceVersion = {
  id: string;
  source_id: string;
  version: number;
  content_hash: string;
  content: string;
  parser_version: string;
  change_note: string;
  created_at: string;
  span_count: number;
  proposal_count: number;
};

export type Proposal = {
  id: string;
  source_id: string;
  source_title: string;
  type: string;
  statement: string;
  rationale: string;
  source_excerpt: string;
  status: string;
  critic_notes: string;
  created_at: string;
};

export type Knowledge = {
  id: string;
  proposal_id: string;
  source_id: string;
  source_title: string;
  type: string;
  statement: string;
  rationale: string;
  source_excerpt: string;
  status: string;
  version: number;
  approved_at: string;
  revision_count: number;
  stale: boolean;
  conflict_ids: string[];
};

export type KnowledgeRevision = {
  id: string;
  knowledge_id: string;
  revision: number;
  statement: string;
  rationale: string;
  source_id: string;
  source_version_id: string;
  source_span_id: string | null;
  source_excerpt: string;
  change_note: string;
  approved_at: string;
};

export type Integrity = {
  stale_count: number;
  conflict_count: number;
  issues: Array<{
    kind: "stale_source" | "possible_conflict";
    knowledge_id: string;
    related_id: string | null;
    detail: string;
  }>;
};

export type ChatResult = {
  answer: string;
  grounded: boolean;
  citations: Array<{
    knowledge_id: string;
    source_id: string;
    source_title: string;
    excerpt: string;
  }>;
};

// --- Studio types ---

export type InterviewSession = {
  id: string;
  workspace_id: string;
  title: string;
  topic: string;
  person: string;
  audience: string;
  outcome: string;
  status: string;
  source_id: string | null;
  created_at: string;
  completed_at: string | null;
  question_count: number;
  response_count: number;
  extracted_count: number;
};

export type InterviewQuestion = {
  id: string;
  session_id: string;
  ordinal: number;
  question_text: string;
  response_text: string;
  extracted: boolean;
  created_at: string;
};

export type InterviewSessionDetail = InterviewSession & {
  questions: InterviewQuestion[];
};

export type Draft = {
  id: string;
  workspace_id: string;
  title: string;
  intent: string;
  audience: string;
  status: string;
  created_at: string;
  updated_at: string;
  section_count: number;
  citation_count: number;
};

export type DraftSection = {
  id: string;
  draft_id: string;
  ordinal: number;
  title: string;
  content: string;
  created_at: string;
  citations: Array<{ id: string; section_id: string; knowledge_id: string; created_at: string }>;
  knowledge_items: Array<{ id: string; statement: string; type: string; source_excerpt?: string }>;
};

export type DraftDetail = Draft & {
  sections: DraftSection[];
};

/** The server's own wording for a refusal, when it sent one. */
async function refusedDetail(response: Response): Promise<string | undefined> {
  const payload = await response.json().catch(() => null);
  return typeof payload?.detail === "string" ? payload.detail : undefined;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const session = getSession();
  const token = getToken();
  const authHeaders: Record<string, string> = {};
  // Exactly one credential class per request — matches the API invariant.
  if (session) authHeaders["X-Brain-Session"] = session;
  else if (token) authHeaders["X-Brain-Token"] = token;
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
      ...options.headers,
    },
  });
  // A refused credential is a different thing from a failed request: it means
  // the page should go back to asking for one instead of reporting a broken Brain.
  if (response.status === 401) {
    throw new Unauthorized(await refusedDetail(response));
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? "The Brain could not complete that request.");
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export type AuthStatus = {
  sign_in_available: boolean;
  provider: string | null;
};

export type AuthUser = {
  id: string;
  provider: string;
  email: string;
  display_name: string;
};

export type McpConnection = {
  id: string;
  client_id: string;
  client_name: string;
  source_kind: string;
  principal_preview: string;
  role: string;
  user_agent: string;
  access_count: number;
  first_seen: string;
  last_seen: string;
  status: string;
};

export type GraphMemory = { id: string; memory: string; content: string | null; version: number; memoryRelations: Record<string, string> };
export type GraphDocument = { id: string; title: string; summary: string; documentType: string; createdAt: string; updatedAt: string; memories: GraphMemory[] };
export type GraphEdge = { source: string; target: string; edgeType: string };
export type Graph = { documents: GraphDocument[]; edges: GraphEdge[] };

export type LoginResult = {
  session_token: string;
  expires_at: string;
  user: AuthUser;
};

export const api = {
  authStatus: () =>
    fetch(`${API_URL}/api/v1/auth/status`).then(async (response) => {
      if (!response.ok) return { sign_in_available: false, provider: null } as AuthStatus;
      return response.json() as Promise<AuthStatus>;
    }),
  login: async (credential: string) => {
    const result = await fetch(`${API_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential }),
    });
    if (result.status === 401) {
      throw new Unauthorized(await refusedDetail(result));
    }
    if (!result.ok) {
      const payload = await result.json().catch(() => ({ detail: result.statusText }));
      throw new Error(payload.detail ?? "Sign-in failed.");
    }
    const body = (await result.json()) as LoginResult;
    setSession(body.session_token);
    return body;
  },
  logout: async () => {
    const session = getSession();
    if (session) {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        headers: { "X-Brain-Session": session },
      }).catch(() => undefined);
    }
    clearToken();
  },
  me: () => request<{ user: AuthUser; memberships: unknown[] }>("/api/v1/auth/me"),
  mcpConnections: () => request<McpConnection[]>("/api/v1/mcp/connections"),
  graph: () => request<Graph>("/api/v1/graph"),
  overview: () => request<Overview>("/api/v1/overview"),
  sources: () => request<Source[]>("/api/v1/sources"),
  sourceVersions: (id: string) => request<SourceVersion[]>(`/api/v1/sources/${id}/versions`),
  addSourceVersion: (id: string, content: string, changeNote: string) =>
    request<SourceVersion>(`/api/v1/sources/${id}/versions`, {
      method: "POST",
      body: JSON.stringify({ content, change_note: changeNote }),
    }),
  proposals: () => request<Proposal[]>("/api/v1/proposals?status=proposed"),
  knowledge: (query = "") => request<Knowledge[]>(`/api/v1/knowledge?q=${encodeURIComponent(query)}`),
  knowledgeRevisions: (id: string) =>
    request<KnowledgeRevision[]>(`/api/v1/knowledge/${id}/revisions`),
  supersedeKnowledge: (
    id: string,
    statement: string,
    rationale: string,
    changeNote: string,
  ) =>
    request<Knowledge>(`/api/v1/knowledge/${id}/supersede`, {
      method: "POST",
      body: JSON.stringify({ statement, rationale, change_note: changeNote }),
    }),
  integrity: () => request<Integrity>("/api/v1/integrity"),
  createSource: (payload: Pick<Source, "title" | "kind" | "sensitivity" | "content">) =>
    request<Source>("/api/v1/sources", { method: "POST", body: JSON.stringify(payload) }),
  approveProposal: (id: string, statement: string, rationale: string) =>
    request<Knowledge>(`/api/v1/proposals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ statement, rationale }),
    }),
  rejectProposal: (id: string, reason: string) =>
    request<Proposal>(`/api/v1/proposals/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  chat: (question: string) =>
    request<ChatResult>("/api/v1/chat", { method: "POST", body: JSON.stringify({ question }) }),
  exportUrl: `${API_URL}/api/v1/export`,

  // --- Studio ---
  interviews: () => request<InterviewSession[]>("/api/v1/studio/interviews"),
  interview: (id: string) => request<InterviewSessionDetail>(`/api/v1/studio/interviews/${id}`),
  createInterview: (payload: { title: string; topic?: string; person?: string; audience?: string; outcome?: string }) =>
    request<InterviewSession>("/api/v1/studio/interviews", { method: "POST", body: JSON.stringify(payload) }),
  addQuestion: (sessionId: string, questionText: string) =>
    request<InterviewQuestion>(`/api/v1/studio/interviews/${sessionId}/questions`, {
      method: "POST", body: JSON.stringify({ question_text: questionText }),
    }),
  submitResponse: (sessionId: string, questionId: string, responseText: string) =>
    request<InterviewQuestion>(`/api/v1/studio/interviews/${sessionId}/questions/${questionId}/respond`, {
      method: "POST", body: JSON.stringify({ response_text: responseText }),
    }),
  completeInterview: (sessionId: string) =>
    request<InterviewSession>(`/api/v1/studio/interviews/${sessionId}/complete`, { method: "POST" }),

  drafts: () => request<Draft[]>("/api/v1/studio/drafts"),
  draft: (id: string) => request<DraftDetail>(`/api/v1/studio/drafts/${id}`),
  createDraft: (payload: { title: string; intent?: string; audience?: string }) =>
    request<Draft>("/api/v1/studio/drafts", { method: "POST", body: JSON.stringify(payload) }),
  addSection: (draftId: string, payload: { title: string; content: string; knowledge_ids?: string[] }) =>
    request<DraftSection>(`/api/v1/studio/drafts/${draftId}/sections`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  deleteSection: (draftId: string, sectionId: string) =>
    request<void>(`/api/v1/studio/drafts/${draftId}/sections/${sectionId}`, { method: "DELETE" }),
  assembleDraft: (payload: { title: string; intent?: string; audience?: string; knowledge_ids: string[]; include_excerpts?: boolean }) =>
    request<DraftDetail>("/api/v1/studio/drafts/assemble", { method: "POST", body: JSON.stringify(payload) }),
};
