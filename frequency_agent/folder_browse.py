"""Browser + optional server save helpers for Workspace ZIP exports.

Primary UX (Windows / Mac in Chrome & Edge): OS Save As / folder picker via the
File System Access API, with an automatic blob-download fallback.

Server-path helpers remain for Docker host mounts (Advanced).
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
    """Writable roots for Advanced server-side save (host mounts + exports)."""
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

    for name in ("Documents", "Downloads", "Desktop"):
        _add(Path("/host") / name)
        env_path = (os.getenv(f"FREQUENCY_HOST_{name.upper()}") or "").strip()
        if env_path:
            _add(Path(env_path))

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
    """Native OS folder dialog when display + tkinter are available (local Python)."""
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


def sanitize_zip_file_name(file_name: str) -> str:
    name = (file_name or "").strip() or "frequency_selected_fetches.zip"
    name = name.replace("\\", "").replace("/", "").replace('"', "").replace("'", "")
    if not name.lower().endswith(".zip"):
        name = f"{name}.zip"
    return name[:180]


def render_save_zip_panel(
    zip_bytes: bytes,
    *,
    file_name: str = "frequency_selected_fetches.zip",
    fetch_count: int = 0,
    height: int = 175,
) -> None:
    """
    Proper Save UX for Windows/Mac browsers:

    1. showSaveFilePicker → OS Save As (browse + name in the dialog; no in-page name field)
    2. showDirectoryPicker / blob download → show in-page file name, then save

    Embeds ZIP as base64 so the click handler can write without a second round-trip.
    """
    import streamlit.components.v1 as components

    safe_name = sanitize_zip_file_name(file_name)
    b64 = base64.b64encode(zip_bytes).decode("ascii")
    n = max(0, int(fetch_count or 0))
    count_bit = f" · {n} fetch{'es' if n != 1 else ''}" if n else ""

    markup = f"""
<div style="
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
  padding: 0.35rem 0.15rem 0.15rem;
  color: #0f172a;
">
  <div id="fx-name-row" style="display:none; margin-bottom:0.55rem;">
    <label for="fx-zip-name" style="display:block; font-size:0.8rem; font-weight:600; margin-bottom:0.25rem;">
      File name
    </label>
    <input id="fx-zip-name" type="text" value="{html.escape(safe_name)}"
      style="
        width:100%; box-sizing:border-box; padding:0.45rem 0.6rem;
        border:1px solid #cbd5e1; border-radius:8px; font-size:0.9rem;
      " />
    <div style="margin-top:0.25rem; font-size:0.72rem; color:#94a3b8;">
      Your browser’s save dialog won’t let you rename here — set the name above.
    </div>
  </div>
  <button id="fx-save-zip" type="button" style="
      width:100%; cursor:pointer; padding:0.55rem 0.9rem; border-radius:8px;
      border:1px solid #0f766e; background:#0d9488; color:#fff;
      font-weight:650; font-size:0.95rem;">
    Save ZIP to this PC{html.escape(count_bit)}…
  </button>
  <div id="fx-save-status" style="margin-top:0.4rem; font-size:0.82rem; color:#64748b; min-height:1.2em;"></div>
  <div id="fx-save-hint" style="margin-top:0.15rem; font-size:0.75rem; color:#94a3b8;"></div>
