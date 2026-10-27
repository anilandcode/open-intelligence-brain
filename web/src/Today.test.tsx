import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TodayPanel, UnansweredPanel } from "./Today";
import { readSharedCapture } from "./captureLinks";
import { BrainClientContext } from "./client";
import { createDemoClient } from "./demo";

describe("today", () => {
  it("lists what needs a person and opens the right view", async () => {
    const client = createDemoClient();
    await client.chat("Who is our accountant?");
    const onNavigate = vi.fn();
    render(<BrainClientContext.Provider value={client}><TodayPanel onNavigate={onNavigate} /></BrainClientContext.Provider>);
    const reviews = await screen.findByRole("button", { name: /suggestions to review/ });
    fireEvent.click(reviews);
    expect(onNavigate).toHaveBeenCalledWith("inbox");
    fireEvent.click(screen.getByRole("button", { name: /question the Brain couldn't answer/ }));
    expect(onNavigate).toHaveBeenCalledWith("ask");
    expect(screen.getByRole("button", { name: /agent working note/ })).toBeTruthy();
  });
});

describe("couldn't answer", () => {
  afterEach(() => { window.location.hash = ""; });

  it("folds repeats, links to capture an answer, and dismisses", async () => {
    window.location.hash = "#/demo/ask";
    const client = createDemoClient();
    await client.chat("Who is our accountant?");
    await client.chat("who is the accountant");
    render(<BrainClientContext.Provider value={client}><UnansweredPanel version={0} /></BrainClientContext.Provider>);
    expect(await screen.findByText("who is the accountant")).toBeTruthy();
    expect(screen.getByText(/Asked 2 times/)).toBeTruthy();
    const link = screen.getByRole("link", { name: "Capture an answer" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("#/demo/capture?question=who+is+the+accountant");
    expect(readSharedCapture({ search: "", hash: link.getAttribute("href")! })).toMatchObject({ title: "who is the accountant", question: "who is the accountant", via: "console" });
    fireEvent.click(screen.getByRole("button", { name: "Dismiss: who is the accountant" }));
    await waitFor(() => expect(screen.getByText("No open questions.")).toBeTruthy());
  });

  it("stays hidden when the log is not readable", async () => {
    const client = createDemoClient();
    vi.spyOn(client, "unanswered").mockRejectedValue(new Error("forbidden"));
    const { container } = render(<BrainClientContext.Provider value={client}><UnansweredPanel version={0} /></BrainClientContext.Provider>);
    await waitFor(() => expect(client.unanswered).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
