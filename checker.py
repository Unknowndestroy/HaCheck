import os
import threading
import time
import psutil
import tkinter as tk
from tkinter import messagebox
import tempfile
import subprocess
import ctypes
from ctypes import wintypes
import queue

# ------------------------
# Win32 API sabitleri vs
# ------------------------

GWL_EXSTYLE      = -20
WS_EX_TOPMOST    = 0x0008
WS_EX_TOOLWINDOW = 0x0080
WS_EX_LAYERED    = 0x80000
WS_EX_NOACTIVATE = 0x08000000

user32 = ctypes.windll.user32
SetWindowLong = user32.SetWindowLongW
GetWindowLong = user32.GetWindowLongW
SetWindowPos = user32.SetWindowPos

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
GetClassName = user32.GetClassNameW
GetWindowText = user32.GetWindowTextW
PostMessage = user32.PostMessageW
SendMessage = user32.SendMessageW

WM_CLOSE = 0x0010

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040

windows_to_close = []

def foreach_window(hwnd, lParam):
    length = 256
    class_name = ctypes.create_unicode_buffer(length)
    GetClassName(hwnd, class_name, length)
    window_text = ctypes.create_unicode_buffer(length)
    GetWindowText(hwnd, window_text, length)

    cls = class_name.value.lower()
    title = window_text.value.lower()

    # Task Manager penceresi
    if "taskmgr" in title or cls == "taskmgr":
        windows_to_close.append(hwnd)
        return True

    # Run dialog penceresi (class #32770 ve title run)
    if cls == "#32770" and ("run" in title or "çalıştır" in title):
        windows_to_close.append(hwnd)
        return True

    # CMD penceresi (class ConsoleWindowClass)
    if cls == "consolewindowclass":
        windows_to_close.append(hwnd)
        return True

    return True

# ------------------------
# Keywordler
# ------------------------

KEYWORDS = [
    "wurst", "liquid", "meteor", "krypton", "alambda", "future", "rusherhack",
    "impact", "konas", "inertia", "hydra", "salhack", "gamesense", "forgehax",
    "skillclient", "aristois", "metro", "huzuni", "nodus", "wolfram", "kami",
    "vapid", "nova", "backdoored", "pyro", "ares", "dotgod.cc", "infinity",
    "rootnet", "vort3x", "helix", "xulu", "xdolf", "mahanware", "esohack",
    "phobos", "kinodupe", "adolf", "g4dmode", "nhack", "etikahack", "sigma"
]

def get_drives():
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:/"
        if os.path.exists(drive):
            drives.append(drive)
    return drives

DRIVE_PATHS = get_drives()

def is_cheatengine_installed():
    installed = False
    program_dirs = [
        os.getenv('PROGRAMFILES', ''),
        os.getenv('PROGRAMFILES(X86)', '')
    ]
    for prog_dir in program_dirs:
        if prog_dir and os.path.isdir(prog_dir):
            for entry in os.listdir(prog_dir):
                if entry.lower().startswith('cheat engine'):
                    installed = True
                    break
        if installed:
            break
    return installed

# ------------------------
# Ana Uygulama Sınıfı
# ------------------------

class HackScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.overrideredirect(True)
        self.root.config(bg='black')
        self.root.geometry('1100x200+100+0')
        self._make_overlay()
        self.root.lift()
        self.root.attributes('-topmost', True)

        self.current_keyword = tk.StringVar(value="Bekleniyor...")
        self.current_dir = tk.StringVar(value="Bekleniyor...")
        self.total_detected = tk.IntVar(value=0)
        self.texture_count = tk.IntVar(value=0)
        self.taskmgr_kill_count = tk.IntVar(value=0)
        self.cmd_run_close_count = tk.IntVar(value=0)

        self.detected_entries = []
        self.txt_detected_list = []
        self.detect_lock = threading.Lock()

        self.create_widgets()

        self.root.after(1000, self.keep_on_top)

        self.stop_event = threading.Event()
        self.scanning_done = threading.Event()

        self.queue_dirs = queue.Queue()
        for drive in DRIVE_PATHS:
            self.queue_dirs.put(drive)

        threading.Thread(target=self.scan_worker, daemon=True).start()
        threading.Thread(target=self.monitor_taskmgr, daemon=True).start()
        threading.Thread(target=self.monitor_cmd_run_taskmgr_windows, daemon=True).start()

        if is_cheatengine_installed():
            messagebox.showinfo("Cheat Engine Tespiti", "Cheat Engine yüklü! Lütfen kontrol et.")

    def _make_overlay(self):
        hwnd = user32.GetParent(self.root.winfo_id())
        ex_style = GetWindowLong(hwnd, GWL_EXSTYLE)
        new_ex_style = ex_style | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE
        SetWindowLong(hwnd, GWL_EXSTYLE, new_ex_style)
        SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

    def keep_on_top(self):
        hwnd = user32.GetParent(self.root.winfo_id())
        SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        self.root.after(1000, self.keep_on_top)

    def create_widgets(self):
        tk.Label(self.root, text="Kontrol Ediliyor:", fg='white', bg='black')\
            .place(x=10, y=5)
        tk.Label(self.root, textvariable=self.current_keyword, fg='lime', bg='black')\
            .place(x=150, y=5)

        tk.Label(self.root, text="Taranan Dizin:", fg='white', bg='black')\
            .place(x=10, y=30)
        tk.Label(self.root, textvariable=self.current_dir, fg='cyan', bg='black')\
            .place(x=150, y=30)

        tk.Label(self.root, text="Tespit Edilen (Toplam):", fg='white', bg='black')\
            .place(x=10, y=55)
        tk.Label(self.root, textvariable=self.total_detected, fg='red', bg='black')\
            .place(x=200, y=55)

        tk.Label(self.root, text="Tespit Edilen (Liste):", fg='white', bg='black')\
            .place(x=10, y=80)
        tk.Button(self.root, text="Liste", command=self.open_detected_list,
                  fg='white', bg='gray20').place(x=350, y=80)

        tk.Label(self.root, text="Tespit Edilen (Texture Pack):", fg='white', bg='black')\
            .place(x=10, y=110)
        tk.Label(self.root, textvariable=self.texture_count, fg='orange', bg='black')\
            .place(x=250, y=110)
        tk.Button(self.root, text="Liste(txt)", command=self.open_txt_list,
                  fg='white', bg='gray20').place(x=350, y=110)

        tk.Label(self.root, text="Engeller (Görev yöneticisi):", fg='white', bg='black')\
            .place(x=10, y=140)
        tk.Label(self.root, textvariable=self.taskmgr_kill_count, fg='yellow', bg='black')\
            .place(x=200, y=140)

        tk.Label(self.root, text="Engeller (Komut istemi, Çalıştır):", fg='white', bg='black')\
            .place(x=10, y=165)
        tk.Label(self.root, textvariable=self.cmd_run_close_count, fg='orange', bg='black')\
            .place(x=250, y=165)

    def open_detected_list(self):
        with self.detect_lock:
            lines = [f"Detected - {kw}: {path}" for kw, path in self.detected_entries]
        content = "\n".join(lines)
        self._open_temp_text("Tespit Edilen Dosyalar", content)

    def open_txt_list(self):
        with self.detect_lock:
            content = "\n".join(self.txt_detected_list)
        self._open_temp_text("Tespit Edilen Texture Pack", content)

    def _open_temp_text(self, title, content):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='w', encoding='utf-8')
        temp_file.write(content)
        temp_file.close()
        if os.name == 'nt':
            os.startfile(temp_file.name)
        else:
            subprocess.call(['open', temp_file.name])

    def scan_worker(self):
        while not self.queue_dirs.empty() and not self.stop_event.is_set():
            root_dir = self.queue_dirs.get()
            self.current_dir.set(root_dir)
            try:
                for dirpath, dirnames, filenames in os.walk(root_dir):
                    for file in filenames:
                        path = os.path.join(dirpath, file)
                        lower_path = path.lower()

                        for kw in KEYWORDS:
                            if kw in lower_path:
                                with self.detect_lock:
                                    self.detected_entries.append((kw, path))
                                    self.total_detected.set(len(self.detected_entries))
                                    self.current_keyword.set(kw)
                                break

                        if file.lower().endswith('.txt') and 'resourcepacks' in lower_path:
                            with self.detect_lock:
                                self.txt_detected_list.append(path)
                                self.texture_count.set(len(self.txt_detected_list))
                    if self.stop_event.is_set():
                        break
            except Exception as e:
                pass
            self.queue_dirs.task_done()

        self.scanning_done.set()

    def monitor_taskmgr(self):
        while not self.stop_event.is_set():
            windows_to_close.clear()
            EnumWindows(EnumWindowsProc(foreach_window), 0)
            for hwnd in windows_to_close:
                PostMessage(hwnd, WM_CLOSE, 0, 0)
                self.taskmgr_kill_count.set(self.taskmgr_kill_count.get() + 1)
            time.sleep(1)

    def monitor_cmd_run_taskmgr_windows(self):
        while not self.stop_event.is_set():
            windows_to_close.clear()
            EnumWindows(EnumWindowsProc(foreach_window), 0)
            for hwnd in windows_to_close:
                PostMessage(hwnd, WM_CLOSE, 0, 0)
                self.cmd_run_close_count.set(self.cmd_run_close_count.get() + 1)
            time.sleep(1)

    def on_close(self):
        self.stop_event.set()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = HackScannerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == '__main__':
    main()
