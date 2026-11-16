"""Direct InDesign Windows COM + ExtendScript bridge.

Requires pywin32, InDesign 2026, active user desktop. Never invokes arbitrary
code provided by MCP clients: all JSX is defined in this package.
"""
from __future__ import annotations

import json
import os
import queue
import threading
from typing import Any

JAVASCRIPT = 1246973031  # InDesign ScriptLanguage.JAVASCRIPT


class IndesignError(RuntimeError):
    pass


def _js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _wrap(body: str) -> str:
    # No JSON.parse dependency (ExtendScript ES3).
    return "(function(){\n" + body + "\n})();"


def jsx_status() -> str:
    return _wrap(r'''
        var d = app.documents.length ? app.activeDocument : null;
        var selectionKind = 'none';
        if(app.selection.length) {
            try { selectionKind = app.selection[0].constructor.name; }
            catch(e) { selectionKind='unknown'; }
        }
        var actions=[];
        for(var i=0; i<app.menuActions.length; i++) {
            try {
                var a=app.menuActions[i];
                if(/mathmagic|new equation|edit equation|apply styleset/i.test(a.name))
                    actions.push({id:a.id,name:a.name,enabled:a.enabled});
            } catch(e) {}
        }
        return 'JSON_OUTPUT:' + ({
            document: d ? d.name : null,
            modified: d ? d.modified : null,
            selectionKind: selectionKind,
            menuActions: actions
        }).toSource();
    ''')


def jsx_actions() -> str:
    return _wrap(r'''
        var entries=[];
        for(var i=0;i<app.menuActions.length;i++) {
          try {
            var a=app.menuActions[i];
            if(/mathmagic|new equation|edit equation|shift baseline|styleset/i.test(a.name))
              entries.push(a.id + '|' + a.name + '|' + a.enabled);
          } catch(e){}
        }
        return entries.join('\n');
    ''')


def jsx_document() -> str:
    return _wrap(r'''
        var d=app.documents.length ? app.activeDocument : null;
        if(!d) return 'NO_DOCUMENT';
        else {
          var s=app.selection.length ? app.selection[0] : null;
          var selectionType='none';
          try { selectionType = s ? s.constructor.name : 'none'; } catch(e) {}
          var documentPath='';
          try { documentPath=d.fullName.fsName; } catch(e) {}
          return [d.name, documentPath, String(d.modified), selectionType, String(app.selection.length)].join('|');
        }
    ''')


def jsx_invoke(action_name: str) -> str:
    return _wrap(r'''
        if (!app.documents.length) throw Error('No open document');
        var target = ''' + _js_string(action_name) + r''';
        var found=null;
        for (var i=0;i<app.menuActions.length;i++) {
          var a=app.menuActions[i];
          if(a.name===target) { found=a; break; }
        }
        if(!found) throw Error('Menu action not found: '+target);
        if(!found.enabled) throw Error('Menu action disabled: '+target);
        found.invoke();
        return 'ACTION_INVOKED:' + target;
    ''')


def jsx_select_marker(marker: str) -> str:
    return _wrap(r'''
        if (!app.documents.length) throw Error('No document');
        var marker = ''' + _js_string(marker) + r''';
        if(!marker || marker.length>128) throw Error('Marker length invalid');
        app.findTextPreferences = NothingEnum.nothing;
        app.changeTextPreferences = NothingEnum.nothing;
        try {
          app.findTextPreferences.findWhat=marker;
          var matches=app.activeDocument.findText();
          if(matches.length!==1) throw Error('Marker matches: '+matches.length);
          app.select(matches[0].insertionPoints[0]);
          return 'MARKER_SELECTED:' + marker;
        } finally {
          app.findTextPreferences = NothingEnum.nothing;
          app.changeTextPreferences = NothingEnum.nothing;
        }
    ''')


