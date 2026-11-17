"""v0.4 unit tests (no live MathMagic/InDesign needed; Win32 and COM are faked)."""
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mathmagic_mcp import eps, idbridge as ib, latexcheck, mmwin, pipeline as pl, style, synclock, win32util as w  # noqa: E402

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
STYLE = "\r".join(["\\INFORMATION", "{", "\\DATE(11, 16, 2026, 19:40:17)", "}", "\\SETTING", "{", "\\SSNAME(User Setting)",
                   "\\st(0,Helvetica Neue, 0)", "\\st(1,Helvetica Neue, 0)", "\\st(2,Helvetica Neue, 0)", "\\st(3,MMGreek, 0)",
                   "\\st(4,MMGreek, 0)", "\\st(5,Helvetica Neue, 1)", "\\st(6,Helvetica Neue, 0)", "\\st(7,Helvetica Neue, 0)",
                   "\\st(8,Courier New, 0)", "\\st(12,Helvetica Neue, 0)", "\\sz(0,2,12)", "\\sz(1,1,70)", "\\sp(0,1,0)", "}"])


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
    p.write_text(json.dumps({"equations": [{"marker": f"[[MM:Q{i}]]", "latex": "x"} for i in range(3000)]}))
    assert len(pl.read_manifest(str(p))) == 3000
    p.write_text(json.dumps({"equations": [{"marker": "[[MM:A]]", "latex": "x", "size_pt": 2}]}))
    with pytest.raises(ValueError, match="size_pt"):
        pl.read_manifest(str(p))


# ---------------------------------------------------------------- dialogs / commands / formats
@pytest.mark.parametrize("title,texts,combo,lst,kind", [
    ("Authorization", ["License Code:"], False, False, "license"),
    ("Tip of the Day", [], False, False, "tip"),
    ("MathMagic Pro", ["Tamam", "Helvetica Neue\n\nCould not get the PostScript name from a font"], False, False, "font_warning"),
    ("Save As", ["&Kaydet"], True, False, "save_as"),
    ("StyleSet", ["Apply"], False, True, "styleset"),
    ("MathMagic Pro", ["Save changes to Equation-1?"], False, False, "save_changes"),
    ("Equation Preferences", ["Define Style"], False, False, "unknown"),
    ("MathMagic Pro", ["Tamam", "Saving PDF file failed : Error No.= 3 \n\n (Font file not found for the specified PS Font name.)"],
     False, False, "error_box"),
])
def test_classify_dialog(title, texts, combo, lst, kind):
    assert mmwin.classify_dialog(title, texts, combo, lst) == kind


def test_single_ok_message_box_is_error_box():
    assert mmwin.classify_dialog("MathMagic Pro", ["Tamam", "Encountered an improper argument."], buttons=["Tamam"]) == "error_box"
    assert mmwin.classify_dialog("MathMagic Pro", ["Something happened"], buttons=["Tamam"]) == "error_box"
    assert mmwin.classify_dialog("MathMagic Pro", ["Proceed?"], buttons=["&Yes", "&No"]) == "unknown"
    assert mmwin.classify_dialog("Other App", ["x"], buttons=["OK"]) == "unknown"


def test_size_commands():
    assert mmwin.size_commands(9) == [32865]
    assert mmwin.size_commands(9.5) == [32865] + [mmwin.SIZE_PLUS_01] * 5
    assert mmwin.size_commands(13) == [32868] + [mmwin.SIZE_PLUS_01] * 10
    for bad in (3, 80):
        with pytest.raises(ValueError):
            mmwin.size_commands(bad)


def test_format_keyword():
    assert mmwin.format_keyword("a.eps") == "MathMagic EPS"
    assert mmwin.format_keyword("a.SVG") == "SVG"
    assert mmwin.format_keyword("a.mml") == "MathML"
    assert mmwin.format_keyword("a.tex") == "LaTeX" and mmwin.format_keyword("a.tex", ams=True) == "AMS LaTeX"
    with pytest.raises(ValueError):
        mmwin.format_keyword("a.docx")


