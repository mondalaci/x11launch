# Default config when no ~/.config/x11launch/config.py (or X11LAUNCH_CONFIG) exists.
# Copy to that path to customize. Accelerators: GTK native strings (gtk_accelerator_parse).


def open(url: str) -> str:
    """Shell command: open URL in the user's default browser via xdg-open.

    Use %s in url for the launcher query (URL-encoded). xdg-open does not
    accept `--`; rely on URLs starting with http(s):// so they are never
    mistaken for an option.
    """
    return f'xdg-open "{url}"'


CLAUDE = open("https://claude.ai/new?q=%s&submit=1")

# %w = X11 window that had focus before the launcher opened.
# Ctrl+Enter: ask Claude, then restore focus to the pre-launcher window
# (so the new browser tab opens in the background instead of stealing focus).
shortcut(
    "<Control>Return",
    'WID=%w; ' + CLAUDE + ' & sleep 0.2; xdotool windowactivate "$WID"',
)
shortcut("<Control>a", open("https://www.aliexpress.com/wholesale?SearchText=%s"))
shortcut("<Control>e", open("https://translate.google.com/?sl=en&tl=hu&text=%s"))
shortcut("<Control>g", open("https://www.google.com/search?q=%s"))
shortcut("<Control>h", open("https://translate.google.com/?sl=hu&tl=en&text=%s"))
shortcut("<Control>i", open("https://www.google.com/search?tbm=isch&q=%s"))
shortcut("<Control>r", open("https://www.reddit.com/search/?q=%s"))
shortcut("<Control>w", open("https://en.wikipedia.org/wiki/Special:Search?search=%s"))
shortcut("<Control>y", open("https://www.youtube.com/results?search_query=%s"))

# Plain Enter: ask Claude (URL is auto-submitted by claude-autosubmit.userscript.js).
submit(CLAUDE)

# Ctrl+P / Ctrl+N step backward / forward through the launcher's query history,
# replacing the input field with the remembered query (use a different accelerator
# string here to rebind, e.g. historyPrev("<Alt>k")).
historyPrev("<Control>p")
historyNext("<Control>n")
