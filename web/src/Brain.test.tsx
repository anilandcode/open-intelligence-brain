import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrainView } from "./LivePages";
import { BrainClientContext, type BrainClient } from "./client";
import { createDemoClient } from "./demo";
import type { Knowledge } from "./api";

const due: Knowledge = { id: "k1", proposal_id: "p1", source_id: "s1", source_title: "Pricing", type: "fact", statement: "Enterprise pays 1200 dollars per seat.", rationale: "", source_excerpt: "Enterprise pays 1200 dollars per seat.", status: "canonical", version: 1, approved_at: "2026-01-01T00:00:00Z", revision_count: 1, stale: false, conflict_ids: [], review_by: "2026-02-01T00:00:00Z", due_for_review: true, expired: false };
const fine: Knowledge = { ...due, id: "k2", statement: "Lessons stay true.", review_by: null, due_for_review: false };

describe("brain dates", () => {
  it("counts due items as needing attention and confirms one as still true", async () => {
    const markReviewed = vi.fn(async () => ({ ...due, due_for_review: false }));
    const onNotice = vi.fn();
    render(
      <BrainClientContext.Provider value={{ ...createDemoClient(), markReviewed } as BrainClient}>
        <BrainView recordId="k1" onSelect={vi.fn()} initial={[due, fine]} onChanged={vi.fn(async () => {})} onNotice={onNotice} onError={vi.fn()} />
      </BrainClientContext.Provider>,
    );
    expect(screen.getByRole("button", { name: /^Needs attention \d/ }).textContent).toBe("Needs attention 1");
    expect(screen.getByText("Due for review")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Still true/ }));
    await waitFor(() => expect(markReviewed).toHaveBeenCalledWith("k1", 90));
    expect(onNotice).toHaveBeenCalledWith("Marked as still true. Next review in 90 days.");
  });
});
