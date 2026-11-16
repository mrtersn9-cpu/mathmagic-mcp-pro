"""MathMagic + InDesign coordination with explicit mutation authorization."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .indesign import InDesignBridge, IndesignError, jsx_invoke, jsx_select_marker
from .windows_ui import MathMagicUI, MathMagicUIError

_LOCK=threading.Lock()
_FORBIDDEN_TEX=re.compile(r'\\(?:write18|input|include|openout|read|catcode|def|special|immediate|loop|csname)\b',re.I)
_ALLOWED_ACTIONS={'New Equation','Edit Equation'}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MathMagicEngine:
    def __init__(self, env: dict[str,str] | None=None, bridge=None, ui=None):
        self.env=dict(os.environ if env is None else env)
        self.exe=self.env.get('MATHMAGIC_EXE',r'C:\Program Files (x86)\MathMagic Pro Edition\MathMagic Pro 9.31 InD.exe')
        self.prog_id=self.env.get('INDESIGN_PROGID','InDesign.Application')
        self.new_action=self.env.get('MATHMAGIC_NEW_ACTION','New Equation')
        self.edit_action=self.env.get('MATHMAGIC_EDIT_ACTION','Edit Equation')
        self.logs=Path(self.env.get('MATHMAGIC_LOG_DIR',str(Path.home()/'MathMagicMCP'/'logs')))
        self.bridge=bridge if bridge is not None else InDesignBridge(self.prog_id)
        self.ui=ui if ui is not None else MathMagicUI(self.exe,
            self.env.get('MATHMAGIC_CONVERT_KEYS','+{ENTER}'),
            self.env.get('MATHMAGIC_SAVE_KEYS','^s'),
            self.env.get('MATHMAGIC_CLOSE_EDITOR','false').lower()=='true')

    @staticmethod
    def validate_latex(latex: str) -> None:
        if not isinstance(latex,str) or not latex.strip():
            raise ValueError('LaTeX expression is empty')
        if len(latex)>4000:
            raise ValueError('LaTeX expression exceeds 4000 characters')
        if '\x00' in latex or _FORBIDDEN_TEX.search(latex):
            raise ValueError('Potentially unsafe or unsupported TeX command')
        depth=0
        for ch in latex:
            if ch=='{': depth+=1
            elif ch=='}': depth-=1
            if depth<0:
                raise ValueError('Unbalanced braces')
        if depth:
            raise ValueError('Unbalanced braces')

    @staticmethod
    def validate_marker(marker: str) -> None:
        if not isinstance(marker,str) or not re.fullmatch(r'\[\[MM:[a-zA-Z0-9_-]{1,40}\]\]',marker):
            raise ValueError('Marker must be [[MM:ID]] with alphanumeric ID')

    def _log(self, event: dict) -> str | None:
        try:
            self.logs.mkdir(parents=True,exist_ok=True)
            filename=self.logs/('mm-'+datetime.now(timezone.utc).strftime('%Y%m%d')+'.jsonl')
            with filename.open('a',encoding='utf-8') as fp:
                fp.write(json.dumps(event,ensure_ascii=False)+'\n')
            return str(filename)
        except OSError:
            return None

    def preflight(self) -> dict:
        checks={
            'windows': os.name=='nt',
            'mathmagic_executable_exists':Path(self.exe).is_file(),
            'mathmagic_exe':self.exe,
            'indesign_prog_id':self.prog_id,
            'indesign_plugin_folder_exists':Path(r'C:\Program Files\Adobe\Adobe InDesign 2026\Plug-Ins\MathMagic CC2026-64bit').is_dir(),
        }
        try: import win32com.client  # type: ignore
        except ImportError: checks['pywin32_installed']=False
        else: checks['pywin32_installed']=True
        try: import pywinauto  # type: ignore
        except ImportError: checks['pywinauto_installed']=False
        else: checks['pywinauto_installed']=True
        checks['ready_to_attempt']=all(checks[k] for k in ['windows','mathmagic_executable_exists','pywin32_installed','pywinauto_installed','indesign_plugin_folder_exists'])
        return {'ok':True,'checks':checks,'note':'File checks do not prove that the plugin action works; run inspect_indesign.'}

    def inspect(self) -> dict:
        try:
            info=self.bridge.document()
            acts=self.bridge.actions()
            return {'ok':True,'document':info,'mathmagic_candidate_actions':acts,
                'configured_actions': {'create':self.new_action,'edit':self.edit_action},
                'note':'Only menu actions detected by InDesign are callable; name may vary by installation locale.'}
        except Exception as exc:
            return {'ok':False,'error':str(exc),'hint':'Start InDesign 2026 and open a document, then check Plug-Ins > MathMagic.'}

    def preview(self,latex: str, mode: str='create', marker: str='') -> dict:
        self.validate_latex(latex)
        if mode not in ('create','edit'):
            raise ValueError('mode must be create or edit')
        if marker: self.validate_marker(marker)
        return {'ok':True,'dry_run':True,'mode':mode,
            'target':'marker' if marker else 'current InDesign selection',
            'marker':marker or None,
            'latex_sha256':hashlib.sha256(latex.encode()).hexdigest(),
            'latex_length':len(latex),
            'actions':[('Select marker '+marker) if marker else 'Use current InDesign selection',
                'Invoke plugin '+(self.new_action if mode=='create' else self.edit_action),
                'Wait for MathMagic editor (process path verified)','Paste LaTeX and convert (Shift+Enter)',
                'Save (Ctrl+S)','Manual visual and editability check required'],
            'original_documents_untouched':True}

    def run_equation(self,latex: str, mode: str='create', marker: str='', confirm: bool=False,
                     window_timeout: int=25) -> dict:
        self.validate_latex(latex)
        if mode not in ('create','edit'):
            raise ValueError('mode must be create or edit')
        if marker:
            self.validate_marker(marker)
            if mode=='edit':
                raise ValueError('Marker targeting is supported for create only. Select an existing equation for edit.')
        if not confirm:
            return self.preview(latex,mode,marker)
        if os.name!='nt':
            return {'ok':False,'error':'Windows required for live operations'}
        if not 5<=window_timeout<=90:
            raise ValueError('window_timeout must be between 5 and 90')
        if not _LOCK.acquire(blocking=False):
            return {'ok':False,'error':'Another MathMagic MCP operation is running'}
        opid=uuid.uuid4().hex[:12]
        event={'job_id':opid,'created_at':_now(),'mode':mode,'marker':marker or None,
               'latex_sha256':hashlib.sha256(latex.encode()).hexdigest()}
        try:
            doc=self.bridge.document()
            if not doc.get('document'):
                raise IndesignError('Open an InDesign document first')
            if marker:
                self.bridge.execute(jsx_select_marker(marker),timeout=15)
            else:
                if doc.get('selection_count')=='0':
                    raise IndesignError('No current selection. Place text caret or select MathMagic object via existing InDesign MCP.')
            action=self.new_action if mode=='create' else self.edit_action
            available={a['name']:a for a in self.bridge.actions()}
            if action not in available:
                raise IndesignError(f'Configured action {action!r} was not found. Run inspect_indesign and configure MATHMAGIC_NEW_ACTION / _EDIT_ACTION.')
            if not available[action]['enabled']:
                raise IndesignError(f'Menu action disabled: {action}; check selection and MathMagic plugin')
            thread,q=self.bridge.run_async(jsx_invoke(action))
            # The plugin may keep the COM action pending while the editor runs.
            # Therefore GUI operation runs concurrently with the COM call.
            result=self.ui.paste_convert_save(latex,replace=(mode=='edit'),timeout=window_timeout)
            thread.join(timeout=5)
            if not q.empty():
                ok, payload=q.get_nowait()
                if not ok:
                    raise IndesignError('Plugin menu invocation failed: '+payload)
                event['plugin_result']=payload
            else:
                event['plugin_result']='COM action still pending (cannot independently verify)'
            event['status']='SUBMITTED_UNVERIFIED'
            event['steps']=result.get('stages',[])
            event['source_document']=doc.get('document')
            logpath=self._log(event)
            return {'ok':True,'job_id':opid,'status':'SUBMITTED_UNVERIFIED',
                    'plugin_action':action,'gui':result,'audit_log':logpath,
                    'requires_manual_review':True,
                    'note':'Success only means input/save shortcuts were sent; not a verified native MathMagic equation.'}
        except Exception as exc:
            event['status']='FAILED_OR_PARTIAL'
            event['error']=str(exc)
            logpath=self._log(event)
            return {'ok':False,'job_id':opid,'status':'FAILED_OR_PARTIAL','error':str(exc),
                    'audit_log':logpath,
                    'warning':'InDesign or MathMagic may have been partially modified; inspect before retrying.'}
        finally:
            _LOCK.release()

    def backup_document(self, folder: str, confirm: bool=False) -> dict:
        if not confirm:
            return {'ok':True,'dry_run':True,'note':'Would copy last saved INDD file, without changing source. Unsaved in-memory changes are NOT included.'}
        info=self.bridge.document()
        origin=Path(info.get('path') or '')
        if not origin.is_file() or origin.suffix.lower()!='.indd':
            return {'ok':False,'error':'Save the document to a .indd file first'}
        target=Path(folder).expanduser().resolve()
        if target == origin.parent.resolve():
            return {'ok':False,'error':'Choose another backup folder'}
        target.mkdir(parents=True,exist_ok=True)
        name=origin.stem+'-mm-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+origin.suffix
        output=target/name
        if output.exists():
            return {'ok':False,'error':'Backup target already exists'}
        shutil.copy2(origin,output)
        return {'ok':True,'backup':str(output),'source':str(origin),'unsaved_changes_included':False}

    def check_marker(self, marker: str) -> dict:
        self.validate_marker(marker)
        from .indesign import jsx_check_marker
        raw=self.bridge.execute(jsx_check_marker(marker))
        return {'ok':True,'raw':raw,
                'verification':'Marker position diagnostic only. Does NOT prove MathMagic object integrity or LaTeX match.'}

    def batch_preview(self,manifest_path: str) -> dict:
        jobs=self._read_manifest(manifest_path)
        return {'ok':True,'dry_run':True,'count':len(jobs),
                'jobs':[{'id':x['id'],'marker':x['marker'],'length':len(x['latex'])} for x in jobs],
                'note':'Only one interactive equation at a time. Each equation requires review before continuing.'}

    def _read_manifest(self,manifest_path: str) -> list[dict]:
        path=Path(manifest_path).resolve()
        if path.suffix.lower()!='.json' or not path.is_file() or path.stat().st_size>1024*1024:
            raise ValueError('Manifest must be an existing JSON file up to 1 MB')
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        items=data.get('equations') if isinstance(data,dict) else None
        if not isinstance(items,list) or not (1<=len(items)<=100):
            raise ValueError('Manifest equations must contain 1..100 entries')
        seen=set()
        for x in items:
            if not isinstance(x,dict) or not all(k in x for k in ('id','marker','latex')):
                raise ValueError('Each equation needs id, marker, latex')
            self.validate_marker(x['marker']);self.validate_latex(x['latex'])
            if x['marker'] in seen: raise ValueError('Duplicate marker: '+x['marker'])
            seen.add(x['marker'])
        return items

    def run_batch(self,manifest_path: str, confirm: bool=False, stop_on_unverified: bool=True, start_index: int=0) -> dict:
        items=self._read_manifest(manifest_path)
        if not isinstance(start_index,int) or not 0<=start_index<len(items):
            raise ValueError('start_index out of range')
        if not confirm:
            preview=self.batch_preview(manifest_path)
            preview['start_index']=start_index
            return preview
        if not stop_on_unverified:
            raise ValueError('Fully unattended batch is not supported: every equation requires review')
        # Intentionally execute ONE, stop, report. Next equation requires a new call.
        first=items[start_index]
        result=self.run_equation(first['latex'],mode='create',marker=first['marker'],confirm=True)
        return {'ok':result['ok'],'attempted':1,'total':len(items),'index':start_index,'first_id':first['id'],
                'first_result':result,'remaining':len(items)-start_index-1,
                'status':'PAUSED_FOR_REVIEW',
                'note':'Continue only after verifying the native MathMagic object and removing/reconciling the marker.'}

    def cleanup_marker(self, marker: str, confirm: bool=False, human_verified: bool=False) -> dict:
        self.validate_marker(marker)
        if not confirm or not human_verified:
            return {'ok':True,'dry_run':True,'marker':marker,
                    'note':'Confirm and human_verified must both be true to remove a marker after visual checking.'}
        from .indesign import jsx_remove_marker
        if not _LOCK.acquire(blocking=False):
            return {'ok':False,'error':'MathMagic MCP operation already running'}
        try:
            raw=self.bridge.execute(jsx_remove_marker(marker))
            return {'ok':True,'result':raw,'note':'Marker removed; MathMagic equation fidelity was not automatically checked.'}
        except Exception as exc:
            return {'ok':False,'error':str(exc)}
        finally:
            _LOCK.release()