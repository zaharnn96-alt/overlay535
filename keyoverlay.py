"""
KeyOverlay - оверлей нажатий клавиш для экрана (не для стрима).

Управление:
  ЛКМ + перетаскивание  - переместить оверлей
  ПКМ                   - меню (настройки, поверх окон, выход)
  Ctrl + Alt + Q        - выход из программы (работает из любого окна)
"""
import copy
import ctypes
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import colorchooser

from pynput import keyboard

_mutex_handle = None  # держим ссылку, чтобы мьютекс жил все время работы

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # чёткая картинка при масштабе 125%+
except Exception:
    pass

APP_DIR = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
           else os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(APP_DIR, "config.json")

DEFAULT_KEYS = [
    {"id": "w", "label": "W", "aliases": ["w"], "x": 1.0, "y": 0, "w": 1, "h": 1},
    {"id": "a", "label": "A", "aliases": ["a"], "x": 0.0, "y": 1, "w": 1, "h": 1},
    {"id": "s", "label": "S", "aliases": ["s"], "x": 1.0, "y": 1, "w": 1, "h": 1},
    {"id": "d", "label": "D", "aliases": ["d"], "x": 2.0, "y": 1, "w": 1, "h": 1},
    {"id": "shift", "label": "SHIFT", "aliases": ["shift", "shift_l", "shift_r"],
     "x": 0.0, "y": 2, "w": 1.6, "h": 1},
    {"id": "ctrl", "label": "CTRL", "aliases": ["ctrl", "ctrl_l", "ctrl_r"],
     "x": 1.7, "y": 2, "w": 1.3, "h": 1},
    {"id": "bksp", "label": "BACKSPACE", "aliases": ["backspace"],
     "x": 3.1, "y": 0, "w": 1.9, "h": 1},
]

DEFAULT_CFG = {
    "unit": 66,
    "gap": 8,
    "padding": 14,
    "radius": 14,
    "depth": 6,
    "press_scale": 0.94,
    "anim_speed": 0.35,
    "opacity": 0.95,
    "font_family": "Segoe UI",
    "font_size": 16,
    "glow": True,
    "show_bg": True,
    "always_on_top": True,
    "x": 80,
    "y": 80,
    "colors": {
        "bg": "#12151c",
        "key": "#1d2130",
        "key_border": "#2d3448",
        "text": "#e6eaf3",
        "accent": "#6d8bff",
        "accent2": "#c084fc",
        "shadow": "#06070b",
    },
    "keys": DEFAULT_KEYS,
}

UI_BG = "#14171f"
UI_FG = "#e6eaf3"
UI_MUTED = "#8b93a7"


# ---------- одиночный запуск ----------

def ensure_single_instance():
    """Если уже запущена другая копия - выходим. Работает только на Windows."""
    global _mutex_handle
    try:
        k32 = ctypes.windll.kernel32
        _mutex_handle = k32.CreateMutexW(None, False, "Local\\KeyOverlaySingleInstance")
        if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            sys.exit(0)
    except Exception:
        pass


# ---------- конфиг ----------

def load_cfg():
    cfg = copy.deepcopy(DEFAULT_CFG)
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if k == "colors" and isinstance(v, dict):
                    cfg["colors"].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


def save_cfg(cfg):
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


# ---------- цвета и геометрия ----------

def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    ra, ga, ba = hex2rgb(a)
    rb, gb, bb = hex2rgb(b)
    return "#%02x%02x%02x" % (round(ra + (rb - ra) * t),
                              round(ga + (gb - ga) * t),
                              round(ba + (bb - ba) * t))


def rrect(c, x1, y1, x2, y2, r, **kw):
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    if r < 1:
        c.create_rectangle(x1, y1, x2, y2, **kw)
        return
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    c.create_polygon(pts, smooth=True, **kw)


# ---------- слушатель клавиатуры ----------

CTRL_NAMES = {"ctrl", "ctrl_l", "ctrl_r"}
ALT_NAMES = {"alt", "alt_l", "alt_r", "alt_gr"}


