import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CaptureView, WatchesPanel } from "./Capture";
import { bookmarklet, isShareLanding, readSharedCapture } from "./captureLinks";
import { BrainClientContext } from "./client";
import { createDemoClient } from "./demo";

describe("shared captures", () => {
  it("reads a phone share from the query and a clip from the hash", () => {
    expect(readSharedCapture({ search: "?title=Pricing&text=Worth+reading+https%3A%2F%2Fexample.com%2Fp", hash: "" })).toEqual({ title: "Pricing", text: "Worth reading https://example.com/p", url: "https://example.com/p", via: "share" });
    expect(readSharedCapture({ search: "?text=https%3A%2F%2Fexample.com%2Fonly", hash: "" })).toEqual({ title: "", text: "", url: "https://example.com/only", via: "share" });
    expect(readSharedCapture({ search: "", hash: "#/console/capture?title=Doc&url=https%3A%2F%2Fa.io&text=Picked" })).toEqual({ title: "Doc", text: "Picked", url: "https://a.io", via: "clipper" });
    expect(readSharedCapture({ search: "", hash: "#/console/capture" })).toBeNull();
  });

  it("treats only a share as a share landing", () => {
    expect(isShareLanding("?text=hello")).toBe(true);
    expect(isShareLanding("?session_uri=x&text=hello")).toBe(false);
    expect(isShareLanding("")).toBe(false);
  });

  it("builds a bookmarklet that opens the capture view", () => {
    const link = bookmarklet("https://brain.example.com/");
    expect(link.startsWith("javascript:")).toBe(true);
    expect(link).toContain('"https://brain.example.com/#/console/capture?"');
  });
});

describe("capture view", () => {
  afterEach(() => { window.location.hash = ""; });

  it("prefills a clipped page and saves it for review", async () => {
    window.location.hash = "#/console/capture?title=Launch%20plan&url=https%3A%2F%2Fexample.com%2Flaunch&text=The%20launch%20moves%20to%20May%20after%20the%20pricing%20review.";
    const client = createDemoClient();
    const capture = vi.spyOn(client, "capture");
    const onNotice = vi.fn();
    const onChanged = vi.fn().mockResolvedValue(undefined);
    render(<BrainClientContext.Provider value={client}><CaptureView onChanged={onChanged} onNotice={onNotice} onError={vi.fn()} /></BrainClientContext.Provider>);
    expect(screen.getByRole("status").textContent).toContain("https://example.com/launch");
    expect((screen.getByLabelText(/Title/) as HTMLInputElement).value).toBe("Launch plan");
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "research" } });
    fireEvent.click(screen.getByRole("button", { name: /Save for review/ }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(capture).toHaveBeenCalledWith(expect.objectContaining({ title: "Launch plan", url: "https://example.com/launch", kind: "research", via: "clipper" }));
    expect(onNotice.mock.calls[0][0]).toMatch(/Saved “Launch plan”. 1 suggestion is in the Inbox/);
    expect((screen.getByLabelText("What to capture") as HTMLTextAreaElement).value).toBe("");
    expect(window.location.hash).toBe("#/console/capture");
  });

  it("explains transcripts and hides dictation without browser support", () => {
    render(<BrainClientContext.Provider value={createDemoClient()}><CaptureView onChanged={vi.fn()} onNotice={vi.fn()} onError={vi.fn()} /></BrainClientContext.Provider>);
    expect(screen.queryByRole("button", { name: /Dictate/ })).toBeNull();
    expect((screen.getByRole("button", { name: /Save for review/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "transcript" } });
    expect(screen.getByText(/Timings are dropped and each suggestion notes who said it/)).toBeTruthy();
  });
});

describe("watched folders", () => {
  it("adds a folder, syncs it with a token, and stops watching", async () => {
    const client = createDemoClient();
    const sync = vi.spyOn(client, "syncWatch");
    const onNotice = vi.fn();
    render(<BrainClientContext.Provider value={client}><WatchesPanel onChanged={vi.fn().mockResolvedValue(undefined)} onNotice={onNotice} onError={vi.fn()} /></BrainClientContext.Provider>);
    fireEvent.change(await screen.findByLabelText("Folder ID"), { target: { value: "folder-1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Meeting notes" } });
    fireEvent.change(screen.getByLabelText("Documents are"), { target: { value: "transcript" } });
    fireEvent.click(screen.getByRole("button", { name: "Watch folder" }));
    expect(await screen.findByText("Meeting notes")).toBeTruthy();
    expect(screen.getByText(/meeting transcripts · private · 0 documents/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/access token for Meeting notes/), { target: { value: "tok" } });
    fireEvent.click(screen.getByRole("button", { name: "Sync" }));
    await waitFor(() => expect(sync).toHaveBeenCalledWith(expect.any(String), "tok"));
    await waitFor(() => expect(onNotice.mock.calls.at(-1)?.[0]).toMatch(/Meeting notes: 1 new.*New suggestions are in the Inbox/));
    expect(await screen.findByText(/1 document$/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Stop watching Meeting notes" }));
    await waitFor(() => expect(screen.queryByText("Meeting notes")).toBeNull());
  });
});
