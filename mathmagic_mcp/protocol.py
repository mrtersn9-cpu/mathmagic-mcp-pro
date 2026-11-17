"""Small dependency-free MCP stdio JSON-RPC 2.0 implementation.

Transport: one UTF-8 JSON-RPC message per line. Stdout is reserved for MCP.
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable


class ProtocolError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


def schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


def s(description: str, **extra: Any) -> dict:
    return {"type": "string", "description": description, **extra}


def b(description: str) -> dict:
    return {"type": "boolean", "description": description}


class MCPServer:
    def __init__(self, tools: dict[str, tuple[dict, Callable]], version="0.1.0", instructions: str = ""):
        self.tools = tools
        self.version = version
        self.instructions = instructions

    @staticmethod
    def _send(message: dict) -> None:
        sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def handle(self, request: dict) -> dict | None:
        if not isinstance(request, dict):
            raise ProtocolError(-32600, "Invalid JSON-RPC request")
        method = request.get("method")
        ident = request.get("id")
        # JSON-RPC notifications must not receive a response.
        if ident is None:
            return None
        params = request.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion", "2025-03-26")
            # We support the core messages used by current Claude Desktop MCP clients.
            supported = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"}
            version = requested if requested in supported else "2025-06-18"
            result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "mathmagic-mcp-pro", "version": self.version}}
            if self.instructions:
                result["instructions"] = self.instructions   # MCP InitializeResult.instructions (client system prompt)
            return {"jsonrpc": "2.0", "id": ident, "result": result}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": ident, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": ident, "result": {"tools": [
                {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
                for name, (spec, _) in self.tools.items()
            ]}}
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name not in self.tools:
                raise ProtocolError(-32602, f"Unknown tool: {name}")
            if not isinstance(args, dict):
                raise ProtocolError(-32602, "Tool arguments must be an object")
            spec, fn = self.tools[name]
            allowed = set(spec["inputSchema"].get("properties", {}))
            required = set(spec["inputSchema"].get("required", []))
            if not required.issubset(args):
                raise ProtocolError(-32602, f"Missing arguments: {sorted(required - set(args))}")
            if set(args) - allowed:
                raise ProtocolError(-32602, f"Unexpected arguments: {sorted(set(args)-allowed)}")
            try:
                result = fn(**args)
                return {"jsonrpc": "2.0", "id": ident, "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
                    "isError": bool(result.get("ok") is False),
                }}
            except Exception as exc:
                print(f"[{name}] {type(exc).__name__}: {exc}", file=sys.stderr)
                return {"jsonrpc": "2.0", "id": ident, "result": {
                    "content": [{"type": "text", "text": json.dumps({"ok": False, "error": str(exc), "type": type(exc).__name__}, ensure_ascii=False)}],
                    "isError": True,
                }}
        raise ProtocolError(-32601, f"Method not found: {method}")

    def run(self) -> None:
        for raw in sys.stdin.buffer:
            if not raw.strip():
                continue
            ident = None
            try:
                req = json.loads(raw)
                if isinstance(req, dict):
                    ident = req.get("id")
                response = self.handle(req)
                if response is not None:
                    self._send(response)
            except ProtocolError as exc:
                self._send({"jsonrpc": "2.0", "id": ident, "error": {"code": exc.code, "message": str(exc)}})
            except (ValueError, UnicodeDecodeError) as exc:
                self._send({"jsonrpc": "2.0", "id": ident, "error": {"code": -32700, "message": str(exc)}})
            except Exception:
                print(traceback.format_exc(), file=sys.stderr)
                self._send({"jsonrpc": "2.0", "id": ident, "error": {"code": -32603, "message": "Internal error"}})
