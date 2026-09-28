"""An OpenAI-compatible proxy that exists to fix one provider edge.

The self-hosted engine calls its model provider through `python-httpx`, and the
provider's edge answers that User-Agent with **403 and a Cloudflare block page**,
not JSON. The engine's own log then only says `memory agent completed (5908ms, 0
memories)`, so the failure reads as "the model returned nothing" rather than
"the request never reached a model" — a hosted engine that accepts every
document and extracts nothing from any of them, which is the silent-empty-store
failure this project exists to prevent.

A plain client User-Agent on the same request returns 200. So the engine points
`OPENAI_BASE_URL` here, and this forwards each request upstream with an ordinary
UA. It also gives the engine's opaque one-line logs something to be checked
against: every request and response is summarised to stdout, which is where a
container's logs are read.

The engine is given a dummy `OPENAI_API_KEY` and this holds the real one, so the
real credential is never visible to the engine process itself.

Configuration (all env, no files, no defaults that could dial somewhere
unintended):
  PROXY_UPSTREAM     required, e.g. https://api.commandcode.ai/provider/v1
  PROXY_API_KEY      required, sent as the upstream bearer token, never logged
  PROXY_LISTEN_PORT  default 6799
  PROXY_LISTEN_HOST  default 127.0.0.1 — sidecar only, never exposed
  PROXY_UA           default curl/8.7.1
  PROXY_LOG_BODIES   default 0; 1 also writes failing response bodies to disk
  PROXY_VERBOSE      default 1
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM = os.environ.get("PROXY_UPSTREAM", "").rstrip("/")
KEY = os.environ.get("PROXY_API_KEY", "")
LISTEN_HOST = os.environ.get("PROXY_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("PROXY_LISTEN_PORT", "6799"))
UA = os.environ.get("PROXY_UA", "curl/8.7.1")
VERBOSE = os.environ.get("PROXY_VERBOSE", "1") not in ("0", "", "false")
LOG_BODIES = os.environ.get("PROXY_LOG_BODIES", "0") not in ("0", "", "false")
BODY_DIR = Path(os.environ.get("PROXY_BODY_DIR", "/tmp"))

if not UPSTREAM:
    sys.exit("PROXY_UPSTREAM is required, e.g. https://api.commandcode.ai/provider/v1")
if not KEY:
    sys.exit("PROXY_API_KEY is required (the upstream bearer token)")


def log(text: str) -> None:
    """One line per event, flushed: a container's stdout is the log."""
    print(time.strftime("[%H:%M:%S] ") + text, flush=True)


def summarise_chat(raw: bytes) -> str:
    """One line saying whether the model produced usable content.

    This is the whole point of the proxy: the engine reports only that a memory
    agent completed, so "the model returned an empty completion" and "the model
    returned 200 with content" look identical from the engine's side.
    """
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return f"unparseable body ({len(raw)} bytes): {raw[:200]!r}"
    out = []
    for choice in body.get("choices") or []:
        message = choice.get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning") or ""
        details = message.get("reasoning_details") or []
        out.append(
            f"finish={choice.get('finish_reason')} content={len(content)}c "
            f"reasoning={len(reasoning)}c details={len(details)} "
            f"content_head={content[:120]!r}"
        )
    if body.get("error"):
        out.append(f"ERROR={json.dumps(body['error'])[:300]}")
    usage = body.get("usage") or {}
    if usage:
        out.append(f"usage={json.dumps(usage)[:160]}")
    return " | ".join(out) or f"no choices: {json.dumps(body)[:200]}"


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seq = 0

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — stdlib's name
        """Silence the default per-request stderr noise; we log our own lines."""

    def _health(self) -> None:
        body = json.dumps(
            {"ok": True, "upstream": UPSTREAM, "ua": UA, "port": LISTEN_PORT}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self) -> None:
        Handler.seq += 1
        n = Handler.seq
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length) if length else b""
        route = self.path

        if VERBOSE:
            log(f"#{n} -> {self.command} {route} ({length}b)")
        if VERBOSE and payload and "chat/completions" in route:
            try:
                sent = json.loads(payload)
                messages = sent.get("messages") or []
                log(
                    f"#{n} model={sent.get('model')} stream={sent.get('stream')} "
                    f"max_tokens={sent.get('max_tokens')} n_messages={len(messages)}"
                )
            except ValueError:
                log(f"#{n} body not json")

        headers = {
            "Authorization": f"Bearer {KEY}",
            "Content-Type": self.headers.get("Content-Type", "application/json"),
            "Accept": self.headers.get("Accept", "*/*"),
            # The entire reason this process exists.
            "User-Agent": UA,
        }
        upstream = urllib.request.Request(
            f"{UPSTREAM}{route}", data=payload or None, headers=headers, method=self.command
        )
        try:
            with urllib.request.urlopen(upstream, timeout=180) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = exc.code
        except Exception as exc:  # noqa: BLE001 — any transport failure is a 502 here
            body = json.dumps(
                {"error": {"type": type(exc).__name__, "msg": str(exc)}}
            ).encode()
            status = 502

        if VERBOSE:
            detail = summarise_chat(body) if "chat/completions" in route else repr(body[:160])
            log(f"#{n} <- {status} {detail}")
        if status >= 400 and LOG_BODIES:
            (BODY_DIR / "llmproxy_body.txt").write_bytes(body)

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.startswith("/__proxy/health"):
            return self._health()
        self._proxy()

    do_GET = do_POST
    do_PUT = do_POST
    do_DELETE = do_POST


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    log(f"proxy up on {LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM} (UA: {UA})")
    Server((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()