@pytest.mark.parametrize("path,cid,cls", [
    ("Edit > Convert TeX to equation\tShift+return", 32922, "used_by_mcp"),
    ("Edit > Copy As LaTeX", 32925, "excluded_clipboard"),
    ("Style > Define Style...\tCtrl+Shift+5", 32811, "dialog_only"),
    ("Style > Variable", 32780, "message_safe_available"),
    ("Help > Enter Authorization code...", 32845, "excluded_external_or_license"),
    ("View > 300%\tCtrl+3", 32851, "ui_only_not_needed"),
])
def test_classify_command(path, cid, cls):
    assert mmwin.classify_command(path, cid) == cls


class DialogMM(mmwin.MathMagicWindows):
    def __init__(self, dialogs):
        super().__init__("C:/x/MathMagic.exe", sleep=lambda s: None)
        self._d = dialogs

    def dialogs(self):
        return self._d


def test_strict_guard_stops_on_unexpected_dialog(monkeypatch):
    monkeypatch.setattr(w, "post", lambda *a: True)
    mm = DialogMM([mmwin.Dialog(1, 2, "Equation Preferences", ["Define Style"])])
    assert mm.guard_dialogs(strict=False) == []
    with pytest.raises(mmwin.MathMagicError) as e:
        mm.guard_dialogs(strict=True)
    assert e.value.status == "UNEXPECTED_DIALOG"
    ok = DialogMM([mmwin.Dialog(3, 2, "Save As", ["&Kaydet"], True)])
    assert ok.guard_dialogs(strict=True, allowed=("save_as",)) == []
    lic = DialogMM([mmwin.Dialog(4, 2, "Authorization", ["Try"])])
    with pytest.raises(mmwin.MathMagicError, match="Authorization"):
        lic.guard_dialogs()


# ---------------------------------------------------------------- style files
def test_style_parse_and_build():
    info = style.parse_style(STYLE)
    assert info["base_size_pt"] == 12 and info["slots"]["variable"] == {"font": "Helvetica Neue", "face": "plain"}
    new = style.build_style(STYLE, "Kitap 9pt", font="Times New Roman", size_pt=9, variable_italic=True)
    out = style.parse_style(new)
    assert out["name"] == "Kitap 9pt" and out["base_size_pt"] == 9
    assert out["slots"]["text"]["font"] == "Times New Roman"
    assert out["slots"]["variable"] == {"font": "Times New Roman", "face": "italic"}
    assert out["slots"]["vector"] == {"font": "Times New Roman", "face": "bold"}
    assert out["slots"]["greek_lc"]["font"] == "MMGreek" and out["slots"]["user1"]["font"] == "Helvetica Neue"
    assert "\\st(12,Times New Roman, 2)" in new and "\\sz(1,1,70)" in new and "\n" not in new
    for bad in ({"name": "a/b"}, {"name": "ok", "size_pt": 2}, {"name": "ok", "font": "Bad,Font"}):
        with pytest.raises(ValueError):
            style.build_style(STYLE, **bad)


def test_font_installed_matching():
    fonts = {"times new roman", "times new roman bold", "helvetica neue light"}
    assert style.font_installed("Times New Roman", fonts)
    assert style.font_installed("Helvetica Neue", fonts)
    assert not style.font_installed("Garamond", fonts)


