# x11launch

Minimal GTK 3 launcher: a small query window, optional system tray entry, and a global **Ctrl+Space** hotkey to raise it. Geared toward an **X11** stack (Keybinder); on Wayland the hotkey may be unavailable.

## Requirements

- **Python** 3.10+
- **GTK 3** and **PyGObject** (e.g. Debian/Ubuntu: `gir1.2-gtk-3.0`, `python3-gi`)
- Optional: **Keybinder 3** (`gir1.2-keybinder-3.0`) for global Ctrl+Space
- Optional: **AppIndicator** / Ayatana (`gir1.2-ayatanaappindicator3-0.1` or equivalent) for the tray icon

## Install

Repository: [github.com/mondalaci/x11launch](https://github.com/mondalaci/x11launch).

From the repository root:

```bash
pip install .
```

This installs the `x11launch` console script. You can also run without installing:

```bash
python -m x11launch
```

## Usage

- **Ctrl+Space** (global): show the launcher and focus the query field (X11 + Keybinder).
- **Escape** or **Ctrl+Space** (while focused): hide the launcher.
- **Enter**: if the loaded config defines **`submit(…)`** (or **`shortcut("Return", …)`**), that command runs; with no user config, the bundled example supplies **`submit`**. Otherwise Enter clears the field and hides the launcher.
- **Shift+Enter**: newline in the query (multi-line input).

If Keybinder is missing or the binding fails, a message is printed to stderr and you can still open the app from the tray (when available) or by running `x11launch` again.

## Configuration (shortcuts)

**Official config:** `~/.config/x11launch/config.py`, or the path in **`X11LAUNCH_CONFIG`**. If that file **exists**, it is loaded **only** from there (no defaults mixed in).

If there is **no** official config file, x11launch loads the bundled **`x11launch/config_example.py`** as the whole config (copy it to `~/.config/x11launch/config.py` when you want to customize).

In the active config file, register keys with **`shortcut(gtk_accelerator, command)`** and plain **Enter** with **`submit(command)`**. Accelerators use GTK’s native format (`gtk_accelerator_parse`), e.g. `<Control>l`, `<Alt>F4`. See the [GTK 3 docs](https://docs.gtk.org/gtk3/func.accelerator_parse.html). A **`shortcut("Return", …)`** overrides **`submit(…)`** if both are present.

If **`command`** contains **`%s`**, each is replaced with the query **URL-encoded** (for `http://…?q=…`-style use). **`%w`** is replaced with the X11 window id that had focus **before** the launcher was shown (so you can **`xdotool windowactivate`** back to it; **`$(xdotool getactivewindow)`** inside the command would see the launcher instead). Without placeholders, the command runs unchanged.

Example (see `x11launch/config_example.py`):

```python
shortcut("<Control>g", 'google-chrome "https://www.google.com/search?q=%s"')
```

Put **`%s`** only where URL-encoding the typed text is right (usually inside `http://…?…=%s`). A bare **`xdg-open %s`** with a full pasted URL will break, because **`https://`** becomes percent-encoded. The bundled **`submit`** example shows a safe pattern.

## Debugging

Set **`X11LAUNCH_DEBUG=1`** to enable debug logging on stderr.

## License

MIT
