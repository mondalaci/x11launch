"""
Optional user shortcuts from a Python config file.

Official config path: $X11LAUNCH_CONFIG if set, else
  $XDG_CONFIG_HOME/x11launch/config.py, or ~/.config/x11launch/config.py

If that file exists, it is the only config loaded. If it does not exist, the
bundled x11launch/config_example.py is loaded instead (no merging).

Call shortcut(accelerator, command) for each binding. Accelerators use GTK’s
native format (gtk_accelerator_parse), e.g. <Control>l, <Alt>F4,
<Primary>space. See: https://docs.gtk.org/gtk3/func.accelerator_parse.html

Use submit(command) for plain Enter (Return). If you also use shortcut("Return",
…), that shortcut wins and submit() is ignored (with a stderr notice).

If command contains %s, each is replaced with the query URL-encoded
(urllib.parse.quote with an empty safe set). Use inside http(s) query values or
path segments, not as a raw shell word for arbitrary text.

If command contains %w, it is replaced with the X11 window id that had focus
before the launcher was shown (captured when opening from a hidden launcher).
Use instead of $(xdotool getactivewindow) in shortcuts so restore targets the
correct window. Otherwise the command runs unchanged and the query is ignored.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from typing import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

_config_shortcuts: list[tuple[str, str]] = []
_config_submit: list[str] = []


def shortcut(accelerator: str, command: str) -> None:
    """Register a shortcut; intended for use only inside the user config file."""
    _config_shortcuts.append((accelerator, command))


def submit(command: str) -> None:
    """Register plain Enter (Return); intended for use only inside the user config file."""
    _config_submit.append(command)


def _reset_registry() -> None:
    _config_shortcuts.clear()
    _config_submit.clear()


def spec_to_keyval_mods(accel: str) -> tuple[int, Gdk.ModifierType]:
    s = accel.strip()
    if not s:
        raise ValueError("empty accelerator")
    key, mods = Gtk.accelerator_parse(s)
    if key == 0 and mods == 0:
        raise ValueError(f"invalid GTK accelerator: {accel!r}")
    mask = Gtk.accelerator_get_default_mod_mask()
    mods = Gdk.ModifierType(int(mods) & int(mask))
    return key, mods


def keyboard_event_matches(
    event: Gdk.EventKey, keyval: int, mods: Gdk.ModifierType
) -> bool:
    mask = Gtk.accelerator_get_default_mod_mask()
    ev_mods = Gdk.ModifierType(int(event.state) & int(mask))
    return event.keyval == keyval and ev_mods == mods


def resolve_config_path() -> Path | None:
    env = os.environ.get("X11LAUNCH_CONFIG", "").strip()
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        p = Path(xdg) / "x11launch" / "config.py"
    else:
        p = Path.home() / ".config" / "x11launch" / "config.py"
    return p


def bundled_config_example_path() -> Path:
    return Path(__file__).resolve().parent / "config_example.py"


def load_shortcuts() -> list[tuple[int, Gdk.ModifierType, str]]:
    """Load config from the official file if it exists, else from bundled example."""
    _reset_registry()
    official = resolve_config_path()
    use_user = official is not None and official.is_file()
    if use_user:
        path = official
    else:
        path = bundled_config_example_path()
        if not path.is_file():
            print(
                "x11launch: no config: user file missing and bundled config_example.py not found",
                file=sys.stderr,
            )
            return []

    ns: dict[str, Callable[..., None]] = {"shortcut": shortcut, "submit": submit}
    try:
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), ns, ns)
    except OSError as e:
        print(f"x11launch: could not read config {path}: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"x11launch: error loading config {path}: {e}", file=sys.stderr)
        return []

    out: list[tuple[int, Gdk.ModifierType, str]] = []
    seen: set[tuple[int, int]] = set()
    for accel, cmd in list(_config_shortcuts):
        try:
            kv, md = spec_to_keyval_mods(accel)
        except Exception as e:
            print(
                f"x11launch: skipping shortcut {accel!r} -> {cmd!r}: {e}",
                file=sys.stderr,
            )
            continue
        dup_key = (kv, int(md))
        if dup_key in seen:
            print(
                f"x11launch: duplicate accelerator {accel!r}; keeping first binding",
                file=sys.stderr,
            )
            continue
        seen.add(dup_key)
        out.append((kv, md, cmd.strip()))

    if _config_submit:
        if len(_config_submit) > 1:
            print(
                "x11launch: submit() called multiple times; using the last command",
                file=sys.stderr,
            )
        sub = _config_submit[-1].strip()
        try:
            r_kv, r_md = spec_to_keyval_mods("Return")
        except Exception as e:
            print(f"x11launch: could not register submit (Return): {e}", file=sys.stderr)
            return out
        r_key = (r_kv, int(r_md))
        if r_key in seen:
            print(
                'x11launch: submit() ignored because shortcut("Return", …) is already defined',
                file=sys.stderr,
            )
        else:
            seen.add(r_key)
            out.append((r_kv, r_md, sub))

    resolved = path.resolve()
    if use_user:
        origin = "user config"
    else:
        origin = f"bundled example (no {official.resolve()})"
    print(f"x11launch: config: {resolved} ({origin})", file=sys.stderr)
    return out


def dispatch_shortcut_command(
    command: str,
    query: str,
    *,
    pre_launcher_x11_wid: str | None = None,
) -> None:
    line = command
    if "%w" in line:
        line = line.replace("%w", pre_launcher_x11_wid or "")
    if "%s" in line:
        enc = quote(query, safe="")
        line = line.replace("%s", enc)
    print(f"x11launch: execute: {line}", file=sys.stderr)
    # start_new_session would isolate the child in a new POSIX session; Chrome’s
    # Linux singleton sometimes fails to attach to the running instance and
    # opens a second window instead of a tab.
    subprocess.Popen(
        line,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
