"""
GTK 3 + PyGObject launcher: query field, tray icon, global Ctrl+Space (Keybinder).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import warnings
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from x11launch.config import (
    dispatch_shortcut_command,
    keyboard_event_matches,
    load_shortcuts,
)

try:
    gi.require_version("Keybinder", "3.0")
    from gi.repository import Keybinder

    _HAVE_KEYBINDER = True
except ValueError:
    Keybinder = None
    _HAVE_KEYBINDER = False

APP_ID = "dev.x11launch.Launcher"

_HOTKEY_ACCELS = ("<Control>space", "<Ctrl>space", "<Primary>space")

_TRAY_ICON_FALLBACK = "system-search-symbolic"
_TRAY_SVG = Path(__file__).resolve().parent / "icons" / "scalable" / "apps" / "x11launch-tray.svg"
# HiDPI tray: rasterize large then let the panel scale down (tiny bitmaps look blocky).
_TRAY_PNG_PX = 128
_TRAY_RASTER_REVISION = 1  # bump if raster size / pipeline changes (cache file name)

# Query field typography (points); one-line height is derived from this + margins.
_QUERY_FONT_PT = 16
_QUERY_WINDOW_WIDTH = 720

# Vertical gap between Shift+Enter paragraphs (tag-based so the last paragraph has no extra bottom pad).
_PARA_GAP_PX = 12

# Gtk lays out paragraph spacing poorly on a totally empty last line; Shift+Enter inserts this then we strip it for submit.
_PARA_EMPTY_PLACEHOLDER = "\u200b"  # zero-width space

# Outer margin around the shell; keep well above box-shadow reach or GTK clips the blur at the window edge.
_CHROME_SHADOW_GUTTER_PX = 64

_WINDOW_CHROME_CSS_DONE = False

_log = logging.getLogger("x11launch")


def _ensure_window_chrome_css() -> None:
    global _WINDOW_CHROME_CSS_DONE
    if _WINDOW_CHROME_CSS_DONE:
        return
    css = b"""
    #x11launch-window {
      background-color: transparent;
    }
    .x11launch-gutter {
      background-color: transparent;
    }
    .x11launch-shell {
      border-radius: 10px;
      border: 1px solid alpha(@theme_fg_color, 0.42);
      /* Moderate blur so most of the falloff stays inside the transparent gutter (64px). */
      box-shadow: 0 2px 14px rgba(0, 0, 0, 0.2);
      background-color: @theme_base_color;
      color: @theme_text_color;
      padding: 4px;
    }
    .x11launch-shell textview {
      background-color: transparent;
      color: inherit;
    }
    .x11launch-shell textview.view {
      background-color: transparent;
      border-radius: 7px;
    }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    _WINDOW_CHROME_CSS_DONE = True


def debug_enabled() -> bool:
    return os.environ.get("X11LAUNCH_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def configure_logging() -> None:
    """Call from main(); set X11LAUNCH_DEBUG=1 for stderr traces."""
    if _log.handlers:
        return
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d [x11launch] %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    _log.addHandler(h)
    _log.propagate = False
    _log.setLevel(logging.DEBUG if debug_enabled() else logging.CRITICAL)


def _xdotool_get_active_window_id() -> str | None:
    """X11 window id (decimal string) for the currently focused window, or None."""
    try:
        r = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        if r.returncode == 0:
            w = r.stdout.strip()
            if w.isdigit():
                return w
    except Exception as e:
        _log.debug("xdotool getactivewindow: %s", e)
    return None


def _import_appindicator():
    for name, ver in (("AyatanaAppIndicator3", "0.1"), ("AppIndicator3", "0.1")):
        try:
            gi.require_version(name, ver)
        except ValueError:
            continue
        try:
            return __import__(f"gi.repository.{name}", fromlist=[name])
        except ImportError:
            continue
    return None


def _tray_png_cache_path() -> Path | None:
    """Raster tray SVG to PNG; AppIndicator often ignores theme SVG and set_icon_full(svg)."""
    if not _TRAY_SVG.is_file():
        return None
    cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    out = base / "x11launch" / f"tray-r{_TRAY_RASTER_REVISION}.png"
    try:
        regen = True
        if out.is_file():
            regen = _TRAY_SVG.stat().st_mtime > out.stat().st_mtime
        if regen:
            out.parent.mkdir(parents=True, exist_ok=True)
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(_TRAY_SVG), _TRAY_PNG_PX, _TRAY_PNG_PX, True
            )
            pb.savev(str(out), "png", [], [])
        return out if out.is_file() else None
    except GLib.Error as e:
        _log.debug("tray PNG cache: %s", e)
        return None


