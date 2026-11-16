"""MCP stdio entrypoint. Run: python -u server.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mathmagic_mcp.protocol import MCPServer, schema, s, b
from mathmagic_mcp.engine import MathMagicEngine
from mathmagic_mcp import __version__

engine=MathMagicEngine()

TOOLS={
  'mathmagic_preflight': (
    {'description':'Read-only check of Windows, MathMagic executable, InDesign plugin folder and Python adapters.',
     'inputSchema':schema({})},engine.preflight),
  'mathmagic_inspect_indesign':(
    {'description':'Read-only InDesign COM probe: active document, selected object and actual MathMagic menu action names.',
     'inputSchema':schema({})},engine.inspect),
  'mathmagic_preview_equation':(
    {'description':'Validate a TeX expression and show how MathMagic would be used. Never edits the document.',
     'inputSchema':schema({'latex':s('TeX / LaTeX expression'),
       'mode':s('create or edit',enum=['create','edit']),
       'marker':s('Optional unique [[MM:ID]] marker for create operations')},['latex'])},engine.preview),
  'mathmagic_create_equation':(
    {'description':'Create a native MathMagic equation via its real InDesign plugin and focused keyboard adapter. Requires confirm=true; manual QA is mandatory.',
     'inputSchema':schema({'latex':s('LaTeX expression'),
       'marker':s('Optional unique text marker [[MM:ID]] instead of current InDesign text caret'),
       'confirm':b('Must be true to allow document mutation'),
       'window_timeout':{'type':'integer','minimum':5,'maximum':90}},['latex'])},
     lambda latex,marker='',confirm=False,window_timeout=25:engine.run_equation(latex,'create',marker,confirm,window_timeout)),
  'mathmagic_edit_equation':(
    {'description':'Edit selected native MathMagic equation through its InDesign Edit Equation plugin command. Requires confirm=true; GUI replacement must be manually validated.',
     'inputSchema':schema({'latex':s('Replacement LaTeX'),
       'confirm':b('Must be true to allow document mutation'),
       'window_timeout':{'type':'integer','minimum':5,'maximum':90}},['latex'])},
     lambda latex,confirm=False,window_timeout=25:engine.run_equation(latex,'edit','',confirm,window_timeout)),
  'mathmagic_backup_indd':(
    {'description':'Copy the last saved .indd file to a dedicated backup folder. Does not save or modify original file; unsaved changes excluded.',
     'inputSchema':schema({'folder':s('Absolute backup directory'), 'confirm':b('Must be true to copy file')},['folder'])},engine.backup_document),
  'mathmagic_check_marker':(
    {'description':'Read-only diagnostic of an [[MM:ID]] placeholder position, not a full equation integrity check.',
     'inputSchema':schema({'marker':s('Marker to inspect')},['marker'])},engine.check_marker),
  'mathmagic_preview_batch':(
    {'description':'Validate a JSON manifest containing up to 100 marked equations; no changes.',
     'inputSchema':schema({'manifest_path':s('Absolute path to JSON manifest')},['manifest_path'])},engine.batch_preview),
  'mathmagic_cleanup_marker':(
    {'description':'Remove exactly one placeholder marker after user has visually verified equation. Requires confirm=true and human_verified=true.',
     'inputSchema':schema({'marker':s('Unique placeholder [[MM:ID]]'),
       'confirm':b('Explicitly approve deletion'), 'human_verified':b('User confirms equation manually reviewed')},['marker'])},engine.cleanup_marker),
  'mathmagic_run_batch_first':(
    {'description':'Attempt only the FIRST equation in a JSON manifest then stop for human review. No unattended batch mode is claimed.',
     'inputSchema':schema({'manifest_path':s('Absolute path to JSON manifest'),
       'confirm':b('Must be true to mutate'), 'stop_on_unverified':b('Must be true, for safety'),
       'start_index':{'type':'integer','minimum':0}},['manifest_path'])},engine.run_batch),
}

if __name__=='__main__':
    MCPServer(TOOLS,version=__version__).run()