"""InDesign COM bridge (never launches InDesign; fixed JSX only).

All ExtendScript is generated here from validated parameters; MCP clients cannot
inject code. Results are JSON produced by a tiny ES3 serializer.

Synchronisation features (v0.4):
- every mutating script runs as ONE undo step (app.doScript + UndoModes.ENTIRE_SCRIPT)
- equation frames carry script labels (mm.id, mm.latex, mm.sha, mm.style, mm.tool), so equations
  stay identifiable after markers are removed and can be listed, verified, re-rendered or restyled
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
LABEL_KEYS = ("id", "latex", "sha", "style", "tool")


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
var __KEYS=["id","latex","sha","style","tool"];
function __labels(fr){var o={};for(var i=0;i<__KEYS.length;i++){var v="";try{v=fr.extractLabel("mm."+__KEYS[i]);}catch(e){}if(v)o[__KEYS[i]]=v;}return o;}
function __setLabels(fr,o){for(var k in o){if(o.hasOwnProperty(k)&&o[k]!==null)fr.insertLabel("mm."+k,String(o[k]));}}
function __info(eq,checkEdit){var l=null;try{l=eq.graphic.itemLink;}catch(e){}
 var r={type:eq.graphic.constructor.name,link:l?l.name:null,path:l?l.filePath:null,status:l?String(l.status):null,
   embedded:l?(l.status===LinkStatus.LINK_EMBEDDED):null,placeholder:l?(l.name==="EmptyEquation.eps"):null,
   bounds:eq.frame.geometricBounds,labels:__labels(eq.frame)};
 try{r.anchor_y_offset=eq.frame.anchoredObjectSettings.anchorYoffset;}catch(e){}
 try{r.overset=!eq.frame.parentPage;}catch(e){r.overset=true;}
 if(checkEdit){var prev=app.selection;
   try{app.select(eq.frame);r.edit_equation_enabled=__en(__action("Edit Equation",512513));}catch(e){r.edit_equation_enabled=null;r.select_error=String(e);}
   try{if(prev.length)app.select(prev);else app.select(NothingEnum.NOTHING);}catch(e){try{app.select(NothingEnum.NOTHING);}catch(e2){}}}
 return r;}
function __baseline(fr,want,descent,res){if(!want){res.baseline="NOT_REQUESTED";return;}
 var b=__action("Default Baseline",512525);
 try{if(!b)throw Error("missing");app.select(fr);b.invoke();res.baseline="PLUGIN_DEFAULT_BASELINE";}
 catch(e){if(descent!==null){var mu=app.scriptPreferences.measurementUnit;app.scriptPreferences.measurementUnit=MeasurementUnits.POINTS;
   try{fr.anchoredObjectSettings.anchorYoffset=-descent;res.baseline="EPS_HEADER_BASELINE";}finally{app.scriptPreferences.measurementUnit=mu;}}
   else{res.baseline="BASELINE_NOT_ADJUSTED";}}
 try{app.select(NothingEnum.NOTHING);}catch(e){}}
function __frameById(doc,id){var L=doc.links;for(var i=0;i<L.length;i++){try{var fr=L[i].parent.parent;if(fr.extractLabel("mm.id")===id)return fr;}catch(e){}}return null;}
'''


def _wrap(body: str) -> str:
    return "(function(){" + _PRELUDE + "\ntry{\n" + body + "\n}catch(e){return __j({ok:false,error:String(e)});}\n})();"


def _wrap_undo(body: str, undo_name: str) -> str:
    """Run body as a single undoable step named undo_name."""
    return ("(function(){" + _PRELUDE + "\nvar __r=null;\ntry{app.doScript(function(){__r=(function(){\n" + body +
            "\n})();},ScriptLanguage.JAVASCRIPT,[],UndoModes.ENTIRE_SCRIPT," + js(undo_name[:80]) +
            ");}catch(e){return __j({ok:false,error:String(e)});}\nreturn __r;})();")


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
    """Fast document list (no menu-action scan, ~20 ms)."""
    return _wrap(r'''
 var out={ok:true,documents:[]};
 for(var i=0;i<app.documents.length;i++){var d=app.documents[i];var p="";try{p=d.fullName.fsName;}catch(e){}
   out.documents.push({name:d.name,path:p,modified:d.modified,saved:d.saved});}
 out.active=app.documents.length?app.activeDocument.name:null;
 return __j(out);''')


def jsx_select_marker(doc_name: str, marker: str) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});if(app.activeDocument!==doc)app.activeDocument=doc;
 var m=__findMarker(doc,{js(marker)});
 if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 app.select(m[0].insertionPoints[0]);
 return __j({{ok:true,new_equation_enabled:__en(__action("New Equation",{ACTION_IDS["New Equation"]}))}});''')


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
 return __j({{ok:true,marker_count:1,marker_index:ix,equation:eq?__info(eq,{js(check_edit)}):null}});''')


def jsx_select_equation(doc_name: str, marker: str) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});if(app.activeDocument!==doc)app.activeDocument=doc;
 var m=__findMarker(doc,{js(marker)});if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 var st=m[0].parentStory;var ix=m[0].insertionPoints[0].index;var eq=ix>0?__eqBefore(st.characters[ix-1]):null;
 if(!eq)return __j({{ok:false,error:"NO_EQUATION_BEFORE_MARKER"}});
 app.select(eq.frame);
 return __j({{ok:true,edit_equation_enabled:__en(__action("Edit Equation",{ACTION_IDS["Edit Equation"]})),
   link:eq.graphic.itemLink?eq.graphic.itemLink.name:null}});''')


def jsx_place_eps(doc_name: str, marker: str, eps_path: str, embed: bool, default_baseline: bool, replace: bool,
                  descent_pt: float | None = None, labels: dict | None = None, remove_marker: bool = False) -> str:
    """Place (or replace) the EPS right before the marker, fit, embed, baseline, label, verify: one undo step."""
    return _wrap_undo(f'''
 var doc=__doc({js(doc_name)});var f=File({js(eps_path.replace(chr(92), "/"))});
 if(!f.exists)return __j({{ok:false,error:"EPS_NOT_FOUND"}});
 var m=__findMarker(doc,{js(marker)});if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 var st=m[0].parentStory;var ix=m[0].insertionPoints[0].index;var old=ix>0?__eqBefore(st.characters[ix-1]):null;
 var g=null;var isPh=false;try{{isPh=old&&old.graphic.itemLink.name==="EmptyEquation.eps";}}catch(e){{}}
 if(old&&({js(replace)}||isPh)){{g=old.frame.place(f)[0];}}
 else if(old){{return __j({{ok:false,error:"EQUATION_ALREADY_PRESENT",equation:__info(old,false)}});}}
 else{{st.insertionPoints[ix].place(f);var eq0=__eqBefore(st.characters[ix]);g=eq0?eq0.graphic:null;}}
 if(!g)return __j({{ok:false,error:"PLACE_FAILED"}});
 var fr=g.parent;
 try{{g.absoluteHorizontalScale=100;g.absoluteVerticalScale=100;}}catch(e){{}}
 try{{fr.fit(FitOptions.FRAME_TO_CONTENT);}}catch(e){{}}
 if({js(embed)}){{try{{g.itemLink.unlink();}}catch(e){{}}}}
 __setLabels(fr,{js(labels or {})});
 var res={{ok:true}};
 __baseline(fr,{js(default_baseline)},{js(descent_pt)},res);
 var m2=__findMarker(doc,{js(marker)});var st2=m2[0].parentStory;var ix2=m2[0].insertionPoints[0].index;
 var eq=__eqBefore(st2.characters[ix2-1]);res.equation=eq?__info(eq,true):null;
 if({js(remove_marker)}&&res.equation&&!res.equation.placeholder){{m2[0].remove();res.marker_removed=true;}}
 return __j(res);''', f"MathMagic MCP {marker}")


def jsx_replace_by_id(doc_name: str, eq_id: str, eps_path: str, embed: bool, default_baseline: bool,
                      descent_pt: float | None, labels: dict) -> str:
    return _wrap_undo(f'''
 var doc=__doc({js(doc_name)});var f=File({js(eps_path.replace(chr(92), "/"))});
 if(!f.exists)return __j({{ok:false,error:"EPS_NOT_FOUND"}});
 var fr=__frameById(doc,{js(eq_id)});if(!fr)return __j({{ok:false,error:"ID_NOT_FOUND"}});
 var g=fr.place(f)[0];
 try{{g.absoluteHorizontalScale=100;g.absoluteVerticalScale=100;}}catch(e){{}}
 try{{fr.fit(FitOptions.FRAME_TO_CONTENT);}}catch(e){{}}
 if({js(embed)}){{try{{g.itemLink.unlink();}}catch(e){{}}}}
 __setLabels(fr,{js(labels)});var res={{ok:true}};
 __baseline(fr,{js(default_baseline)},{js(descent_pt)},res);
 res.equation=__info({{frame:fr,graphic:fr.allGraphics[0]}},true);return __j(res);''', f"MathMagic MCP restyle {eq_id}")


def jsx_tag_at_marker(doc_name: str, marker: str, labels: dict) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});var m=__findMarker(doc,{js(marker)});
 if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 var st=m[0].parentStory;var ix=m[0].insertionPoints[0].index;var eq=ix>0?__eqBefore(st.characters[ix-1]):null;
 if(!eq)return __j({{ok:false,error:"NO_EQUATION_BEFORE_MARKER"}});
 __setLabels(eq.frame,{js(labels)});return __j({{ok:true}});''')


def jsx_list_equations(doc_name: str, include_latex: bool = False, deep: bool = False) -> str:
    """Tagged equations, plugin names (EQ-MMDD-HHMMSS.eps), placeholders and v0.3 offline names (<id>-<sha10>.eps).
    deep=True also asks the plugin (Edit Equation enabled) for every other EPS link (~40 ms each)."""
    return _wrap(f'''
 var doc=__doc({js(doc_name)});var L=doc.links;var out=[];
 for(var i=0;i<L.length;i++){{var l=L[i];var g=null,fr=null;try{{g=l.parent;fr=g.parent;}}catch(e){{continue;}}
   var lab=__labels(fr);var name=l.name;
   var known=lab.id||/^EQ-\\d{{4}}-\\d{{6}}\\.eps$/i.test(name)||name==="EmptyEquation.eps"||/^[A-Za-z0-9_-]{{1,40}}-[0-9a-f]{{10}}\\.eps$/i.test(name);
   if(!known&&{js(deep)}&&/\\.eps$/i.test(name)){{var prev=app.selection;try{{app.select(fr);known=__en(__action("Edit Equation",512513))===true;}}catch(e){{}}
     try{{if(prev.length)app.select(prev);else app.select(NothingEnum.NOTHING);}}catch(e){{}}}}
   if(!known)continue;
   var page=null;try{{page=fr.parentPage?fr.parentPage.name:null;}}catch(e){{}}
   var anchored=false;try{{anchored=fr.parent.constructor.name==="Character";}}catch(e){{}}
   var item={{id:lab.id||null,link:name,embedded:l.status===LinkStatus.LINK_EMBEDDED,placeholder:name==="EmptyEquation.eps",
     page:page,anchored:anchored,sha:lab.sha||null,style:lab.style||null,tool:lab.tool||null}};
   if({js(include_latex)})item.latex=lab.latex||null;
   out.push(item);}}
 return __j({{ok:true,count:out.length,equations:out}});''')


def jsx_save_document(doc_name: str) -> str:
    return _wrap(f'''
 var doc=__doc({js(doc_name)});if(!doc.saved)return __j({{ok:false,error:"DOCUMENT_NEVER_SAVED"}});
 doc.save();return __j({{ok:true,modified:doc.modified}});''')


def jsx_remove_marker(doc_name: str, marker: str) -> str:
    return _wrap_undo(f'''
 var doc=__doc({js(doc_name)});var m=__findMarker(doc,{js(marker)});
 if(m.length!==1)return __j({{ok:false,error:"MARKER_COUNT",count:m.length}});
 m[0].remove();return __j({{ok:true}});''', f"MathMagic MCP remove {marker}")


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
