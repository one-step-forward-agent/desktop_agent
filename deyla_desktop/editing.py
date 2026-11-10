"""Text fields that behave like Windows ones.

Tk binds Ctrl+C/V/X/A by the letter, so with the Russian layout (Ctrl+М) nothing happens: the keys are matched by
their physical key code here. A right-click menu has the same commands. Files copied in Explorer are on the clipboard
as CF_HDROP, which Tk cannot read: clipboard_files() reads them for the input to attach.
"""

import ctypes
import os
import tkinter as tk
from ctypes import wintypes

# Windows virtual key codes of the physical keys, whatever the layout
KEYS = {65: "select_all", 67: "<<Copy>>", 86: "<<Paste>>", 88: "<<Cut>>"}
LATIN = {"a", "c", "v", "x"}


def _select_all(widget) -> None:
    if isinstance(widget, tk.Text):
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
    else:
        widget.select_range(0, "end")
        widget.icursor("end")


def shortcut(widget, keycode: int, keysym: str) -> str | None:
    """Ctrl+<key> by the physical key: "break" when done here, None when Tk's own binding does it."""
    command = KEYS.get(keycode)
    if not command or keysym.lower() in LATIN:
        # The English layout: Tk's own bindings do it (Ctrl+A in a Text is not one of them)
        if command == "select_all" and isinstance(widget, tk.Text):
            _select_all(widget)
            return "break"
        return None
    if command == "select_all":
        _select_all(widget)
    else:
        widget.event_generate(command)
    return "break"


def fix_shortcuts(widget) -> None:
    widget.bind("<Control-KeyPress>", lambda event: shortcut(widget, event.keycode, event.keysym), add="+")


def context_menu(widget) -> None:
    menu = tk.Menu(widget, tearoff=False)
    menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="Вставить", command=lambda: widget.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Выделить всё", command=lambda: _select_all(widget))

    def show(event):
        widget.focus_set()
        menu.tk_popup(event.x_root, event.y_root)

    widget.bind("<Button-3>", show, add="+")


def readonly_menu(widget) -> None:
    """The chat log: copy and select all."""
    menu = tk.Menu(widget, tearoff=False)
    menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="Выделить всё", command=lambda: widget.tag_add("sel", "1.0", "end"))
    widget.bind("<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root), add="+")
    fix_shortcuts(widget)


def clipboard_files() -> list[str]:
    """Files copied in Explorer (CF_HDROP), or [] when the clipboard holds none."""
    if os.name != "nt":
        return []
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    user32.GetClipboardData.restype = wintypes.HANDLE
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    CF_HDROP = 15
    if not user32.IsClipboardFormatAvailable(CF_HDROP) or not user32.OpenClipboard(None):
        return []
    try:
        handle = user32.GetClipboardData(CF_HDROP)
        if not handle:
            return []
        count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        files = []
        for index in range(min(count, 20)):
            length = shell32.DragQueryFileW(handle, index, None, 0) + 1
            buffer = ctypes.create_unicode_buffer(length)
            shell32.DragQueryFileW(handle, index, buffer, length)
            files.append(buffer.value)
        return [path for path in files if os.path.isfile(path)]
    finally:
        user32.CloseClipboard()
