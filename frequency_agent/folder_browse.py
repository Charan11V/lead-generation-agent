"""Local folder browse + save helpers for Workspace exports.

Works in Docker (host Documents/Downloads/Desktop mounts + in-app navigator)
and on a bare Windows/macOS Python run (tkinter dialog when available).
Also supports Chromium's showDirectoryPicker to write a ZIP into a browsed folder.
"""

from __future__ import annotations

import base64
import html
import os
from pathlib import Path


def default_save_folder(project_root: Path) -> str:
    for candidate in browse_roots(project_root):
        return str(candidate)
    fallback = project_root / "output" / "exports"
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback)


def browse_roots(project_root: Path) -> list[Path]:
    """Writable roots the user can browse (host mounts first, then project exports)."""
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if not resolved.is_dir():
            return
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    # Docker / compose host mounts (see docker-compose.override.yml)
    for name in ("Documents", "Downloads", "Desktop"):
        _add(Path("/host") / name)
        env_path = (os.getenv(f"FREQUENCY_HOST_{name.upper()}") or "").strip()
        if env_path:
            _add(Path(env_path))

    # Native local run (outside Docker)
    home = Path.home()
    for name in ("Documents", "Downloads", "Desktop"):
        _add(home / name)

    exports = project_root / "output" / "exports"
    try:
        exports.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    _add(exports)
    return roots


def list_subfolders(folder: str | Path) -> list[Path]:
    path = Path(folder).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return []
    if not path.is_dir():
        return []
    out: list[Path] = []
    try:
        for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() and not child.name.startswith("."):
                out.append(child)
    except OSError:
        return []
    return out


def parent_within_roots(folder: str | Path, roots: list[Path]) -> Path | None:
    path = Path(folder).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return None
    parent = path.parent
    if parent == path:
        return None
    for root in roots:
        try:
            parent.relative_to(root)
            return parent
        except ValueError:
            if parent == root:
                return parent
    return None


def tk_pick_folder(initial: str = "") -> str | None:
    """Native OS folder dialog when display + tkinter are available."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        kwargs: dict = {"title": "Choose folder for Frequency export ZIP"}
        start = (initial or "").strip()
        if start and Path(start).is_dir():
            kwargs["initialdir"] = start
        chosen = filedialog.askdirectory(**kwargs)
        root.destroy()
        return (chosen or "").strip() or None
    except Exception:
        return None


def render_browser_directory_save(
    zip_bytes: bytes,
    *,
    file_name: str = "frequency_selected_fetches.zip",
    height: int = 72,
) -> None:
    """
    Chrome/Edge on localhost: native folder picker, then write ZIP into that folder.
    Uses the parent window when Streamlit embeds this in an iframe.
    """
    import streamlit.components.v1 as components

    safe_name = file_name.replace("\\", "").replace('"', "").replace("'", "")
    b64 = base64.b64encode(zip_bytes).decode("ascii")
    label = html.escape("Browse folder & save ZIP")
    markup = f"""
<div style="font-family: system-ui, sans-serif; padding: 0.15rem 0;">
  <button id="fx-browse-save" style="
      cursor:pointer; padding:0.45rem 0.9rem; border-radius:8px;
      border:1px solid #1a6b63; background:#0d9488; color:#fff; font-weight:600;">
    {label}
  </button>
  <div id="fx-browse-status" style="margin-top:0.35rem; font-size:0.85rem; color:#334155;"></div>
</div>
<script>
(function() {{
  const fileName = {safe_name!r};
  const b64 = {b64!r};
  const status = document.getElementById("fx-browse-status");
  const btn = document.getElementById("fx-browse-save");

  function setStatus(msg, ok) {{
    if (!status) return;
    status.textContent = msg;
    status.style.color = ok ? "#0f766e" : "#b45309";
  }}

  function b64ToBytes(s) {{
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }}

  function pickerHost() {{
    try {{
      if (window.parent && window.parent.showDirectoryPicker) return window.parent;
    }} catch (e) {{}}
    return window;
  }}

  btn.addEventListener("click", async function() {{
    const host = pickerHost();
    if (!host.showDirectoryPicker) {{
      setStatus("Folder picker needs Chrome or Edge. Use Download below, or browse folders in the list.", false);
      return;
    }}
    try {{
      const dir = await host.showDirectoryPicker({{ mode: "readwrite" }});
      const handle = await dir.getFileHandle(fileName, {{ create: true }});
      const writable = await handle.createWritable();
      await writable.write(b64ToBytes(b64));
      await writable.close();
      const where = dir.name ? ("“" + dir.name + "”") : "the selected folder";
      setStatus("Saved " + fileName + " to " + where + " on this computer.", true);
    }} catch (err) {{
      if (err && err.name === "AbortError") {{
        setStatus("Cancelled.", false);
        return;
      }}
      setStatus("Could not save there (" + ((err && err.message) || err) + "). Try Download, or pick a folder below.", false);
    }}
  }});
}})();
</script>
"""
    components.html(markup, height=height)
