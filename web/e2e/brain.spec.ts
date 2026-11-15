import { test, expect } from "@playwright/test";

test.describe("Open Intelligence Brain E2E Suite", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/#/demo/overview");
  });

  test("loads the Overview dashboard with Today items and navigation", async ({ page }) => {
    await expect(page).toHaveTitle(/Open Brain/i);
    await expect(page.locator("h1")).toContainText(/Overview/i);

    // Verify Today section with actionable review counters
    await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
    await expect(page.getByRole("button", { name: /suggestions to review/i })).toBeVisible();

    // Verify Workspace summary metrics
    await expect(page.getByText(/Approved knowledge/i).first()).toBeVisible();
    await expect(page.getByText(/Waiting for review/i).first()).toBeVisible();
  });

  test("Inbox review flow: inspect candidate proposals and batch governance", async ({ page }) => {
    await page.goto("/#/demo/inbox");
    await expect(page.locator("h1")).toContainText(/Review inbox/i);

    // Verify proposal review card with editable canonical statement
    const statementBox = page.getByRole("textbox", { name: "Canonical statement" });
    await expect(statementBox).toBeVisible();
    await expect(statementBox).toHaveValue(/Send a written recap after every setup call/);

    // Verify governance action buttons
    await expect(page.getByRole("button", { name: "Approve to Brain" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();
  });

  test("Knowledge base and time-travel inspection", async ({ page }) => {
    await page.goto("/#/demo/brain");
    await expect(page.locator("h1")).toContainText(/Your Brain/i);

    // Verify bi-temporal time-travel controls (Bit 5 / v2.1.0)
    await expect(page.locator('input[type="datetime-local"]')).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Include superseded" })).toBeVisible();

    // Verify search box and canonical knowledge items
    const searchInput = page.getByRole("searchbox", { name: "Search approved knowledge" });
    await expect(searchInput).toBeVisible();
    await expect(page.getByText("Assign one named owner for the first customer week.")).toBeVisible();
  });

  test("Working memory and agent scratchpad flow", async ({ page }) => {
    await page.goto("/#/demo/working-memory");
    await expect(page.locator("h1")).toContainText(/Working memory/i);

    // Verify agent note is rendered
    await expect(page.getByText(/renewal pricing/i).first()).toBeVisible();
  });

  test("Connections and staged actions hub (M6)", async ({ page }) => {
    await page.goto("/#/demo/connections");
    // Verify Connections / staged actions view
    await expect(page.locator("h1, h2").first()).toBeVisible();
    await expect(page.getByText(/Connections/i).first()).toBeVisible();
  });
});
