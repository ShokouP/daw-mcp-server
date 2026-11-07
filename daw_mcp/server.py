"""daw-mcp-server: MCP server exposing DAW automation / verification tools.

Run (stdio, for MCP clients):
    python -m daw_mcp.server --config config.json

Run (HTTP JSON-RPC, for training loops / debugging):
    python -m daw_mcp.server --http 8765 --config config.json
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .tools import TOOLS, Context, dispatch

SERVER_INFO = {"name": "daw-mcp-server", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"


def _rpc_response(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def handle_message(ctx: Context, msg: dict) -> dict | None:
    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        return _rpc_response(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _rpc_response(rid, {})
    if method == "tools/list":
        return _rpc_response(rid, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        return _rpc_response(rid, dispatch(ctx, name, args))
    if method in ("shutdown", "exit"):
        return _rpc_response(rid, {})
    return _rpc_response(rid, error={"code": -32601, "message": f"method not found: {method}"})


def run_stdio(ctx: Context) -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps(_rpc_response(None, error={"code": -32700, "message": "parse error"})),
                  flush=True)
            continue
        try:
            resp = handle_message(ctx, msg)
        except Exception:  # noqa: BLE001
            resp = _rpc_response(msg.get("id"),
                                 error={"code": -32603, "message": traceback.format_exc(limit=2)})
        if resp is not None:
            print(json.dumps(resp, ensure_ascii=False), flush=True)
    return 0


class Handler(BaseHTTPRequestHandler):
    ctx: Context = None  # set by factory

    def log_message(self, fmt, *args):  # quiet
        pass

    def do_GET(self):
        if self.path in ("/health", "/"):
            body = json.dumps({"ok": True, "server": SERVER_INFO}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            msgs = json.loads(raw)
        except json.JSONDecodeError:
            self.send_error(400)
            return
        batch = isinstance(msgs, list)
        results = []
        for msg in (msgs if batch else [msgs]):
            resp = handle_message(self.ctx, msg)
            if resp is not None:
                results.append(resp)
        body = json.dumps(results if batch else (results[0] if results else None),
                          ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_http(ctx: Context, port: int) -> int:
    handler = type("BoundHandler", (Handler,), {"ctx": ctx})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"daw-mcp-server HTTP JSON-RPC on http://127.0.0.1:{port} (POST /)", file=sys.stderr)
    httpd.serve_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DAW MCP server")
    ap.add_argument("--config", help="JSON config (render_cmd, bridge_queue, telemetry_path)")
    ap.add_argument("--http", type=int, help="run HTTP JSON-RPC on this port instead of stdio")
    args = ap.parse_args(argv)
    config = {}
    if args.config:
        config = json.loads(open(args.config, encoding="utf-8").read())
    ctx = Context(config)
    if args.http:
        return run_http(ctx, args.http)
    return run_stdio(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
