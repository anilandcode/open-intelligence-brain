import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const overview = { sources: 1, proposals: 2, canonical: 1, pending_reviews: 1, recent_activity: [] };
const integrity = { stale_count: 0, conflict_count: 0, issues: [] };
const source = { id: "src_1", title: "Interview", kind: "interview", sensitivity: "private", content: "A sufficiently long source note for this fixture.", created_at: new Date().toISOString(), proposal_count: 1, current_version: 1, content_hash: "a".repeat(64) };
const proposal = { id: "prop_1", source_id: "src_1", source_title: "Interview", type: "belief", statement: "Approved context makes generated work more distinctive.", rationale: "Candidate extracted from source.", source_excerpt: "Approved context makes generated work more distinctive.", status: "proposed", created_at: new Date().toISOString() };
const knowledge = { id: "know_1", proposal_id: "prop_0", source_id: "src_1", source_title: "Interview", type: "belief", statement: "Proprietary context improves generated work.", rationale: "Grounded in experience.", source_excerpt: "Proprietary context improves generated work.", status: "canonical", version: 1, approved_at: new Date().toISOString(), revision_count: 1, stale: false, conflict_ids: [] };
const revision = { id: "rev_1", knowledge_id: knowledge.id, revision: 1, statement: knowledge.statement, rationale: knowledge.rationale, source_id: source.id, source_version_id: "srcv_1", source_span_id: "span_1", source_excerpt: knowledge.source_excerpt, change_note: "Initial approval", approved_at: knowledge.approved_at };

function mockJson(value: unknown) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(value) } as Response);
}

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal("scrollTo", vi.fn());
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/overview")) return mockJson(overview);
      if (url.includes("/integrity")) return mockJson(integrity);
      if (url.includes("/sources")) return mockJson([source]);
      if (url.includes("/proposals")) return mockJson([proposal]);
      if (url.includes("/knowledge/know_1/revisions")) return mockJson([revision]);
      if (url.includes("/knowledge")) return mockJson([knowledge]);
      if (url.includes("/chat")) return mockJson({ answer: knowledge.statement, grounded: true, citations: [{ knowledge_id: knowledge.id, source_id: source.id, source_title: source.title, excerpt: knowledge.source_excerpt }] });
      return mockJson({});
    }));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("loads the dashboard and navigates to approved knowledge", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Make your thinking compound." })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Brain" }));
    expect(screen.getByRole("heading", { name: "Your Brain" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: knowledge.statement })).toBeInTheDocument();
  });

  it("asks a grounded question and renders evidence", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Recently approved");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await user.click(screen.getByRole("button", { name: /Ask the Brain/i }));
    await waitFor(() => expect(screen.getByText("Grounded answer")).toBeInTheDocument());
    expect(screen.getByText(source.title)).toBeInTheDocument();
  });

  it("shows immutable source provenance and knowledge history", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Recently approved");

    await user.click(screen.getByRole("button", { name: "Sources" }));
    expect(screen.getByText("aaaaaaaaaaaa")).toBeInTheDocument();
    await user.click(screen.getByText("Add immutable version"));
    expect(screen.getByLabelText("What changed?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Brain" }));
    await user.click(screen.getByText(/1 revision · inspect or supersede/i));
    expect(await screen.findByText("Initial approval")).toBeInTheDocument();
  });
});
