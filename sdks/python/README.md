# Open Intelligence Brain Python SDK

The official Python SDK for [Open Intelligence Brain](https://github.com/anilandcode/open-intelligence-brain).

## Installation

```bash
pip install openbrain
```

## Quickstart

```python
from openbrain import Brain

brain = Brain(base_url="http://localhost:8000", api_key="your-token")

# Ingest content with exact source span tracking
source = brain.add(
    "All customer data must be encrypted with AES-256 at rest.",
    title="Security Policy",
    kind="decision",
)

# Search with bi-temporal filters
memories = brain.search("encryption policy")
for mem in memories:
    print(mem["statement"], mem["valid_from"])

# Ask questions with citation provenance
answer = brain.ask("How is customer data encrypted?")
print(answer["answer"])
for citation in answer["citations"]:
    print(f"Evidence from {citation['source_title']}: {citation['excerpt']}")
```
