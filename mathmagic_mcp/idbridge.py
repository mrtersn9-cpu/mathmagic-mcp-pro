"""InDesign COM bridge for v0.3 (never launches InDesign; fixed JSX only).

All ExtendScript is generated here from validated parameters; MCP clients cannot
inject code. Results are returned as JSON produced by a tiny ES3 serializer.
"""
from __future__ import annotations

import json
import queue
import threading

from . import win32util as w

JAVASCRIPT = 1246973031
INDESIGN_EXE = "InDesign.exe"
ACTION_IDS = {"New Equation": 512512, "Edit Equation": 512513, "Shift Baseline...": 512515,
              "Default Baseline": 512525, "Convert to Equation": 512534}


class InDesignError(RuntimeError):
    pass


def js(value) -> str:
    return json.dumps(value, ensure_ascii=True)


_PRELUDE = r'''
function __j(v){var t=typeof v;if(v===null||t==="undefined")return "null";
 if(t==="number"||t==="boolean")return String(v);
 if(t==="string"){return '"'+v.replace(/\\/g,"\\\\").replace(/"/g,'\\"').replace(/\r/g,"\\r").replace(/\n/g,"\\n").replace(/\t/g,"\\t").replace(/[\u0000-\u001f\u007f-\uffff]/g,function(c){var h=c.charCodeAt(0).toString(16);while(h.length<4)h="0"+h;return "\\u"+h;})+'"';}
 if(v instanceof Array){var a=[];for(var i=0;i<v.length;i++)a.push(__j(v[i]));return "["+a.join(",")+"]";}
 var o=[];for(var k in v){if(v.hasOwnProperty(k))o.push(__j(k)+":"+__j(v[k]));}return "{"+o.join(",")+"}";}
function __doc(name){if(!app.documents.length)throw Error("NO_DOCUMENT");
 if(!name)return app.activeDocument;
 for(var i=0;i<app.documents.length;i++)if(app.documents[i].name===name)return app.documents[i];
 throw Error("DOCUMENT_NOT_OPEN:"+name);}
function __action(name,id){var a=null;try{a=app.menuActions.itemByID(id);a.name;}catch(e){a=null;}
 if(!a||a.name!==name){a=null;for(var i=0;i<app.menuActions.length;i++){try{if(app.menuActions[i].name===name){a=app.menuActions[i];break;}}catch(e){}}}
 return a;}
function __en(a){if(!a)return null;try{return a.enabled;}catch(e){return null;}}
function __findMarker(doc,marker){app.findTextPreferences=NothingEnum.nothing;app.changeTextPreferences=NothingEnum.nothing;
 try{app.findTextPreferences.findWhat=marker;var m=doc.findText();return m;}
 finally{app.findTextPreferences=NothingEnum.nothing;app.changeTextPreferences=NothingEnum.nothing;}}
function __eqBefore(ch){try{if(ch.contents!=="\uFFFC")return null;var it=ch.allPageItems;if(!it.length)return null;
 var fr=it[0];var g=fr.allGraphics.length?fr.allGraphics[0]:null;if(!g)return null;return {frame:fr,graphic:g};}catch(e){return null;}}
'''


def _wrap(body: str) -> str:
    return "(function(){" + _PRELUDE + "\ntry{\n" + body + "\n}catch(e){return __j({ok:false,error:String(e)});}\n})();"


def jsx_status(doc_name: str = "") -> str:
    return _wrap(r'''
 var out={ok:true,documents:[],actions:[]};
 for(var i=0;i<app.documents.length;i++){var d=app.documents[i];var p="";try{p=d.fullName.fsName;}catch(e){}
   out.documents.push({name:d.name,path:p,modified:d.modified});}
 out.active=app.documents.length?app.activeDocument.name:null;
 out.selection=app.selection.length?app.selection[0].constructor.name:"none";
 for(var k=0;k<app.menuActions.length;k++){try{var a=app.menuActions[k];
   if(a.area==="MathMagic"||/mathmagic|equation|baseline|styleset/i.test(a.name))out.actions.push({id:a.id,name:a.name,area:a.area,enabled:__en(a)});}catch(e){}}
 return __j(out);''')


