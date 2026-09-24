# Agent working agreement

Read `docs/architecture.md` before changing persistence, approval, citations, or authentication.

- Keep raw sources, proposals, and canonical knowledge distinct.
- Only the approval endpoint can create canonical knowledge.
- Never trust a workspace, owner, status, or permission supplied by model output.
- Never commit secrets, private user data, database files, model caches, or generated exports.
- Preserve citation links from knowledge back to the exact source excerpt.
- Never overwrite source content; create a `source_versions` record with a new hash.
- Never overwrite canonical wording without adding a `knowledge_revisions` record.
- Restore only into an empty workspace after a successful preview.
- Keep hosted AI, Jev, Hermes, Codex, and Claude integrations optional.
- Run backend and frontend tests before committing.
- Do not publish, deploy, merge, or perform external actions unless explicitly requested.
