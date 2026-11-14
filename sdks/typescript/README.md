# @openbrain/sdk

The official TypeScript/JavaScript client for [Open Intelligence Brain](https://github.com/anilandcode/open-intelligence-brain).

## Features

- **Bi-Temporal Memory**: Query what your agent knew at any point in history (`as_of`).
- **Verbatim Span Provenance**: Strict citation links to exact source characters.
- **Fast Review & Batch Governance**: Approve or reject memory proposals individually or in batches.
- **Full Type Definitions**: Strict TypeScript types for sources, proposals, knowledge, and citations.
- **Zero Heavy Dependencies**: Built on standard `fetch`.

## Installation

```bash
npm install @openbrain/sdk
```

## Quickstart

```typescript
import { BrainClient } from "@openbrain/sdk";

const brain = new BrainClient({
  baseUrl: "http://localhost:8000",
  apiKey: "your-token",
});

// 1. Ingest raw content into immutable source history
const source = await brain.add({
  content: "PostgreSQL 16 is our designated production database standard.",
  title: "Engineering Architecture Decision Record 004",
  kind: "decision",
});

// 2. Search canonical knowledge (with optional time-travel)
const memories = await brain.search({
  query: "database standard",
  // as_of: new Date("2024-01-01T00:00:00Z"), // time-travel
});

// 3. Grounded question answering with citations
const { answer, citations, grounded } = await brain.ask("What database do we use?");
console.log(answer);
citations.forEach((c) => {
  console.log(`- [${c.source_title}] "${c.excerpt}"`);
});

// 4. Batch approve pending proposals
const pending = await brain.proposals("proposed");
if (pending.length > 0) {
  const result = await brain.batchApprove(pending.map((p) => p.id));
  console.log(`Approved ${result.approved} proposals.`);
}
```

## License

Apache-2.0