class KeyWatcher:
    def __init__(self):
        self._down = set()
        self._lock = threading.Lock()
        self.quit_requested = False
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.daemon = True
        self._listener.start()

    @staticmethod
    def _name(key):
        if isinstance(key, keyboard.Key):
            return key.name
        vk = getattr(key, "vk", None)
        if vk and 65 <= vk <= 90:  # буквы по коду клавиши: работает с Ctrl и с русской раскладкой
            return chr(vk).lower()
        ch = getattr(key, "char", None)
        return ch.lower() if ch else None

    def _press(self, key):
        n = self._name(key)
        if not n:
            return
        with self._lock:
            self._down.add(n)
            d = self._down
            if "q" in d and d & CTRL_NAMES and d & ALT_NAMES:
                self.quit_requested = True

    def _release(self, key):
        n = self._name(key)
        if n:
            with self._lock:
                self._down.discard(n)

    def snapshot(self):
        with self._lock:
            return set(self._down)

    def stop(self):
        try:
            self._listener.stop()
        except Exception:
            pass


# ---------- оверлей ----------

class Overlay:
    def __init__(self, root, cfg, watcher):
        self.root = root
        self.cfg = cfg
        self.watcher = watcher
        self.anim = {k["id"]: 0.0 for k in cfg["keys"]}
        self.settings_win = None
        self._closing = False

        root.overrideredirect(True)
        root.title("KeyOverlay")

        self.key_transparent = "#010101"
        root.configure(bg=self.key_transparent)
        try:
            root.attributes("-transparentcolor", self.key_transparent)
        except tk.TclError:
            self.key_transparent = cfg["colors"]["bg"]
            root.configure(bg=self.key_transparent)

        self.canvas = tk.Canvas(root, highlightthickness=0, bd=0, bg=self.key_transparent)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: save_cfg(self.cfg))
        self.canvas.bind("<Button-3>", self._menu_popup)

        self._top_var = tk.BooleanVar(value=cfg["always_on_top"])
        self.menu = tk.Menu(root, tearoff=0, bg=UI_BG, fg=UI_FG, activebackground="#2a3040",
                            activeforeground=UI_FG, bd=0)
        self.menu.add_command(label="Настройки…", command=self.open_settings)
        self.menu.add_checkbutton(label="Поверх всех окон", variable=self._top_var,
                                  command=self._toggle_top)
        self.menu.add_separator()
        self.menu.add_command(label="Выход            Ctrl+Alt+Q", command=self.quit)

        self.apply_window()
        self._tick()

    # --- геометрия ---

    def _size(self):
        u, g, p = self.cfg["unit"], self.cfg["gap"], self.cfg["padding"]
        cols = max(k["x"] + k["w"] for k in self.cfg["keys"])
        rows = max(k["y"] + k.get("h", 1) for k in self.cfg["keys"])
        return int(2 * p + cols * (u + g) - g), int(2 * p + rows * (u + g) - g)

    def apply_window(self):
        W, H = self._size()
        self.root.geometry(f"{W}x{H}+{self.cfg['x']}+{self.cfg['y']}")
        self.canvas.config(width=W, height=H)
        self.root.attributes("-alpha", self.cfg["opacity"])
        self.root.attributes("-topmost", self.cfg["always_on_top"])
        self._top_var.set(self.cfg["always_on_top"])

    # --- анимация ---

    def _tick(self):
        if self._closing:
            return
        if self.watcher.quit_requested:
            self.quit()
            return
        down = self.watcher.snapshot()
        speed = self.cfg["anim_speed"]
        for k in self.cfg["keys"]:
            kid = k["id"]
            target = 1.0 if any(a in down for a in k["aliases"]) else 0.0
            t = self.anim.setdefault(kid, 0.0)
            step = speed * 1.8 if target > t else speed
            t += (target - t) * step
            if abs(target - t) < 0.002:
                t = target
            self.anim[kid] = t
        self._draw()
        self.root.after(16, self._tick)

    # --- отрисовка ---

    def _draw(self):
        c = self.canvas
        c.delete("all")
        cfg = self.cfg
        col = cfg["colors"]
        u, g, p, r = cfg["unit"], cfg["gap"], cfg["padding"], cfg["radius"]
        depth, scale = cfg["depth"], cfg["press_scale"]
        W, H = self._size()

        if cfg["show_bg"]:
            rrect(c, 0, 0, W - 1, H - 1, r + p / 2,
                  fill=col["bg"], outline=mix(col["bg"], "#ffffff", 0.07), width=1)

        for k in cfg["keys"]:
            t = self.anim.get(k["id"], 0.0)
            x = p + k["x"] * (u + g)
            y = p + k["y"] * (u + g)
            w = k["w"] * (u + g) - g
            h = k.get("h", 1) * (u + g) - g

            ins = (1 - scale) * min(w, h) / 2 * t
            d = depth * t

            rrect(c, x, y + depth, x + w, y + h + depth, r, fill=col["shadow"])

            bx1, by1 = x + ins, y + ins + d
            bx2, by2 = x + w - ins, y + h - ins + d

            if cfg["glow"] and t > 0.01:
                for pad, fac in ((6, 0.45), (12, 0.2)):
                    rrect(c, bx1 - pad, by1 - pad, bx2 + pad, by2 + pad, r + pad,
                          fill="", outline=mix(col["bg"], col["accent"], fac * t), width=2)

            rrect(c, bx1, by1, bx2, by2, r,
                  fill=mix(col["key"], col["accent"], 0.85 * t),
                  outline=mix(col["key_border"], col["accent2"], t), width=1)

            label = k["label"]
            fs = cfg["font_size"]
            if len(label) > 4:
                fs = max(8, int(fs * 0.72))
            c.create_text((bx1 + bx2) / 2, (by1 + by2) / 2, text=label,
                          fill=mix(col["text"], "#ffffff", t),
                          font=(cfg["font_family"], fs, "bold"))

    # --- перетаскивание и меню ---

    def _drag_start(self, e):
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        x = e.x_root - self._dx
        y = e.y_root - self._dy
        self.cfg["x"], self.cfg["y"] = x, y
        self.root.geometry(f"+{x}+{y}")

    def _menu_popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _toggle_top(self):
        self.cfg["always_on_top"] = self._top_var.get()
        self.apply_window()

    def open_settings(self):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        self.settings_win = SettingsWindow(self.root, self)

    def quit(self):
        """Полное завершение: сохранить, остановить слушатель клавиатуры, закрыть окно."""
        if self._closing:
            return
        self._closing = True
        save_cfg(self.cfg)
        self.watcher.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


