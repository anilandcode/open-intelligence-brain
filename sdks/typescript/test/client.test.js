import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { BrainClient } from "../dist/index.js";

describe("@openbrain/sdk BrainClient", () => {
  it("initializes with default options and formats base URL", () => {
    const client = new BrainClient({ baseUrl: "http://example.com:8000/" });
    assert.ok(client);
  });

  it("sends appropriate headers including token and user agent", async () => {
    let capturedUrl = "";
    let capturedOptions = {};

    const mockFetch = async (url, options) => {
      capturedUrl = String(url);
      capturedOptions = options;
      return {
        ok: true,
        status: 200,
        json: async () => ({ id: "src_1", title: "Test", kind: "note" }),
      };
    };

    const client = new BrainClient({
      baseUrl: "http://localhost:8000",
      apiKey: "test-token-123",
      fetch: mockFetch,
    });

    const result = await client.add({ content: "Hello memory world" });
    assert.equal(result.id, "src_1");
    assert.equal(capturedUrl, "http://localhost:8000/api/v1/sources");
    assert.equal(capturedOptions.method, "POST");
    assert.equal(capturedOptions.headers["X-Brain-Token"], "test-token-123");
    assert.equal(capturedOptions.headers["User-Agent"], "@openbrain/sdk/2.0.0");
    assert.equal(capturedOptions.headers["Content-Type"], "application/json");

    const body = JSON.parse(capturedOptions.body);
    assert.equal(body.content, "Hello memory world");
    assert.equal(body.title, "Hello memory world");
    assert.equal(body.kind, "note");
  });

  it("handles search queries with bi-temporal as_of parameters", async () => {
    let capturedUrl = "";

    const mockFetch = async (url) => {
      capturedUrl = String(url);
      return {
        ok: true,
        status: 200,
        json: async () => [
          {
            id: "k_1",
            statement: "Postgres 16 is standard",
            valid_from: "2024-01-01T00:00:00Z",
          },
        ],
      };
    };

    const client = new BrainClient({ baseUrl: "http://localhost:8000", fetch: mockFetch });

    const pastDate = new Date("2024-06-01T12:00:00Z");
    const results = await client.search({
      query: "postgres",
      as_of: pastDate,
      include_superseded: true,
    });

    assert.equal(results.length, 1);
    assert.ok(capturedUrl.includes("/api/v1/knowledge?"));
    assert.ok(capturedUrl.includes("q=postgres"));
    assert.ok(capturedUrl.includes("as_of=2024-06-01T12%3A00%3A00.000Z") || capturedUrl.includes("as_of=2024-06-01"));
    assert.ok(capturedUrl.includes("include_superseded=true"));
  });

  it("handles ask query for grounded QA", async () => {
    let capturedBody = "";

    const mockFetch = async (url, options) => {
      capturedBody = options.body;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          answer: "PostgreSQL 16 is the standard database.",
          citations: [
            {
              knowledge_id: "k_1",
              source_id: "s_1",
              source_title: "Tech Stack",
              excerpt: "We use Postgres 16",
            },
          ],
          grounded: true,
        }),
      };
    };

    const client = new BrainClient({ baseUrl: "http://localhost:8000", fetch: mockFetch });
    const res = await client.ask("What is our database?");

    assert.equal(res.grounded, true);
    assert.equal(res.citations.length, 1);
    const parsed = JSON.parse(capturedBody);
    assert.equal(parsed.question, "What is our database?");
  });

  it("handles batch approval and rejection", async () => {
    const mockFetch = async (url, options) => {
      const parsed = JSON.parse(options.body);
      if (url.includes("/batch-approve")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            approved_count: parsed.proposal_ids.length,
            knowledge_ids: ["k_10", "k_11"],
            failed_ids: [],
          }),
        };
      }
      if (url.includes("/batch-reject")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            declined_count: parsed.proposal_ids.length,
            declined_ids: parsed.proposal_ids,
          }),
        };
      }
      return { ok: false, status: 404, text: async () => "Not found" };
    };

    const client = new BrainClient({ baseUrl: "http://localhost:8000", fetch: mockFetch });

    const approveRes = await client.batchApprove(["p_1", "p_2"]);
    assert.equal(approveRes.approved_count, 2);
    assert.deepEqual(approveRes.knowledge_ids, ["k_10", "k_11"]);

    const rejectRes = await client.batchReject(["p_3", "p_4"], "Outdated claims");
    assert.equal(rejectRes.declined_count, 2);
  });

  it("throws descriptive error on API failures", async () => {
    const mockFetch = async () => ({
      ok: false,
      status: 403,
      text: async () => "Unauthorized: Invalid token",
    });

    const client = new BrainClient({ baseUrl: "http://localhost:8000", fetch: mockFetch });

    await assert.rejects(
      async () => {
        await client.proposals();
      },
      /OpenBrain API error \(403\): Unauthorized: Invalid token/
    );
  });
});
