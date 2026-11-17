"""LaTeX content QA for MathMagic conversions.

1. fix_mathmagic_quirks(): MathMagic 9.31 binds a script after a large operator's operand to the whole
   operator group (\\int_0^1 x^2 dx -> {\\int_0^1 x}^2 dx, \\sum_k k^2 -> {\\sum_k k}^2; verified live).
   Wrapping the operand+script in braces (\\int_0^1 {x^2} dx) converts correctly (verified live).
2. compare(): MathMagic's LaTeX export (every token braced, variables as \\mathrm, \\mathop{\\int}\\nolimits ...)
   is parsed into a small structure tree and compared with the typed LaTeX. Meaningless braces and font
   commands are ignored, while fractions, roots, scripts and script bases are compared structurally:
   x^2 == {x}^{2}, but {\\int x}^2 != \\int x^2.
"""
from __future__ import annotations

import re

_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)
_BODY = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.S)
_ENVS = re.compile(r"\\(?:begin|end)\{(?:equation\*?|displaymath|math|align\*?|gather\*?)\}")
LARGE_OPS = {"int", "iint", "iiint", "oint", "sum", "prod", "coprod", "bigcup", "bigcap", "bigoplus", "bigotimes",
             "bigvee", "bigwedge", "lim", "max", "min", "sup", "inf", "limsup", "liminf"}
# Style-only variants: MathMagic exports \dfrac{12}{18} as \mbox{\Large $\frac{12}{18}$} (verified live, v0.4 E2E)
STYLE_ALIASES = {"dfrac": "frac", "tfrac": "frac", "cfrac": "frac", "dbinom": "binom", "tbinom": "binom"}
IGNORED = {"left", "right", "displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle", "limits", "nolimits", ",", ";", ":", "!", " ", "quad", "qquad",
           # size hints MathMagic's exporter adds for non-12pt StyleSets, e.g. \mbox{\Large $\frac{a}{b}$} (verified live)
           "tiny", "scriptsize", "footnotesize", "small", "normalsize", "large", "Large", "LARGE", "huge", "Huge"}
UNWRAP_1 = {"mathrm", "mathit", "mathnormal", "text", "textrm", "mathop", "mbox", "operatorname"}
ARITY = {"frac": 2, "dfrac": 2, "tfrac": 2, "binom": 2, "sqrt": 1, "overline": 1, "underline": 1, "vec": 1, "hat": 1,
         "bar": 1, "mathbf": 1, "boldsymbol": 1, "widehat": 1, "overbrace": 1}
OPENERS = {")": "(", "]": "["}

# ---------------------------------------------------------------- native accents (wide hat / arc)
# MathMagic 9.31's TeX importer cannot build these: \widehat{DEF} silently loses its content (m(\widehat{DEF}) -> m()),
# \wideparen becomes literal text, \overparen raises an error (verified live 2026-11-17). Its native .mmf text format
# writes them as the Over template T(46) with a variable symbol: V(42) = Wide Hat, V(19) = Over Elliptical Arc,
# V(15) = over brace (verified live). The MCP therefore types an \overbrace placeholder, verifies the structure,
# saves the equation as .mmf, swaps V(15) for the wanted symbol and reopens the file in MathMagic.
NATIVE_ACCENTS = {"widehat": 42, "overarc": 19, "wideparen": 19, "overparen": 19}
NATIVE_PLACEHOLDER, NATIVE_PLACEHOLDER_SYMBOL = "overbrace", 15
_NATIVE_RE = re.compile(r"\\(" + "|".join(sorted(NATIVE_ACCENTS, key=len, reverse=True)) + r")(?![A-Za-z])")
_MMF_SYMBOL_RE = re.compile(r"\\V(?:\[[^\]]*\])?\(" + str(NATIVE_PLACEHOLDER_SYMBOL) + r"\)")


class NativeAccentError(ValueError):
    pass


def native_accent_plan(latex: str) -> tuple[str, list[int]] | None:
    """Return (placeholder LaTeX, [MathMagic symbol ids in reading order]) or None when no native accent is used."""
    found = [m.group(1) for m in _NATIVE_RE.finditer(latex)]
    if not found:
        return None
    if re.search(r"\\" + NATIVE_PLACEHOLDER + r"(?![A-Za-z])", latex):
        raise NativeAccentError("\\overbrace cannot be combined with \\widehat/\\overarc in one equation "
                                "(it is the placeholder for the native-accent route)")
    placeholder = _NATIVE_RE.sub(lambda m: "\\" + NATIVE_PLACEHOLDER, latex)
    return placeholder, [NATIVE_ACCENTS[name] for name in found]


def swap_native_symbols(mmf_text: str, symbols: list[int]) -> str:
    """Replace the placeholder symbols in a MathMagic .mmf text, in order, with the wanted variable symbols."""
    matches = list(_MMF_SYMBOL_RE.finditer(mmf_text))
    if len(matches) != len(symbols):
        raise NativeAccentError(f"expected {len(symbols)} placeholder symbol(s) in the .mmf, found {len(matches)}")
    out, last = [], 0
    for m, sym in zip(matches, symbols):
        out.append(mmf_text[last:m.start()])
        out.append(f"\\V({sym})")
        last = m.end()
    out.append(mmf_text[last:])
    return "".join(out)


def extract_math(tex: str) -> str:
    text = _COMMENT.sub("", tex.replace("\r\n", "\n").replace("\r", "\n"))
    body = _BODY.search(text)
    text = body.group(1) if body else text
    text = re.sub(r"\\(?:documentclass|usepackage)(\[[^\]]*\])?\{[^}]*\}", "", text)
    text = _ENVS.sub("", text).strip()
    for left, right in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if text.startswith(left) and text.endswith(right) and len(text) >= len(left) + len(right):
            text = text[len(left):len(text) - len(right)].strip()
            break
    return text