def jsx_documents() -> str:
    """Fast document list (no menu-action scan); used on every equation."""
    return _wrap(r'''
 var out={ok:true,documents:[]};
 for(var i=0;i<app.documents.length;i++){var d=app.documents[i];var p="";try{p=d.fullName.fsName;}catch(e){}
   out.documents.push({name:d.name,path:p,modified:d.modified});}
 out.active=app.documents.length?app.activeDocument.name:null;
 return __j(out);''')


def jsx_select_marker(doc_name: str, marker: str) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});if(app.activeDocument!==doc)app.activeDocument=doc;
 var m=__findMarker(doc,{js(marker)});
 if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 app.select(m[0].insertionPoints[0]);
 var a=__action("New Equation",{ACTION_IDS["New Equation"]});
 return __j({{ok:true,new_equation_enabled:__en(a)}});''')


def jsx_invoke(name: str) -> str:
    return _wrap(f'''
 var a=__action({js(name)},{ACTION_IDS.get(name, 0)});
 if(!a)return __j({{ok:false,error:"ACTION_NOT_FOUND"}});
 if(__en(a)===false)return __j({{ok:false,error:"ACTION_DISABLED"}});
 a.invoke();return __j({{ok:true}});''')


def jsx_equation_at_marker(doc_name: str, marker: str, check_edit: bool = True) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});var m=__findMarker(doc,{js(marker)});
 if(m.length!==1)return __j({{ok:true,marker_count:m.length,equation:null}});
 var st=m[0].parentStory;var ix=m[0].insertionPoints[0].index;
 var eq=ix>0?__eqBefore(st.characters[ix-1]):null;
 var res={{ok:true,marker_count:1,marker_index:ix,equation:null}};
 if(eq){{var l=null;try{{l=eq.graphic.itemLink;}}catch(e){{}}
   res.equation={{type:eq.graphic.constructor.name,link:l?l.name:null,path:l?l.filePath:null,
     status:l?String(l.status):null,embedded:l?(l.status===LinkStatus.LINK_EMBEDDED):null,
     placeholder:l?(l.name==="EmptyEquation.eps"):null,bounds:eq.frame.geometricBounds}};
   if({js(check_edit)}){{var prev=app.selection;app.select(eq.frame);
     var a=__action("Edit Equation",{ACTION_IDS["Edit Equation"]});res.equation.edit_equation_enabled=__en(a);
     try{{res.equation.anchor_y_offset=eq.frame.anchoredObjectSettings.anchorYoffset;}}catch(e){{}}
     try{{if(prev.length)app.select(prev);else app.select(NothingEnum.NOTHING);}}catch(e){{app.select(NothingEnum.NOTHING);}}}}}}
 return __j(res);''')


