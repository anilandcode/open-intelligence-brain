import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const overview = { sources: 1, proposals: 2, canonical: 1, pending_reviews: 1, recent_activity: [] };
const source = { id: "src_1", title: "Interview", kind: "interview", sensitivity: "private", content: "A sufficiently long source note for this fixture.", created_at: new Date().toISOString(), proposal_count: 1 };
const proposal = { id: "prop_1", source_id: "src_1", source_title: "Interview", type: "belief", statement: "Approved context makes generated work more distinctive.", rationale: "Candidate extracted from source.", source_excerpt: "Approved context makes generated work more distinctive.", status: "proposed", created_at: new Date().toISOString() };
const knowledge = { id: "know_1", proposal_id: "prop_0", source_id: "src_1", source_title: "Interview", type: "belief", statement: "Proprietary context improves generated work.", rationale: "Grounded in experience.", source_excerpt: "Proprietary context improves generated work.", status: "canonical", version: 1, approved_at: new Date().toISOString() };

function mockJson(value: unknown) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(value) } as Response);
}

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal("scrollTo", vi.fn());
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/overview")) return mockJson(overview);
      if (url.includes("/sources")) return mockJson([source]);
      if (url.includes("/proposals")) return mockJson([proposal]);
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
    expect(screen.getByText(knowledge.statement)).toBeInTheDocument();
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
});

