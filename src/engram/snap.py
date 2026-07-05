"""Region screenshot: freeze the screen, drag a rectangle, get a PIL image."""

from __future__ import annotations

import base64
import io
import tkinter as tk

from PIL import ImageGrab, ImageTk

MAX_EDGE = 1568  # plenty for vision models, keeps token cost down


def grab_region(root):
    shot = ImageGrab.grab()
    sel = {}
    start = [0, 0]

    top = tk.Toplevel(root)
    top.attributes("-fullscreen", True)
    top.attributes("-topmost", True)
    canvas = tk.Canvas(top, cursor="cross", highlightthickness=0, bg="black")
    canvas.pack(fill="both", expand=True)
    photo = ImageTk.PhotoImage(shot)
    canvas.create_image(0, 0, image=photo, anchor="nw")
    canvas.photo = photo  # keep a reference or tk garbage-collects it
    rect = None

    def on_press(e):
        nonlocal rect
        start[0], start[1] = e.x, e.y
        rect = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#4f8cc9", width=2)

    def on_drag(e):
        if rect is not None:
            canvas.coords(rect, start[0], start[1], e.x, e.y)

    def on_release(e):
        x1, y1 = min(start[0], e.x), min(start[1], e.y)
        x2, y2 = max(start[0], e.x), max(start[1], e.y)
        if x2 - x1 > 8 and y2 - y1 > 8:
            sel["box"] = (x1, y1, x2, y2)
            sel["canvas_size"] = (canvas.winfo_width(), canvas.winfo_height())
        top.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    top.bind("<Escape>", lambda _e: top.destroy())
    top.focus_force()
    root.wait_window(top)

    if "box" not in sel:
        return None

    # scale tk coords to screenshot pixels in case dpi scaling differs
    cw, ch = sel["canvas_size"]
    sx = shot.width / cw if cw else 1
    sy = shot.height / ch if ch else 1
    x1, y1, x2, y2 = sel["box"]
    return shot.crop((int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy)))


def to_b64_png(img) -> str:
    img = img.copy()
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")