# ---------------------------------------------------------------- latex check / eps / png
def test_latex_check():
    doc = "% MathMagic\n\\documentclass{article}\n\\begin{document}\n$$\\frac{a}{b}+x^{2}$$\n\\end{document}\n"
    assert latexcheck.compare(r"\frac{a}{b}+x^2", doc)["verdict"] == "EQUIVALENT"
    assert latexcheck.compare(r"\frac{a}{b}+x^{2}", doc)["verdict"] == "EXACT"
    assert latexcheck.compare(r"\frac{a}{c}+x^2", doc)["verdict"] == "DIFFERENT"
    assert latexcheck.compare(r"\sqrt{x}", "\\[ \\sqrt{x} \\]")["verdict"] == "EXACT"
    # real MathMagic 9.31 export (live, 17.11.2026): every token braced, variables as \mathrm, MMF comment
    real = ("\\documentclass[12pt]{article}\r\\begin{document}\r$\r%Translator MathMagic Pro Win v9.31, LaTeX converter\r"
            "\\frac{{a}{+}{b}}{{c}{-}{d}}{+}{\\mathrm{x}}^{2}\r%MathMagic MMF.7h^O4P00QES.mmf\r$\r\\end{document}\r")
    assert latexcheck.extract_math(real) == "\\frac{{a}{+}{b}}{{c}{-}{d}}{+}{\\mathrm{x}}^{2}"
    assert latexcheck.compare(r"\frac{a+b}{c-d}+x^2", real)["verdict"] == "EQUIVALENT"
    assert latexcheck.compare(r"\frac{a}{b+c-d}+x^2", real)["verdict"] == "DIFFERENT"
    assert latexcheck.normalise(r"\frac{12}{3}") != latexcheck.normalise(r"\frac{1}{23}")


# live MathMagic exports (17.11.2026) -> expected verdicts
@pytest.mark.parametrize("typed,exported,verdict", [
    (r"\int_0^1 x^2\,dx", r"{\mathop{\int}\nolimits_{0}\nolimits^{1}{\mathrm{x}}}^{2}\,{\mathrm{dx}}", "DIFFERENT"),
    (r"\int_0^1 {x^2}\,dx", r"\mathop{\int}\nolimits_{0}\nolimits^{1}{{\mathrm{x}}^{2}}\,{\mathrm{dx}}", "EQUIVALENT"),
    (r"\sum_{k=1}^{n} k^2", r"{\mathop{\sum}\nolimits_{{\mathrm{k}}{=}{1}}\nolimits^{\mathrm{n}}{\mathrm{k}}}^{2}", "DIFFERENT"),
    (r"\sqrt[3]{27}=3", r"\sqrt[3]{27}{=}{3}", "EQUIVALENT"),
    (r"|x-3|<5", r"{|}{\mathrm{x}}{-}{3}{|}{<}{5}", "EQUIVALENT"),
    (r"\sqrt{x^2+9}", r"\sqrt{{x}^{2}{+}{9}}", "EQUIVALENT"),
    ("(a+b)^2", r"{\left({a}{+}{b}\right)}^{2}", "EQUIVALENT"),
    (r"\frac{a+b}{c-d}", r"\frac{{a}{+}{b}}{{c}{-}{d}}", "EQUIVALENT"),
    (r"\sqrt[3]{27}=3", r"\mbox{\Large $\sqrt[3]{27}$}{=}{3}", "EQUIVALENT"),
    (r"\frac{a}{b}+x^2", r"\mbox{\Large $\frac{a}{b}$}{+}{x}^{2}", "EQUIVALENT"),
    (r"\frac{a}{b}+x^2", r"\mbox{\Large $\frac{a}{c}$}{+}{x}^{2}", "DIFFERENT"),
    ("(a+b)^2=a^2+2ab+b^2", r"{(}{\mathrm{a}}{+}{\mathrm{b}}{)}^{2}{=}{\mathrm{a}}^{2}{+}{2}{\mathrm{ab}}{+}{\mathrm{b}}^{2}", "EQUIVALENT"),
    (r"\dfrac{12}{18}", r"\mbox{\Large $\frac{12}{18}$}", "EQUIVALENT"),        # live, soru bankasi E2E
    (r"\dfrac{12}{18}", r"\mbox{\Large $\frac{12}{17}$}", "DIFFERENT"),
    (r"\tbinom{n}{k}", r"\binom{n}{k}", "EQUIVALENT"),
])
def test_live_export_verdicts(typed, exported, verdict):
    assert latexcheck.compare(typed, "$" + exported + "$")["verdict"] == verdict


