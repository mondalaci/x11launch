"""
Optional user shortcuts from a Python config file.

Official config path: $X11LAUNCH_CONFIG if set, else
  $XDG_CONFIG_HOME/x11launch/config.py, or ~/.config/x11launch/config.py

If that file exists, it is the only config loaded. If it does not exist, the
bundled x11launch/config_example.py is loaded instead (no merging).

Config helpers:
  shortcut(accelerator, command)
      Run a shell command when the accelerator is pressed.
  submit(command)
      Run a shell command on plain Enter (Return). Equivalent to
      shortcut("Return", command); an explicit shortcut("Return", …) wins.
  historyPrev(accelerator="<Control>p")
  historyNext(accelerator="<Control>n")
      Bind the built-in "query history previous/next" launcher actions.
      They replace the input field with the previous / next remembered
      query (queries are remembered each time a shell command runs).
      An explicit shortcut(...) for the same accelerator wins.

Accelerators use GTK's native format (gtk_accelerator_parse), e.g.
<Control>l, <Alt>F4, <Primary>space. See:
https://docs.gtk.org/gtk3/func.accelerator_parse.html

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
from typing import Callable, NamedTuple
from urllib.parse import quote

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

# Built-in action identifiers used by app.py to dispatch non-shell bindings.
BUILTIN_HISTORY_PREV = "history-prev"
BUILTIN_HISTORY_NEXT = "history-next"


class Binding(NamedTuple):
    """A loaded keybinding.

    kind:
        "shell"   -> payload is a shell command (see dispatch_shortcut_command)
        "builtin" -> payload is a BUILTIN_* identifier handled by the app
    """

    keyval: int
    mods: Gdk.ModifierType
    kind: str
    payload: str


_config_shortcuts: list[tuple[str, str]] = []
_config_submit: list[str] = []
# History helpers store accelerator overrides (empty list means "not registered").
_config_history_prev: list[str] = []
_config_history_next: list[str] = []


def shortcut(accelerator: str, command: str) -> None:
    """Register a shortcut; intended for use only inside the user config file."""
    _config_shortcuts.append((accelerator, command))


def submit(command: str) -> None:
    """Register plain Enter (Return); intended for use only inside the user config file."""
    _config_submit.append(command)


def historyPrev(accelerator: str = "<Control>p") -> None:
    """Bind the built-in 'history previous' launcher action (default <Control>p)."""
    _config_history_prev.append(accelerator)


def historyNext(accelerator: str = "<Control>n") -> None:
    """Bind the built-in 'history next' launcher action (default <Control>n)."""
    _config_history_next.append(accelerator)


def _reset_registry() -> None:
    _config_shortcuts.clear()
    _config_submit.clear()
    _config_history_prev.clear()
    _config_history_next.clear()


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


def load_shortcuts() -> list[Binding]:
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

    ns: dict[str, Callable[..., None]] = {
        "historyNext": historyNext,
        "historyPrev": historyPrev,
        "shortcut": shortcut,
        "submit": submit,
    }
    try:
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), ns, ns)
    except OSError as e:
        print(f"x11launch: could not read config {path}: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"x11launch: error loading config {path}: {e}", file=sys.stderr)
        return []

    out: list[Binding] = []
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
        out.append(Binding(kv, md, "shell", cmd.strip()))

    # submit(command): a shell command on the fixed accelerator "Return".
    if _config_submit:
        if len(_config_submit) > 1:
            print(
                "x11launch: submit() called multiple times; using the last command",
                file=sys.stderr,
            )
        sub_cmd = _config_submit[-1].strip()
        try:
            kv, md = spec_to_keyval_mods("Return")
        except Exception as e:
            print(f"x11launch: could not register submit (Return): {e}", file=sys.stderr)
        else:
            key = (kv, int(md))
            if key in seen:
                print(
                    'x11launch: submit() ignored because shortcut("Return", …) is already defined',
                    file=sys.stderr,
                )
            else:
                seen.add(key)
                out.append(Binding(kv, md, "shell", sub_cmd))

    # historyPrev()/historyNext(): built-in launcher actions; argument overrides the accelerator.
    for helper_name, accels, default_accel, action_id in (
        ("historyPrev", _config_history_prev, "<Control>p", BUILTIN_HISTORY_PREV),
        ("historyNext", _config_history_next, "<Control>n", BUILTIN_HISTORY_NEXT),
    ):
        if not accels:
            continue
        if len(accels) > 1:
            print(
                f"x11launch: {helper_name}() called multiple times; using the last accelerator",
                file=sys.stderr,
            )
        accel = accels[-1].strip() or default_accel
        try:
            kv, md = spec_to_keyval_mods(accel)
        except Exception as e:
            print(
                f"x11launch: could not register {helper_name} ({accel}): {e}",
                file=sys.stderr,
            )
            continue
        key = (kv, int(md))
        if key in seen:
            print(
                f"x11launch: {helper_name}() ignored because shortcut({accel!r}, …) "
                "is already defined",
                file=sys.stderr,
            )
            continue
        seen.add(key)
        out.append(Binding(kv, md, "builtin", action_id))

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
    print(f"x11launch: execute: {line}")
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
