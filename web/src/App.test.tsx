import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { TOKEN_KEY } from "./api";

const overview = {
  sources: 1,
  proposals: 2,
  canonical: 1,
  pending_reviews: 1,
  recent_activity: [],
  // The Overview reads this to show which engine produced the proposals, so a
  // fixture without it would crash the whole app rather than one pill.
  engine: {
    name: "deterministic",
    available: true,
    detail: "Local extraction, no inference",
    container_tag: "",
  },
};
const integrity = { stale_count: 0, conflict_count: 0, issues: [] };
const source = { id: "src_1", title: "Interview", kind: "interview", sensitivity: "private", content: "A sufficiently long source note for this fixture.", created_at: new Date().toISOString(), proposal_count: 1, current_version: 1, content_hash: "a".repeat(64) };
const proposal = { id: "prop_1", source_id: "src_1", source_title: "Interview", type: "belief", statement: "Approved context makes generated work more distinctive.", rationale: "Candidate extracted from source.", source_excerpt: "Approved context makes generated work more distinctive.", status: "proposed", critic_notes: "", summary: "Candidate extracted from source.", tags: '["context"]', created_at: new Date().toISOString() };
const knowledge = { id: "know_1", proposal_id: "prop_0", source_id: "src_1", source_title: "Interview", type: "belief", statement: "Proprietary context improves generated work.", rationale: "Grounded in experience.", source_excerpt: "Proprietary context improves generated work.", status: "canonical", version: 1, approved_at: new Date().toISOString(), revision_count: 1, stale: false, conflict_ids: [] };
const revision = { id: "rev_1", knowledge_id: knowledge.id, revision: 1, statement: knowledge.statement, rationale: knowledge.rationale, source_id: source.id, source_version_id: "srcv_1", source_span_id: "span_1", source_excerpt: knowledge.source_excerpt, change_note: "Initial approval", approved_at: knowledge.approved_at };

function mockJson(value: unknown) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(value) } as Response);
}