@pytest.mark.parametrize("src,fixed", [
    (r"\int_0^1 x^2\,dx", r"\int_0^1 {x^2}\,dx"),
    (r"\sum_{k=1}^{n} k^2", r"\sum_{k=1}^{n} {k^2}"),
    (r"\int_0^1 {x^2}\,dx", r"\int_0^1 {x^2}\,dx"),
    (r"\lim_{x\to 0} x_n^2", r"\lim_{x\to 0} {x_n^2}"),
    (r"\int_0^1 2x\,dx", r"\int_0^1 2x\,dx"),
    (r"\frac{a}{b}+x^2", r"\frac{a}{b}+x^2"),
    (r"\sum_{i=1}^{n} (i+1)^2", r"\sum_{i=1}^{n} {(i+1)^2}"),
])
def test_fix_mathmagic_quirks(src, fixed):
    assert latexcheck.fix_mathmagic_quirks(src)[0] == fixed


def test_eps_header_and_descent():
    info = eps.inspect_eps_text(REAL_HEADER)
    assert info["is_mathmagic"] and info["has_mmf_data"]
    assert info["fonts"] == ["MMCenturyNew-Regular", "MMCenturyOldGreek"]
    assert info["descent_pt"] == 3.0
    assert eps.inspect_eps_text(REAL_HEADER.replace("\n", "\r")) == info


def test_png_writer(tmp_path):
    out = tmp_path / "x.png"
    w.write_png(str(out), 2, 1, bytes([0, 0, 255, 0, 255, 0, 0, 0]))
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == (2, 1)
    idat = data.index(b"IDAT"); length = struct.unpack(">I", data[idat - 4:idat])[0]
    assert zlib.decompress(data[idat + 4:idat + 4 + length]) == bytes([0, 255, 0, 0, 0, 0, 255])


def test_utf16_units_and_post_chars(monkeypatch):
    sent = []
    monkeypatch.setattr(w, "post", lambda h, m, wp=0, lp=0: sent.append((m, wp)) or True)
    assert w.post_chars(1, "ğ𝑥")
    assert [wp for _, wp in sent] == [0x011F, 0xD835, 0xDC65] and all(m == w.WM_CHAR for m, _ in sent)


def test_focus_recorder():
    seq = iter([{"hwnd": 1, "exe": "claude.exe", "title": "Claude"}, {"hwnd": 1, "exe": "claude.exe"},
                {"hwnd": 2, "exe": "InDesign.exe", "title": "doc"}])
    rec = w.FocusRecorder(lambda: next(seq)); rec.sample(); s = rec.summary()
    assert s["foreground_changed"] and s["took_focus_from_user"]
    seq2 = iter([{"hwnd": 5, "exe": "MathMagic Pro 9.31 InD.exe"}, {"hwnd": 6, "exe": "MathMagic Pro 9.31 InD.exe"},
                 {"hwnd": 5, "exe": "MathMagic Pro 9.31 InD.exe"}])
    rec2 = w.FocusRecorder(lambda: next(seq2)); rec2.sample(); s2 = rec2.summary()
    assert s2["foreground_changed"] and not s2["took_focus_from_user"]
    # live E2E: the user Alt+Tabs between their own apps -> not "taken", reported as user_switched_apps
    seq3 = iter([{"hwnd": 7, "exe": "explorer.exe", "title": "Görev Geçişi"}, {"hwnd": 8, "exe": "chrome.exe"},
                 {"hwnd": 7, "exe": "explorer.exe"}, {"hwnd": 7, "exe": "explorer.exe"}])
    rec3 = w.FocusRecorder(lambda: next(seq3)); rec3.sample(); rec3.sample(); s3 = rec3.summary()
    assert s3["user_switched_apps"] and not s3["took_focus_from_user"]


