import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AskView } from "./LivePages";
import { BrainClientContext, type BrainClient } from "./client";
import { createDemoClient } from "./demo";
import type { ChatResult } from "./api";

const written: ChatResult = {
  answer: "Enterprise customers pay annually. Dana owns the migration.",
  grounded: true,
  written: true,
  dropped_sentences: 1,
  sentences: [
    { text: "Enterprise customers pay annually.", knowledge_ids: ["k1"] },
    { text: "Dana owns the migration.", knowledge_ids: ["k2", "k1"] },
  ],
  citations: [
    { knowledge_id: "k1", source_id: "s1", source_title: "Pricing", excerpt: "We bill enterprise annually." },
    { knowledge_id: "k2", source_id: "s2", source_title: "Plan", excerpt: "Dana owns it." },
  ],
};

function renderAsk(overrides: Partial<BrainClient>) {
  const client = { ...createDemoClient(), ...overrides } as BrainClient;
  render(
    <BrainClientContext.Provider value={client}>
      <AskView />
    </BrainClientContext.Provider>,
  );
  return client;
}

describe("playground", () => {
  it("shows a written answer with per-sentence citations and saves it as a test question", async () => {
    const addEvalQuestion = vi.fn(async (payload: { question: string }) => ({ id: "q1", question: payload.question, expected_ids: ["k1", "k2"], expect_abstain: false, note: "", created_at: "2026-10-27T10:00:00Z" }));
    renderAsk({ chat: vi.fn(async () => written), addEvalQuestion });
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How does enterprise billing work?" } });
    fireEvent.click(screen.getByRole("button", { name: /Ask the Brain/ }));
    expect(await screen.findByText("Enterprise customers pay annually.")).toBeTruthy();
    expect(screen.getAllByText("[1]")).toHaveLength(2);
    expect(screen.getByText("[2]")).toBeTruthy();
    expect(screen.getByText(/1 that could not be traced was left out/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save as test question" }));
    await waitFor(() => expect(addEvalQuestion).toHaveBeenCalledWith({ question: "How does enterprise billing work?", expected_ids: ["k1", "k2"] }));
    expect(await screen.findByText(/cites one of these items/)).toBeTruthy();
  });

  it("saves an unanswered question as one the Brain should not answer, then runs the set", async () => {
    renderAsk({});
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "What is the office dog called?" } });
    fireEvent.click(screen.getByRole("button", { name: /Ask the Brain/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Save as test question" }));
    expect(await screen.findByText("Saved as a question the Brain should not answer.")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Run 1" }));
    expect(await screen.findByText("Every question passed.")).toBeTruthy();
    expect(screen.getByText("Abstained correctly")).toBeTruthy();
  });
});
