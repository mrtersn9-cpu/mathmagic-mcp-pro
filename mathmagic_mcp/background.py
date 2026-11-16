"""Read-only background diagnostics and offline TeX preparation.

Never focuses a window, sends keys, accesses the clipboard or claims a supported
MathMagic API. The original foreground editor automation remains inaccessible in
the safe background MCP entrypoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SAFE_LEGACY_TOOLS = frozenset({
    "mathmagic_preflight", "mathmagic_inspect_indesign",
    "mathmagic_preview_equation", "mathmagic_backup_indd",
    "mathmagic_check_marker", "mathmagic_preview_batch",
})


def filter_safe_legacy_tools(registry: dict) -> dict:
    """Never expose the legacy create/edit/cleanup/batch mutation tools."""
    return {name: spec for name, spec in registry.items() if name in SAFE_LEGACY_TOOLS}


def _foreground_handle() -> int:
    import ctypes
    return int(ctypes.windll.user32.GetForegroundWindow())


def _control_capabilities(window: Any, limit: int = 150) -> dict[str, Any]:
    """Inspect capability flags only; do not read MathMagic/user text."""
    result: dict[str, Any] = {
        "scanned": 0, "truncated": False,
        "value_pattern": 0, "invoke_pattern": 0,
        "text_pattern": 0, "edit_controls": 0,
    }
    controls = window.descendants()
    result["truncated"] = len(controls) > limit
    for control in controls[:limit]:
        result["scanned"] += 1
        info = getattr(control, "element_info", None)
        try:
            if getattr(info, "control_type", "") == "Edit":
                result["edit_controls"] += 1
            element = getattr(info, "element", None)
            for key, attribute in (
                ("value_pattern", "CurrentIsValuePatternAvailable"),
                ("invoke_pattern", "CurrentIsInvokePatternAvailable"),
                ("text_pattern", "CurrentIsTextPatternAvailable"),
            ):
                try:
                    if bool(getattr(element, attribute, False)):
                        result[key] += 1
                except Exception:
                    pass
        except Exception:
            pass
    return result


class BackgroundService:
    """Strict no-focus operations to complement the original v0.1 engine."""

    def __init__(
        self,
        engine: Any,
        platform_name: str | None = None,
        foreground_getter: Callable[[], int] | None = None,
        window_locator: Callable[[], Any] | None = None,
        control_inspector: Callable[[Any], dict] | None = None,
    ):
        self.engine = engine
        self.platform_name = os.name if platform_name is None else platform_name
        self.foreground_getter = foreground_getter or _foreground_handle
        # Lazily resolve the UI adapter: read-only/file operations need no UI.
        self.window_locator = (
            window_locator if window_locator is not None
            else lambda: self.engine.ui._find_window()
        )
        self.control_inspector = control_inspector or _control_capabilities

    def policy(self) -> dict:
        return {
            "ok": True,
            "mode": "STRICT_NO_FOREGROUND",
            "allow_set_focus": False,
            "allow_send_keys": False,
            "allow_clipboard": False,
            "allow_unverified_mathmagic_edit": False,
            "interactive_legacy_tools_exposed": False,
            "actual_background_equation_creation_available": False,
            "reason": "No verified MathMagic 9.31 non-focusing conversion/save API.",
            "next_step": "Inspect UIA in Windows and test separately with a disposable document.",
        }

    def probe(self) -> dict:
        """Read MathMagic UIA capabilities; never move focus or send input."""
        if self.platform_name != "nt":
            return {
                "ok": True, "status": "NOT_WINDOWS",
                "focus_free_proven": False,
                "note": "Requires the user's Windows host for live UIA inspection.",
            }
        if not Path(self.engine.exe).is_file():
            return {
                "ok": False, "status": "MATHMAGIC_EXE_NOT_FOUND",
                "focus_free_proven": False,
            }
        before = self.foreground_getter()
        try:
            window = self.window_locator()
            if window is None:
                return {
                    "ok": True, "status": "EDITOR_WINDOW_NOT_FOUND",
                    "foreground_unchanged_at_samples": (
                        self.foreground_getter() == before
                    ),
                    "focus_free_proven": False,
                    "note": "Open MathMagic manually for the read-only UIA inspection.",
                }
            capabilities = self.control_inspector(window)
        except Exception as exc:
            return {
                "ok": False, "status": "UIA_INSPECTION_FAILED",
                "error_type": type(exc).__name__,
                "focus_free_proven": False,
            }
        after = self.foreground_getter()
        return {
            "ok": True,
            "status": "INSPECTED_NOT_VALIDATED",
            "foreground_unchanged_at_samples": before == after,
            "capabilities": capabilities,
            "focus_free_proven": False,
            "native_equation_save_proven": False,
            "note": "Two foreground samples do not prove uninterrupted focus, or conversion/save.",
        }

    def plan(self, latex: str, mode: str = "create", marker: str = "") -> dict:
        self.engine.validate_latex(latex)
        if mode not in ("create", "edit"):
            raise ValueError("mode must be create or edit")
        if marker:
            self.engine.validate_marker(marker)
            if mode == "edit":
                raise ValueError("Marker-targeted editing is not supported")
        return {
            "ok": True, "dry_run": True,
            "sha256": hashlib.sha256(latex.encode("utf-8")).hexdigest(),
            "length": len(latex), "mode": mode, "marker": marker or None,
            "background_execution": "BLOCKED_UNTIL_VERIFIED",
            "reason": "No verified non-focusing MathMagic equation editor API.",
            "focus_or_input_sent": False,
        }

    def prepare_batch(self, manifest_path: str, output_dir: str, confirm: bool = False) -> dict:
        """Stage .tex text inputs only. Never modify InDesign or MathMagic."""
        jobs = self.engine._read_manifest(manifest_path)
        if not str(output_dir).strip():
            raise ValueError("output_dir must not be blank")
        target_dir = Path(output_dir).expanduser().resolve()
        records = []
        for job in jobs:
            job_id = str(job["id"])
            if not _ID.fullmatch(job_id):
                raise ValueError("job id must match [A-Za-z0-9_-]{1,40}")
            latex = job["latex"]
            records.append({
                "id": job_id,
                "marker": job["marker"],
                "file": f"{job_id}.tex",
                "sha256": hashlib.sha256(latex.encode("utf-8")).hexdigest(),
            })
        files = [r["file"].casefold() for r in records]
        if len(files) != len(set(files)):
            raise ValueError("duplicate job IDs, ignoring case")
        if not confirm:
            return {
                "ok": True, "dry_run": True, "count": len(records),
                "output_dir": str(target_dir), "jobs": records,
                "no_mathmagic_or_indesign_changes": True,
            }
        target_dir.mkdir(parents=True, exist_ok=True)
        targets = [target_dir / r["file"] for r in records] + [target_dir / "index.json"]
        if any(target.exists() for target in targets):
            return {
                "ok": False, "status": "REFUSED_OVERWRITE",
                "note": "Choose an empty staging directory. Existing files were not overwritten.",
            }
        created: list[Path] = []
        try:
            for job, path in zip(jobs, targets):
                with path.open("x", encoding="utf-8", newline="\n") as stream:
                    created.append(path)
                    stream.write(job["latex"] + "\n")
            index = {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "status": "INPUT_ONLY_NOT_RENDERED",
                "jobs": records,
            }
            with targets[-1].open("x", encoding="utf-8") as stream:
                created.append(targets[-1])
                json.dump(index, stream, ensure_ascii=False, indent=2)
        except Exception:
            for path in created:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
        return {
            "ok": True, "status": "INPUT_FILES_PREPARED",
            "count": len(records), "output_dir": str(target_dir),
            "index": str(targets[-1]),
            "native_mathmagic_equations_created": 0,
            "no_mathmagic_or_indesign_changes": True,
            "note": "Staging inputs only; no MathMagic conversion was performed.",
        }