def test_wait_modifiers_released(monkeypatch):
    states = iter([["alt"], ["alt"], []])
    monkeypatch.setattr(w, "modifiers_down", lambda: next(states))
    r = w.wait_modifiers_released(timeout=2, poll=0.001)
    assert r["released"] and r["held"] == ["alt"]
    monkeypatch.setattr(w, "modifiers_down", lambda: ["ctrl"])
    r = w.wait_modifiers_released(timeout=0.02, poll=0.005)
    assert not r["released"] and r["held"] == ["ctrl"]


# ---------------------------------------------------------------- lock
def test_cross_process_lock(tmp_path):
    lock = tmp_path / "x.lock"
    with synclock.exclusive("first", path=lock):
        code = ("import sys; sys.path.insert(0, r'%s'); from mathmagic_mcp import synclock; from pathlib import Path\n"
                "try:\n  with synclock.exclusive('second', timeout=0.5, path=Path(r'%s')): print('ACQUIRED')\n"
                "except synclock.LockBusy: print('BUSY')" % (ROOT, lock))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        assert out.stdout.strip() == "BUSY", out.stderr
    with synclock.exclusive("again", timeout=0.5, path=lock):
        pass


# ---------------------------------------------------------------- JSX generation
def test_jsx_is_fixed_escaped_and_undoable():
    js = ib.jsx_select_marker("Doc \"x\".indd", "[[MM:Q1]]")
    assert '"Doc \\"x\\".indd"' in js and "function __j(" in js
    place = ib.jsx_place_eps("D.indd", "[[MM:Q1]]", r"C:\a b\c.eps", True, True, False, None, {"id": "Q1", "latex": 'a"b'})
    assert '"C:/a b/c.eps"' in place and "UndoModes.ENTIRE_SCRIPT" in place and '"MathMagic MCP [[MM:Q1]]"' in place
    assert '"latex": "a\\"b"' in place and "EmptyEquation.eps" in place
    assert "\\d{4}-\\d{6}" in ib.jsx_list_equations("D.indd")


# ---------------------------------------------------------------- pipeline with fakes
class FakeFocus:
    def sample(self):
        pass

    def summary(self):
        return {"foreground_changed": False, "foreground_changes": [], "took_focus_from_user": False}


class FakeIDC:
    def __init__(self):
        self.calls = []

    def running(self):
        return True

    def run(self, script, timeout=30):
        self.calls.append(script)
        return json.loads(script)


@pytest.fixture
def fake_jsx(monkeypatch):
    r = {"docs": {"ok": True, "documents": [{"name": "T.indd", "path": "C:/t/T.indd"}], "active": "T.indd"},
         "select": {"ok": True, "new_equation_enabled": True}, "invoke": {"ok": True},
         "eq": {"ok": True, "marker_count": 1, "equation": {"link": "EQ-1.eps", "placeholder": False, "edit_equation_enabled": True,
                                                              "labels": {}}},
         "ok": {"ok": True}}
    for name, key in (("jsx_status", "docs"), ("jsx_documents", "docs"), ("jsx_select_marker", "select"), ("jsx_invoke", "invoke"),
                      ("jsx_equation_at_marker", "eq"), ("jsx_remove_marker", "ok"), ("jsx_tag_at_marker", "ok"),
                      ("jsx_save_document", "ok")):
        monkeypatch.setattr(pl.ib, name, (lambda k: (lambda *a, **kw: json.dumps(r[k])))(key))
    return r


class FakeMM:
    def __init__(self, license_block=False):
        self.license_block = license_block
        self.ops = []

    def status(self):
        return {"running": True}

    def guard_dialogs(self, auto_ack=True, strict=False, allowed=()):
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
        self.ops.append("keeper"); return True

    def queue_latex(self, doc, latex, size_pt=None):
        self.ops.append(("queue", latex, size_pt))

    def update_linked(self, doc, timeout=20, on_tick=None, acks=None):
        self.ops.append("update")


