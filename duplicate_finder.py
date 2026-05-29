# Media Duplicate Finder — Python GUI application for detecting and removing duplicate media files
import os, sys, json, threading, concurrent.futures, shutil, datetime
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, scrolledtext
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
import urllib.request, webbrowser

try:
    from PIL import Image, ImageTk
    import imagehash
    HAS_IMAGE_HASH = True
except ImportError:
    HAS_IMAGE_HASH = False

try:
    import xxhash
    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False

try:
    import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False


IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.ico', '.svg'}
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.webm', '.flv', '.m4v'}
AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma'}
ALL_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS

VERSION = "2.0"
REPO = "BYDofficial1/Duplicare-Media-Deleter"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
MIN_FILE_SIZE = 1
CHUNK_SIZE = 64 * 1024
D_HASH_SIZE = 8



def get_file_type(ext: str) -> str:
    ext = ext.lower()
    if ext in IMAGE_EXTS: return 'Image'
    elif ext in VIDEO_EXTS: return 'Video'
    elif ext in AUDIO_EXTS: return 'Audio'
    return 'Unknown'


def compute_image_hash(file_path: str, hash_size: int = D_HASH_SIZE) -> Optional[str]:
    if not HAS_IMAGE_HASH: return None
    try:
        with Image.open(file_path) as img:
            img = img.convert('RGB').resize((hash_size+1, hash_size))
            h = imagehash.dhash(img, hash_size=hash_size)
            return str(h)
    except Exception:
        return None


def compute_file_hash(file_path: str) -> Optional[str]:
    if not HAS_XXHASH: return None
    try:
        h = xxhash.xxh64()
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk: break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1024**4: return f"{size_bytes/1024**4:.2f} TB"
    elif size_bytes >= 1024**3: return f"{size_bytes/1024**3:.2f} GB"
    elif size_bytes >= 1024**2: return f"{size_bytes/1024**2:.2f} MB"
    elif size_bytes >= 1024: return f"{size_bytes/1024:.1f} KB"
    return f"{size_bytes} bytes"


def scan_folder(folder_path: str, filter_types: Set[str] = None, progress_callback=None, cancel_flag=None) -> List[dict]:
    files = []
    folder = Path(folder_path)
    if not folder.exists(): return files
    all_files = []
    for root, dirs, filenames in os.walk(folder):
        for fn in filenames: all_files.append(os.path.join(root, fn))
    total = len(all_files)
    for i, fp in enumerate(all_files):
        if cancel_flag and cancel_flag(): return []
        if progress_callback: progress_callback(f"Scanning... ({i+1}/{total})", i+1, total)
        ext = os.path.splitext(fp)[1].lower()
        if ext not in ALL_EXTS: continue
        ftype = get_file_type(ext)
        if filter_types and ftype not in filter_types: continue
        try:
            sz = os.path.getsize(fp)
            if sz < MIN_FILE_SIZE: continue
        except OSError: continue
        try: mtime = os.path.getmtime(fp)
        except OSError: mtime = 0
        files.append({'path': fp, 'size': sz, 'ext': ext, 'type': ftype, 'mtime': mtime})
    return files


def find_duplicates(files: List[dict], progress_callback=None, cancel_flag=None, hash_size: int = D_HASH_SIZE) -> List[dict]:
    size_groups: Dict[int, List[dict]] = {}
    for f in files: size_groups.setdefault(f['size'], []).append(f)
    potential = [g for g in size_groups.values() if len(g) > 1]
    total_hash = sum(len(g) for g in potential)
    if total_hash == 0: return []
    file_map = {}
    for g in potential:
        for f in g: file_map[f['path']] = f
    paths = list(file_map.keys())

    def compute(path: str) -> Tuple[str, Optional[str]]:
        if cancel_flag and cancel_flag(): return (path, None)
        info = file_map[path]
        if info['type'] == 'Image':
            return (path, compute_image_hash(path, hash_size))
        else:
            return (path, compute_file_hash(path))

    results: Dict[str, str] = {}
    hashed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        fut = {ex.submit(compute, p): p for p in paths}
        for f in concurrent.futures.as_completed(fut):
            if cancel_flag and cancel_flag(): ex.shutdown(wait=False, cancel_futures=True); return []
            p, h = f.result()
            if progress_callback:
                hashed += 1
                progress_callback(f"Hashing... ({hashed}/{total_hash})", hashed, total_hash)
            if h: results[p] = h
    hg: Dict[str, List[dict]] = {}
    for p, h in results.items(): hg.setdefault(h, []).append(file_map[p])
    dupes, gid = [], 1
    for h, fl in hg.items():
        if len(fl) > 1:
            fl.sort(key=lambda x: os.path.basename(x['path']).lower())
            dupes.append({'id': gid, 'hash': h, 'type': fl[0]['type'], 'files': fl})
            gid += 1
    return dupes