def jsx_check_marker(marker: str) -> str:
    return _wrap(r'''
        if (!app.documents.length) throw Error('No document');
        var marker = ''' + _js_string(marker) + r''';
        app.findTextPreferences=NothingEnum.nothing;
        try {
          app.findTextPreferences.findWhat=marker;
          var matches=app.activeDocument.findText();
          if(matches.length!==1) return 'MARKER_COUNT:' + matches.length;
          var match=matches[0];
          var ix=match.insertionPoints[0].index;
          var story=match.parentStory;
          var before='';
          try { if(ix>0) before=story.characters[ix-1].contents; }catch(e){}
          return 'MARKER_FOUND:' + String(before==='\uFFFC') + ':' + String(ix);
        } finally { app.findTextPreferences=NothingEnum.nothing; }
    ''')


def _parse_result(value: Any) -> str:
    return "" if value is None else str(value)


class InDesignBridge:
    def __init__(self, prog_id: str = "InDesign.Application", enabled: bool = True):
        self.prog_id = prog_id
        self.enabled = enabled

    def _connect_and_run(self, script: str, q: queue.Queue) -> None:
        try:
            import pythoncom  # type: ignore
            from win32com.client import Dispatch  # type: ignore
            pythoncom.CoInitialize()
            try:
                app=Dispatch(self.prog_id)
                value=app.DoScript(script, JAVASCRIPT)
                q.put((True, _parse_result(value)))
            finally:
                pythoncom.CoUninitialize()
        except Exception as exc:
            q.put((False, f"{type(exc).__name__}: {exc}"))

    def execute(self, script: str, timeout: float = 15.0) -> str:
        if not self.enabled:
            raise IndesignError('InDesign COM is disabled')
        if os.name != 'nt':
            raise IndesignError('InDesign COM requires Windows')
        q: queue.Queue = queue.Queue(maxsize=1)
        t = threading.Thread(target=self._connect_and_run, args=(script,q), daemon=True)
        t.start()
        try:
            ok, payload=q.get(timeout=timeout)
        except queue.Empty:
            raise IndesignError('InDesign COM timeout; a modal dialog or plugin may be blocking')
        if not ok:
            raise IndesignError(payload)
        return payload

    def run_async(self, script: str) -> tuple[threading.Thread, queue.Queue]:
        q: queue.Queue=queue.Queue(maxsize=1)
        t=threading.Thread(target=self._connect_and_run,args=(script,q),daemon=True)
        t.start()
        return t,q

    def actions(self) -> list[dict]:
        raw=self.execute(jsx_actions())
        ret=[]
        for line in raw.splitlines():
            parts=line.split('|',2)
            if len(parts)==3:
                ret.append({'id':parts[0],'name':parts[1], 'enabled':parts[2].lower()=='true'})
        return ret

    def document(self) -> dict:
        raw=self.execute(jsx_document())
        if raw == 'NO_DOCUMENT':
            return {'document':None}
        parts=raw.split('|',4)
        if len(parts)!=5:
            raise IndesignError('Unexpected InDesign document response: '+raw[:200])
        return dict(zip(['document','path','modified','selection_type','selection_count'],parts))


def jsx_remove_marker(marker: str) -> str:
    """Remove an exact unique marker only after caller verifies equation visually."""
    return _wrap(r'''
        if(!app.documents.length) throw Error('No open document');
        var marker = ''' + _js_string(marker) + r''';
        app.findTextPreferences=NothingEnum.nothing;
        app.changeTextPreferences=NothingEnum.nothing;
        try {
            app.findTextPreferences.findWhat=marker;
            var matches=app.activeDocument.findText();
            if(matches.length!==1) throw Error('Expected exactly one marker, found '+matches.length);
            matches[0].remove();
            return 'MARKER_REMOVED:' + marker;
        } finally {
            app.findTextPreferences=NothingEnum.nothing;
            app.changeTextPreferences=NothingEnum.nothing;
        }
    ''')