"""v0.3 unit tests (no live MathMagic/InDesign needed; Win32 and COM are faked)."""
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mathmagic_mcp import eps, idbridge as ib, mmwin, pipeline as pl, win32util as w  # noqa: E402

REAL_HEADER = """%!PS-Adobe-3.0 EPSF-3.0
%%BoundingBox: -2.094 -0.125 56.656 13.188
%%Creator: MathMagic Pro Win v9.31
%%Title: MathMagic Equation EPS
%%DocumentFonts: MMCenturyNew-Regular
%%+ MMCenturyOldGreek
%%Baseline: 10.313
%%MMFDataBegin
%% abc
%%MMFDataEnd
%%EndComments
"""


# ---------------------------------------------------------------- validation
def test_latex_validation():
    for good in [r"\frac{1}{2}", r"\sqrt{x^2+9}", r"\int_0^1 x^2\,dx", r"\text{ğüşiöç}"]:
        pl.validate_latex(good)
    for bad in ["", r"\frac{1}{2", r"\input{x}", r"\write18{x}", "a\nb", "x" * 4001]:
        with pytest.raises(ValueError):
            pl.validate_latex(bad)


def test_marker_validation():
    assert pl.validate_marker("[[MM:Q_001-a]]") == "Q_001-a"
    for bad in ["MM:1", "[[MM:]]", "[[MM:a/b]]", '[[MM:a"b]]', "[[MM:" + "x" * 41 + "]]"]:
        with pytest.raises(ValueError):
            pl.validate_marker(bad)


def test_manifest_limits(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"equations": [{"marker": "[[MM:A]]", "latex": "x"}, {"marker": "[[MM:A]]", "latex": "y"}]}))
    with pytest.raises(ValueError, match="Duplicate"):
        pl.read_manifest(str(p))
    p.write_text(json.dumps({"equations": [{"marker": f"[[MM:Q{i}]]", "latex": "x"} for i in range(1500)]}))
    assert len(pl.read_manifest(str(p))) == 1500


# ---------------------------------------------------------------- dialogs / eps / png
@pytest.mark.parametrize("title,texts,combo,kind", [
    ("Authorization", ["License Code:"], False, "license"),
    ("Tip of the Day", [], False, "tip"),
    ("MathMagic Pro", ["Tamam", "Helvetica Neue\n\nCould not get the PostScript name from a font"], False, "font_warning"),
    ("Save As", ["&Kaydet"], True, "save_as"),
    ("MathMagic Pro", ["Save changes to Equation-1?"], False, "save_changes"),
    ("Something", ["?"], False, "unknown"),
])
def test_classify_dialog(title, texts, combo, kind):
    assert mmwin.classify_dialog(title, texts, combo) == kind


def test_eps_header_and_descent():
    info = eps.inspect_eps_text(REAL_HEADER)
    assert info["is_mathmagic"] and info["has_mmf_data"]
    assert info["fonts"] == ["MMCenturyNew-Regular", "MMCenturyOldGreek"]
    assert info["descent_pt"] == 3.0  # matches plugin Default Baseline (-1.058 mm) measured live
    assert eps.inspect_eps_text(REAL_HEADER.replace("\n", "\r")) == info  # CR-only files as MathMagic writes them


def test_png_writer(tmp_path):
    out = tmp_path / "x.png"
    w.write_png(str(out), 2, 1, bytes([0, 0, 255, 0, 255, 0, 0, 0]))
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (2, 1)
    idat = data.index(b"IDAT")
    length = struct.unpack(">I", data[idat - 4:idat])[0]
    # BGRA (0,0,255) is red, (255,0,0) is blue -> filter byte 0, then RGB 255,0,0 and 0,0,255
    assert zlib.decompress(data[idat + 4:idat + 4 + length]) == bytes([0, 255, 0, 0, 0, 0, 255])


def test_type_chars_uses_utf16_units(monkeypatch):
    sent = []
    monkeypatch.setattr(w, "send_timeout", lambda h, m, wp, lp, t=3000: sent.append((m, wp)) or True)
    assert w.type_chars(1, "ğ𝑥")
    assert [wp for _, wp in sent] == [0x011F, 0xD835, 0xDC65]
    assert all(m == w.WM_CHAR for m, _ in sent)


