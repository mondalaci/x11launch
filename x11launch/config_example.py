# Default config when no ~/.config/x11launch/config.py (or X11LAUNCH_CONFIG) exists.
# Copy to that path to customize. Accelerators: GTK native strings (gtk_accelerator_parse).


def chrome(url: str) -> str:
    """Shell command: open URL in Google Chrome. Use %s in url for the launcher query (URL-encoded).

    --new-tab asks the running Chrome instance to open a tab. -- stops option parsing so
    odd URLs are never treated as flags.
    """
    return f'google-chrome --new-tab -- "{url}"'


# %w = X11 window that had focus before the launcher opened (not $(xdotool getactivewindow)).
shortcut(
    "<Control>Return",
    'WID=%w; '
    + chrome("http://claude.ai/new?submit=1&q=%s")
    + ' & sleep 0.1; xdotool windowactivate "$WID"',
)
shortcut("<Control>a", chrome("https://www.aliexpress.com/wholesale?SearchText=%s"))
shortcut("<Control>e", chrome("https://translate.google.com/?sl=en&tl=hu&text=%s"))
shortcut("<Control>g", chrome("https://www.google.com/search?q=%s"))
shortcut("<Control>h", chrome("https://translate.google.com/?sl=hu&tl=en&text=%s"))
shortcut("<Control>i", chrome("https://www.google.com/search?tbm=isch&q=%s"))
shortcut("<Control>r", chrome("https://www.reddit.com/search/?q=%s"))
shortcut("<Control>w", chrome("https://en.wikipedia.org/wiki/Special:Search?search=%s"))
shortcut("<Control>y", chrome("https://www.youtube.com/results?search_query=%s"))
submit(chrome("http://claude.ai/new?submit=1&q=%s"))
