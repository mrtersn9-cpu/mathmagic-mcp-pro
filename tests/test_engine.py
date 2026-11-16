import json
import pytest
from mathmagic_mcp.engine import MathMagicEngine
from mathmagic_mcp.indesign import jsx_invoke, jsx_select_marker, jsx_document, jsx_actions

class FakeBridge:
    def __init__(self): self.calls=[]
    def document(self): return {'document':'Test.indd','selection_count':'1','path':'','modified':'False'}
    def actions(self): return [{'name':'New Equation','enabled':True},{'name':'Edit Equation','enabled':True}]
    def execute(self,script,timeout=15): self.calls.append(script);return 'OK'
    def run_async(self,script):
        import queue,threading
        self.calls.append(script)
        q=queue.Queue();q.put((True,'ACTION_INVOKED'))
        return threading.Thread(),q

class FakeUI:
    def paste_convert_save(self,latex,replace=False,timeout=25):
        return {'submitted':True,'stages':['paste_latex','save_mathmagic'],'verification':'NOT_VERIFIED'}

@pytest.fixture
def engine(tmp_path):
    return MathMagicEngine(env={'MATHMAGIC_LOG_DIR':str(tmp_path)},bridge=FakeBridge(),ui=FakeUI())

def test_latex_validation(engine):
    for good in [r'\frac{1}{2}',r'\sqrt{x^{2}+3}',r'\int_{0}^{1} x dx']:
        engine.validate_latex(good)
    for bad in ['',r'\frac{1}{2',r'\input{evil}',r'\write18{cmd}', 'x'*4001]:
        with pytest.raises(ValueError): engine.validate_latex(bad)

def test_marker_validation(engine):
    engine.validate_marker('[[MM:Q_22]]')
    for m in ['MM:X','[[MM:foo/bar]]','[[MM:]]']:
        with pytest.raises(ValueError):engine.validate_marker(m)

def test_preview_no_calls(engine):
    r=engine.preview(r'\sqrt{16}',marker='[[MM:A1]]')
    assert r['ok'] and r['dry_run']
    assert engine.bridge.calls==[]

def test_mutation_requires_confirmation(engine):
    r=engine.run_equation(r'x^2',confirm=False)
    assert r['dry_run'] and engine.bridge.calls==[]

def test_live_linux_refuses(engine):
    # On non-Windows we must never misreport a real edit.
    import os
    if os.name!='nt':
        r=engine.run_equation(r'x^2',confirm=True)
        assert r['ok'] is False

def test_manifest(engine,tmp_path):
    m=tmp_path/'jobs.json'
    m.write_text(json.dumps({'equations':[{'id':'1','marker':'[[MM:1]]','latex':r'\frac{1}{2}'}]}))
    r=engine.batch_preview(str(m))
    assert r['count']==1 and r['dry_run']

def test_jsx_escapes_and_returns():
    assert 'return entries.join' in jsx_actions()
    assert "return 'NO_DOCUMENT'" in jsx_document()
    assert 'return' in jsx_invoke('New Equation')
    assert '\\"' in jsx_select_marker('[[MM:A\"B]]')  # JS string serialization