/**
 * Open Intelligence Brain TypeScript SDK.
 *
 * Official TypeScript client with bi-temporal search, exact span verification,
 * and Fast Review batch governance.
 */

export interface BrainClientOptions {
  baseUrl?: string;
  apiKey?: string;
  workspaceId?: string;
  fetch?: typeof globalThis.fetch;
}

export interface Source {
  id: string;
  workspace_id: string;
  title: string;
  kind: string;
  sensitivity: string;
  current_version: number;
  created_at: string;
}

export interface Proposal {
  id: string;
  workspace_id: string;
  source_id: string;
  type: string;
  statement: string;
  rationale: string;
  source_excerpt: string;
  status: string;
  conflict_with_id?: string | null;
  conflict_note?: string | null;
  summary?: string;
  tags?: string;
  created_at: string;
}

export interface Knowledge {
  id: string;
  workspace_id: string;
  proposal_id: string;
  source_id: string;
  type: string;
  statement: string;
  rationale: string;
  source_excerpt: string;
  status: string;
  version: number;
  valid_from: string;
  valid_to?: string | null;
  superseded_by?: string | null;
  approved_at: string;
}

export interface Citation {
  knowledge_id: string;
  source_id: string;
  source_title: string;
  excerpt: string;
}

export interface ChatResult {
  answer: string;
  citations: Citation[];
  grounded: boolean;
}

export interface BatchApprovalResult {
  approved_count: number;
  knowledge_ids: string[];
  failed_ids: string[];
}

export interface BatchRejectResult {
  declined_count: number;
  declined_ids: string[];
}

export class BrainClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchFn: typeof globalThis.fetch;

  constructor(options: BrainClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchFn = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  private async request<T>(method: string, path: string, body?: unknown, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
    let url = `${this.baseUrl}${path}`;
    if (params) {
      const searchParams = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined) searchParams.append(k, String(v));
      }
      const qs = searchParams.toString();
      if (qs) url += `?${qs}`;
    }

    const headers: Record<string, string> = {
      "Accept": "application/json",
      "User-Agent": "@openbrain/sdk/2.0.0",
    };
    if (this.apiKey) {
      headers["X-Brain-Token"] = this.apiKey;
    }
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    const res = await this.fetchFn(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`OpenBrain API error (${res.status}): ${text}`);
    }

    if (res.status === 204) return null as T;
    return res.json() as Promise<T>;
  }

  /** Ingest raw content into Brain as an immutable source. */
  async add(payload: { content: string; title?: string; kind?: string; sensitivity?: string }): Promise<Source> {
    return this.request<Source>("POST", "/api/v1/sources", {
      content: payload.content,
      title: payload.title ?? payload.content.trim().slice(0, 60),
      kind: payload.kind ?? "note",
      sensitivity: payload.sensitivity ?? "internal",
    });
  }

  /** Search canonical knowledge with optional bi-temporal time-travel filter. */
  async search(options: { query?: string; limit?: number; as_of?: string | Date; include_superseded?: boolean } = {}): Promise<Knowledge[]> {
    const asOfStr = options.as_of instanceof Date ? options.as_of.toISOString() : options.as_of;
    return this.request<Knowledge[]>("GET", "/api/v1/knowledge", undefined, {
      q: options.query ?? "",
      limit: options.limit ?? 20,
      as_of: asOfStr,
      include_superseded: options.include_superseded,
    });
  }

  /** Grounded QA over canonical knowledge with citations. */
  async ask(question: string): Promise<ChatResult> {
    return this.request<ChatResult>("POST", "/api/v1/chat", { question });
  }

  /** Retrieve proposals in review inbox. */
  async proposals(status: string = "proposed"): Promise<Proposal[]> {
    return this.request<Proposal[]>("GET", "/api/v1/proposals", undefined, { status });
  }

  /** Approve a single proposal to canonical knowledge. */
  async approve(proposalId: string, options: { statement?: string; rationale?: string; supersedes_knowledge_id?: string; valid_from?: string | Date } = {}): Promise<Knowledge> {
    const vFromStr = options.valid_from instanceof Date ? options.valid_from.toISOString() : options.valid_from;
    return this.request<Knowledge>("POST", `/api/v1/proposals/${proposalId}/approve`, {
      statement: options.statement,
      rationale: options.rationale,
      supersedes_knowledge_id: options.supersedes_knowledge_id,
      valid_from: vFromStr,
    });
  }

  /** Batch approve multiple proposals in one call. */
  async batchApprove(proposalIds: string[]): Promise<BatchApprovalResult> {
    return this.request<BatchApprovalResult>("POST", "/api/v1/proposals/batch-approve", {
      proposal_ids: proposalIds,
    });
  }

  /** Reject a single proposal. */
  async reject(proposalId: string, reason: string = "Rejected by reviewer"): Promise<Proposal> {
    return this.request<Proposal>("POST", `/api/v1/proposals/${proposalId}/reject`, { reason });
  }

  /** Batch reject multiple proposals. */
  async batchReject(proposalIds: string[], reason: string = "Batch rejected"): Promise<BatchRejectResult> {
    return this.request<BatchRejectResult>("POST", "/api/v1/proposals/batch-reject", {
      proposal_ids: proposalIds,
      reason,
    });
  }

  /** Retrieve revision provenance history for a knowledge item. */
  async history(knowledgeId: string): Promise<unknown[]> {
    return this.request<unknown[]>("GET", `/api/v1/knowledge/${knowledgeId}/revisions`);
  }
}