# ---------- окно настроек (применяется сразу) ----------

class SettingsWindow(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        cfg = app.cfg
        self.title("KeyOverlay - настройки")
        self.configure(bg=UI_BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        frm = tk.Frame(self, bg=UI_BG, padx=20, pady=16)
        frm.pack()

        tk.Label(frm, text="Настройки", bg=UI_BG, fg=UI_FG,
                 font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2,
                                                      sticky="w", pady=(0, 10))
        specs = [
            ("Размер клавиши", "unit", 30, 120, 1),
            ("Расстояние", "gap", 0, 30, 1),
            ("Скругление", "radius", 0, 40, 1),
            ("Глубина 3D", "depth", 0, 14, 1),
            ("Сжатие при нажатии", "press_scale", 0.7, 1.0, 0.01),
            ("Скорость анимации", "anim_speed", 0.05, 1.0, 0.01),
            ("Прозрачность", "opacity", 0.2, 1.0, 0.01),
            ("Размер шрифта", "font_size", 8, 40, 1),
            ("Отступ панели", "padding", 0, 40, 1),
        ]
        row = 1
        for label, key, lo, hi, res in specs:
            self._scale(frm, row, label, key, lo, hi, res)
            row += 1

        tk.Label(frm, text="Цвета", bg=UI_BG, fg=UI_MUTED,
                 font=("Segoe UI", 10, "bold")).grid(row=row, column=0, columnspan=2,
                                                      sticky="w", pady=(10, 4))
        row += 1
        for label, key in [("Фон панели", "bg"), ("Клавиша", "key"), ("Рамка", "key_border"),
                           ("Текст", "text"), ("Акцент", "accent"), ("Акцент 2", "accent2"),
                           ("Тень", "shadow")]:
            self._color(frm, row, label, key)
            row += 1

        tk.Label(frm, text="Опции", bg=UI_BG, fg=UI_MUTED,
                 font=("Segoe UI", 10, "bold")).grid(row=row, column=0, columnspan=2,
                                                      sticky="w", pady=(10, 4))
        row += 1
        for label, key in [("Подложка-панель", "show_bg"), ("Свечение", "glow"),
                           ("Поверх всех окон", "always_on_top")]:
            self._check(frm, row, label, key)
            row += 1

        btns = tk.Frame(frm, bg=UI_BG)
        btns.grid(row=row, column=0, columnspan=2, sticky="we", pady=(14, 0))
        self.status = tk.Label(btns, text="", bg=UI_BG, fg=UI_MUTED, font=("Segoe UI", 9))
        self.status.pack(side="left")
        self._btn(btns, "Сбросить", self._reset).pack(side="right", padx=(6, 0))
        self._btn(btns, "Сохранить", self._save).pack(side="right")

    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=self.app.cfg["colors"]["accent"],
                         fg="#ffffff", relief="flat", padx=12, pady=4,
                         activebackground=self.app.cfg["colors"]["accent2"],
                         activeforeground="#ffffff", cursor="hand2")

    def _scale(self, parent, row, label, key, lo, hi, res):
        tk.Label(parent, text=label, bg=UI_BG, fg=UI_FG,
                 font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 14))
        var = tk.DoubleVar(value=self.app.cfg[key])
        is_int = isinstance(DEFAULT_CFG[key], int)

        def on_change(v, k=key, i=is_int):
            self.app.cfg[k] = round(float(v)) if i else round(float(v), 2)
            self.app.apply_window()

        tk.Scale(parent, from_=lo, to=hi, resolution=res, orient="horizontal", length=220,
                 variable=var, command=on_change, showvalue=True, bg=UI_BG, fg=UI_FG,
                 troughcolor="#2a3040", highlightthickness=0, bd=0,
                 activebackground=UI_FG).grid(row=row, column=1, sticky="we")

    def _color(self, parent, row, label, key):
        tk.Label(parent, text=label, bg=UI_BG, fg=UI_FG,
                 font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=2)
        btn = tk.Button(parent, width=12, bg=self.app.cfg["colors"][key], fg="#ffffff",
                        relief="flat", cursor="hand2")

        def pick():
            res = colorchooser.askcolor(color=self.app.cfg["colors"][key], parent=self)
            if res and res[1]:
                self.app.cfg["colors"][key] = res[1]
                btn.config(bg=res[1])
                self.app.apply_window()

        btn.config(command=pick)
        btn.grid(row=row, column=1, sticky="w", pady=2)

    def _check(self, parent, row, label, key):
        var = tk.BooleanVar(value=self.app.cfg[key])

        def on_toggle(k=key, v=var):
            self.app.cfg[k] = v.get()
            self.app.apply_window()

        tk.Checkbutton(parent, text=label, variable=var, command=on_toggle, bg=UI_BG,
                       fg=UI_FG, selectcolor="#2a3040", activebackground=UI_BG,
                       activeforeground=UI_FG, font=("Segoe UI", 10)
                       ).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)

    def _save(self):
        ok = save_cfg(self.app.cfg)
        self.status.config(text="Сохранено" if ok else "Ошибка записи",
                           fg=UI_FG if ok else "#ff6b6b")

    def _reset(self):
        cfg = self.app.cfg
        keep_pos = (cfg["x"], cfg["y"])
        cfg.clear()
        cfg.update(copy.deepcopy(DEFAULT_CFG))
        cfg["x"], cfg["y"] = keep_pos
        self.app.anim = {k["id"]: self.app.anim.get(k["id"], 0.0) for k in cfg["keys"]}
        self.app.apply_window()
        self.destroy()
        self.app.open_settings()


def main():
    ensure_single_instance()
    cfg = load_cfg()
    root = tk.Tk()
    watcher = KeyWatcher()
    Overlay(root, cfg, watcher)
    try:
        root.mainloop()
    finally:
        watcher.stop()


if __name__ == "__main__":
    main()
