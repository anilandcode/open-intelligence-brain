# Open Intelligence Brain Python SDK & CLI

The official Python SDK and developer CLI for [Open Intelligence Brain](https://github.com/anilandcode/open-intelligence-brain).

## Installation

```bash
pip install openbrain
```

---

## 1. Developer CLI (`openbrain`)

When installed, the `openbrain` command-line interface provides instant terminal access to search, ask, ingest, and govern agent memories:

```bash
# Check connectivity, latency, and workspace auto-approval policy
openbrain status

# Search canonical facts with bi-temporal time-travel
openbrain search "PostgreSQL"
openbrain search "database standard" --as-of 2025-01-01

# Ask grounded questions with citations
openbrain ask "What is our database standard?"

# Ingest raw text or documents into the review queue
openbrain ingest "Architecture Note: All agent updates require bi-temporal timestamps." --title "Memory Policy"
openbrain ingest path/to/spec.md --kind decision

# Interactive terminal governance (human-in-the-loop review)
openbrain review
openbrain review --approve prop_12345
openbrain review --reject prop_12345 --reason "Obsolete specification"

# Inspect or update auto-approval policy
openbrain policy get
openbrain policy set --auto-approve true --types note,fact,evidence

# Export or restore AES-256 encrypted backups
openbrain export -o backup.oib -p secretpassphrase

# Inspect knowledge graph nodes and evolutionary lineage
openbrain graph --include-superseded
```

### Environment Configuration

The CLI automatically reads standard environment variables:

- `OPENBRAIN_URL`: Server endpoint (default: `http://localhost:8000`)
- `OPENBRAIN_TOKEN`: API access token (default: `local-dev-token`)
- `OPENBRAIN_WORKSPACE`: Workspace slug or ID (default: `default`)

---

## 2. Python SDK

```python
from openbrain import Brain

with Brain(base_url="http://localhost:8000", api_key="your-token") as brain:
    # 1. Ingest content with exact source span tracking
    source = brain.add(
        "All customer data must be encrypted with AES-256 at rest.",
        title="Security Policy",
        kind="decision",
    )

    # 2. Search with bi-temporal filters
    memories = brain.search("encryption policy", as_of="2025-06-01")
    for mem in memories:
        print(mem["statement"], mem["valid_from"], mem["superseded_by"])

    # 3. Grounded Q&A with citation provenance
    result = brain.ask("How is customer data encrypted?")
    print(f"Grounded: {result['grounded']}")
    print(f"Answer: {result['answer']}")
    for cit in result["citations"]:
        print(f"  • {cit['statement']}")

    # 4. Review proposals
    pending = brain.proposals(status="proposed")
    for p in pending:
        if not p.get("conflict_with_id"):
            brain.approve(p["id"])
```
