import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { InboxView } from "./LivePages";
import { BrainClientContext, type BrainClient } from "./client";
import { createDemoClient } from "./demo";
import type { Proposal } from "./api";

function proposal(id: string, sourceId: string, title: string, statement: string): Proposal {
  return { id, source_id: sourceId, source_title: title, type: "decision", statement, rationale: "", source_excerpt: statement, status: "proposed", critic_notes: "", tags: "[]", created_at: "2026-10-27T10:00:00Z" };
}

const queue = [
  proposal("p1", "s1", "Pricing notes", "Enterprise customers pay annually."),
  proposal("p2", "s1", "Pricing notes", "Monthly billing is retired for new accounts."),
  proposal("p3", "s2", "Hiring notes", "We hire a second designer this quarter."),
];

function renderInbox(client: Partial<BrainClient>) {
  const onChanged = vi.fn(async () => {});
  const onNotice = vi.fn();
  render(
    <BrainClientContext.Provider value={{ ...createDemoClient(), ...client } as BrainClient}>
      <InboxView proposals={queue} onChanged={onChanged} onNotice={onNotice} onError={vi.fn()} />
    </BrainClientContext.Provider>,
  );
  return { onChanged, onNotice };
}

describe("review inbox", () => {
  it("groups proposals by source", () => {
    renderInbox({});
    expect(screen.getByRole("group", { name: "Pricing notes" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Hiring notes" })).toBeTruthy();
  });

  it("approves the selected proposals as written", async () => {
    const reviewProposals = vi.fn(async () => ({ approved: ["k1", "k2"], rejected: [], skipped: [] }));
    const { onChanged, onNotice } = renderInbox({ reviewProposals });
    fireEvent.click(screen.getByLabelText("Select: Enterprise customers pay annually."));
    fireEvent.click(screen.getByLabelText("Select: We hire a second designer this quarter."));
    expect(screen.getByText("2 selected")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Approve as written/ }));
    await waitFor(() => expect(reviewProposals).toHaveBeenCalledWith(["p1", "p3"], "approve", undefined));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith("2 approved to the Brain."));
    expect(onChanged).toHaveBeenCalled();
  });

  it("asks once more before dismissing the rest of a source", async () => {
    const dismissSourceProposals = vi.fn(async () => ({ source_id: "s1", rejected: 2 }));
    renderInbox({ dismissSourceProposals });
    const pricing = screen.getByRole("group", { name: "Pricing notes" });
    const dismiss = pricing.querySelector(".queue-dismiss") as HTMLButtonElement;
    fireEvent.click(dismiss);
    expect(dismissSourceProposals).not.toHaveBeenCalled();
    expect(dismiss.textContent).toBe("Confirm: reject 2");
    fireEvent.click(dismiss);
    await waitFor(() => expect(dismissSourceProposals).toHaveBeenCalledWith("s1", expect.any(String)));
  });
});