</div>
<script>
(function() {{
  const defaultName = {safe_name!r};
  const b64 = {b64!r};
  const status = document.getElementById("fx-save-status");
  const hint = document.getElementById("fx-save-hint");
  const btn = document.getElementById("fx-save-zip");
  const nameRow = document.getElementById("fx-name-row");
  const nameInput = document.getElementById("fx-zip-name");

  function setStatus(msg, kind) {{
    if (!status) return;
    status.textContent = msg || "";
    status.style.color = kind === "ok" ? "#0f766e" : (kind === "err" ? "#b45309" : "#64748b");
  }}

  function sanitizeName(raw) {{
    let n = (raw || "").trim() || defaultName;
    n = n.replace(/[\\\\/:"']/g, "");
    if (!/\\.zip$/i.test(n)) n = n + ".zip";
    return n.slice(0, 180);
  }}

  function b64ToBytes(s) {{
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }}

  function hosts() {{
    const list = [];
    for (const w of [window, window.parent, window.top]) {{
      try {{
        if (w && list.indexOf(w) < 0) list.push(w);
      }} catch (e) {{}}
    }}
    return list;
  }}

  function findApi(name) {{
    for (const w of hosts()) {{
      try {{
        if (w && typeof w[name] === "function") return w[name].bind(w);
      }} catch (e) {{}}
    }}
    return null;
  }}

  const hasSaveAs = !!findApi("showSaveFilePicker");
  const hasDirPicker = !!findApi("showDirectoryPicker");
  // Name in-page only when OS Save As (with rename) is unavailable.
  const needInPageName = !hasSaveAs;
  if (nameRow) nameRow.style.display = needInPageName ? "block" : "none";
  if (hint) {{
    if (hasSaveAs) {{
      hint.textContent = "Opens your normal Save dialog — choose the folder and file name there.";
    }} else if (hasDirPicker) {{
      hint.textContent = "Opens a folder picker. Set the file name above, then choose the folder.";
    }} else {{
      hint.textContent = "This browser has no folder dialog — set a name above, or use Download ZIP below.";
    }}
  }}

  function blobDownload(fileName, bytes) {{
    const blob = new Blob([bytes], {{ type: "application/zip" }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(function() {{
      URL.revokeObjectURL(url);
      a.remove();
    }}, 1500);
    setStatus("Download started — pick a folder in your browser’s save dialog (or check Downloads).", "ok");
  }}

  async function saveWithPicker(fileName, bytes) {{
    const savePicker = findApi("showSaveFilePicker");
    if (savePicker) {{
      const handle = await savePicker({{
        suggestedName: defaultName,
        types: [{{
          description: "ZIP archive",
          accept: {{ "application/zip": [".zip"] }}
        }}]
      }});
      const writable = await handle.createWritable();
      await writable.write(bytes);
      await writable.close();
      const savedAs = (handle && handle.name) ? handle.name : defaultName;
      setStatus("Saved “" + savedAs + "” to the folder you chose.", "ok");
      return true;
    }}

    const dirPicker = findApi("showDirectoryPicker");
    if (dirPicker) {{
      const dir = await dirPicker({{ mode: "readwrite" }});
      const handle = await dir.getFileHandle(fileName, {{ create: true }});
      const writable = await handle.createWritable();
      await writable.write(bytes);
      await writable.close();
      const where = dir.name ? ("“" + dir.name + "”") : "the selected folder";
      setStatus("Saved “" + fileName + "” to " + where + ".", "ok");
      return true;
    }}
    return false;
  }}

  btn.addEventListener("click", async function() {{
    const fileName = needInPageName
      ? sanitizeName(nameInput ? nameInput.value : defaultName)
      : defaultName;
    if (needInPageName && nameInput) nameInput.value = fileName;
    btn.disabled = true;
    setStatus("Opening save dialog…", "info");
    const bytes = b64ToBytes(b64);
    try {{
      const ok = await saveWithPicker(fileName, bytes);
      if (!ok) {{
        if (!needInPageName && nameRow) {{
          nameRow.style.display = "block";
          if (hint) hint.textContent = "Set the file name above, then try again — or use Download ZIP.";
        }}
        blobDownload(fileName, bytes);
      }}
    }} catch (err) {{
      if (err && err.name === "AbortError") {{
        setStatus("Cancelled.", "info");
      }} else {{
        try {{
          if (nameRow) nameRow.style.display = "block";
          blobDownload(sanitizeName(nameInput ? nameInput.value : fileName), bytes);
          setStatus(
            "Folder dialog unavailable here — started a normal download instead.",
            "err"
          );
        }} catch (e2) {{
          setStatus(
            "Could not save (" + ((err && err.message) || err) + "). Use Download ZIP below.",
            "err"
          );
        }}
      }}
    }} finally {{
      btn.disabled = false;
    }}
  }});
}})();
</script>
"""
    components.html(markup, height=height)


# Back-compat alias
def render_browser_directory_save(
    zip_bytes: bytes,
    *,
    file_name: str = "frequency_selected_fetches.zip",
    height: int = 175,
) -> None:
    render_save_zip_panel(zip_bytes, file_name=file_name, height=height)