def make_pipeline(tmp_path, mm=None):
    return pl.Pipeline("C:/x/MathMagic.exe", str(tmp_path / "logs"), mm=mm or FakeMM(), idc=FakeIDC(),
                       focus_factory=FakeFocus, sleep=lambda s: None)


def test_create_plugin_flow_labels_and_audit(tmp_path, fake_jsx):
    p = make_pipeline(tmp_path)
    r = p.create_plugin(r"\frac{2}{3}", "[[MM:Q1]]", remove_marker=True, size_pt=9)
    assert r["ok"] and r["status"] == "INSERTED_VERIFIED" and r["marker_removed"] and r["keeper_document_created"]
    assert p.mm.ops == ["wait_linked", "keeper", ("queue", r"\frac{2}{3}", 9), "update"]
    log = next((tmp_path / "logs").glob("*.jsonl")).read_text(encoding="utf-8")
    assert "frac" not in log and "latex_sha256" in log


def test_create_plugin_license_block(tmp_path, fake_jsx):
    r = make_pipeline(tmp_path, FakeMM(license_block=True)).create_plugin("x", "[[MM:Q1]]")
    assert not r["ok"] and r["status"] == "LICENSE_REQUIRED" and "hint" in r


def test_create_plugin_unverified_keeps_marker(tmp_path, fake_jsx):
    fake_jsx["eq"]["equation"]["placeholder"] = True
    r = make_pipeline(tmp_path).create_plugin("x", "[[MM:Q1]]", remove_marker=True)
    assert not r["ok"] and r["status"] == "UPDATE_SENT_NOT_VERIFIED" and not r.get("marker_removed")


def test_batch_skip_existing_journal_and_stop(tmp_path, fake_jsx, monkeypatch):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"equations": [{"marker": f"[[MM:Q{i}]]", "latex": f"x{i}"} for i in range(5)]}))
    p = make_pipeline(tmp_path)
    fake_jsx["eq"]["equation"] = None  # no equations yet
    outcomes = iter([True, True, False, True, True])
    monkeypatch.setattr(p, "create_offline", lambda *a, **k: {"ok": next(outcomes), "status": "S", "seconds": 0.1, "focus": {}})
    r = p.batch(str(m), "offline", eps_dir=str(tmp_path / "eps"))
    assert (r["processed"], r["failed"], r["next_index"], r["ok"]) == (3, 1, 3, False)
    journal = (tmp_path / "m.progress.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(journal) == 3 and json.loads(journal[0])["sha"] == pl._sha("x0")
    # second run: marker 3 already holds an equation with the same sha -> skipped, no rendering
    fake_jsx["eq"]["equation"] = {"link": "Q3.eps", "placeholder": False, "labels": {"sha": pl._sha("x3")}}
    r2 = p.batch(str(m), "offline", start_index=3, eps_dir=str(tmp_path / "eps"))
    assert r2["skipped"] == 2 and r2["next_index"] is None


def test_batch_relaunches_once(tmp_path, fake_jsx, monkeypatch):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"equations": [{"marker": "[[MM:Q1]]", "latex": "x"}]}))
    fake_jsx["eq"]["equation"] = None
    p = make_pipeline(tmp_path)
    seq = iter([{"ok": False, "status": "MATHMAGIC_NOT_READY"}, {"ok": True, "status": "INSERTED_VERIFIED", "seconds": 1}])
    monkeypatch.setattr(p, "create_offline", lambda *a, **k: next(seq))
    p.mm.launch_no_activate = lambda: {"ok": True, "status": "READY"}
    r = p.batch(str(m), "offline", eps_dir=str(tmp_path / "eps"))
    assert r["ok"] and r["inserted"] == 1 and r["mathmagic_relaunches"] == 1


