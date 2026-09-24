const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const API_TOKEN = import.meta.env.VITE_API_TOKEN ?? "local-dev-token";

export type Overview = {
  sources: number;
  proposals: number;
  canonical: number;
  pending_reviews: number;
  recent_activity: Array<{ id: string; action: string; detail: string; created_at: string }>;
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

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Brain-Token": API_TOKEN,
      ...options.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? "The Brain could not complete that request.");
  }
  return response.json() as Promise<T>;
}

export const api = {
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
  exportToken: API_TOKEN,
};