def test_focus_recorder_detects_change():
    seq = iter([{"hwnd": 1, "exe": "claude.exe", "title": "Claude"}, {"hwnd": 1, "exe": "claude.exe"},
                {"hwnd": 2, "exe": "InDesign.exe", "title": "doc"}])
    rec = w.FocusRecorder(lambda: next(seq))
    rec.sample(); s = rec.summary()
    assert s["foreground_changed"] and "InDesign.exe" in s["foreground_changes"][0]
    assert s["took_focus_from_user"] is True


def test_focus_recorder_mathmagic_internal_dialog_is_not_stealing():
    seq = iter([{"hwnd": 5, "exe": "MathMagic Pro 9.31 InD.exe", "title": "From InDesign"},
                {"hwnd": 6, "exe": "MathMagic Pro 9.31 InD.exe", "title": "Save As"},
                {"hwnd": 5, "exe": "MathMagic Pro 9.31 InD.exe", "title": "From InDesign"}])
    rec = w.FocusRecorder(lambda: next(seq))
    rec.sample(); s = rec.summary()
    assert s["foreground_changed"] and not s["foreground_process_changed"] and not s["took_focus_from_user"]


# ---------------------------------------------------------------- JSX generation
def test_jsx_is_fixed_and_escaped():
    js = ib.jsx_select_marker("Doc \"x\".indd", "[[MM:Q1]]")
    assert '"Doc \\"x\\".indd"' in js and "function __j(" in js
    place = ib.jsx_place_eps("D.indd", "[[MM:Q1]]", r"C:\a b\c.eps", True, True, False, None)
    assert '"C:/a b/c.eps"' in place and "var d=null" in place
    assert "512525" in place and "anchorYoffset" in place


# ---------------------------------------------------------------- pipeline with fakes
class FakeFocus:
    def sample(self):
        pass

    def summary(self):
        return {"foreground_changed": False, "foreground_changes": [], "took_focus_from_user": False}


class FakeIDC:
    def __init__(self, equation_after=None):
        self.calls = []
        self.equation_after = equation_after or {"link": "EQ-1.eps", "placeholder": False, "edit_equation_enabled": True}

    def running(self):
        return True

    def run(self, script, timeout=30):
        self.calls.append(script)
        return json.loads(script)


@pytest.fixture
def fake_jsx(monkeypatch):
    responses = {
        "status": {"ok": True, "documents": [{"name": "T.indd", "path": "C:/t/T.indd"}], "active": "T.indd", "actions": []},
        "select": {"ok": True, "new_equation_enabled": True},
        "invoke": {"ok": True},
        "eq": {"ok": True, "marker_count": 1, "equation": {"link": "EQ-1.eps", "placeholder": False, "edit_equation_enabled": True}},
        "remove": {"ok": True},
    }
    monkeypatch.setattr(pl.ib, "jsx_status", lambda *a: json.dumps(responses["status"]))
    monkeypatch.setattr(pl.ib, "jsx_documents", lambda *a: json.dumps(responses["status"]))
    monkeypatch.setattr(pl.ib, "jsx_select_marker", lambda *a: json.dumps(responses["select"]))
    monkeypatch.setattr(pl.ib, "jsx_invoke", lambda *a: json.dumps(responses["invoke"]))
    monkeypatch.setattr(pl.ib, "jsx_equation_at_marker", lambda *a, **k: json.dumps(responses["eq"]))
    monkeypatch.setattr(pl.ib, "jsx_remove_marker", lambda *a: json.dumps(responses["remove"]))
    return responses


class FakeMM:
    def __init__(self, license_block=False):
        self.license_block = license_block
        self.ops = []

    def status(self):
        return {"running": True}

    def guard_dialogs(self, auto_ack=True):
        if self.license_block:
            raise mmwin.MathMagicError("LICENSE_REQUIRED", "license")
        return []

    def all_documents(self):
        return []

    def wait_linked_document(self, before, timeout=20, on_tick=None, acks=None):
        self.ops.append("wait_linked")
        if acks is not None:
            acks.append({"acknowledged": "font_warning"})
        return mmwin.Document(10, 11, "From InDesign: T.indd-1", 9)

    def ensure_keeper(self, doc, on_tick=None):
        self.ops.append("keeper")
        return True

    def write_latex(self, doc, latex, replace=True):
        self.ops.append(("write", latex, replace))

    def update_linked(self, doc, timeout=20, on_tick=None, acks=None):
        self.ops.append("update")


