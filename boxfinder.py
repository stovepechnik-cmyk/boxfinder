# =============================================================================
# BoxFinder — Подборщик коробок
# Version:    1.0
# Platform:   Windows 11 (standalone .exe via PyInstaller)
#
# CAPABILITIES:
#   Парсинг .txt файла: ищет паттерн ЧЧЧхЧЧЧхЧЧЧ (х кириллица или x латиница).
#   Таблица коробок: Д × Ш × В + комментарий (остаток строки).
#   Три поля габаритов груза — мгновенная фильтрация.
#   Авторотация: коробка подходит если вмещает груз в ЛЮБОЙ ориентации.
#   Допуск +5 мм: такие строки видны, но затемнены.
#   Крестик: помечает строку [использована] в файле и скрывает из списка.
#   Автосохранение пути к файлу между запусками (JSON в AppData).
#   Поддержка UTF-8, UTF-8 BOM, Windows-1251.
# =============================================================================

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re
import os
import json
import sys
from itertools import permutations
from pathlib import Path

# ── Константы ─────────────────────────────────────────────────────────────────
APP_NAME    = "BoxFinder — Подборщик коробок"
APP_VERSION = "1.0"
USED_MARKER = "[использована]"
TOLERANCE   = 5

COLORS = {
    "bg":         "#f5f0e4",
    "bg_header":  "#e8dfc8",
    "bg_num":     "#ede5d0",
    "border":     "#c9b99a",
    "text":       "#3a2e1e",
    "muted":      "#9a8a6a",
    "accent":     "#8b4513",
    "match_bg":   "#e8f4e8",
    "near_bg":    "#f5f0e4",   # те же что фон, но opacity через цвет
    "near_fg":    "#c0b090",
    "white":      "#fdf8ee",
    "del_hover":  "#c0392b",
}

FONT_MAIN  = ("Century Gothic", 10)
FONT_SMALL = ("Century Gothic", 9)
FONT_MONO  = ("Consolas", 10, "bold")
FONT_TINY  = ("Century Gothic", 8)

# ── Настройки (JSON в AppData) ─────────────────────────────────────────────────
def prefs_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / "BoxFinder"
    base.mkdir(parents=True, exist_ok=True)
    return base / "prefs.json"

def prefs_load() -> dict:
    try:
        p = prefs_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def prefs_save(data: dict):
    try:
        prefs_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

# ── Парсинг файла ──────────────────────────────────────────────────────────────
DIM_RE = re.compile(r"(\d+)\s*[хxХX]\s*(\d+)\s*[хxХX]\s*(\d+)", re.IGNORECASE)

def read_lines(filepath: str):
    """Читает файл с автоопределением кодировки (UTF-8 BOM / UTF-8 / CP1251)."""
    raw = Path(filepath).read_bytes()
    # Снять BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(enc).splitlines()
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace").splitlines()

def parse_boxes(filepath: str):
    """Возвращает список словарей {dims, comment, raw, line_idx}."""
    lines = read_lines(filepath)
    boxes = []
    for idx, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if s.startswith(USED_MARKER):
            continue
        m = DIM_RE.search(s)
        if not m:
            continue
        dims = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        comment = DIM_RE.sub("", s).strip(" \t-–—,:;()[]")
        boxes.append({"dims": dims, "comment": comment, "raw": s, "line_idx": idx})
    return boxes

def mark_used_in_file(filepath: str, line_idx: int, raw: str) -> bool:
    """Добавляет маркер [использована] в начало нужной строки файла."""
    try:
        lines = read_lines(filepath)
        target = line_idx
        if target >= len(lines) or lines[target].strip() != raw.strip():
            # fallback — ищем по содержимому
            target = next(
                (i for i, l in enumerate(lines)
                 if l.strip() == raw.strip() and not l.strip().startswith(USED_MARKER)),
                None
            )
            if target is None:
                return False
        lines[target] = USED_MARKER + " " + lines[target]
        Path(filepath).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except Exception as e:
        print(f"mark_used error: {e}")
        return False

