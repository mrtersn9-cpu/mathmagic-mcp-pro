"""Strict background tests. Real Windows/MathMagic integration not covered."""
import json
from pathlib import Path
import pytest
from mathmagic_mcp.background import BackgroundService, filter_safe_legacy_tools

class FakeEngine:
    exe = '/test/MathMagic.exe'
    def validate_latex(self, text):
        if not text or '\\input' in text:
            raise ValueError('unsafe')
    def validate_marker(self, marker):
        if not marker.startswith('[[MM:'):
            raise ValueError('bad marker')
    def _read_manifest(self, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        for job in data['equations']:
            self.validate_latex(job['latex'])
            self.validate_marker(job['marker'])
        return data['equations']

def service():
    return BackgroundService(FakeEngine(), platform_name='posix')

def manifest(tmp_path, ids=('Q1',)):
    path = tmp_path / 'equations.json'
    path.write_text(json.dumps({'equations': [
        {'id': i, 'marker': '[[MM:' + i + ']]', 'latex': r'\sqrt{9}'}
        for i in ids]}), encoding='utf-8')
    return str(path)

def test_policy_blocks_foreground_automation():
    p = service().policy()
    assert p['allow_set_focus'] is False
    assert p['allow_send_keys'] is False
    assert p['allow_clipboard'] is False
    assert p['actual_background_equation_creation_available'] is False
    assert p['interactive_legacy_tools_exposed'] is False

def test_non_windows_probe_is_truthful():
    p = service().probe()
    assert p['status'] == 'NOT_WINDOWS'
    assert p['focus_free_proven'] is False

def test_plan_no_input_sent():
    p = service().plan(r'\frac{2}{3}', marker='[[MM:A]]')
    assert p['dry_run'] and not p['focus_or_input_sent']
    assert p['background_execution'] == 'BLOCKED_UNTIL_VERIFIED'

def test_rejects_unsafe_latex():
    with pytest.raises(ValueError):
        service().plan(r'\input{evil}')

def test_edit_rejects_marker():
    with pytest.raises(ValueError):
        service().plan('x', mode='edit', marker='[[MM:A]]')

def test_preview_does_not_create_files(tmp_path):
    out = tmp_path / 'prepared'
    result = service().prepare_batch(manifest(tmp_path), str(out))
    assert result['dry_run'] and not out.exists()

def test_staging_creates_tex_and_index(tmp_path):
    out = tmp_path / 'prepared'
    result = service().prepare_batch(manifest(tmp_path), str(out), True)
    assert result['status'] == 'INPUT_FILES_PREPARED'
    assert (out / 'Q1.tex').read_text(encoding='utf-8') == '\\sqrt{9}\n'
    index = json.loads((out / 'index.json').read_text(encoding='utf-8'))
    assert index['status'] == 'INPUT_ONLY_NOT_RENDERED'
    assert result['native_mathmagic_equations_created'] == 0

def test_staging_refuses_overwrite(tmp_path):
    m = manifest(tmp_path)
    out = tmp_path / 'prepared'
    service().prepare_batch(m, str(out), True)
    assert service().prepare_batch(m, str(out), True)['status'] == 'REFUSED_OVERWRITE'

def test_duplicate_id_rejected_case_insensitive(tmp_path):
    with pytest.raises(ValueError, match='duplicate'):
        service().prepare_batch(manifest(tmp_path, ('Q1', 'q1')), str(tmp_path / 'staging'), True)

def test_invalid_id_prevents_files(tmp_path):
    out = tmp_path / 'staging'
    with pytest.raises(ValueError, match='job id'):
        service().prepare_batch(manifest(tmp_path, ('bad/../name',)), str(out), True)
    assert not out.exists()

def test_mock_windows_probe_does_not_set_focus(monkeypatch):
    from mathmagic_mcp import background as bg
    monkeypatch.setattr(bg.Path, 'is_file', lambda self: True)
    calls = []
    def get_focus():
        calls.append('read_foreground')
        return 123
    obj = BackgroundService(
        FakeEngine(), platform_name='nt', foreground_getter=get_focus,
        window_locator=lambda: object(),
        control_inspector=lambda w: {'scanned': 2, 'value_pattern': 1},
    )
    result = obj.probe()
    assert result['status'] == 'INSPECTED_NOT_VALIDATED'
    assert result['foreground_unchanged_at_samples']
    assert not result['focus_free_proven']
    assert calls == ['read_foreground', 'read_foreground']

def test_strict_registry_filters_interactive_tools():
    registry = {name: (None, None) for name in (
        'mathmagic_preflight', 'mathmagic_inspect_indesign',
        'mathmagic_create_equation', 'mathmagic_edit_equation',
        'mathmagic_run_batch_first', 'mathmagic_cleanup_marker')}
    filtered = filter_safe_legacy_tools(registry)
    assert set(filtered) == {'mathmagic_preflight', 'mathmagic_inspect_indesign'}