def make_pipeline(tmp_path, mm=None):
    return pl.Pipeline("C:/x/MathMagic.exe", str(tmp_path / "logs"), mm=mm or FakeMM(), idc=FakeIDC(),
                       focus_factory=FakeFocus, sleep=lambda s: None)


def test_create_plugin_flow(tmp_path, fake_jsx):
    p = make_pipeline(tmp_path)
    r = p.create_plugin(r"\frac{2}{3}", "[[MM:Q1]]", remove_marker=True)
    assert r["ok"] and r["status"] == "INSERTED_VERIFIED" and r["marker_removed"]
    assert p.mm.ops == ["wait_linked", "keeper", ("write", r"\frac{2}{3}", True), "update"]
    assert r["keeper_document_created"] is True
    assert r["acknowledged_dialogs"] == [{"acknowledged": "font_warning"}]
    log = next((tmp_path / "logs").glob("*.jsonl")).read_text(encoding="utf-8")
    assert "frac" not in log and "latex_sha256" in log  # audit log never stores raw LaTeX


def test_create_plugin_license_block(tmp_path, fake_jsx):
    p = make_pipeline(tmp_path, FakeMM(license_block=True))
    r = p.create_plugin("x", "[[MM:Q1]]")
    assert not r["ok"] and r["status"] == "LICENSE_REQUIRED"


def test_create_plugin_unverified_keeps_marker(tmp_path, fake_jsx):
    fake_jsx["eq"]["equation"]["placeholder"] = True
    p = make_pipeline(tmp_path)
    r = p.create_plugin("x", "[[MM:Q1]]", remove_marker=True)
    assert not r["ok"] and r["status"] == "UPDATE_SENT_NOT_VERIFIED" and not r["marker_removed"]


def test_batch_budget_and_stop(tmp_path, monkeypatch):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"equations": [{"marker": f"[[MM:Q{i}]]", "latex": "x"} for i in range(5)]}))
    p = make_pipeline(tmp_path)
    outcomes = iter([True, True, False, True, True])
    monkeypatch.setattr(p, "create_offline", lambda *a, **k: {"ok": next(outcomes), "status": "S", "seconds": 0.1, "focus": {}})
    r = p.batch(str(m), "offline")
    assert r["processed"] == 3 and r["succeeded"] == 2 and r["next_index"] == 3 and not r["ok"]
    r2 = p.batch(str(m), "offline", start_index=3, stop_on_error=True)
    assert r2["next_index"] is None and r2["succeeded"] == 2


# ---------------------------------------------------------------- server registry / stdio
def test_server_never_loads_keyboard_adapter():
    code = ("import sys; sys.path.insert(0, r'%s'); import server_pro; "
            "print(sorted(server_pro.TOOLS)); print('windows_ui' in ' '.join(sys.modules))" % ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    names, loaded = out.stdout.strip().splitlines()
    assert "mathmagic_create_equation" in names and "mathmagic_run_batch" in names
    assert loaded == "False"


def test_stdio_dry_runs():
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "mathmagic_create_equation",
                                                                          "arguments": {"latex": r"\frac{1}{2}", "marker": "[[MM:Q1]]"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "mathmagic_policy", "arguments": {}}},
    ]
    p = subprocess.run([sys.executable, "-u", str(ROOT / "server_pro.py")], input="\n".join(map(json.dumps, reqs)) + "\n",
                       capture_output=True, text=True, timeout=60)
    msgs = [json.loads(x) for x in p.stdout.splitlines()]
    assert msgs[0]["result"]["serverInfo"]["version"] == "0.3.0"
    assert len(msgs[1]["result"]["tools"]) == 19
    assert json.loads(msgs[2]["result"]["content"][0]["text"])["dry_run"] is True
    assert "clipboard" in msgs[3]["result"]["content"][0]["text"]