# ── Логика подбора ─────────────────────────────────────────────────────────────
def check_fit(cargo: tuple, box: tuple):
    """
    'exact'    — вмещается точно
    'loose'    — вмещается с допуском TOLERANCE мм
    'no'       — не вмещается
    Авторотация: проверяем все перестановки осей груза относительно сортированного ящика.
    """
    b = tuple(sorted(box))
    for perm in set(permutations(cargo)):
        if all(perm[i] <= b[i] for i in range(3)):
            return "exact"
    for perm in set(permutations(cargo)):
        if all(perm[i] <= b[i] + TOLERANCE for i in range(3)):
            return "loose"
    return "no"

# ── Главное окно ───────────────────────────────────────────────────────────────
class BoxFinderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("820x520")
        self.minsize(560, 280)
        self.configure(bg=COLORS["bg"])

        # Данные
        self.filepath: str = ""
        self.boxes: list   = []          # все незамаркированные коробки
        self.row_widgets   = []          # список строк таблицы

        self._build_ui()
        self._load_prefs()

    # ── Построение интерфейса ──────────────────────────────────────────────────
    def _build_ui(self):
        self._build_header()
        self._build_table()
        self._build_statusbar()

    def _build_header(self):
        hdr = tk.Frame(self, bg=COLORS["bg_header"],
                       bd=0, highlightthickness=1,
                       highlightbackground=COLORS["border"])
        hdr.pack(fill="x", side="top")

        # Кнопка открыть
        btn = tk.Button(hdr, text="📂  Открыть файл",
                        bg=COLORS["bg_num"], fg=COLORS["accent"],
                        activebackground=COLORS["border"],
                        font=FONT_SMALL, relief="flat", bd=1,
                        padx=10, pady=3, cursor="hand2",
                        command=self._open_file)
        btn.pack(side="left", padx=(8, 4), pady=6)

        # Путь к файлу
        self.lbl_path = tk.Label(hdr, text="файл не выбран",
                                 bg=COLORS["bg_header"], fg=COLORS["muted"],
                                 font=FONT_TINY, anchor="w")
        self.lbl_path.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Разделитель
        tk.Frame(hdr, bg=COLORS["border"], width=1).pack(side="left", fill="y", pady=4)

        # Поля габаритов
        dims_frame = tk.Frame(hdr, bg=COLORS["bg_header"])
        dims_frame.pack(side="left", padx=8)

        tk.Label(dims_frame, text="Габарит:", bg=COLORS["bg_header"],
                 fg=COLORS["muted"], font=FONT_TINY).pack(side="left")

        self.var_d = [tk.StringVar() for _ in range(3)]
        placeholders = ["Д", "Ш", "В"]
        self.dim_entries = []
        for i, (var, ph) in enumerate(zip(self.var_d, placeholders)):
            if i > 0:
                tk.Label(dims_frame, text="×", bg=COLORS["bg_header"],
                         fg=COLORS["muted"], font=FONT_SMALL).pack(side="left", padx=2)
            e = tk.Entry(dims_frame, textvariable=var, width=6,
                         bg=COLORS["white"], fg=COLORS["text"],
                         font=FONT_MONO, relief="flat", bd=1,
                         highlightthickness=1,
                         highlightbackground=COLORS["border"],
                         highlightcolor=COLORS["accent"],
                         justify="center", insertbackground=COLORS["accent"])
            e.pack(side="left", padx=1, ipady=2)
            # Placeholder-эффект
            e._ph = ph
            e.insert(0, ph)
            e.config(fg=COLORS["muted"])
            e.bind("<FocusIn>",  lambda ev, en=e, v=var: self._ph_focus_in(en, v))
            e.bind("<FocusOut>", lambda ev, en=e, v=var: self._ph_focus_out(en, v, en._ph))
            var.trace_add("write", lambda *_: self._filter())
            self.dim_entries.append(e)

        # Кнопка очистить
        btn_clr = tk.Button(dims_frame, text="✕",
                            bg=COLORS["bg_header"], fg=COLORS["muted"],
                            activeforeground=COLORS["accent"],
                            font=FONT_TINY, relief="flat", bd=1,
                            padx=5, cursor="hand2",
                            command=self._clear_dims)
        btn_clr.pack(side="left", padx=(4, 0))

        # Разделитель
        tk.Frame(hdr, bg=COLORS["border"], width=1).pack(side="left", fill="y", pady=4)

        # Счётчик
        self.lbl_counter = tk.Label(hdr, text="", bg=COLORS["bg_header"],
                                    fg=COLORS["muted"], font=FONT_TINY)
        self.lbl_counter.pack(side="left", padx=8)

    def _ph_focus_in(self, entry, var):
        if entry.cget("fg") == COLORS["muted"]:
            entry.delete(0, "end")
            entry.config(fg=COLORS["text"])

    def _ph_focus_out(self, entry, var, ph):
        if not entry.get().strip():
            entry.delete(0, "end")
            entry.insert(0, ph)
            entry.config(fg=COLORS["muted"])

    def _build_table(self):
        # Контейнер с полосой прокрутки
        frame = tk.Frame(self, bg=COLORS["bg"])
        frame.pack(fill="both", expand=True)

        # Заголовок таблицы (фиксированный)
        th = tk.Frame(frame, bg=COLORS["bg_header"],
                      highlightthickness=1,
                      highlightbackground=COLORS["border"])
        th.pack(fill="x", side="top")

        cols = [("#",  40, "e"),
                ("Размер (мм)", 165, "w"),
                ("Комментарий", 0,   "w"),
                ("",  28,  "center")]
        self.col_widths = cols
        for text, w, anchor in cols:
            lbl = tk.Label(th, text=text, bg=COLORS["bg_header"], fg=COLORS["muted"],
                           font=FONT_TINY, anchor=anchor, padx=6, pady=4)
            if w:
                lbl.pack(side="left", width=w)
            else:
                lbl.pack(side="left", fill="x", expand=True)

        # Canvas + Scrollbar для прокрутки строк
        self.canvas = tk.Canvas(frame, bg=COLORS["bg"], highlightthickness=0)
        vsb = tk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.table_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.table_frame, anchor="nw"
        )

        self.table_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>",      self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>",     self._on_mousewheel)
        self.table_frame.bind("<MouseWheel>", self._on_mousewheel)

        # Подсказка "открыть файл"
        self.lbl_hint = tk.Label(self.table_frame,
                                 text="Нажмите «📂 Открыть файл» чтобы загрузить список коробок",
                                 bg=COLORS["bg"], fg=COLORS["muted"],
                                 font=FONT_MAIN, pady=60)
        self.lbl_hint.pack()

    def _on_frame_configure(self, _ev=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, ev):
        self.canvas.itemconfig(self.canvas_window, width=ev.width)

    def _on_mousewheel(self, ev):
        self.canvas.yview_scroll(-1 * (ev.delta // 120), "units")

    def _build_statusbar(self):
        self.statusbar = tk.Label(self, text="", bg=COLORS["bg_header"],
                                  fg=COLORS["muted"], font=FONT_TINY,
                                  anchor="w", padx=8, pady=2,
                                  highlightthickness=1,
                                  highlightbackground=COLORS["border"])
        self.statusbar.pack(fill="x", side="bottom")

    # ── Загрузка файла ─────────────────────────────────────────────────────────
    def _open_file(self):
        init_dir = os.path.dirname(self.filepath) if self.filepath else ""
        path = filedialog.askopenfilename(
            title="Открыть список коробок",
            initialdir=init_dir,
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")]
        )
        if not path:
            return
        self._load_file(path)

    def _load_file(self, path: str):
        try:
            boxes = parse_boxes(path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{path}\n\n{e}")
            return
        if not boxes:
            messagebox.showwarning("Пусто",
                "В файле не найдено ни одной строки с размерами.\n"
                "Ожидаемый формат: 300x200x150 или 300х200х150")
            return
        self.filepath = path
        self.boxes    = boxes
        short = os.path.basename(path)
        self.lbl_path.config(text=short)
        prefs = prefs_load()
        prefs["filepath"] = path
        prefs_save(prefs)
        self._render_table()
        self._filter()
        self._set_status(f"Загружено: {len(boxes)} коробок  ·  {path}")

    # ── Рендер таблицы ─────────────────────────────────────────────────────────
    def _render_table(self):
        # Очищаем
        for w in self.table_frame.winfo_children():
            w.destroy()
        self.row_widgets = []

        if not self.boxes:
            self.lbl_hint = tk.Label(self.table_frame, text="Нет коробок",
                                     bg=COLORS["bg"], fg=COLORS["muted"],
                                     font=FONT_MAIN, pady=40)
            self.lbl_hint.pack()
            return

        for box in self.boxes:
            self._add_row(box)

        self._on_frame_configure()

    def _add_row(self, box: dict):
        idx = len(self.row_widgets)
        row_frame = tk.Frame(self.table_frame, bg=COLORS["bg"],
                             highlightthickness=1,
                             highlightbackground=COLORS["border"])
        row_frame.pack(fill="x")

        # Номер
        lbl_n = tk.Label(row_frame, text=str(idx + 1), width=4,
                         bg=COLORS["bg_num"], fg=COLORS["muted"],
                         font=FONT_TINY, anchor="e", padx=4, pady=4)
        lbl_n.pack(side="left")

        # Размеры
        d = box["dims"]
        lbl_d = tk.Label(row_frame,
                         text=f"{d[0]} × {d[1]} × {d[2]}",
                         width=16,
                         bg=COLORS["bg"], fg=COLORS["accent"],
                         font=FONT_MONO, anchor="w", padx=6, pady=4)
        lbl_d.pack(side="left")

        # Комментарий
        lbl_c = tk.Label(row_frame, text=box["comment"],
                         bg=COLORS["bg"], fg=COLORS["muted"],
                         font=FONT_SMALL, anchor="w", padx=4)
        lbl_c.pack(side="left", fill="x", expand=True)

        # Кнопка удалить
        btn_x = tk.Button(row_frame, text="×", width=2,
                          bg=COLORS["bg"], fg=COLORS["border"],
                          activeforeground=COLORS["del_hover"],
                          activebackground=COLORS["bg"],
                          font=("Arial", 12), relief="flat", bd=0,
                          cursor="hand2",
                          command=lambda b=box, rf=row_frame: self._mark_used(b, rf))
        btn_x.pack(side="right", padx=4)

        # Hover
        for w in (row_frame, lbl_n, lbl_d, lbl_c):
            w.bind("<Enter>", lambda ev, rf=row_frame: self._row_hover(rf, True))
            w.bind("<Leave>", lambda ev, rf=row_frame: self._row_hover(rf, False))
        row_frame.bind("<MouseWheel>", self._on_mousewheel)
        for w in (lbl_n, lbl_d, lbl_c, btn_x):
            w.bind("<MouseWheel>", self._on_mousewheel)

        self.row_widgets.append({
            "frame": row_frame,
            "lbl_n": lbl_n,
            "lbl_d": lbl_d,
            "lbl_c": lbl_c,
            "box":   box,
            "state": "normal",   # normal | match | loose | hidden
        })

    def _row_hover(self, frame, enter: bool):
        # Не меняем hover если уже окрашено как match
        rw = next((r for r in self.row_widgets if r["frame"] is frame), None)
        if rw and rw["state"] == "match":
            return
        color = COLORS["bg_header"] if enter else COLORS["bg"]
        self._row_set_bg(frame, color)

    def _row_set_bg(self, frame, color):
        frame.config(bg=color)
        for child in frame.winfo_children():
            try:
                if child.cget("bg") not in (COLORS["bg_num"],):
                    child.config(bg=color)
            except tk.TclError:
                pass

    # ── Пометить использованной ────────────────────────────────────────────────
    def _mark_used(self, box: dict, row_frame: tk.Frame):
        if self.filepath:
            mark_used_in_file(self.filepath, box["line_idx"], box["raw"])
        row_frame.destroy()
        self.row_widgets = [r for r in self.row_widgets if r["frame"] is not row_frame]
        # Перенумеровать
        for i, r in enumerate(self.row_widgets):
            r["lbl_n"].config(text=str(i + 1))
        self._filter()

    # ── Фильтрация ─────────────────────────────────────────────────────────────
    def _get_dims(self):
        vals = []
        for e, v in zip(self.dim_entries, self.var_d):
            raw = e.get().strip()
            if e.cget("fg") == COLORS["muted"]:
                vals.append(0)
                continue
            try:
                vals.append(int(raw))
            except ValueError:
                vals.append(0)
        return tuple(vals)

    def _filter(self):
        d = self._get_dims()
        entered = [v for v in d if v > 0]
        exact = loose = 0

        for rw in self.row_widgets:
            frame = rw["frame"]
            if not entered:
                rw["state"] = "normal"
                frame.pack(fill="x")
                self._row_set_bg(frame, COLORS["bg"])
                # Восстанавливаем цвет текста
                rw["lbl_d"].config(fg=COLORS["accent"])
                rw["lbl_c"].config(fg=COLORS["muted"])
                continue

            fit = check_fit(d, rw["box"]["dims"])
            if fit == "exact":
                rw["state"] = "match"
                frame.pack(fill="x")
                self._row_set_bg(frame, COLORS["match_bg"])
                rw["lbl_d"].config(fg=COLORS["accent"])
                rw["lbl_c"].config(fg=COLORS["muted"])
                exact += 1
            elif fit == "loose":
                rw["state"] = "loose"
                frame.pack(fill="x")
                self._row_set_bg(frame, COLORS["bg"])
                rw["lbl_d"].config(fg=COLORS["near_fg"])
                rw["lbl_c"].config(fg=COLORS["near_fg"])
                loose += 1
            else:
                rw["state"] = "hidden"
                frame.pack_forget()

        # Счётчик
        alive = len(self.row_widgets)
        if not self.boxes:
            self.lbl_counter.config(text="")
        elif not entered:
            self.lbl_counter.config(text=f"Коробок: {alive}")
        else:
            parts = []
            if exact:  parts.append(f"{exact} подходит")
            if loose:  parts.append(f"{loose} с допуском {TOLERANCE}мм")
            self.lbl_counter.config(
                text=" · ".join(parts) if parts else "нет подходящих"
            )

    def _clear_dims(self):
        for e, v, ph in zip(self.dim_entries, self.var_d, ["Д", "Ш", "В"]):
            v.set("")
            e.delete(0, "end")
            e.insert(0, ph)
            e.config(fg=COLORS["muted"])
        self._filter()

    # ── Статусбар ──────────────────────────────────────────────────────────────
    def _set_status(self, text: str):
        self.statusbar.config(text=text)

    # ── Загрузка настроек при старте ───────────────────────────────────────────
    def _load_prefs(self):
        prefs = prefs_load()
        path = prefs.get("filepath", "")
        if not path:
            return
        if not os.path.exists(path):
            self._set_status(f"Файл из прошлой сессии не найден: {path}")
            return
        self._load_file(path)


# ── Точка входа ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Убираем консоль на Windows (для --windowed PyInstaller)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32  # просто убеждаемся что работает
        except Exception:
            pass

    app = BoxFinderApp()
    app.mainloop()
