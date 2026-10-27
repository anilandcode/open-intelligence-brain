import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PeopleView } from "./People";
import { BrainClientContext } from "./client";
import { createDemoClient } from "./demo";
import { formatEntityText, parseEntityText } from "./entities";

describe("entity text", () => {
  it("round-trips names and kinds, defaulting to topic", () => {
    expect(parseEntityText("Dana Lee (person), Acme (Company), Billing, x, dana lee (person), Odd (vendor)")).toEqual([
      { name: "Dana Lee", kind: "person" },
      { name: "Acme", kind: "company" },
      { name: "Billing", kind: "topic" },
      { name: "Odd", kind: "topic" },
    ]);
    expect(formatEntityText([{ name: "Dana Lee", kind: "person" }, { name: "Billing", kind: "topic" }])).toBe("Dana Lee (person), Billing");
  });
});

describe("people and projects", () => {
  it("lists entities, opens one, and adds a new name", async () => {
    const client = createDemoClient();
    const onSelect = vi.fn();
    const onNotice = vi.fn();
    const { rerender } = render(
      <BrainClientContext.Provider value={client}>
        <PeopleView onSelect={onSelect} onNotice={onNotice} onError={vi.fn()} />
      </BrainClientContext.Provider>,
    );
    const row = await screen.findByRole("button", { name: /Product team/ });
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith("sample-entity-2");

    rerender(
      <BrainClientContext.Provider value={client}>
        <PeopleView recordId="sample-entity-2" onSelect={onSelect} onNotice={onNotice} onError={vi.fn()} />
      </BrainClientContext.Provider>,
    );
    expect(await screen.findByText("Record the rationale behind each product decision.")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("Add a person, company, project or topic"), { target: { value: "Customer week" } });
    fireEvent.click(screen.getByRole("button", { name: /^Add$/ }));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith(expect.stringContaining("Customer week added")));
  });
});
