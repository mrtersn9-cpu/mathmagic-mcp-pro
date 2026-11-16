"""v0.2 strict no-foreground MCP entrypoint (legacy writing tools removed)."""
from server import TOOLS as LEGACY_TOOLS, engine
from mathmagic_mcp.background import BackgroundService, filter_safe_legacy_tools
from mathmagic_mcp.protocol import MCPServer, schema, s, b

background = BackgroundService(engine)
TOOLS = filter_safe_legacy_tools(LEGACY_TOOLS)
TOOLS.update({
    "mathmagic_background_policy": (
        {"description": "Read strict background policy; no GUI interaction.",
         "inputSchema": schema({})}, background.policy),
    "mathmagic_background_probe": (
        {"description": "Read-only MathMagic Windows UIA capability inspection; never focuses, clicks or types; not proof of working MathMagic automation.",
         "inputSchema": schema({})}, background.probe),
    "mathmagic_background_plan": (
        {"description": "Validate and plan an equation without sending input or changing InDesign.",
         "inputSchema": schema({
             "latex": s("LaTeX expression"),
             "mode": s("create or edit", enum=["create", "edit"]),
             "marker": s("Optional [[MM:ID]] for create")}, ["latex"])},
        background.plan),
    "mathmagic_prepare_offline_batch": (
        {"description": "Validate up to 100 equations and stage .tex inputs WITHOUT MathMagic conversion or InDesign changes. confirm=true only authorizes local staging files.",
         "inputSchema": schema({
             "manifest_path": s("Absolute JSON input manifest path"),
             "output_dir": s("Empty output directory for .tex files"),
             "confirm": b("Approve creation of staging files only")},
             ["manifest_path", "output_dir"])},
        background.prepare_batch),
})

if __name__ == "__main__":
    MCPServer(TOOLS, version="0.2.0-experimental").run()