describe("App", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", window.location.pathname);
    vi.stubGlobal("scrollTo", vi.fn());
    // The bundle carries no token of its own, so the page meets every visitor —
    // including this test — with the access gate. A presented token is what
    // gets the workspace to render at all.
    window.sessionStorage.setItem(TOKEN_KEY, "test-token");
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/overview")) return mockJson(overview);
      if (url.includes("/integrity")) return mockJson(integrity);
      if (url.includes("/sources")) return mockJson([source]);
      if (url.includes("/proposals")) return mockJson([proposal]);
      if (url.includes("/knowledge/know_1/revisions")) return mockJson([revision]);
      if (url.includes("/knowledge")) return mockJson([knowledge]);
      if (url.includes("/chat")) return mockJson({ answer: knowledge.statement, grounded: true, citations: [{ knowledge_id: knowledge.id, source_id: source.id, source_title: source.title, excerpt: knowledge.source_excerpt }] });
      if (url.includes("/studio/interviews")) return mockJson([]);
      if (url.includes("/studio/drafts")) return mockJson([]);
      if (url.includes("/mcp/connections")) return mockJson([]);
      return mockJson({});
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
  });

  it("loads the dashboard and navigates to approved knowledge", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Brain" }));
    expect(screen.getByRole("heading", { name: "Your Brain" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: new RegExp(knowledge.statement) }));
    expect(screen.getByRole("heading", { name: knowledge.statement })).toBeInTheDocument();
  });

  it("keeps rail search and secondary Settings navigation usable in the isolated demo", async () => {
    window.location.hash = "/demo/overview";
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Recently approved");
    expect(fetch).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Search or jump to… ⌘K" }));
    const search = screen.getByRole("dialog");
    await user.type(within(search).getByRole("textbox"), "Settings");
    await user.click(within(search).getByRole("option", { name: /Settings/ }));
    expect(screen.getByRole("heading", { name: "General" })).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "Settings navigation" });
    await user.click(within(navigation).getByRole("button", { name: "Team Preview" }));
    expect(screen.getByRole("heading", { level: 1, name: "Team" })).toBeInTheDocument();
    expect(screen.getByText("Settings for team are not connected in this UI phase.")).toBeInTheDocument();
    await user.click(within(navigation).getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("asks a grounded question and renders evidence", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Recently approved");
    await user.click(screen.getByRole("button", { name: "Ask the Brain" }));
    await user.click(screen.getByRole("button", { name: /Ask the Brain/i }));
    await waitFor(() => expect(screen.getByText("Grounded answer")).toBeInTheDocument());
    expect(screen.getByText(source.title)).toBeInTheDocument();
  });

  it("shows immutable source provenance and knowledge history", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Recently approved");

    await user.click(screen.getByRole("button", { name: "Sources" }));
    await user.click(screen.getByRole("button", { name: /Interviewinterviewprivatev1/i }));
    expect(screen.getByText("aaaaaaaaaaaa")).toBeInTheDocument();
    await user.click(screen.getByText("Add immutable version"));
    expect(screen.getByLabelText("What changed?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close details" }));

    await user.click(screen.getByRole("button", { name: "Brain" }));
    await user.click(screen.getByRole("button", { name: new RegExp(knowledge.statement) }));
    await user.click(screen.getByText(/1 revision · inspect or supersede/i));
    expect(await screen.findByText("Initial approval")).toBeInTheDocument();
  });

  it("shows the public landing and token gate without a workspace request", async () => {
    window.sessionStorage.clear();
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("heading", { name: /A shared brain for/i })).toBeInTheDocument();
    // The page must not disclose the workspace it is guarding, so nothing is
    // requested and none of the workspace's own copy is on screen.
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Overview" })).toBeNull();
    expect(screen.queryByText("Personal Brain")).toBeNull();

    // A presented token is what lets the workspace load.
    await user.click(screen.getAllByRole("button", { name: "Open your Brain" })[0]);
    expect(screen.getByRole("heading", { name: "Welcome to your Brain." })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Access token"), "test-token");
    await user.click(screen.getByRole("button", { name: "Open the Brain" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe("test-token");
  });

  it("navigates to the live Intelligence Studio", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Recently approved");
    await user.click(screen.getByRole("button", { name: "Studio" }));
    expect(screen.getByRole("heading", { name: "Intelligence Studio" })).toBeInTheDocument();
    // Studio now has live interview and draft tabs
    expect(screen.getByText("Interviews")).toBeInTheDocument();
    expect(screen.getByText("Drafts")).toBeInTheDocument();
  });
  it("runs the real demo layouts without requesting the authenticated workspace", async () => {
    window.history.replaceState(null, "", "#/demo/inbox");
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", {name: /Send a written recap/});
    await user.click(screen.getByRole("button", {name: /Approve to Brain/}));
    await screen.findByText(/approved and added/i);
    await user.click(screen.getByRole("button", {name: "Brain"}));
    await screen.findByRole("button", {name: /Send a written recap/});
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows failed loading honestly and recovers when retried", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("Workspace connection failed"));
    const user=userEvent.setup();render(<App/>);
    expect(await screen.findByRole("heading",{name:"Workspace unavailable"})).toBeInTheDocument();
    expect(screen.queryByText("Recently approved")).toBeNull();
    await user.click(screen.getByRole("button",{name:"Retry loading"}));
    expect(await screen.findByText("Recently approved")).toBeInTheDocument();
  });

  it("keeps public home accessible when a token is already present", () => {
    window.history.replaceState(null,"","#/");render(<App/>);
    expect(screen.getByRole("heading", {name:/A shared brain for/})).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps landing section links public and supports keyboard workflow tabs", async () => {
    window.history.replaceState(null,"","#/"); const user=userEvent.setup(); render(<App/>);
    await user.click(screen.getByRole("link", {name:/Inside the console/}));
    await waitFor(()=>expect(window.location.hash).toBe("#product"));
    expect(screen.getByRole("heading", {name:/A shared brain for/})).toBeInTheDocument();
    await user.click(screen.getByRole("tab", {name:/Capture/}));
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", {name:/Review/})).toHaveAttribute("aria-selected","true");
    expect(screen.getByRole("tabpanel", {name:/Capture|Review|Reuse/})).toHaveTextContent("awaiting approval");
    await user.keyboard("{End}");
    expect(screen.getByRole("tabpanel", {name:/Capture|Review|Reuse/})).toHaveTextContent("Approved knowledge");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("copies synthetic landing context and gives a usable failure message", async () => {
    window.history.replaceState(null,"","#/"); const user=userEvent.setup(); render(<App/>);
    const copy=vi.spyOn(navigator.clipboard,"writeText");
    await user.click(screen.getByRole("button", {name:"Copy sample context"}));
    expect(await screen.findByText("Sample context copied.")).toBeInTheDocument();
    expect(copy).toHaveBeenCalledWith(expect.stringContaining("Synthetic example"));
    copy.mockRejectedValueOnce(new Error("Copy denied"));
    await user.click(screen.getByRole("button", {name:"Copy sample context"}));
    expect(await screen.findByText(/Copy is unavailable here/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled(); copy.mockRestore();
  });

  it("switches public recall examples and exposes exact synthetic evidence without a workspace request", async () => {
    window.history.replaceState(null,"","#/"); const user=userEvent.setup(); render(<App/>);
    await user.click(screen.getByRole("tab", {name:"Context"}));
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", {name:"History"})).toHaveAttribute("aria-selected","true");
    const history = screen.getByRole("tabpanel", {name:"History"});
    expect(history).toHaveTextContent("Send a written recap after every customer interview.");
    await user.click(within(history).getByText("Research practice · v2"));
    expect(history.querySelector("details")).toHaveAttribute("open");
    expect(history).toHaveTextContent("A written recap helps the whole team check what they heard before making a decision.");
    await user.keyboard("{Tab}");
    await user.click(screen.getByRole("tab", {name:"Evidence"}));
    expect(screen.getByRole("tabpanel",{name:"Evidence"})).toHaveTextContent("Record the rationale behind each product decision.");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("retains failed import content and retries a single capture", async () => {
    const originalFetch = vi.mocked(fetch).getMockImplementation()!;
    let captures = 0;
    vi.mocked(fetch).mockImplementation((input, init) => {
      if (String(input).endsWith("/sources") && init?.method === "POST") {
        captures++;
        return captures === 1 ? Promise.reject(new Error("Capture temporarily unavailable")) : mockJson(source);
      }
      return originalFetch(input, init);
    });
    window.history.replaceState(null, "", "#/console/import");
    const user = userEvent.setup(); render(<App/>);
    const title = await screen.findByLabelText("Title");
    await user.type(title, "Sample interview");
    const content = screen.getByLabelText("Source content");
    await user.type(content, "Retain the complete original interview and review its claims.");
    await user.click(screen.getByRole("button", {name:"Capture and extract"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("Capture temporarily unavailable");
    expect(content).toHaveValue("Retain the complete original interview and review its claims.");
    await user.click(screen.getByRole("button", {name:"Capture and extract"}));
    expect(await screen.findByText("Source captured. Review its proposals in Inbox.")).toBeInTheDocument();
    expect(captures).toBe(2); expect(content).toHaveValue("");
  });

  it("opens a source deep link and reports an unavailable record", async () => {
    window.history.replaceState(null, "", "#/demo/sources?record=missing-record");
    render(<App/>);
    expect(await screen.findByRole("heading", {name:"Source unavailable"})).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps key previews away from the real API", async () => {
    window.history.replaceState(null, "", "#/demo/api-keys");
    const user = userEvent.setup(); render(<App/>);
    await user.click(await screen.findByRole("button", {name:"Create key · Preview"}));
    await user.type(screen.getByLabelText("Name"), "Dummy development row");
    await user.click(screen.getByRole("button", {name:"Add preview row"}));
    await user.click(screen.getByRole("button", {name:/Dummy development row/}));
    await user.click(screen.getByRole("button", {name:"Remove preview row"}));
    expect(screen.getByText("No preview keys yet")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("contains mobile navigation focus and restores it on Escape", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    window.history.replaceState(null, "", "#/demo/brain");
    const user = userEvent.setup(); render(<App/>);
    const opener = await screen.findByRole("button", {name:"Open navigation"});
    expect(screen.queryByRole("dialog", {name:"Workspace navigation"})).toBeNull();
    await user.click(opener);
    const close = screen.getByRole("button", {name:"Close navigation drawer"});
    expect(close).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", {name:"Settings Preview"})).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(opener).toHaveFocus();
    expect(opener).toHaveAttribute("aria-expanded", "false");
    await user.click(opener);
    await user.click(screen.getByRole("button", {name:"Search or jump to… ⌘K"}));
    const search = screen.getByRole("dialog", {name:"Search and jump to"});
    fireEvent(search, new Event("cancel", {bubbles:true, cancelable:true}));
    expect(opener).toHaveFocus();
    expect(screen.queryByRole("dialog", {name:"Search and jump to"})).toBeNull();
  });

});