def _set_tray_indicator_icon(ind: object) -> None:
    """Load bundled rocket via set_icon_full; theme name lookup is unreliable for SVG."""
    sif = getattr(ind, "set_icon_full", None)
    if not callable(sif):
        return
    for candidate in (_tray_png_cache_path(), _TRAY_SVG if _TRAY_SVG.is_file() else None):
        if candidate is None:
            continue
        path = str(candidate)
        for desc in ("local", ""):
            try:
                sif(path, desc)
                return
            except Exception as e:
                _log.debug("set_icon_full(%r, %r): %s", path, desc, e)


class X11launchApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._window: Gtk.ApplicationWindow | None = None
        self._query_view: Gtk.TextView | None = None
        self._hotkey_accel: str | None = None
        self._indicator = None
        self._appind = None
        self._keybinder_inited = False
        self._keybinder_closure = None
        self._query_buffer_changed_id: int = 0
        self._shortcuts: list[tuple[int, Gdk.ModifierType, str]] = load_shortcuts()
        self._x11_pre_launcher_wid: str | None = None

    def do_startup(self) -> None:
        # PyGObject: chain GObject vfuncs with Class.method(self), not super().
        Gtk.Application.do_startup(self)
        _log.debug(
            "do_startup session_type=%s display=%s",
            os.environ.get("XDG_SESSION_TYPE", ""),
            os.environ.get("DISPLAY", ""),
        )
        self._setup_keybinder()
        self._setup_tray()

    def do_activate(self) -> None:
        _log.debug(
            "do_activate has_window=%s", self._window is not None
        )
        if self._window is None:
            self._build_window()
        else:
            self._present_launcher()

    def _ensure_keybinder_closure(self) -> None:
        """Hold a bound callable on self so PyGObject never drops the Keybinder callback."""
        if self._keybinder_closure is not None:
            return

        def on_hotkey(keystring: str, app: X11launchApp) -> None:
            _log.debug(
                "Keybinder callback fired keystring=%r app_id=%s",
                keystring,
                id(app),
            )
            GLib.idle_add(app._present_launcher_idle)

        self._keybinder_closure = on_hotkey

    def _setup_keybinder(self) -> None:
        if not _HAVE_KEYBINDER:
            print(
                "x11launch: Keybinder GIR missing; install gir1.2-keybinder-3.0 "
                "(global Ctrl+Space disabled).",
                file=sys.stderr,
            )
            return
        if not self._keybinder_inited:
            Keybinder.init()
            self._keybinder_inited = True
            _log.debug("Keybinder.init() done")
            if hasattr(Keybinder, "set_use_cooked_accelerators"):
                Keybinder.set_use_cooked_accelerators(True)
                _log.debug("Keybinder.set_use_cooked_accelerators(True)")
            if hasattr(Keybinder, "supported"):
                _log.debug("Keybinder.supported() -> %s", Keybinder.supported())
        self._ensure_keybinder_closure()
        self._bind_global_hotkey()

    def _unbind_all_hotkeys(self) -> None:
        if not _HAVE_KEYBINDER:
            return
        _log.debug("unbind all hotkey strings")
        for accel in _HOTKEY_ACCELS:
            try:
                Keybinder.unbind(accel)
            except Exception as e:
                _log.debug("Keybinder.unbind(%r) raised: %s", accel, e)
        self._hotkey_accel = None

    def _bind_global_hotkey(self) -> None:
        if not _HAVE_KEYBINDER or self._keybinder_closure is None:
            _log.debug(
                "_bind_global_hotkey skip have_keybinder=%s closure=%s",
                _HAVE_KEYBINDER,
                self._keybinder_closure is not None,
            )
            return
        self._unbind_all_hotkeys()
        for accel in _HOTKEY_ACCELS:
            ok = Keybinder.bind(accel, self._keybinder_closure, self)
            _log.debug("Keybinder.bind(%r, ...) -> %s", accel, ok)
            if ok:
                self._hotkey_accel = accel
                break
        if not self._hotkey_accel:
            print(
                "x11launch: could not bind Ctrl+Space (X11 only; conflict or Wayland).",
                file=sys.stderr,
            )
        else:
            _log.debug("active hotkey accel=%r", self._hotkey_accel)

    def _present_launcher_idle(self) -> bool:
        _log.debug("_present_launcher_idle (from GLib idle)")
        self._present_launcher()
        return GLib.SOURCE_REMOVE

    def _present_launcher(self) -> None:
        if not self._window or not self._query_view:
            _log.debug("_present_launcher bail: no window/query view")
            return
        vis_before = self._window.get_visible()
        _log.debug("_present_launcher visible_before=%s", vis_before)
        # Before we raise the launcher, record who had focus (not the launcher).
        if not vis_before:
            self._x11_pre_launcher_wid = _xdotool_get_active_window_id()
            _log.debug("_present_launcher captured pre-launcher X11 wid=%s", self._x11_pre_launcher_wid)
        self._window.show_all()
        self._window.present()
        gdk_win = self._window.get_window()
        if gdk_win is not None:
            gdk_win.raise_()
            gdk_win.focus(Gdk.CURRENT_TIME)
        self._query_view.grab_focus()
        _log.debug(
            "_present_launcher after present visible=%s grab_widget=%s",
            self._window.get_visible(),
            Gtk.grab_get_current(),
        )

    def _hide_launcher(self) -> None:
        """Release any Gtk grab so Keybinder keeps receiving Ctrl+Space after hide."""
        if not self._window:
            _log.debug("_hide_launcher bail: no window")
            return
        current = Gtk.grab_get_current()
        _log.debug(
            "_hide_launcher grab_get_current=%s window_visible=%s",
            current,
            self._window.get_visible(),
        )
        if current is not None and current.is_ancestor(self._window):
            _log.debug("_hide_launcher Gtk.grab_remove(%s)", current)
            Gtk.grab_remove(current)
        self._window.hide()
        _log.debug("_hide_launcher after hide visible=%s", self._window.get_visible())
        # Do not call Keybinder unbind/bind here. Cycling bind on every hide breaks the
        # X grab on many setups (second Ctrl+Space never reaches our callback).

    def _setup_tray(self) -> None:
        self._appind = _import_appindicator()
        if self._appind is None:
            print(
                "x11launch: no Ayatana/AppIndicator GIR; tray disabled. "
                "Install gir1.2-ayatanaappindicator3-0.1 (GNOME may need an AppIndicator extension).",
                file=sys.stderr,
            )
            return
        Mod = self._appind
        menu = Gtk.Menu()
        open_item = Gtk.MenuItem.new_with_label("Open x11launch")
        open_item.connect("activate", lambda *_: self._present_launcher())
        menu.append(open_item)
        quit_item = Gtk.MenuItem.new_with_label("Quit")
        quit_item.connect("activate", lambda *_: self.quit())
        menu.append(quit_item)
        menu.show_all()

        cat_enum = getattr(Mod, "IndicatorCategory", None) or getattr(
            Mod, "AppIndicatorCategory", None
        )
        status_enum = getattr(Mod, "IndicatorStatus", None) or getattr(
            Mod, "AppIndicatorStatus", None
        )
        if cat_enum is None or status_enum is None:
            print("x11launch: AppIndicator enums missing; tray disabled.", file=sys.stderr)
            return
        cat = cat_enum.APPLICATION_STATUS
        ind = Mod.Indicator.new("x11launch", _TRAY_ICON_FALLBACK, cat)
        _set_tray_indicator_icon(ind)
        ind.set_status(status_enum.ACTIVE)
        ind.set_title("x11launch")
        ind.set_menu(menu)
        self._indicator = ind

    def _build_window(self) -> None:
        _ensure_window_chrome_css()
        win = Gtk.ApplicationWindow(application=self)
        win.set_name("x11launch-window")
        win.set_title("x11launch")
        # Height follows query widget; keep initial request compact (one line).
        win.set_default_size(_QUERY_WINDOW_WIDTH, 52)
        win.set_resizable(True)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_position(Gtk.WindowPosition.CENTER)
        screen = Gdk.Screen.get_default()
        rgba = screen.get_rgba_visual() if screen is not None else None
        if rgba is not None:
            win.set_visual(rgba)
            win.set_app_paintable(True)

        margin = 16
        tv = Gtk.TextView()
        tv.override_font(Pango.FontDescription.from_string(f"Sans {_QUERY_FONT_PT}"))
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(margin)
        tv.set_right_margin(margin)
        tv.set_top_margin(margin)
        tv.set_bottom_margin(margin)
        # Paragraph spacing via tag (see _sync_paragraph_gap_tag), not pixels_below_lines — that
        # adds empty space after the last paragraph too.
        tv.set_pixels_inside_wrap(0)
        tv.set_pixels_above_lines(0)
        tv.set_pixels_below_lines(0)
        tv.set_accepts_tab(False)
        tv.connect("key-press-event", self._on_query_key_press)
        tv.connect("size-allocate", self._on_query_size_allocate)
        buf = tv.get_buffer()
        buf.create_tag("para_gap_above", pixels_above_lines=_PARA_GAP_PX)
        buf.create_tag("para_gap_trail", pixels_below_lines=_PARA_GAP_PX)
        self._query_buffer_changed_id = buf.connect("changed", self._on_query_buffer_changed)

        # Gutter keeps CSS box-shadow from touching the window clip rect.
        gutter = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        gutter.get_style_context().add_class("x11launch-gutter")
        gutter.set_margin_top(_CHROME_SHADOW_GUTTER_PX)
        gutter.set_margin_bottom(_CHROME_SHADOW_GUTTER_PX)
        gutter.set_margin_start(_CHROME_SHADOW_GUTTER_PX)
        gutter.set_margin_end(_CHROME_SHADOW_GUTTER_PX)

        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        shell.get_style_context().add_class("x11launch-shell")
        shell.set_hexpand(True)
        shell.set_halign(Gtk.Align.FILL)
        tv.set_hexpand(True)
        shell.pack_start(tv, False, False, 0)
        gutter.pack_start(shell, False, False, 0)
        win.add(gutter)

        win.connect("delete-event", self._on_window_delete)

        self._window = win
        self._query_view = tv
        win.hide()
        _log.debug("_build_window done")

    def _on_window_delete(self, _w: Gtk.Widget, _e: Gdk.Event) -> bool:
        _log.debug("delete-event on window")
        self._hide_launcher()
        return True

    def _query_buffer_text(self) -> str:
        if not self._query_view:
            return ""
        buf = self._query_view.get_buffer()
        start, end = buf.get_bounds()
        return buf.get_text(start, end, True).replace(_PARA_EMPTY_PLACEHOLDER, "")

    def _sync_query_view_height(self) -> None:
        """One line by default; grow to full wrapped height (window expands, no scrollbar)."""
        tv = self._query_view
        if tv is None or not tv.get_realized():
            return
        w = tv.get_allocated_width()
        if w < 2:
            return
        _min_h, nat_h = tv.get_preferred_height_for_width(w)
        buf = tv.get_buffer()
        _y, line_h = tv.get_line_yrange(buf.get_start_iter())
        if line_h <= 0:
            line_h = max(22, round(_QUERY_FONT_PT * 1.45))
        floor_h = line_h + tv.get_top_margin() + tv.get_bottom_margin()
        start, end = buf.get_bounds()
        text = buf.get_text(start, end, False)
        if not text:
            content_h = floor_h
        elif "\n" in text:
            content_h = max(floor_h, nat_h)
        else:
            # Single logical line: expand only when word-wrap needs more than one display line.
            content_h = nat_h if nat_h > floor_h else floor_h
        _wr, cur_h = tv.get_size_request()
        if cur_h != content_h:
            tv.set_size_request(-1, content_h)

    def _sync_paragraph_gap_tag(self) -> None:
        """Gap between paragraphs: above_lines on text after each \\n; for an empty last line, below_lines on the char before the final \\n."""
        tv = self._query_view
        if tv is None or not self._query_buffer_changed_id:
            return
        buf = tv.get_buffer()
        bid = self._query_buffer_changed_id
        buf.handler_block(bid)
        try:
            start = buf.get_start_iter()
            end = buf.get_end_iter()
            buf.remove_tag_by_name("para_gap_above", start, end)
            buf.remove_tag_by_name("para_gap_trail", start, end)
            search = buf.get_start_iter()
            limit = buf.get_end_iter()
            while True:
                r = search.forward_search("\n", Gtk.TextSearchFlags.TEXT_ONLY, limit)
                if r is None:
                    break
                ms, me = r
                ps = me.copy()
                if ps.compare(end) < 0:
                    pe = ps.copy()
                    pe.forward_to_line_end()
                    buf.apply_tag_by_name("para_gap_above", ps, pe)
                search = me.copy()

            whole = buf.get_text(start, end, False)
            if whole.endswith("\n"):
                last_nl = end.copy()
                last_nl.backward_char()
                before = last_nl.copy()
                if before.backward_char():
                    buf.apply_tag_by_name("para_gap_trail", before, last_nl)
                else:
                    buf.apply_tag_by_name("para_gap_trail", last_nl, end)
        finally:
            buf.handler_unblock(bid)
        if tv.get_realized():
            tv.queue_resize()

    def _on_query_buffer_changed(self, _buf: Gtk.TextBuffer) -> None:
        self._sync_paragraph_gap_tag()
        GLib.idle_add(self._sync_query_height_idle)

    def _sync_query_height_idle(self) -> bool:
        self._sync_query_view_height()
        return GLib.SOURCE_REMOVE

    def _on_query_size_allocate(self, _tv: Gtk.TextView, _allocation: Gdk.Rectangle) -> None:
        self._sync_query_view_height()

    def _on_query_key_press(self, _tv: Gtk.TextView, event: Gdk.EventKey) -> bool:
        _log.debug(
            "query key-press keyval=%s state=%#x",
            event.keyval,
            event.state,
        )
        if event.keyval == Gdk.KEY_Escape:
            _log.debug("query: Escape -> hide")
            self._hide_launcher()
            return True
        for keyval, mods, command in self._shortcuts:
            if keyboard_event_matches(event, keyval, mods):
                _log.debug("query: user shortcut -> %r", command)
                self._activate_user_shortcut(command)
                return True
        mods = event.state & Gdk.ModifierType.MODIFIER_MASK
        if mods & Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_space,
            Gdk.KEY_KP_Space,
        ):
            _log.debug("query: Ctrl+Space -> hide")
            self._hide_launcher()
            return True
        if event.keyval in (
            Gdk.KEY_Return,
            Gdk.KEY_KP_Enter,
            Gdk.KEY_ISO_Enter,
        ):
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                _log.debug("query: Shift+Enter -> newline + layout placeholder")
                buf = self._query_view.get_buffer()
                buf.insert_at_cursor("\n" + _PARA_EMPTY_PLACEHOLDER)
                return True
            _log.debug("query: Enter -> submit")
            self._submit_query()
            return True
        return False

    def _activate_user_shortcut(self, command: str) -> None:
        if not self._query_view:
            return
        dispatch_shortcut_command(
            command,
            self._query_buffer_text(),
            pre_launcher_x11_wid=self._x11_pre_launcher_wid,
        )
        self._query_view.get_buffer().set_text("")
        self._hide_launcher()

    def _submit_query(self) -> None:
        if not self._query_view:
            return
        _log.debug(
            "query: Enter submit fallback (define submit(...) or shortcut(\"Return\", ...) in config)"
        )
        self._query_view.get_buffer().set_text("")
        self._hide_launcher()

    def do_shutdown(self) -> None:
        _log.debug("do_shutdown")
        self._unbind_all_hotkeys()
        Gtk.Application.do_shutdown(self)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    if debug_enabled():
        _log.debug(
            "debug on (X11LAUNCH_DEBUG=1) pid=%s argv=%s",
            os.getpid(),
            argv if argv is not None else sys.argv,
        )
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="gi")
    if argv is None:
        argv = sys.argv
    app = X11launchApp()
    return int(app.run(argv))
