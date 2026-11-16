import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_stdio_handshake():
    requests=[
      {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'test','version':'1'}}},
      {'jsonrpc':'2.0','method':'notifications/initialized'},
      {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}},
      {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'mathmagic_preview_equation','arguments':{'latex':r'\sqrt{4}'}}},
      {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'mathmagic_preflight','arguments':{}}},
    ]
    p=subprocess.run([sys.executable,'-u',str(ROOT/'server.py')],input='\n'.join(json.dumps(x) for x in requests)+'\n',
        text=True,capture_output=True,timeout=15)
    assert p.returncode==0,p.stderr
    data=[json.loads(x) for x in p.stdout.splitlines()]
    assert len(data)==4
    assert data[0]['result']['serverInfo']['name']=='mathmagic-mcp-pro'
    names={t['name'] for t in data[1]['result']['tools']}
    assert 'mathmagic_edit_equation' in names
    assert 'mathmagic_run_batch_first' in names
    assert data[2]['result']['isError']==False
    assert 'dry_run' in data[2]['result']['content'][0]['text']