class DuplicateFinderGUI:
    C = {'navy': '#1a1a2e', 'dark': '#16213e', 'accent': '#0f3460', 'pink': '#e94560',
         'bg': '#f0f2f5', 'card': '#ffffff', 'text': '#2c3e50', 'text_light': '#95a5a6',
         'border': '#e0e0e0', 'green': '#27ae60', 'orange': '#f39c12', 'red': '#e74c3c',
         'blue': '#3498db', 'hover_bg': '#e8f0fe', 'header_sub': '#bdc3c7', 'sep_bg': '#f0f4f8'}
    C_DARK = {'navy': '#0d0d1a', 'dark': '#111122', 'accent': '#1a1a3e', 'pink': '#ff6b81',
              'bg': '#1a1a2e', 'card': '#222244', 'text': '#e0e0e0', 'text_light': '#8888aa',
              'border': '#333355', 'green': '#2ecc71', 'orange': '#f1c40f', 'red': '#e74c3c',
              'blue': '#5dade2', 'hover_bg': '#2a2a4e', 'header_sub': '#9999bb', 'sep_bg': '#1e1e3a'}
    FONT = ('Segoe UI', 10); FONT_BOLD = ('Segoe UI', 10, 'bold'); FONT_HEADER = ('Segoe UI', 16, 'bold')
    FONT_SUB = ('Segoe UI', 9); FONT_TITLE = ('Segoe UI', 11, 'bold'); FONT_MONO = ('Consolas', 9)
    TYPE_ICONS = {'Image': '🖼️', 'Video': '🎬', 'Audio': '🎵'}

    def __init__(self, root):
        self.root = root
        self.root.title("Media Duplicate Finder")
        self.root.geometry("1350x760")
        self.dark_mode = False
        self._apply_theme()
        self.folder_path = tk.StringVar()
        self.duplicate_groups: List[dict] = []
        self.check_vars: Dict[str, tk.BooleanVar] = {}
        self.group_parent_ids: Set[str] = set()
        self.scanning = False; self.cancel_flag = False
        self.deleted_paths: Set[str] = set()
        self.filter_img = tk.BooleanVar(value=True)
        self.filter_vid = tk.BooleanVar(value=True)
        self.filter_aud = tk.BooleanVar(value=True)
        self.hash_size = tk.IntVar(value=D_HASH_SIZE)
        self.sort_by = tk.StringVar(value="Group")
        self.preview_img = None
        self.scanned_files: List[dict] = []
        self._setup_styles()
        self._check_deps()
        self._build_ui()
        self.root.after(3000, self._check_updates)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_theme(self):
        self.C = self.C_DARK if self.dark_mode else self.C
        self.root.configure(bg=self.C['bg'])

    def _toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self._apply_theme()
        messagebox.showinfo("Theme", f"{'Dark' if self.dark_mode else 'Light'} mode enabled.\nRestart for full effect.")

    def _setup_styles(self):
        s = ttk.Style(); s.theme_use('clam')
        s.configure('.', font=self.FONT, background=self.C['bg'], foreground=self.C['text'])
        s.configure('TButton', background=self.C['accent'], foreground='white', borderwidth=0, focuscolor='none', font=self.FONT)
        s.map('TButton', background=[('active', '#1a5276'), ('disabled', '#b0b0b0')], foreground=[('disabled', 'white')])
        s.configure('TProgressbar', background=self.C['accent'], troughcolor='#e0e0e0', borderwidth=0, thickness=14)
        s.configure('TEntry', fieldbackground='#fafafa', borderwidth=1, foreground=self.C['text'])
        s.map('TEntry', fieldbackground=[('focus', '#ffffff')])
        s.configure('Treeview', background=self.C['card'], foreground=self.C['text'], rowheight=30, fieldbackground=self.C['card'], font=self.FONT)
        s.configure('Treeview.Heading', background='#f8f9fa', foreground=self.C['text'], font=self.FONT_BOLD, relief='flat', borderwidth=0)
        s.map('Treeview', background=[('selected', self.C['hover_bg'])], foreground=[('selected', self.C['text'])])
        s.map('Treeview.Heading', background=[('active', '#eef0f4')])

    def _check_deps(self):
        missing = []
        if not HAS_IMAGE_HASH: missing.append("• Pillow + imagehash  (pip install Pillow imagehash)")
        if not HAS_XXHASH: missing.append("• xxhash  (pip install xxhash)")
        if missing:
            messagebox.showwarning("Missing Dependencies", "Missing packages:\n\n" + "\n".join(missing) + "\n\nInstall: pip install -r requirements.txt")

    def _build_ui(self):
        self._build_header()
        self._build_toolbar()
        self._build_progress()
        self._build_dashboard()
        self._build_main_area()
        self._build_actions()
        self._build_statusbar()

    def _build_header(self):
        self.hdr = tk.Frame(self.root, bg=self.C['navy'], height=56)
        self.hdr.pack(fill=tk.X); self.hdr.pack_propagate(False)
        tk.Label(self.hdr, text='🖼️', font=('Segoe UI', 20), bg=self.C['navy'], fg='white').place(x=16, y=10)
        tk.Label(self.hdr, text='Media Duplicate Finder', font=self.FONT_HEADER, bg=self.C['navy'], fg='white').place(x=50, y=8)
        tk.Label(self.hdr, text='Find & remove duplicate media files across folders', font=self.FONT_SUB, bg=self.C['navy'], fg=self.C['header_sub']).place(x=50, y=34)
        self.theme_btn = tk.Button(self.hdr, text='🌙', font=('Segoe UI', 14), bg=self.C['navy'], fg='white',
                                    bd=0, cursor='hand2', command=self._toggle_theme)
        self.theme_btn.place(x=865, y=10)

    def _build_toolbar(self):
        outer = tk.Frame(self.root, bg=self.C['bg']); outer.pack(fill=tk.X, padx=12, pady=(8,0))
        card = tk.Frame(outer, bg=self.C['card'], bd=0, highlightbackground=self.C['border'], highlightthickness=1, padx=10, pady=8)
        card.pack(fill=tk.X)
        row = tk.Frame(card, bg=self.C['card']); row.pack(fill=tk.X)
        # Browse
        self._mkbtn(row, '📂 Browse', 'white', self.C['text'], 1, self._browse).pack(side=tk.LEFT)
        # Entry
        e = tk.Entry(row, textvariable=self.folder_path, font=self.FONT, bg='#fafafa', fg=self.C['text'], bd=1, relief='solid')
        e.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6,6), ipady=4); e.configure(state='readonly')
        # Type filters (vertical)
        sep1 = tk.Frame(row, width=1, bg=self.C['border']).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        vbox = tk.Frame(row, bg=self.C['card']); vbox.pack(side=tk.LEFT, padx=(4,0))
        cht = {'side': tk.TOP, 'anchor': 'w', 'padx': 0, 'pady': 0}
        ttk.Checkbutton(vbox, text='🖼️ Images', variable=self.filter_img).pack(**cht)
        ttk.Checkbutton(vbox, text='🎬 Videos', variable=self.filter_vid).pack(**cht)
        ttk.Checkbutton(vbox, text='🎵 Audio', variable=self.filter_aud).pack(**cht)
        # Hash threshold
        sep2 = tk.Frame(row, width=1, bg=self.C['border']).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        tk.Label(row, text='Sensitivity:', font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light']).pack(side=tk.LEFT, padx=(4,2))
        s = ttk.Scale(row, from_=4, to=16, variable=self.hash_size, orient='horizontal', length=60)
        s.pack(side=tk.LEFT)
        self.hash_lbl = tk.Label(row, text=f'{D_HASH_SIZE}', font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text'], width=2)
        self.hash_lbl.pack(side=tk.LEFT)
        s.configure(command=lambda v: self.hash_lbl.config(text=str(int(float(v)))))
        # Sort
        sep3 = tk.Frame(row, width=1, bg=self.C['border']).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        tk.Label(row, text='Sort:', font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light']).pack(side=tk.LEFT, padx=(4,2))
        self.sort_combo = ttk.Combobox(row, textvariable=self.sort_by, values=['Group', 'Size ↓', 'Size ↑', 'Name A-Z', 'Type'], state='readonly', width=10, font=self.FONT_SUB)
        self.sort_combo.pack(side=tk.LEFT)
        self.sort_combo.bind('<<ComboboxSelected>>', lambda e: self._re_sort())
        # Scan button
        self.scan_btn = self._mkbtn(row, '🔍 Scan Now', self.C['accent'], 'white', 0, self._start_scan, bold=True, px=16, py=5)
        self.scan_btn.pack(side=tk.RIGHT, padx=(4,0))
        # Cancel button (hidden)
        self.cancel_btn = self._mkbtn(row, '⏹ Cancel', self.C['red'], 'white', 0, self._cancel_scan, bold=True, px=12, py=5)
        self.cancel_btn.pack_forget()

    def _mkbtn(self, parent, text, bg, fg, bd, cmd, bold=False, px=10, py=4):
        f = self.FONT_BOLD if bold else self.FONT
        if self.dark_mode:
            if bg == self.C['card'] or bg == '#ffffff' or bg == 'white': bg = '#333366'
            if fg == self.C['text'] or fg == '#2c3e50': fg = '#ffffff'
        btn = tk.Button(parent, text=text, font=f, bg=bg, fg=fg, bd=bd, relief='solid' if bd else 'flat',
                         padx=px, pady=py, cursor='hand2', command=cmd)
        self._bind_hover(btn, bg, self.C['hover_bg'] if bg in ('white',self.C['card'],'#ffffff','#333366') else '#1a5276')
        return btn

    def _bind_hover(self, w, n, h):
        w.bind('<Enter>', lambda e: w.configure(bg=h))
        w.bind('<Leave>', lambda e: w.configure(bg=n))

    def _build_progress(self):
        self.prog_frame = tk.Frame(self.root, bg=self.C['card'], bd=0, highlightbackground=self.C['border'], highlightthickness=1, padx=12, pady=8)
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(self.prog_frame, variable=self.progress_var, mode='determinate')
        self.progress.pack(fill=tk.X)
        self.status_label = tk.Label(self.prog_frame, text='Ready', font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light'], anchor='w')
        self.status_label.pack(fill=tk.X, pady=(2,0))

    def _build_dashboard(self):
        self.dash_frame = tk.Frame(self.root, bg=self.C['bg'])

    def _show_dashboard(self, files: List[dict]):
        self.dash_frame.pack_forget()
        for w in self.dash_frame.winfo_children(): w.destroy()
        if not files: return
        self.dash_frame.pack(fill=tk.X, padx=12, pady=(6,0))
        imgs = sum(1 for f in files if f['type']=='Image')
        vids = sum(1 for f in files if f['type']=='Video')
        auds = sum(1 for f in files if f['type']=='Audio')
        total_sz = sum(f['size'] for f in files)
        card = tk.Frame(self.dash_frame, bg=self.C['card'], bd=0, highlightbackground=self.C['border'], highlightthickness=1, padx=12, pady=6)
        card.pack(fill=tk.X)
        items = [
            ('🖼️', 'Images', str(imgs), self.C['blue']),
            ('🎬', 'Videos', str(vids), self.C['orange']),
            ('🎵', 'Audio', str(auds), self.C['green']),
            ('📦', 'Total', str(len(files)), self.C['text']),
            ('💾', 'Size', format_size(total_sz), self.C['red']),
        ]
        for i, (ico, lbl, val, col) in enumerate(items):
            f = tk.Frame(card, bg=self.C['card']); f.pack(side=tk.LEFT, expand=True, fill=tk.X)
            tk.Label(f, text=ico, font=('Segoe UI', 16), bg=self.C['card'], fg=col).pack(side=tk.LEFT, padx=(0,4))
            tf = tk.Frame(f, bg=self.C['card']); tf.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(tf, text=lbl, font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light'], anchor='w').pack(fill=tk.X)
            tk.Label(tf, text=val, font=('Segoe UI', 12, 'bold'), bg=self.C['card'], fg=self.C['text'], anchor='w').pack(fill=tk.X)
            if i < len(items)-1: tk.Frame(card, width=1, bg=self.C['border']).pack(side=tk.LEFT, fill=tk.Y, padx=4)

    def _build_main_area(self):
        main = tk.PanedWindow(self.root, bg=self.C['bg'], sashwidth=4, orient='horizontal')
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=(6,0))
        # Tree
        left = tk.Frame(main, bg=self.C['bg'])
        main.add(left, width=900)
        card = tk.Frame(left, bg=self.C['card'], bd=0, highlightbackground=self.C['border'], highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True)
        cols = ('checked', 'group', 'filename', 'path', 'size', 'type', 'mtime')
        self.tree = ttk.Treeview(card, columns=cols, show='tree headings', height=16, selectmode='extended')
        hdrs = [('checked','Del',50,44,'center'),('group','#',55,50,'center'),('filename','Filename',210,140,'w'),
                ('path','Path',350,180,'w'),('size','Size',90,70,'e'),('type','Type',85,65,'center'),('mtime','Modified',130,80,'e')]
        for c, txt, w, mi, anc in hdrs:
            self.tree.heading(c, text=txt); self.tree.column(c, width=w, minwidth=mi, anchor=anc, stretch=c in('filename','path'))
        self.tree.column('#0', width=22, minwidth=22, stretch=False)
        self.tree.tag_configure('group_parent', background=self.C['sep_bg'], font=('Segoe UI', 10, 'bold'), foreground=self.C['accent'])
        self.tree.tag_configure('child_even', background='#f8faff'); self.tree.tag_configure('child_odd', background=self.C['card'])
        self.tree.tag_configure('original', foreground=self.C['green']); self.tree.tag_configure('dupe', foreground=self.C['text'])
        vsb = ttk.Scrollbar(card, orient='vertical', command=self.tree.yview)
        hsb = ttk.Scrollbar(card, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew'); vsb.grid(row=0, column=1, sticky='ns'); hsb.grid(row=1, column=0, sticky='ew')
        card.grid_rowconfigure(0, weight=1); card.grid_columnconfigure(0, weight=1)
        self.tree.bind('<ButtonRelease-1>', self._on_click)
        self.tree.bind('<space>', lambda e: self._on_click(None))
        self.tree.bind('<Button-3>', self._on_right_click)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        self.tree.bind('<Up>', self._nav_up)
        self.tree.bind('<Down>', self._nav_down)
        self._empty_label = tk.Label(card, font=('Segoe UI', 12), bg=self.C['card'], fg=self.C['text_light'])
        self._show_empty()
        # Preview panel
        right = tk.Frame(main, bg=self.C['bg'], width=250)
        main.add(right, width=250)
        self.preview_card = tk.Frame(right, bg=self.C['card'], bd=0, highlightbackground=self.C['border'], highlightthickness=1)
        self.preview_card.pack(fill=tk.BOTH, expand=True)
        tk.Label(self.preview_card, text='🔍 Preview', font=self.FONT_BOLD, bg=self.C['card'], fg=self.C['text']).pack(padx=10, pady=6, anchor='w')
        self.preview_label = tk.Label(self.preview_card, text='Select a file to preview', font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light'], wraplength=220)
        self.preview_label.pack(padx=10, pady=20, fill=tk.X)
        self.preview_img_label = tk.Label(self.preview_card, bg=self.C['card'])
        self.preview_img_label.pack(padx=10, pady=5)
        self.preview_info = tk.Label(self.preview_card, text='', font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light'], justify='left', wraplength=220)
        self.preview_info.pack(padx=10, pady=5, fill=tk.X)
        self.preview_play_btn = tk.Button(self.preview_card, text='▶ Play', font=self.FONT_BOLD, bg=self.C['green'], fg='white', bd=0, padx=16, pady=6, cursor='hand2', command=self._play_preview)
        self.preview_dur_label = tk.Label(self.preview_card, text='', font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light'], wraplength=220)
        self.preview_dur_label.pack(padx=10, pady=(0,4), fill=tk.X)

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        iid = sel[0]
        if iid in self.group_parent_ids or iid not in self.check_vars: return
        path = iid
        self.preview_label.config(text=os.path.basename(path))
        info_text = f"Path: {os.path.dirname(path)}\nSize: {self._get_tree_val(iid, 'size')}\nType: {self._get_tree_val(iid, 'type')}"
        self.preview_info.config(text=info_text)
        ext = os.path.splitext(path)[1].lower()
        self.preview_play_btn.pack_forget()
        self.preview_dur_label.pack_forget()
        if ext in IMAGE_EXTS and HAS_IMAGE_HASH:
            try:
                img = Image.open(path)
                img.thumbnail((220, 200))
                self.preview_img = ImageTk.PhotoImage(img)
                self.preview_img_label.config(image=self.preview_img)
                self.preview_img_label.image = self.preview_img
            except:
                self.preview_img_label.config(image='')
        else:
            self.preview_img_label.config(image='')
        if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
            self._last_preview_path = path
            lbl = '🎬' if ext in VIDEO_EXTS else '🎵'
            self.preview_play_btn.config(text=f'{lbl}  Play in Player')
            self.preview_play_btn.pack(padx=10, pady=4)
            mt = self._get_tree_val(iid, 'mtime')
            self.preview_dur_label.config(text=f'Click Play to open in system default player')
            self.preview_dur_label.pack(padx=10, pady=(0,4), fill=tk.X)

    def _play_preview(self):
        path = getattr(self, '_last_preview_path', None)
        if not path or not os.path.exists(path): return
        try:
            if sys.platform == 'win32': os.startfile(path)
            elif sys.platform == 'darwin': os.system(f'open "{path}"')
            else: os.system(f'xdg-open "{path}"')
        except: pass

    def _nav_find(self, direction: int):
        all_iids = self.tree.get_children()
        sel = self.tree.selection()
        if not sel: return
        cur = sel[0]
        parent = self.tree.parent(cur) if self.tree.parent(cur) else None
        def find_next_in(parent_iid, start_idx, dir_val):
            sibs = self.tree.get_children(parent_iid) if parent_iid else all_iids
            idx = start_idx
            while 0 <= idx < len(sibs):
                if sibs[idx] not in self.group_parent_ids:
                    return sibs[idx]
                idx += dir_val
            return None
        if parent:
            sibs = self.tree.get_children(parent)
            try: idx = sibs.index(cur)
            except: return
            nxt = find_next_in(parent, idx + direction, direction)
            if nxt:
                self.tree.selection_set(nxt); self.tree.focus(nxt); self.tree.see(nxt)
                self._on_select(None); return
            p_idx = all_iids.index(parent) + direction
            while 0 <= p_idx < len(all_iids):
                nxt = find_next_in(all_iids[p_idx], 0 if direction > 0 else len(self.tree.get_children(all_iids[p_idx]))-1, direction)
                if nxt:
                    self.tree.selection_set(nxt); self.tree.focus(nxt); self.tree.see(nxt)
                    self._on_select(None); return
                p_idx += direction
        else:
            sibs = all_iids
            try: idx = sibs.index(cur)
            except: return
            nxt = find_next_in(None, idx + direction, direction)
            if nxt:
                self.tree.selection_set(nxt); self.tree.focus(nxt); self.tree.see(nxt)
                self._on_select(None)

    def _nav_up(self, event):
        self._nav_find(-1); return 'break'

    def _nav_down(self, event):
        self._nav_find(1); return 'break'

    def _get_tree_val(self, iid, col):
        cols = {'checked':0,'group':1,'filename':2,'path':3,'size':4,'type':5,'mtime':6}
        try: return self.tree.item(iid, 'values')[cols[col]]
        except: return ''

    def _show_empty(self, text=''):
        self.tree.delete(*self.tree.get_children())
        self._empty_label.config(text=text or '📂 Select a folder and click "Scan Now"')
        self._empty_label.place(relx=0.5, rely=0.5, anchor='center')

    def _build_actions(self):
        outer = tk.Frame(self.root, bg=self.C['bg']); outer.pack(fill=tk.X, padx=12, pady=(6,0))
        card = tk.Frame(outer, bg=self.C['card'], bd=0, highlightbackground=self.C['border'], highlightthickness=1, padx=10, pady=8)
        card.pack(fill=tk.X)
        left = tk.Frame(card, bg=self.C['card']); left.pack(side=tk.LEFT)
        self.sel_btn = self._mkbtn(left, '☑ Select Dupes', 'white', self.C['text'], 1, self._select_dupes, px=10, py=4)
        self.sel_btn.pack(side=tk.LEFT, padx=(0,4))
        self.clr_btn = self._mkbtn(left, '☐ Deselect', 'white', self.C['text'], 1, self._deselect_all, px=10, py=4)
        self.clr_btn.pack(side=tk.LEFT, padx=(0,4))
        
        right = tk.Frame(card, bg=self.C['card']); right.pack(side=tk.RIGHT)
        self.del_btn = self._mkbtn(right, '🗑 Delete Selected', self.C['red'], 'white', 0, self._delete_selected, bold=True, px=16, py=5)
        self.del_btn.pack(side=tk.RIGHT)
        self._set_actions_state('disabled')

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=self.C['dark'], height=24); bar.pack(fill=tk.X, side=tk.BOTTOM); bar.pack_propagate(False)
        self.foot_l = tk.Label(bar, text='● Ready', font=self.FONT_SUB, bg=self.C['dark'], fg=self.C['header_sub'])
        self.foot_l.pack(side=tk.LEFT, padx=(10,0))
        self.foot_r = tk.Label(bar, text=f'v{VERSION}  |  ◉ Check Updates', font=self.FONT_SUB, bg=self.C['dark'],
                                fg=self.C['header_sub'], cursor='hand2')
        self.foot_r.pack(side=tk.RIGHT, padx=(0,10))
        self.foot_r.bind('<Button-1>', lambda e: self._check_updates())
        self.foot_r.bind('<Enter>', lambda e: self.foot_r.configure(fg='white'))
        self.foot_r.bind('<Leave>', lambda e: self.foot_r.configure(fg=self.C['header_sub']))

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid in self.group_parent_ids: return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label='📂 Open File Location', command=lambda: self._open_location(iid))
        menu.add_command(label='📋 Copy Path', command=lambda: self._copy_path(iid))
        if iid in self.check_vars:
            checked = self.check_vars[iid].get()
            menu.add_command(label='☑ Toggle Select' if not checked else '☐ Toggle Select', command=lambda: self._toggle_item(iid))
        menu.tk_popup(event.x_root, event.y_root)

    def _open_location(self, iid):
        path = iid
        try:
            if sys.platform == 'win32': os.startfile(os.path.dirname(path))
            elif sys.platform == 'darwin': os.system(f'open "{os.path.dirname(path)}"')
            else: os.system(f'xdg-open "{os.path.dirname(path)}"')
        except: pass

    def _copy_path(self, iid):
        self.root.clipboard_clear(); self.root.clipboard_append(iid)
        self.foot_l.config(text='📋 Path copied!')

    def _toggle_item(self, iid):
        var = self.check_vars.get(iid)
        if var: var.set(not var.get()); self.tree.set(iid, column='checked', value='☑' if var.get() else '☐')

    def _re_sort(self):
        order = self.sort_by.get()
        if order == 'Group': return
        children = list(self.tree.get_children())
        for pid in children:
            kids = list(self.tree.get_children(pid))
            if not kids: continue
            vals = []
            for k in kids:
                v = self.tree.item(k, 'values')
                try: sz = int(v[4].replace(',','').split()[0]) if v[4] else 0
                except: sz = 0
                vals.append((k, sz, v[2].lower(), v[5]))
            if order == 'Size ↓': vals.sort(key=lambda x: -x[1])
            elif order == 'Size ↑': vals.sort(key=lambda x: x[1])
            elif order == 'Name A-Z': vals.sort(key=lambda x: x[2])
            elif order == 'Type': vals.sort(key=lambda x: x[3])
            for i, (k, *_) in enumerate(vals):
                self.tree.move(k, pid, i)

    def _browse(self):
        f = filedialog.askdirectory(title='Select folder')
        if f: self.folder_path.set(f)

    def _get_active_filters(self) -> Set[str]:
        s = set()
        if self.filter_img.get(): s.add('Image')
        if self.filter_vid.get(): s.add('Video')
        if self.filter_aud.get(): s.add('Audio')
        return s

    def _start_scan(self):
        if not self.folder_path.get(): messagebox.showinfo('No Folder', 'Select a folder first.'); return
        if self.scanning: return
        if not self._get_active_filters(): messagebox.showinfo('No Filter', 'Select at least one file type.'); return
        self.scanning = True; self.cancel_flag = False
        self.scan_btn.pack_forget(); self.cancel_btn.pack(side=tk.RIGHT, padx=(4,0))
        self._set_actions_state('disabled')
        self.progress_var.set(0); self.prog_frame.pack(fill=tk.X, padx=12, pady=(6,0))
        self.status_label.config(text='Starting...')
        self.tree.delete(*self.tree.get_children()); self._empty_label.place_forget()
        self.duplicate_groups.clear(); self.check_vars.clear(); self.group_parent_ids.clear(); self.deleted_paths.clear()
        self.dash_frame.pack_forget()
        self.foot_l.config(text='● Scanning...')
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _cancel_scan(self):
        self.cancel_flag = True
        self.status_label.config(text='Cancelling...')

    def _scan_thread(self):
        folder = self.folder_path.get()
        filters = self._get_active_filters()
        try:
            all_files = scan_folder(folder, filters, self._progress, lambda: self.cancel_flag)
            if self.cancel_flag: self.root.after(0, self._scan_cancelled); return
            if not all_files: self.root.after(0, self._no_media); return
            self.scanned_files = all_files
            self.root.after(0, lambda: self._show_dashboard(all_files))
            groups = find_duplicates(all_files, self._progress, lambda: self.cancel_flag, self.hash_size.get())
            if self.cancel_flag: self.root.after(0, self._scan_cancelled); return
            self.root.after(0, lambda: self._show_results(all_files, groups))
        except Exception as e:
            self.root.after(0, lambda: self._error(str(e)))

    def _progress(self, text: str, cur: int, total: int):
        pct = (cur/total)*100 if total else 0
        self.root.after(0, lambda: self.progress_var.set(pct))
        self.root.after(0, lambda: self.status_label.config(text=text))

    def _scan_cancelled(self):
        self.scanning = False; self.cancel_flag = False
        self.cancel_btn.pack_forget(); self.scan_btn.pack(side=tk.RIGHT, padx=(4,0))
        self.prog_frame.pack_forget()
        self.status_label.config(text='Scan cancelled.'); self.foot_l.config(text='● Cancelled')
        self._show_empty()

    def _no_media(self):
        self._scan_done('● No media files found')
        self._show_empty('No media files found in selected folder.')

    def _error(self, msg):
        self._scan_done('● Error')
        messagebox.showerror('Error', f'Scan failed:\n{msg}')

    def _scan_done(self, footer):
        self.scanning = False; self.cancel_flag = False
        self.cancel_btn.pack_forget(); self.scan_btn.pack(side=tk.RIGHT, padx=(4,0))
        self.prog_frame.pack_forget(); self.status_label.config(text='Ready'); self.foot_l.config(text=footer)
        self.progress_var.set(0)

    def _show_results(self, all_files: List[dict], groups: List[dict]):
        self._scan_done('● Ready — Select files to delete' if groups else '● No duplicates found')
        self.duplicate_groups = groups
        total_wasted = sum((len(g['files'])-1)*g['files'][0]['size'] for g in groups)
        for idx, g in enumerate(groups):
            fsz = g['files'][0]['size']
            ico = self.TYPE_ICONS.get(g['type'], '📁')
            parent = f"g_{g['id']}"; self.group_parent_ids.add(parent)
            self.tree.insert('', 'end', iid=parent,
                             values=('', '', f"{ico}  Group #{g['id']} — {len(g['files'])} {g['type']} files — {format_size(fsz)} each", '', '', '', ''),
                             tags=('group_parent',))
            for fi, f in enumerate(g['files']):
                is_dup = fi > 0
                self.check_vars[f['path']] = tk.BooleanVar(value=is_dup)
                tag = 'child_even' if idx%2==0 else 'child_odd'
                mt = datetime.datetime.fromtimestamp(f['mtime']).strftime('%Y-%m-%d %H:%M') if f.get('mtime') else ''
                self.tree.insert(parent, 'end', iid=f['path'],
                                 values=('☑' if is_dup else '☐', f"#{g['id']}", os.path.basename(f['path']),
                                         f['path'], format_size(f['size']), f"{ico} {g['type']}", mt),
                                 tags=(tag, 'dupe' if is_dup else 'original'))
            self.tree.item(parent, open=True)
        dup_cnt = sum(len(g['files'])-1 for g in groups)
        self._show_dashboard(all_files)
        if dup_cnt > 0: self._set_actions_state('normal')
        else: self._set_actions_state('disabled')
        self.foot_l.config(text=f'● {len(groups)} groups, {dup_cnt} dupes, {format_size(total_wasted)} wasted')

    def _set_actions_state(self, state):
        for b in (self.sel_btn, self.clr_btn): b.config(state=state)
        self.del_btn.config(state=state)

    def _on_click(self, event):
        if event:
            col = self.tree.identify_column(event.x)
            if col != '#1': return
            iid = self.tree.identify_row(event.y)
        else:
            sel = self.tree.selection()
            iid = sel[0] if sel else None
        if iid and iid in self.check_vars:
            v = self.check_vars[iid]; v.set(not v.get())
            self.tree.set(iid, column='checked', value='☑' if v.get() else '☐')

    def _select_dupes(self):
        for v in self.check_vars.values(): v.set(False)
        for g in self.duplicate_groups:
            for f in g['files'][1:]:
                if f['path'] in self.check_vars and f['path'] not in self.deleted_paths: self.check_vars[f['path']].set(True)
        self._sync_cb()

    def _deselect_all(self):
        for v in self.check_vars.values(): v.set(False)
        self._sync_cb()

    def _sync_cb(self):
        for p in self.tree.get_children():
            for c in self.tree.get_children(p):
                if c in self.check_vars: self.tree.set(c, column='checked', value='☑' if self.check_vars[c].get() else '☐')

    def _delete_selected(self):
        sel = [p for p,v in self.check_vars.items() if v.get() and p not in self.deleted_paths]
        if not sel: messagebox.showinfo('No Selection', 'No files selected.'); return
        total_sz = sum(os.path.getsize(p) for p in sel if os.path.exists(p))
        self._show_delete_dialog(sel, total_sz)

    def _show_delete_dialog(self, selected: List[str], total_size: int):
        dlg = tk.Toplevel(self.root); dlg.title('Delete Files'); dlg.configure(bg=self.C['card'])
        dlg.resizable(False, False); dlg.transient(self.root); dlg.grab_set()
        w, h = 440, 280; x = self.root.winfo_x()+(self.root.winfo_width()-w)//2; y = self.root.winfo_y()+(self.root.winfo_height()-h)//2
        dlg.geometry(f'{w}x{h}+{x}+{y}')
        tk.Frame(dlg, bg=self.C['navy'], height=44).pack(fill=tk.X)
        tk.Label(dlg, text='🗑 Delete Files', font=self.FONT_BOLD, bg=self.C['navy'], fg='white').place(x=14, y=8)
        body = tk.Frame(dlg, bg=self.C['card'], padx=18, pady=12); body.pack(fill=tk.BOTH, expand=True)
        info = tk.Frame(body, bg=self.C['card']); info.pack(fill=tk.X, pady=(0,10))
        for lbl, val in [('Files:', f'{len(selected)} file(s)'), ('Size:', format_size(total_size))]:
            r = tk.Frame(info, bg=self.C['card']); r.pack(fill=tk.X, pady=1)
            tk.Label(r, text=lbl, font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light'], width=8, anchor='w').pack(side=tk.LEFT)
            tk.Label(r, text=val, font=self.FONT_BOLD, bg=self.C['card'], fg=self.C['text'], anchor='w').pack(side=tk.LEFT)
        bf = tk.Frame(body, bg=self.C['card']); bf.pack(fill=tk.X, pady=(0,4))
        def act(perm, move_to=None):
            dlg.destroy()
            if perm and not messagebox.askyesno('Confirm', 'Permanently delete?\n⚠ This CANNOT be undone.', icon='warning'): return
            self._execute_delete(selected, perm, move_to)
        def move_to():
            dlg.destroy()
            folder = filedialog.askdirectory(title='Select folder to move files to')
            if folder: self._execute_delete(selected, False, folder)
        tk.Button(bf, text='🗑 Move to Recycle Bin (Safe)', font=self.FONT_BOLD, bg=self.C['green'], fg='white',
                  bd=0, padx=12, pady=5, cursor='hand2', command=lambda: act(False)).pack(fill=tk.X, pady=2)
        tk.Button(bf, text='📁 Move to Folder...', font=self.FONT, bg=self.C['blue'], fg='white',
                  bd=0, padx=12, pady=5, cursor='hand2', command=move_to).pack(fill=tk.X, pady=2)
        tk.Button(bf, text='⚠ Delete Permanently', font=self.FONT_BOLD, bg=self.C['red'], fg='white',
                  bd=0, padx=12, pady=5, cursor='hand2', command=lambda: act(True)).pack(fill=tk.X, pady=2)
        btn_bg = '#333366' if self.dark_mode else 'white'
        btn_fg = 'white' if self.dark_mode else self.C['text']
        tk.Button(bf, text='Cancel', font=self.FONT, bg=btn_bg, fg=btn_fg, bd=1, relief='solid',
                  padx=12, pady=3, cursor='hand2', command=dlg.destroy).pack(pady=(3,0))
        dlg.protocol('WM_DELETE_WINDOW', dlg.destroy); dlg.focus_set(); self.root.wait_window(dlg)

    def _execute_delete(self, selected: List[str], permanent: bool, move_to: str = None):
        self._set_actions_state('disabled'); self.del_btn.config(state='disabled', text='⏳ Deleting...')
        self.foot_l.config(text='● Deleting...'); self.root.update()
        deleted, errors = 0, []
        for path in selected:
            try:
                if not os.path.exists(path): continue
                if move_to:
                    dest = os.path.join(move_to, os.path.basename(path))
                    if os.path.exists(dest):
                        base, ext = os.path.splitext(dest); dest = f"{base}_dup{ext}"
                    shutil.move(path, dest)
                elif permanent: os.remove(path)
                else:
                    if not HAS_SEND2TRASH: raise RuntimeError('send2trash not installed')
                    send2trash.send2trash(path)
                deleted += 1; self.deleted_paths.add(path)
            except Exception as e: errors.append(f'{os.path.basename(path)}: {e}')
        for p in self.tree.get_children():
            for c in list(self.tree.get_children(p)):
                if c in self.deleted_paths: self.tree.delete(c); self.check_vars.pop(c, None)
        for p in list(self.group_parent_ids):
            if self.tree.exists(p) and len(self.tree.get_children(p)) < 2: self.tree.delete(p); self.group_parent_ids.discard(p)
        self._update_stats()
        self.del_btn.config(text='🗑 Delete Selected')
        act = 'moved' if move_to else ('permanently deleted' if permanent else 'moved to Recycle Bin')
        if errors: messagebox.showwarning('Partial', f'{deleted}/{len(selected)} {act}.\n\nErrors:\n'+'\n'.join(errors))
        else: messagebox.showinfo('Done', f'{deleted} file(s) {act}.')
        self.foot_l.config(text='● Ready')
        if self.check_vars: self._set_actions_state('normal')

    def _update_stats(self):
        gc, dc, ws = 0, 0, 0
        for p in self.tree.get_children():
            kids = self.tree.get_children(p)
            if len(kids) >= 2:
                gc += 1; dc += len(kids)-1
                try:
                    sz = self.tree.item(kids[0], 'values')[4]
                    for u, m in [('TB',1024**4),('GB',1024**3),('MB',1024**2),('KB',1024)]:
                        if u in str(sz): ws += (len(kids)-1)*int(float(str(sz).replace(f' {u}',''))*m); break
                except: pass
        total_f = sum(1 for _ in self.tree.get_children() for _ in self.tree.get_children(_))
        self._show_dashboard([{'type': 'Image'}] * total_f)  # placeholder
        if dc == 0: self._set_actions_state('disabled'); self.foot_l.config(text='● All duplicates resolved')

    def _check_updates(self):
        self.foot_r.config(text=f'v{VERSION}  |  ⏳ Checking...')
        threading.Thread(target=self._do_update, daemon=True).start()

    def _do_update(self):
        try:
            req = urllib.request.Request(API_URL, headers={'User-Agent': f'MediaDupFinder/{VERSION}'})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read())
                latest = d.get('tag_name','').lstrip('v')
                if latest and latest != VERSION:
                    self.root.after(0, lambda: self._show_update_dlg(latest, d.get('body','')))
                else: self.root.after(0, lambda: self.foot_r.config(text=f'v{VERSION}  |  ✓ Up to date'))
        except: self.root.after(0, lambda: self.foot_r.config(text=f'v{VERSION}  |  ◉ Check Updates'))

    def _show_update_dlg(self, ver, notes):
        dlg = tk.Toplevel(self.root); dlg.title('Update'); dlg.configure(bg=self.C['card'])
        dlg.resizable(False, False); dlg.transient(self.root); dlg.grab_set()
        w, h = 480, 350; x = self.root.winfo_x()+(self.root.winfo_width()-w)//2; y = self.root.winfo_y()+(self.root.winfo_height()-h)//2
        dlg.geometry(f'{w}x{h}+{x}+{y}')
        tk.Frame(dlg, bg=self.C['navy'], height=44).pack(fill=tk.X)
        tk.Label(dlg, text='⬆ Update Available', font=self.FONT_BOLD, bg=self.C['navy'], fg='white').place(x=14, y=8)
        body = tk.Frame(dlg, bg=self.C['card'], padx=16, pady=10); body.pack(fill=tk.BOTH, expand=True)
        for lbl, val in [('Current:', f'v{VERSION}'), ('Latest:', f'v{ver}')]:
            r = tk.Frame(body, bg=self.C['card']); r.pack(fill=tk.X, pady=1)
            tk.Label(r, text=lbl, font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light'], width=10, anchor='w').pack(side=tk.LEFT)
            tk.Label(r, text=val, font=self.FONT_BOLD, bg=self.C['card'], fg=self.C['red'] if 'Latest' in lbl else self.C['text']).pack(side=tk.LEFT)
        tk.Label(body, text='Notes:', font=self.FONT_SUB, bg=self.C['card'], fg=self.C['text_light'], anchor='w').pack(fill=tk.X, pady=(4,2))
        txt = tk.Text(body, font=('Segoe UI',9), bg='#fafafa', fg=self.C['text'], bd=1, relief='solid', padx=6, pady=4, wrap='word', height=6)
        txt.insert('1.0', notes or 'No details.'); txt.config(state='disabled'); txt.pack(fill=tk.BOTH, expand=True, pady=(0,6))
        bf = tk.Frame(body, bg=self.C['card']); bf.pack(fill=tk.X)
        tk.Button(bf, text='⬆ Download & Install', font=self.FONT_BOLD, bg=self.C['green'], fg='white',
                  bd=0, padx=12, pady=5, cursor='hand2', command=lambda: [dlg.destroy(), self._dl_install(ver)]).pack(side=tk.LEFT, padx=(0,4))
        lat_bg = '#333366' if self.dark_mode else 'white'
        lat_fg = 'white' if self.dark_mode else self.C['text']
        tk.Button(bf, text='Later', font=self.FONT, bg=lat_bg, fg=lat_fg, bd=1, relief='solid',
                  padx=12, pady=4, cursor='hand2', command=dlg.destroy).pack(side=tk.LEFT)
        dlg.protocol('WM_DELETE_WINDOW', dlg.destroy); dlg.focus_set(); self.root.wait_window(dlg)

    def _dl_install(self, ver):
        self.foot_l.config(text='● Downloading...'); self.root.update()
        def dl():
            try:
                zurl = f'https://github.com/{REPO}/archive/refs/tags/v{ver}.zip'
                dlp = os.path.join(os.environ.get('TEMP','.'), f'DupUpdate_v{ver}.zip')
                ext = os.path.join(os.environ.get('TEMP','.'), f'DupUpdate_v{ver}')
                urllib.request.urlretrieve(zurl, dlp)
                import zipfile
                with zipfile.ZipFile(dlp,'r') as z: os.makedirs(ext, exist_ok=True); z.extractall(ext)
                self.root.after(0, lambda: self._dl_done(dlp, ext, ver))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror('Error', str(e)))
                self.root.after(0, lambda: self.foot_l.config(text='● Ready'))
        threading.Thread(target=dl, daemon=True).start()

    def _dl_done(self, z, ext, ver):
        messagebox.showinfo('Downloaded', f'Update v{ver} ready at:\n{ext}\n\nClose app, copy files, and restart.')
        webbrowser.open(ext); self.foot_l.config(text='● Ready')

    def _on_close(self):
        try:
            with open('settings.json', 'w') as f:
                json.dump({'dark_mode': self.dark_mode, 'hash_size': self.hash_size.get()}, f)
        except: pass
        self.root.destroy()


def main():
    root = tk.Tk()
    DuplicateFinderGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
 