# ---------------------------------------------------------------- server registry / stdio
def test_server_never_loads_keyboard_adapter():
    code = ("import sys; sys.path.insert(0, r'%s'); import server_pro; "
            "print(len(server_pro.TOOLS)); print('windows_ui' in ' '.join(sys.modules))" % ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    count, loaded = out.stdout.strip().splitlines()
    assert int(count) == 27 and loaded == "False"


def test_stdio_dry_runs():
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "mathmagic_create_equation",
                                                                          "arguments": {"latex": r"\frac{1}{2}", "marker": "[[MM:Q1]]", "size_pt": 9}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "mathmagic_policy", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "mathmagic_export_equation",
                                                                          "arguments": {"latex": "x", "out_path": "C:/t/a.svg"}}},
    ]
    p = subprocess.run([sys.executable, "-u", str(ROOT / "server_pro.py")], input="\n".join(map(json.dumps, reqs)) + "\n",
                       capture_output=True, text=True, timeout=60)
    msgs = [json.loads(x) for x in p.stdout.splitlines()]
    assert msgs[0]["result"]["serverInfo"]["version"] == "0.4.1"
    assert "Never use Windows MCP" in msgs[0]["result"]["instructions"]
    assert len(msgs[1]["result"]["tools"]) == 27
    created = json.loads(msgs[2]["result"]["content"][0]["text"])
    assert created["dry_run"] is True and created["size_pt"] == 9
    assert "clipboard" in msgs[3]["result"]["content"][0]["text"]
    assert json.loads(msgs[4]["result"]["content"][0]["text"])["format"] == "SVG"


# ---------------------------------------------------------------- empty render retry (live E2E 2026-11-17)
class FakeRenderMM:
    """First Save As yields an empty equation (no fonts, empty LaTeX), like characters lost while the user held Alt."""
    def __init__(self, empty_times=1):
        self.empty_times = empty_times
        self.saves = 0
        self.ops = []

    def ensure_ready(self, prefer_linked=False, auto_launch=True):
        return "main"

    def work_document(self, main, on_tick=None):
        return mmwin.Document(1, 2, "Equation-1", 3)

    def queue_latex(self, doc, latex, size_pt=None):
        self.ops.append(("queue", latex))

    def save_as(self, doc, path, keyword, on_tick=None, acks=None):
        empty = self.saves // 2 < self.empty_times      # two saves (EPS + LaTeX) per attempt
        self.saves += 1
        if keyword == "LaTeX":
            Path(path).write_text("$\n%Translator MathMagic\n" + ("" if empty else r"\frac{1}{2}") + "\n$", encoding="utf-8")
        else:
            header = REAL_HEADER.replace("%%DocumentFonts: MMCenturyNew-Regular\n%%+ MMCenturyOldGreek\n", "") if empty else REAL_HEADER
            Path(path).write_text(header, encoding="latin-1")


def test_render_retries_empty_equation_once(tmp_path):
    mm = FakeRenderMM(empty_times=1)
    p = make_pipeline(tmp_path, mm)
    p.wait_keys = lambda: {"waited_s": 0.4, "held": ["alt"], "released": True}
    r = p.render(r"\frac{1}{2}", str(tmp_path / "a.eps"), verify_latex=True)
    assert r["ok"] and r["status"] == "RENDERED" and r["empty_render_retries"] == 1
    assert r["user_modifier_keys_waited"] == {"keys": ["alt"], "seconds": 0.8}
    assert [o for o in mm.ops if o[0] == "queue"] == [("queue", r"\frac{1}{2}")] * 2


def test_render_reports_empty_render_after_retry(tmp_path):
    p = make_pipeline(tmp_path, FakeRenderMM(empty_times=5))
    p.wait_keys = lambda: {"waited_s": 0.0, "held": [], "released": True}
    r = p.render(r"\frac{1}{2}", str(tmp_path / "b.eps"), verify_latex=False)
    assert not r["ok"] and r["status"] == "EMPTY_RENDER" and r["empty_render_retries"] == 1