# ---------------------------------------------------------------- quirk fixer
def _arg_end(s: str, k: int) -> int:
    if k >= len(s):
        return k
    pairs = {"{": "}", "(": ")"}
    if s[k] in pairs:
        depth, open_, close = 0, s[k], pairs[s[k]]
        for j in range(k, len(s)):
            depth += (s[j] == open_) - (s[j] == close)
            if depth == 0:
                return j + 1
        return len(s)
    if s[k] == "\\":
        m = re.match(r"\\([A-Za-z]+|.)", s[k:])
        return k + len(m.group(0)) if m else k + 1
    return k + 1


def _scripts_end(s: str, k: int) -> int:
    while k < len(s) and s[k] in "^_":
        k = _arg_end(s, k + 1)
    return k


def fix_mathmagic_quirks(latex: str) -> tuple[str, list[str]]:
    s, out, changes, i = latex, [], [], 0
    while i < len(s):
        m = re.match(r"\\([A-Za-z]+)", s[i:])
        if not (m and m.group(1) in LARGE_OPS):
            j = _arg_end(s, i) if s[i] == "\\" else i + 1
            out.append(s[i:j]); i = j
            continue
        j = i + len(m.group(0))
        lim = re.match(r"\\(?:no)?limits", s[j:])
        if lim:
            j += len(lim.group(0))
        j = _scripts_end(s, j)
        out.append(s[i:j])
        k = j
        while k < len(s) and s[k] == " ":
            k += 1
        if k < len(s) and s[k] not in "^_}+-=<>|,;\\" or (k < len(s) and s[k] == "\\" and not re.match(r"\\[,;:! ]", s[k:])):
            a_end = _arg_end(s, k)
            sc_end = _scripts_end(s, a_end)
            if sc_end > a_end:
                operand = s[k:sc_end]
                out.append(s[j:k] + "{" + operand + "}")
                changes.append(f"{m.group(0)}: {operand} -> {{{operand}}}")
                i = sc_end
                continue
        i = j
    return "".join(out), changes


# ---------------------------------------------------------------- structural comparison
# Digit runs are one atom: MathMagic exports 60^{\circ} as {60}^{\circ} (live) and both typeset identically.
_TOKEN = re.compile(r"\\[A-Za-z]+|\\.|[{}\[\]^_]|\d+|\S")


class _Parser:
    def __init__(self, tex: str):
        self.toks = _TOKEN.findall(tex)
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self):
        tok = self.peek(); self.i += 1; return tok

    def seq(self, stop: str | None = None) -> list:
        nodes: list = []
        while self.peek() is not None and self.peek() != stop:
            tok = self.take()
            if tok in ("^", "_"):
                arg = self.arg()
                base = nodes.pop() if nodes else ("atom", "")
                if base == ("atom", ")") or base == ("atom", "]"):
                    opener = OPENERS[base[1]]
                    j = max((k for k, n in enumerate(nodes) if n == ("atom", opener)), default=None)
                    if j is not None:
                        base = ("group", nodes[j:] + [base]); del nodes[j:]
                nodes.append(("script", base, tok, arg))
            elif tok == "{":
                inner = self.seq("}"); self.take()
                if self.peek() in ("^", "_"):
                    nodes.append(("group", inner) if len(inner) != 1 else inner[0])
                else:
                    nodes.extend(inner)
            else:
                nodes.extend(self.command(tok))
        return nodes

    def arg(self) -> list:
        tok = self.take()
        if tok is None:
            return []
        if tok == "{":
            inner = self.seq("}"); self.take(); return inner
        return self.command(tok)

    def command(self, tok: str) -> list:
        if tok == "$":
            return []
        if not tok.startswith("\\") or len(tok) == 1:
            return [("atom", tok)]
        name = STYLE_ALIASES.get(tok[1:], tok[1:])
        if name in IGNORED:
            return []
        if name in UNWRAP_1:  # font / operator wrappers change appearance, not structure
            return self.arg()
        if name == "sqrt" and self.peek() == "[":
            self.take(); index = self.seq("]"); self.take()
            return [("cmd", "sqrt", [index, self.arg()])]
        if name in ARITY:
            return [("cmd", name, [self.arg() for _ in range(ARITY[name])])]
        return [("atom", tok)]


def _render(nodes: list) -> str:
    out = []
    for n in nodes:
        kind = n[0]
        if kind == "atom":
            out.append(n[1] + (" " if n[1].startswith("\\") else ""))
        elif kind == "group":
            out.append("{" + _render(n[1]) + "}")
        elif kind == "script":
            out.append(_render([n[1]]) + n[2] + "{" + _render(n[3]) + "}")
        elif kind == "cmd":
            out.append("\\" + n[1] + "".join("{" + _render(a) + "}" for a in n[2]))
    return "".join(out).replace(" }", "}").strip()


def canonical(tex: str) -> str:
    return _render(_Parser(tex).seq())


def normalise(tex: str) -> str:  # kept for callers/tests: canonical structural form
    return canonical(tex)


def compare(typed: str, exported_file_text: str) -> dict:
    exported = extract_math(exported_file_text)
    if exported.strip() == typed.strip():
        verdict = "EXACT"
    else:
        try:
            verdict = "EQUIVALENT" if canonical(exported) == canonical(typed) else "DIFFERENT"
        except Exception:  # unparsable -> be conservative
            verdict = "DIFFERENT"
    return {"verdict": verdict, "typed": typed, "exported": exported[:500]}