def jsx_select_equation(doc_name: str, marker: str) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});if(app.activeDocument!==doc)app.activeDocument=doc;
 var m=__findMarker(doc,{js(marker)});if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 var st=m[0].parentStory;var ix=m[0].insertionPoints[0].index;var eq=ix>0?__eqBefore(st.characters[ix-1]):null;
 if(!eq)return __j({{ok:false,error:"NO_EQUATION_BEFORE_MARKER"}});
 app.select(eq.frame);var a=__action("Edit Equation",{ACTION_IDS["Edit Equation"]});
 return __j({{ok:true,edit_equation_enabled:__en(a),link:eq.graphic.itemLink?eq.graphic.itemLink.name:null}});''')


def jsx_place_eps(doc_name: str, marker: str, eps_path: str, embed: bool, default_baseline: bool, replace: bool,
                  descent_pt: float | None = None) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});var f=File({js(eps_path.replace(chr(92), "/"))});
 if(!f.exists)return __j({{ok:false,error:"EPS_NOT_FOUND"}});
 var m=__findMarker(doc,{js(marker)});if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 var st=m[0].parentStory;var ix=m[0].insertionPoints[0].index;var old=ix>0?__eqBefore(st.characters[ix-1]):null;
 var g=null;
 if(old&&{js(replace)}){{g=old.frame.place(f)[0];}}
 else if(old&&!{js(replace)}){{return __j({{ok:false,error:"EQUATION_ALREADY_PRESENT"}});}}
 else{{st.insertionPoints[ix].place(f);var ch=st.characters[ix];var eq=__eqBefore(ch);g=eq?eq.graphic:null;}}
 if(!g)return __j({{ok:false,error:"PLACE_FAILED"}});
 var fr=g.parent;
 try{{fr.fit(FitOptions.FRAME_TO_CONTENT);}}catch(e){{}}
 if({js(embed)}){{try{{g.itemLink.unlink();}}catch(e){{}}}}
 var res={{ok:true,link:g.itemLink?g.itemLink.name:null,bounds:fr.geometricBounds,baseline:null}};
 app.select(fr);
 var ea=__action("Edit Equation",{ACTION_IDS["Edit Equation"]});res.edit_equation_enabled=__en(ea);
 if({js(default_baseline)}){{var b=__action("Default Baseline",{ACTION_IDS["Default Baseline"]});
   try{{if(!b)throw Error("missing");b.invoke();res.baseline="PLUGIN_DEFAULT_BASELINE";}}
   catch(e){{var d={js(descent_pt)};
     if(d!==null){{var mu=app.scriptPreferences.measurementUnit;app.scriptPreferences.measurementUnit=MeasurementUnits.POINTS;
       try{{fr.anchoredObjectSettings.anchorYoffset=-d;res.baseline="EPS_HEADER_BASELINE";}}
       finally{{app.scriptPreferences.measurementUnit=mu;}}}}
     else{{res.baseline="BASELINE_NOT_ADJUSTED";}}}}}}
 try{{res.anchor_y_offset=fr.anchoredObjectSettings.anchorYoffset;}}catch(e){{}}
 app.select(NothingEnum.NOTHING);
 return __j(res);''')


def jsx_remove_marker(doc_name: str, marker: str) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});var m=__findMarker(doc,{js(marker)});
 if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 m[0].remove();return __j({{ok:true}});''')


class InDesignCOM:
    def __init__(self, prog_id: str = "InDesign.Application"):
        self.prog_id = prog_id

    def running(self) -> bool:
        return w.IS_WINDOWS and w.is_process_running(INDESIGN_EXE)

    def _run(self, script: str, q: queue.Queue) -> None:
        try:
            import pythoncom  # type: ignore
            from win32com.client import Dispatch  # type: ignore
            pythoncom.CoInitialize()
            try:
                q.put((True, Dispatch(self.prog_id).DoScript(script, JAVASCRIPT)))
            finally:
                pythoncom.CoUninitialize()
        except Exception as exc:  # COM errors are reported, never raised into the protocol loop
            q.put((False, f"{type(exc).__name__}: {exc}"))

    def run(self, script: str, timeout: float = 30.0) -> dict:
        if not self.running():
            raise InDesignError("INDESIGN_NOT_RUNNING: start InDesign first (this tool never launches it)")
        q: queue.Queue = queue.Queue(maxsize=1)
        threading.Thread(target=self._run, args=(script, q), daemon=True).start()
        try:
            ok, payload = q.get(timeout=timeout)
        except queue.Empty:
            raise InDesignError("INDESIGN_TIMEOUT: a modal dialog may be open in InDesign")
        if not ok:
            raise InDesignError(str(payload))
        try:
            return json.loads(payload)
        except (TypeError, ValueError):
            raise InDesignError("UNEXPECTED_JSX_RESULT: " + str(payload)[:200])
