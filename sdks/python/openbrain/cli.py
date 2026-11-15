"""Open Intelligence Brain CLI.

Developer command-line interface for Open Intelligence Brain:
Search, ask, ingest, review, and govern agent memory directly from the terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .client import Brain, BrainError

# ANSI styling
USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def color(text: str, code: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return color(text, "1")


def dim(text: str) -> str:
    return color(text, "2")


def green(text: str) -> str:
    return color(text, "32")


def yellow(text: str) -> str:
    return color(text, "33")


def red(text: str) -> str:
    return color(text, "31")


def cyan(text: str) -> str:
    return color(text, "36")


def magenta(text: str) -> str:
    return color(text, "35")


def get_client(args: argparse.Namespace) -> Brain:
    base_url = args.url or os.environ.get("OPENBRAIN_URL", "http://localhost:8000")
    api_key = args.token or os.environ.get("OPENBRAIN_TOKEN", "local-dev-token")
    workspace = args.workspace or os.environ.get("OPENBRAIN_WORKSPACE")
    return Brain(base_url=base_url, api_key=api_key, workspace_id=workspace)


def cmd_status(args: argparse.Namespace) -> int:
    client = get_client(args)
    start = time.perf_counter()
    try:
        health = client.health()
        latency_ms = (time.perf_counter() - start) * 1000
    except (BrainError, OSError) as exc:
        if args.json:
            print(json.dumps({"status": "unreachable", "error": str(exc)}))
        else:
            print(f"{bold('Open Intelligence Brain')}: {red('OFFLINE')}")
            print(f"Target URL: {client.base_url}")
            print(f"Error: {exc}")
        return 1

    policy = None
    try:
        policy = client.get_policy()
    except BrainError:
        policy = None

    if args.json:
        print(
            json.dumps(
                {
                    "status": "online",
                    "health": health,
                    "url": client.base_url,
                    "latency_ms": round(latency_ms, 2),
                    "workspace": client.workspace_id,
                    "policy": policy,
                },
                indent=2,
            )
        )
        return 0

    print(
        f"{bold('Open Intelligence Brain')} v2.4.0: {green('● ONLINE')} {dim(f'({latency_ms:.1f}ms)')}"
    )
    print(f"  {dim('URL:')}       {client.base_url}")
    print(f"  {dim('Workspace:')} {client.workspace_id}")
    if policy:
        auto_status = (
            green("Enabled")
            if policy.get("auto_approve_enabled")
            else yellow("Disabled (Human review)")
        )
        print(f"  {dim('Auto-Gov:')}  {auto_status}")
        if policy.get("auto_approve_enabled"):
            print(f"  {dim('Allowed:')}   {policy.get('auto_approve_types')}")
            print(f"  {dim('Max Sens:')}  {policy.get('auto_approve_max_sensitivity')}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        results = client.search(
            query=args.query,
            limit=args.limit,
            as_of=args.as_of,
            include_superseded=args.include_superseded,
        )
    except BrainError as exc:
        print(f"{red('Search failed')}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    if not results:
        print(f"{yellow('No knowledge atoms matched query:')} {args.query!r}")
        return 0

    query_label = f" for {bold(repr(args.query))}" if args.query else ""
    as_of_label = f" {dim(f'[as of {args.as_of}]')}" if args.as_of else ""
    print(
        f"{bold('Found')} {green(str(len(results)))} {bold('canonical facts')}{query_label}{as_of_label}:"
    )
    print()

    for item in results:
        kid = item.get("id", "")
        statement = item.get("statement", "")
        ktype = item.get("type", "fact")
        excerpt = item.get("source_excerpt", "")
        superseded_by = item.get("superseded_by")
        valid_from = item.get("valid_from")

        status_tag = red("[SUPERSEDED]") if superseded_by else green("[ACTIVE]")
        type_badge = cyan(f"[{ktype.upper()}]")

        print(f"  {bold(kid)} {type_badge} {status_tag}")
        print(f"    {bold(statement)}")
        if excerpt and excerpt != statement:
            print(f"    {dim('Source:')} {dim(excerpt[:120])}")
        if valid_from:
            print(f"    {dim('Valid From:')} {valid_from}")
        if superseded_by:
            print(f"    {yellow('Superseded By:')} {superseded_by}")
        print()
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        res = client.ask(args.question)
    except BrainError as exc:
        print(f"{red('Ask failed')}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    answer = res.get("answer", "")
    grounded = res.get("grounded", False)
    citations = res.get("citations", [])

    status_tag = green("● GROUNDED") if grounded else yellow("⚠ UNGROUNDED / ABSTAINED")
    print(f"{bold('Status:')} {status_tag}")
    print()
    print(f"{bold('Answer:')}")
    print(answer)
    print()

    if citations:
        print(f"{bold('Citations')} ({len(citations)}):")
        for cit in citations:
            kid = cit.get("id", "")
            stmt = cit.get("statement", "")
            print(f"  • {cyan(kid)}: {stmt}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    client = get_client(args)
    target = args.target

    # Determine if target is a file or literal text
    path = Path(target)
    if path.is_file():
        content = path.read_text(encoding="utf-8")
        title = args.title or path.name
    else:
        content = target
        title = args.title or (content.strip().split("\n")[0][:60] or "Captured Note")

    try:
        res = client.add(
            content=content,
            title=title,
            kind=args.kind,
            sensitivity=args.sensitivity,
        )
    except BrainError as exc:
        print(f"{red('Ingestion failed')}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    source_id = res.get("id", "")
    title = res.get("title", "")
    chash = res.get("content_hash", "")
    proposals_count = res.get("proposals_count", 0)

    try:
        all_proposals = client.proposals(status="proposed")
        proposals = [p for p in all_proposals if p.get("source_id") == source_id]
    except BrainError:
        proposals = []

    print(f"{green('✔ Ingested source:')} {bold(source_id)} — {title}")
    if chash:
        print(f"  {dim('Hash:')}        {chash[:16]}...")
    print(
        f"  {dim('Proposals:')}   {len(proposals) or proposals_count} extracted candidates"
    )
    print()

    auto_approved_count = 0
    for p in proposals:
        pid = p.get("id", "")
        stmt = p.get("statement", "")
        ptype = p.get("type", "fact")
        pstatus = p.get("status", "proposed")
        conflict_id = p.get("conflict_with_id")
        conflict_note = p.get("conflict_note")

        if pstatus == "approved":
            auto_approved_count += 1
            print(
                f"  {green('✔ [AUTO-APPROVED]')} {cyan(f'[{ptype.upper()}]')} {bold(stmt)}"
            )
        elif conflict_id:
            print(
                f"  {yellow('⚠ [CONFLICT RADAR]')} {cyan(f'[{ptype.upper()}]')} {bold(stmt)}"
            )
            print(f"    {red('Conflict with:')} {conflict_id}")
            print(f"    {dim('Radar note:')}    {conflict_note}")
        else:
            print(
                f"  {magenta('? [PENDING REVIEW]')} {cyan(f'[{ptype.upper()}]')} {bold(stmt)}"
            )
            print(f"    {dim('Proposal ID:')}  {pid}")

    if auto_approved_count > 0:
        print()
        print(
            f"{green(f'Deterministic policy auto-approved {auto_approved_count} proposal(s).')}"
        )
    elif proposals:
        print()
        print(f"{dim('Review pending items with:')} {bold('openbrain review')}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    client = get_client(args)

    # Single approve / reject commands
    if args.approve:
        try:
            res = client.approve(args.approve)
            print(
                f"{green('✔ Approved proposal')} {bold(args.approve)} -> {cyan(res.get('id', ''))}"
            )
            return 0
        except BrainError as exc:
            print(f"{red('Failed to approve')}: {exc}", file=sys.stderr)
            return 1

    if args.reject:
        try:
            res = client.reject(args.reject, reason=args.reason or "Rejected via CLI")
            print(f"{yellow('✖ Rejected proposal')} {bold(args.reject)}")
            return 0
        except BrainError as exc:
            print(f"{red('Failed to reject')}: {exc}", file=sys.stderr)
            return 1

    try:
        pending = client.proposals(status=args.status)
    except BrainError as exc:
        print(f"{red('Failed to list proposals')}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(pending, indent=2))
        return 0

    if not pending:
        print(f"{green('✔ Inbox zero!')} No proposals awaiting review.")
        return 0

    if args.batch_approve:
        pids = [p["id"] for p in pending]
        print(f"Batch approving {len(pids)} proposals...")
        client.batch_approve(pids)
        print(f"{green(f'✔ Approved {len(pids)} proposals.')}")
        return 0

    if not args.interactive and not sys.stdin.isatty():
        # Non-interactive list
        print(f"{bold('Pending Proposals')} ({len(pending)}):")
        print()
        for p in pending:
            conflict_tag = red(" [CONFLICT]") if p.get("conflict_with_id") else ""
            ptype = p.get("type", "").upper()
            print(f"  {bold(p['id'])} {cyan(f'[{ptype}]')}{conflict_tag}")
            print(f"    {bold(p.get('statement', ''))}")
            if p.get("conflict_note"):
                print(f"    {yellow('Radar:')} {p['conflict_note']}")
            print()
        return 0

    # Interactive review loop
    print(f"{bold('Open Intelligence Brain')} — Interactive Proposal Review")
    print(
        f"Reviewing {len(pending)} candidate facts. Actions: [a]pprove, [r]eject, [s]kip, [q]uit"
    )
    print("=" * 70)
    print()

    for idx, p in enumerate(pending, 1):
        pid = p["id"]
        stmt = p.get("statement", "")
        ptype = p.get("type", "fact")
        rationale = p.get("rationale", "")
        conflict_id = p.get("conflict_with_id")
        conflict_note = p.get("conflict_note")
        critic_notes = p.get("critic_notes", "")

        print(
            f"{dim(f'[{idx}/{len(pending)}]')} {bold(pid)} {cyan(f'[{ptype.upper()}]')}"
        )
        print(f"  {bold('Statement:')} {stmt}")
        if rationale:
            print(f"  {dim('Rationale:')} {rationale}")
        if conflict_id:
            print(f"  {yellow('⚠ CONFLICT RADAR:')} Contradicts {bold(conflict_id)}")
            print(f"    {yellow(conflict_note)}")
        if critic_notes and critic_notes != "[]":
            print(f"  {magenta('Critic notes:')} {critic_notes}")

        while True:
            try:
                choice = input(f"{bold('Action [a/r/s/q]? ')}").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nReview session ended.")
                return 0

            if choice in ("a", "approve"):
                try:
                    res = client.approve(pid)
                    print(f"  {green('✔ Approved')} -> {cyan(res.get('id', ''))}\n")
                except BrainError as exc:
                    print(f"  {red('Error approving:')} {exc}\n")
                break
            elif choice in ("r", "reject"):
                try:
                    client.reject(pid, reason="Rejected via CLI interactive review")
                    print(f"  {yellow('✖ Rejected')}\n")
                except BrainError as exc:
                    print(f"  {red('Error rejecting:')} {exc}\n")
                break
            elif choice in ("s", "skip"):
                print(f"  {dim('Skipped')}\n")
                break
            elif choice in ("q", "quit", "exit"):
                print("Review session stopped.")
                return 0
            else:
                print("  Invalid choice. Enter 'a', 'r', 's', or 'q'.")

    print(f"{green('All proposals in batch processed!')}")
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    client = get_client(args)
    if args.action == "get":
        policy = client.get_policy()
        if args.json:
            print(json.dumps(policy, indent=2))
        else:
            print(f"{bold('Workspace Policy')} ({client.workspace_id}):")
            for k, v in policy.items():
                print(f"  {dim(f'{k}:'):<32} {v}")
        return 0

    if args.action == "set":
        updates: dict[str, Any] = {}
        if args.auto_approve is not None:
            updates["auto_approve_enabled"] = args.auto_approve.lower() in (
                "true",
                "1",
                "yes",
            )
        if args.types is not None:
            updates["auto_approve_types"] = args.types
        if args.max_sensitivity is not None:
            updates["auto_approve_max_sensitivity"] = args.max_sensitivity
        if args.clean_critic is not None:
            updates["require_clean_critic"] = args.clean_critic.lower() in (
                "true",
                "1",
                "yes",
            )
        if args.zero_conflicts is not None:
            updates["require_zero_conflicts"] = args.zero_conflicts.lower() in (
                "true",
                "1",
                "yes",
            )

        if not updates:
            print(f"{yellow('No policy updates specified.')}")
            return 1

        policy = client.update_policy(**updates)
        if args.json:
            print(json.dumps(policy, indent=2))
        else:
            print(f"{green('✔ Policy updated successfully:')}")
            for k, v in updates.items():
                print(f"  {dim(f'{k}:')} {v}")
        return 0
    return 1


def cmd_reindex(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        res = client.reindex()
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(
                f"{green('✔ Reindexing triggered:')} {res.get('message', 'Complete')}"
            )
            print(f"  {dim('Embedded count:')} {res.get('embedded_count', 0)}")
            print(f"  {dim('FTS synced:')}    {res.get('fts_synced', True)}")
        return 0
    except BrainError as exc:
        print(f"{red('Reindex failed')}: {exc}", file=sys.stderr)
        return 1


def cmd_export(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        res = client.export_backup(passphrase=args.passphrase)
    except BrainError as exc:
        print(f"{red('Export failed')}: {exc}", file=sys.stderr)
        return 1

    out_path = args.output
    if not out_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = "oib" if args.passphrase else "json"
        out_path = f"brain_backup_{ts}.{ext}"

    Path(out_path).write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"{green('✔ Workspace exported successfully:')} {bold(out_path)}")
    if args.passphrase:
        print(
            f"  {magenta('Encryption:')} AES-256 Fernet + PBKDF2 (Passphrase protected)"
        )
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        res = client.graph(include_superseded=args.include_superseded)
    except BrainError as exc:
        print(f"{red('Graph fetch failed')}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    nodes = res.get("nodes", res.get("documents", []))
    edges = res.get("edges", [])

    print(f"{bold('Knowledge Graph')} ({len(nodes)} nodes, {len(edges)} edges):")
    print()
    for n in nodes[:25]:
        nid = n.get("id", "")
        label = n.get("label", n.get("title", ""))
        ntype = n.get("type", "")
        superseded = n.get("superseded", False)
        status_tag = red("[SUPERSEDED]") if superseded else green("[APPROVED]")
        print(f"  • {bold(nid)} {cyan(f'[{ntype}]')} {status_tag} {label}")

    if edges:
        print()
        print(f"{bold('Relationships / Edges:')}")
        for e in edges[:25]:
            src = e.get("source", "")
            tgt = e.get("target", "")
            rel = e.get("relationType", e.get("type", "rel"))
            rel_color = magenta if rel == "updates" else cyan
            print(f"  {src} --{rel_color(f'[{rel}]')}--> {tgt}")
    return 0


def cmd_delete_source(args: argparse.Namespace) -> int:
    client = get_client(args)
    try:
        if args.preview:
            res = client.deletion_preview(args.source_id)
            if args.json:
                print(json.dumps(res, indent=2))
                return 0
            blocked = res.get("blocked", False)
            status_str = red("BLOCKED") if blocked else green("SAFE TO DELETE")
            print(
                f"{bold('Deletion Preview')} for {cyan(args.source_id)}: {status_str}"
            )
            print(f"  {dim('Canonical items:')}     {res.get('canonical_items', 0)}")
            print(
                f"  {dim('Knowledge revisions:')} {res.get('knowledge_revisions', 0)}"
            )
            print(f"  {dim('Proposals:')}           {res.get('proposals', 0)}")
            print(f"  {dim('Source versions:')}     {res.get('source_versions', 0)}")
            print(f"  {dim('Reason:')}              {res.get('reason', '')}")
            return 0

        res = client.delete_source(args.source_id)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"{green('✔ Deleted source:')} {bold(args.source_id)}")
            print(f"  {dim('Detail:')} {res.get('detail', '')}")
        return 0
    except BrainError as exc:
        print(f"{red('Source deletion failed')}: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--url", help="API base URL (default: OPENBRAIN_URL or http://localhost:8000)"
    )
    common.add_argument(
        "--token", help="Access token (default: OPENBRAIN_TOKEN or local-dev-token)"
    )
    common.add_argument(
        "--workspace", help="Workspace ID (default: OPENBRAIN_WORKSPACE)"
    )
    common.add_argument("--json", action="store_true", help="Output raw JSON")
    common.add_argument(
        "--no-color", action="store_true", help="Disable ANSI color output"
    )

    parser = argparse.ArgumentParser(
        prog="openbrain",
        description="Open Intelligence Brain CLI — Governed agent memory system.",
        parents=[common],
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = sub.add_parser(
        "status",
        aliases=["health"],
        parents=[common],
        help="Check server health and policy",
    )
    p_status.set_defaults(func=cmd_status)

    # search
    p_search = sub.add_parser(
        "search", parents=[common], help="Search canonical knowledge"
    )
    p_search.add_argument("query", nargs="?", default="", help="Query string")
    p_search.add_argument("--limit", type=int, default=10, help="Max results")
    p_search.add_argument(
        "--as-of", help="Historical ISO-8601 timestamp for time travel"
    )
    p_search.add_argument(
        "--include-superseded", action="store_true", help="Include superseded facts"
    )
    p_search.set_defaults(func=cmd_search)

    # ask
    p_ask = sub.add_parser(
        "ask",
        parents=[common],
        help="Ask a grounded question against canonical knowledge",
    )
    p_ask.add_argument("question", help="Question to ask")
    p_ask.set_defaults(func=cmd_ask)

    # ingest
    p_ingest = sub.add_parser(
        "ingest",
        aliases=["add"],
        parents=[common],
        help="Ingest a file or note into review queue",
    )
    p_ingest.add_argument("target", help="File path or raw text string")
    p_ingest.add_argument("--title", help="Optional title for the source")
    p_ingest.add_argument(
        "--kind", default="note", help="Source kind (note, decision, interview)"
    )
    p_ingest.add_argument(
        "--sensitivity",
        default="internal",
        help="Sensitivity ceiling (public, internal, restricted)",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    # review
    p_review = sub.add_parser(
        "review", parents=[common], help="Review and govern pending proposals"
    )
    p_review.add_argument("--status", default="proposed", help="Filter proposal status")
    p_review.add_argument("--approve", help="Approve proposal ID")
    p_review.add_argument("--reject", help="Reject proposal ID")
    p_review.add_argument("--reason", help="Reason for rejection")
    p_review.add_argument(
        "--batch-approve", action="store_true", help="Approve all pending proposals"
    )
    p_review.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Launch interactive review session",
    )
    p_review.set_defaults(func=cmd_review)

    # policy
    p_policy = sub.add_parser(
        "policy", parents=[common], help="Inspect or update auto-approval policy"
    )
    p_policy.add_argument("action", choices=["get", "set"], help="get or set")
    p_policy.add_argument("--auto-approve", help="true or false")
    p_policy.add_argument(
        "--types", help="Allowed types: comma-separated e.g. note,fact,evidence"
    )
    p_policy.add_argument(
        "--max-sensitivity", help="Sensitivity ceiling: public, internal, restricted"
    )
    p_policy.add_argument("--clean-critic", help="true or false")
    p_policy.add_argument("--zero-conflicts", help="true or false")
    p_policy.set_defaults(func=cmd_policy)

    # reindex
    p_reindex = sub.add_parser(
        "reindex", parents=[common], help="Reindex vector embeddings and FTS"
    )
    p_reindex.set_defaults(func=cmd_reindex)

    # export
    p_export = sub.add_parser(
        "export", parents=[common], help="Export workspace backup"
    )
    p_export.add_argument("-o", "--output", help="Output file path")
    p_export.add_argument("-p", "--passphrase", help="AES-256 encryption passphrase")
    p_export.set_defaults(func=cmd_export)

    # graph
    p_graph = sub.add_parser(
        "graph",
        parents=[common],
        help="Inspect knowledge graph and supersession edges",
    )
    p_graph.add_argument(
        "--include-superseded",
        action="store_true",
        help="Include historical supersession nodes",
    )
    p_graph.set_defaults(func=cmd_graph)

    # delete-source
    p_del_src = sub.add_parser(
        "delete-source",
        parents=[common],
        help="Preview or execute reviewed source deletion",
    )
    p_del_src.add_argument("source_id", help="Source ID to preview or delete")
    p_del_src.add_argument(
        "--preview",
        action="store_true",
        help="Preview deletion dependencies without deleting",
    )
    p_del_src.set_defaults(func=cmd_delete_source)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.no_color:
        global USE_COLOR
        USE_COLOR = False
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
