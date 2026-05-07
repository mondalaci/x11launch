# Default config when no ~/.config/x11launch/config.py (or X11LAUNCH_CONFIG) exists.
# Copy to that path to customize. Accelerators: GTK native strings (gtk_accelerator_parse).


def open(url: str) -> str:
    """Shell command: open URL in the user's default browser via xdg-open.

    Use %s in url for the launcher query (URL-encoded). xdg-open does not
    accept `--`; rely on URLs starting with http(s):// so they are never
    mistaken for an option.
    """
    return f'xdg-open "{url}"'


# %w = X11 window that had focus before the launcher opened (not $(xdotool getactivewindow)).
shortcut(
    "<Control>Return",
    'WID=%w; '
    + open("http://claude.ai/new?submit=1&q=%s")
    + ' & sleep 0.2; xdotool windowactivate "$WID"',
)
shortcut("<Control>a", open("https://www.aliexpress.com/wholesale?SearchText=%s"))
shortcut("<Control>e", open("https://translate.google.com/?sl=en&tl=hu&text=%s"))
shortcut("<Control>g", open("https://www.google.com/search?q=%s"))
shortcut("<Control>h", open("https://translate.google.com/?sl=hu&tl=en&text=%s"))
shortcut("<Control>i", open("https://www.google.com/search?tbm=isch&q=%s"))
shortcut("<Control>r", open("https://www.reddit.com/search/?q=%s"))
shortcut("<Control>w", open("https://en.wikipedia.org/wiki/Special:Search?search=%s"))
shortcut("<Control>y", open("https://www.youtube.com/results?search_query=%s"))
submit(open("http://claude.ai/new?submit=1&q=%s"))
