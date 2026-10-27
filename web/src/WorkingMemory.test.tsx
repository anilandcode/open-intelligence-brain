import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkingMemoryView } from "./WorkingMemory";
import { BrainClientContext } from "./client";
import { createDemoClient } from "./demo";

function setup() {
  const client = createDemoClient();
  const props = { onOpenKnowledge: vi.fn(), onOpenSource: vi.fn(), onChanged: vi.fn().mockResolvedValue(undefined), onNotice: vi.fn(), onError: vi.fn() };
  render(<BrainClientContext.Provider value={client}><WorkingMemoryView {...props} /></BrainClientContext.Provider>);
  return { client, props };
}

describe("working memory", () => {
  it("promotes an agent note for review and then links to it", async () => {
    const { client, props } = setup();
    const promote = vi.spyOn(client, "promoteNote");
    expect(await screen.findByText(/multi-year renewal pricing/)).toBeTruthy();
    expect(screen.getByText("renewal research")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    await waitFor(() => expect(promote).toHaveBeenCalledWith("sample-note-1"));
    await waitFor(() => expect(props.onNotice).toHaveBeenCalledWith(expect.stringMatching(/Filed “Agent note: renewal research” for review/)));
    fireEvent.click(await screen.findByRole("button", { name: "Filed for review" }));
    expect(props.onOpenSource).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Promote" })).toBeNull();
  });

  it("deletes a note", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: /Delete note/ }));
    expect(await screen.findByText("No working notes right now.")).toBeTruthy();
  });

  it("labels source search hits as unreviewed", async () => {
    const { client, props } = setup();
    await client.capture({ text: "Renewal discounts for annual contracts are capped at fifteen percent." });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "renewal discounts" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const badge = await screen.findAllByText("Unreviewed");
    expect(badge.length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: /Renewal discounts for annual/ })[0]);
    expect(props.onOpenSource).toHaveBeenCalled();
  });
});
