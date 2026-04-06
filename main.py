import customtkinter as ctk
import pandas as pd
from pypinyin import pinyin, Style
from datetime import datetime, timedelta
import os
from tkinter import messagebox, ttk
import threading
import time

# --- Matplotlib cho Dashboard ---
try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MPL_AVAILABLE = True
except ImportError:
    MPL_AVAILABLE = False

# --- TTS ---
try:
    from gtts import gTTS
    import pygame
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

# ── CẤU HÌNH ────────────────────────────────────────────────
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

DATA_FILE         = "library.xlsx"
MAX_HANZI_SIZE    = 300
MEANING_FONT_SIZE = 50
PINYIN_FONT_SIZE  = 40
UI_FONT_SIZE      = 18
TABLE_FONT_SIZE   = 16
TABLE_ROW_HEIGHT  = 50
HANZI_FONT_NAME   = "Ma Shan Zheng"
AUDIO_CACHE_DIR   = "audio_cache"
FADE_STEPS        = 12
FADE_MS           = 18
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)


# ════════════════════════════════════════════════════════════
#  TTS PLAYER
# ════════════════════════════════════════════════════════════
def _init_pygame():
    if TTS_AVAILABLE:
        try:
            pygame.mixer.init()
        except Exception:
            pass


class TTSPlayer:
    def __init__(self):
        self._lock = threading.Lock()
        if TTS_AVAILABLE:
            _init_pygame()

    def speak(self, text: str):
        if not TTS_AVAILABLE or not text:
            return
        threading.Thread(target=self._play, args=(text,), daemon=True).start()

    def _play(self, text: str):
        with self._lock:
            try:
                safe = "".join(c if c.isalnum() else "_" for c in text[:30])
                path = os.path.join(AUDIO_CACHE_DIR, f"{safe}.mp3")
                if not os.path.exists(path):
                    gTTS(text=text, lang="zh-CN", slow=False).save(path)
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
            except Exception as e:
                print(f"[TTS] {e}")


# ════════════════════════════════════════════════════════════
#  APP CHÍNH
# ════════════════════════════════════════════════════════════
class ChineseLearningApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("On Tap Tieng Trung  v2")

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}")
        self.after(0, lambda: self.state("zoomed") if os.name == "nt"
                   else self.attributes("-zoomed", True))

        self.df                   = self.load_data()
        self.current_review_list  = pd.DataFrame()
        self.current_index        = 0
        self.step                 = 0
        self.is_cram_mode         = False
        self._undo_stack: list    = []
        self._session_ok          = 0
        self._session_forgot      = 0

        self.tts                  = TTSPlayer()
        self._arrow_press_start   = {}
        self._arrow_hold_threshold = 2.0

        # ── Tabs ──
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=20, fill="both", expand=True)
        self.tabview._segmented_button.configure(font=("Arial", 20, "bold"))

        self.tab_review = self.tabview.add("On Tap")
        self.tab_manage = self.tabview.add("Quan Ly & Tra Cuu")
        self.tab_dash   = self.tabview.add("Dashboard")

        self.setup_review_tab()
        self.setup_manage_tab()
        self.setup_dashboard_tab()

        # Bind phím
        self.bind("<KeyPress-Right>",  self._on_right_press)
        self.bind("<KeyRelease-Right>", self._on_right_release)
        self.bind("<KeyPress-Left>",   self._on_left_press)
        self.bind("<KeyRelease-Left>",  self._on_left_release)
        self.bind("<z>", lambda e: self.undo_last())
        self.bind("<Z>", lambda e: self.undo_last())

        self.tabview.configure(command=self._on_tab_change)

    # ════════════════════════════════════════════════════════
    #  DU LIEU
    # ════════════════════════════════════════════════════════
    def load_data(self):
        cols = ["Hanzi", "Pinyin", "Meaning", "Date", "Level", "Next_Review"]
        if not os.path.exists(DATA_FILE):
            df = pd.DataFrame(columns=cols)
            df.to_excel(DATA_FILE, index=False)
            return df
        try:
            df = pd.read_excel(DATA_FILE)
            if "Pinyin"      not in df.columns: df["Pinyin"]      = df["Hanzi"].apply(self.generate_pinyin)
            if "Level"       not in df.columns: df["Level"]       = 0
            if "Next_Review" not in df.columns: df["Next_Review"] = pd.to_datetime(df["Date"])
            df["Date"]        = pd.to_datetime(df["Date"])
            df["Next_Review"] = pd.to_datetime(df["Next_Review"])
            df.to_excel(DATA_FILE, index=False)
            return df
        except Exception as e:
            messagebox.showerror("Loi", f"Loi file: {e}")
            return pd.DataFrame(columns=cols)

    def save_data(self):
        self.df.to_excel(DATA_FILE, index=False)

    def generate_pinyin(self, text):
        if not isinstance(text, str):
            return ""
        return " ".join(item[0] for item in pinyin(text, style=Style.TONE, heteronym=False))

    # ════════════════════════════════════════════════════════
    #  TAB 1 - ON TAP
    # ════════════════════════════════════════════════════════
    def setup_review_tab(self):
        ctrl = ctk.CTkFrame(self.tab_review, height=80)
        ctrl.pack(pady=10, fill="x", padx=10)

        self.btn_smart_review = ctk.CTkButton(
            ctrl, text="Hoc tu theo ngay", command=self.start_smart_review,
            fg_color="#2ecc71", text_color="black",
            font=("Arial", UI_FONT_SIZE, "bold"), height=50, width=300)
        self.btn_smart_review.pack(side="left", padx=20, pady=10)

        self.btn_cram = ctk.CTkButton(
            ctrl, text="On cap toc", command=self.start_cram_review,
            fg_color="#e74c3c", font=("Arial", UI_FONT_SIZE, "bold"), height=50, width=200)
        self.btn_cram.pack(side="right", padx=(10, 20), pady=10)

        self.cram_option_var = ctk.StringVar(value="10")
        ctk.CTkOptionMenu(ctrl, values=["10","50","100","200","500","1000"],
                          variable=self.cram_option_var,
                          width=100, height=40,
                          font=("Arial", UI_FONT_SIZE)).pack(side="right", pady=10)
        ctk.CTkLabel(ctrl, text="SL:", font=("Arial", UI_FONT_SIZE)).pack(side="right", padx=10)

        # Progress
        pf = ctk.CTkFrame(self.tab_review, fg_color="transparent")
        pf.pack(pady=(10, 0), fill="x", padx=50)
        self.progress_bar = ctk.CTkProgressBar(pf, height=10, corner_radius=8,
                                                progress_color="#094297")
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)
        self.lbl_progress_text = ctk.CTkLabel(pf, text="0 / 0", font=("Arial", 16))
        self.lbl_progress_text.pack(pady=5)

        # Flashcard
        self.card_frame = ctk.CTkFrame(self.tab_review, fg_color="transparent")
        self.card_frame.pack(pady=10, expand=True, fill="both")

        mr = ctk.CTkFrame(self.card_frame, fg_color="transparent")
        mr.pack(pady=(20, 0))
        self.lbl_meaning = ctk.CTkLabel(mr, text="San sang?",
                                         font=("Arial", MEANING_FONT_SIZE, "bold"),
                                         text_color="#1f6aa5", wraplength=1000)
        self.lbl_meaning.pack(side="left", padx=(0, 10))
        ctk.CTkButton(mr, text="🔊", width=50, height=50, font=("Arial", 24),
                      fg_color="transparent", hover_color="#2a2a2a",
                      command=self._speak_current_hanzi).pack(side="left")

        self.lbl_pinyin = ctk.CTkLabel(self.card_frame, text="---",
                                        font=("Arial", PINYIN_FONT_SIZE),
                                        text_color="#d68910", wraplength=1000)
        self.lbl_pinyin.pack(pady=10)

        self.lbl_hanzi = ctk.CTkLabel(self.card_frame, text="---",
                                       font=(HANZI_FONT_NAME, MAX_HANZI_SIZE))
        self.lbl_hanzi.pack(pady=20, expand=True)

        # Bottom buttons
        self.bottom_frame = ctk.CTkFrame(self.tab_review, fg_color="transparent", height=120)
        self.bottom_frame.pack(pady=(10, 20), fill="x")

        # Row 1: Hien dap an + Undo
        top_row = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        top_row.pack(pady=(0, 10))

        self.btn_next_step = ctk.CTkButton(
            top_row, text="Hien dap an  [Space]",
            width=400, height=70, command=self.next_step,
            font=("Arial", 24, "bold"))
        self.btn_next_step.pack(side="left", padx=(0, 16))

        self.btn_undo = ctk.CTkButton(
            top_row, text="Hoan tac  [Z]",
            width=180, height=70, command=self.undo_last,
            fg_color="#7f8c8d", hover_color="#5d6d7e",
            font=("Arial", 18, "bold"))
        self.btn_undo.pack(side="left")
        self.btn_undo.pack_forget()

        # Row 2: QUEN | NHO
        self.btn_forgot = ctk.CTkButton(
            self.bottom_frame, text="QUEN",
            fg_color="#e74c3c", command=lambda: self.rate_word("forgot"),
            width=300, height=70, font=("Arial", 22, "bold"))
        self.btn_ok = ctk.CTkButton(
            self.bottom_frame, text="NHO",
            fg_color="#2ecc71", command=lambda: self.rate_word("ok"),
            width=300, height=70, font=("Arial", 22, "bold"))

        self.bind("<space>", lambda e: self.next_step())
        self.toggle_eval_buttons(False)

    def _speak_current_hanzi(self):
        if self.current_review_list.empty:
            return
        self.tts.speak(self.current_review_list.iloc[self.current_index]["Hanzi"])

    def update_hanzi_display(self, text):
        sw = self.winfo_width()
        if sw < 100:
            sw = self.winfo_screenwidth()
        avail = sw - 200
        n     = len(text)
        if n == 0:
            return
        size = min(MAX_HANZI_SIZE, int(avail / (n * 1.1)))
        if size < 80:
            size = 100
            self.lbl_hanzi.configure(wraplength=avail)
        else:
            self.lbl_hanzi.configure(wraplength=9999)
        self.lbl_hanzi.configure(text=text, font=(HANZI_FONT_NAME, size))

    # ════════════════════════════════════════════════════════
    #  FADE ANIMATION
    # ════════════════════════════════════════════════════════
    def _fade_in(self, widget, final_text, final_font=None,
                 final_color=None, step=0):
        if step == 0:
            try:
                bg = widget.master.cget("fg_color")
                if isinstance(bg, (list, tuple)):
                    bg = bg[0] if ctk.get_appearance_mode() == "Light" else bg[1]
            except Exception:
                bg = "#1a1a1a" if ctk.get_appearance_mode() == "Dark" else "#f0f0f0"
            self._fade_bg = bg
            if final_text is not None:
                widget.configure(text=final_text)
            if final_font is not None:
                widget.configure(font=final_font)

        alpha  = (step + 1) / FADE_STEPS
        tc     = final_color if final_color else self._get_label_color(widget)
        blended = self._blend_hex(self._fade_bg, tc, alpha)
        widget.configure(text_color=blended)

        if step < FADE_STEPS - 1:
            self.after(FADE_MS, lambda: self._fade_in(
                widget, None, None, final_color, step + 1))
        else:
            widget.configure(text_color=tc)

    def _get_label_color(self, lbl):
        try:
            c = lbl.cget("text_color")
            if isinstance(c, (list, tuple)):
                return c[0] if ctk.get_appearance_mode() == "Light" else c[1]
            return c or "#ffffff"
        except Exception:
            return "#ffffff"

    @staticmethod
    def _blend_hex(c1, c2, t):
        def parse(h):
            h = h.strip("#")
            if len(h) == 3:
                h = "".join(x*2 for x in h)
            return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        try:
            r1,g1,b1 = parse(c1); r2,g2,b2 = parse(c2)
            return "#{:02x}{:02x}{:02x}".format(
                int(r1+(r2-r1)*t), int(g1+(g2-g1)*t), int(b1+(b2-b1)*t))
        except Exception:
            return c2

    # ════════════════════════════════════════════════════════
    #  ARROW KEY HOLD
    # ════════════════════════════════════════════════════════
    def _on_right_press(self, _):
        if "right" not in self._arrow_press_start:
            self._arrow_press_start["right"] = time.time()
            self._schedule_hold("right")

    def _on_right_release(self, _): self._arrow_press_start.pop("right", None)

    def _on_left_press(self, _):
        if "left" not in self._arrow_press_start:
            self._arrow_press_start["left"] = time.time()
            self._schedule_hold("left")

    def _on_left_release(self, _): self._arrow_press_start.pop("left", None)

    def _schedule_hold(self, direction):
        def check():
            t0 = self._arrow_press_start.get(direction)
            if t0 is None:
                return
            if time.time() - t0 >= self._arrow_hold_threshold:
                self._arrow_press_start.pop(direction, None)
                if self.step == 2:
                    self.after(0, lambda: self.rate_word(
                        "ok" if direction == "right" else "forgot"))
            else:
                self.after(100, check)
        self.after(100, check)

    # ════════════════════════════════════════════════════════
    #  SESSION
    # ════════════════════════════════════════════════════════
    def start_smart_review(self):
        self.is_cram_mode = False
        mask = self.df["Next_Review"].dt.date <= datetime.now().date()
        due  = self.df[mask]
        if due.empty:
            messagebox.showinfo("Tuyet voi!", "Ban da on het tu can hoc hom nay!")
            return
        self.current_review_list = due.sample(frac=1).reset_index(drop=True)
        self._start_session(len(self.current_review_list))

    def start_cram_review(self):
        self.is_cram_mode = True
        try:   amount = int(self.cram_option_var.get())
        except: amount = 10
        if self.df.empty:
            return
        n = min(amount, len(self.df))
        self.current_review_list = self.df.sample(n).reset_index(drop=True)
        self._start_session(n)

    def _start_session(self, count):
        self.current_index   = 0
        self.step            = 0
        self._session_ok     = 0
        self._session_forgot = 0
        self._undo_stack.clear()
        self._update_undo_btn()

        mode = "CAP TOC" if self.is_cram_mode else "Theo ngay"
        self.progress_bar.set(1 / count)
        self.lbl_progress_text.configure(text=f"1 / {count}")
        messagebox.showinfo("Bat dau", f"Che do: {mode}\nSo luong: {count} tu.")
        self.show_card_state()

    def show_card_state(self):
        row = self.current_review_list.iloc[self.current_index]
        mt  = row["Meaning"].upper()
        self.lbl_meaning.configure(text=mt)
        self._fade_in(self.lbl_meaning, mt, final_color="#1f6aa5")

        self.lbl_pinyin.configure(text="???")
        self.lbl_hanzi.configure(text="?", font=("Arial", 200), wraplength=9999)
        self.toggle_eval_buttons(False)
        self.btn_next_step.pack(side="left", padx=(0, 16))

    def next_step(self):
        if self.current_review_list.empty:
            return
        row = self.current_review_list.iloc[self.current_index]

        if self.step == 0:
            self.step = 1
            py = row.get("Pinyin")
            if pd.isna(py) or py == "":
                py = self.generate_pinyin(row["Hanzi"])
            self._fade_in(self.lbl_pinyin, py, final_color="#d68910")

        elif self.step == 1:
            self.step = 2
            self.update_hanzi_display(row["Hanzi"])
            self._fade_in(self.lbl_hanzi, row["Hanzi"],
                          final_color=self._get_label_color(self.lbl_hanzi))
            self.btn_next_step.pack_forget()
            self.toggle_eval_buttons(True)

    def toggle_eval_buttons(self, show):
        if show:
            self.btn_forgot.pack(side="left",  padx=20, expand=True)
            self.btn_ok.pack(    side="right", padx=20, expand=True)
        else:
            self.btn_forgot.pack_forget()
            self.btn_ok.pack_forget()

    # ════════════════════════════════════════════════════════
    #  DANH GIA + UNDO
    # ════════════════════════════════════════════════════════
    def rate_word(self, rating):
        if self.current_review_list.empty:
            return

        hanzi = self.current_review_list.iloc[self.current_index]["Hanzi"]
        idx   = self.df.index[self.df["Hanzi"] == hanzi].tolist()[0]
        old_lv  = int(self.df.at[idx, "Level"])
        old_rev = self.df.at[idx, "Next_Review"]

        # Snapshot cho undo
        self._undo_stack.append({
            "card_index":  self.current_index,
            "df_idx":      idx,
            "old_level":   old_lv,
            "old_review":  old_rev,
            "snap_ok":     self._session_ok,
            "snap_forgot": self._session_forgot,
        })
        self._update_undo_btn()

        # Cap nhat du lieu
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if self.is_cram_mode:
            if rating == "forgot":
                self.df.at[idx, "Level"]      = 0
                self.df.at[idx, "Next_Review"] = midnight
        else:
            if rating == "ok":
                nv       = old_lv + 1
                days_add = 1 if old_lv == 1 else 2 ** (nv - 1)
            else:
                nv       = 0
                days_add = 0
            self.df.at[idx, "Level"]      = nv
            self.df.at[idx, "Next_Review"] = midnight + timedelta(days=days_add)
        self.save_data()

        if rating == "ok":
            self._session_ok += 1
        else:
            self._session_forgot += 1

        self.step = 0
        total     = len(self.current_review_list)
        if self.current_index < total - 1:
            self.current_index += 1
            self.progress_bar.set((self.current_index + 1) / total)
            self.lbl_progress_text.configure(
                text=f"{self.current_index + 1} / {total}")
            self.show_card_state()
        else:
            self._finish_session(total)

    def _finish_session(self, total):
        self.progress_bar.set(1.0)
        self.lbl_progress_text.configure(text=f"{total} / {total} (HOAN THANH)")
        acc = round(self._session_ok / total * 100) if total else 0
        msg = (
            f"So tu on:  {total}\n"
            f"Nho:       {self._session_ok}  ({acc}%)\n"
            f"Quen:      {self._session_forgot}\n\n"
            + ("Tuyet voi! Tiep tuc phat huy!" if acc >= 80
               else "Co len! Hay on them nhung tu chua nho.")
        )
        messagebox.showinfo("Hoan thanh!", msg)
        self.lbl_meaning.configure(text="HET PHIEN")
        self.lbl_pinyin.configure(text="---")
        self.lbl_hanzi.configure(text="---", font=("Arial", 100))
        self.toggle_eval_buttons(False)
        self._undo_stack.clear()
        self._update_undo_btn()

    def undo_last(self):
        if not self._undo_stack:
            return
        snap = self._undo_stack.pop()
        self._update_undo_btn()

        self.df.at[snap["df_idx"], "Level"]      = snap["old_level"]
        self.df.at[snap["df_idx"], "Next_Review"] = snap["old_review"]
        self.save_data()

        self._session_ok     = snap["snap_ok"]
        self._session_forgot = snap["snap_forgot"]
        self.current_index   = snap["card_index"]
        self.step            = 0

        total = len(self.current_review_list)
        self.progress_bar.set((self.current_index + 1) / total)
        self.lbl_progress_text.configure(text=f"{self.current_index + 1} / {total}")
        self.toggle_eval_buttons(False)
        self.show_card_state()

    def _update_undo_btn(self):
        if self._undo_stack:
            self.btn_undo.pack(side="left")
        else:
            self.btn_undo.pack_forget()

    # ════════════════════════════════════════════════════════
    #  TAB 2 - QUAN LY
    # ════════════════════════════════════════════════════════
    def setup_manage_tab(self):
        inp = ctk.CTkFrame(self.tab_manage)
        inp.pack(pady=20, padx=20, fill="x")

        lf = ctk.CTkFrame(inp, fg_color="transparent")
        lf.pack(side="left", fill="both", expand=True)
        fi = ("Arial", UI_FONT_SIZE)

        ctk.CTkLabel(lf, text="Han tu:", font=fi).grid(row=0, column=0, padx=10, pady=10)
        self.entry_hanzi = ctk.CTkEntry(lf, font=fi, height=40, width=200)
        self.entry_hanzi.grid(row=0, column=1, padx=10, pady=10)

        ctk.CTkLabel(lf, text="Pinyin:", font=fi).grid(row=1, column=0, padx=10, pady=10)
        pr = ctk.CTkFrame(lf, fg_color="transparent")
        pr.grid(row=1, column=1, padx=10, pady=10, sticky="w")
        self.entry_pinyin = ctk.CTkEntry(pr, font=fi, height=40, width=350)
        self.entry_pinyin.pack(side="left", padx=(0, 8))
        ctk.CTkButton(pr, text="🗘", width=44, height=40, font=("Arial", 20),
                      fg_color="#2980b9", hover_color="#1a5276",
                      command=self.regen_pinyin).pack(side="left")
        ctk.CTkButton(pr, text="🔊", width=44, height=40, font=("Arial", 20),
                      fg_color="transparent", hover_color="#2a2a2a",
                      command=self._speak_manage_hanzi).pack(side="left", padx=(4, 0))

        ctk.CTkLabel(lf, text="Nghia TV:", font=fi).grid(row=2, column=0, padx=10, pady=10)
        self.entry_meaning = ctk.CTkEntry(lf, font=fi, height=40, width=400)
        self.entry_meaning.grid(row=2, column=1, padx=10, pady=10)

        bf = ctk.CTkFrame(lf, fg_color="transparent")
        bf.grid(row=3, column=0, columnspan=2, pady=20)
        ctk.CTkButton(bf, text="Them",    command=self.add_word,    width=120, height=40, font=fi).pack(side="left", padx=10)
        ctk.CTkButton(bf, text="Cap Nhat",command=self.update_word, width=120, height=40, font=fi,
                      fg_color="#d68910").pack(side="left", padx=10)
        ctk.CTkButton(bf, text="Xoa",     command=self.delete_word, width=120, height=40, font=fi,
                      fg_color="#c0392b").pack(side="left", padx=10)

        rf = ctk.CTkFrame(inp)
        rf.pack(side="right", fill="y", padx=20, pady=10)
        self.entry_search = ctk.CTkEntry(rf, placeholder_text="Tim kiem...",
                                          font=fi, height=40, width=250)
        self.entry_search.pack(padx=10, pady=20)
        self.entry_search.bind("<KeyRelease>", self.filter_table)

        self.sort_var = ctk.StringVar(value="Ngay them (Moi -> Cu)")
        ctk.CTkOptionMenu(rf,
                          values=["Ngay them (Moi -> Cu)", "Ngay them (Cu -> Moi)",
                                  "Level (Thap -> Cao)",   "Level (Cao -> Thap)"],
                          variable=self.sort_var,
                          command=lambda _: self.refresh_table(),
                          width=250, height=40, font=fi).pack(padx=10, pady=10)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",         font=("Arial", TABLE_FONT_SIZE),   rowheight=TABLE_ROW_HEIGHT)
        style.configure("Treeview.Heading", font=("Arial", TABLE_FONT_SIZE+2, "bold"), rowheight=40)

        self.tree = ttk.Treeview(self.tab_manage,
                                  columns=("Hanzi","Pinyin","Meaning","Date","Level"),
                                  show="headings")
        labels = {"Hanzi":"Han Tu","Pinyin":"Pinyin","Meaning":"Nghia","Date":"Ngay","Level":"Level"}
        widths = {"Hanzi":150,"Pinyin":200,"Meaning":300,"Date":150,"Level":80}
        for col in ("Hanzi","Pinyin","Meaning","Date","Level"):
            self.tree.heading(col, text=labels[col])
            anchor = "center" if col in ("Hanzi","Date","Level") else "w"
            self.tree.column(col, width=widths[col], anchor=anchor)
        self.tree.pack(expand=True, fill="both", padx=20, pady=20)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.refresh_table()

    def regen_pinyin(self):
        h = self.entry_hanzi.get().strip()
        if not h:
            messagebox.showwarning("Chu y", "Vui long nhap Han tu truoc.")
            return
        self.entry_pinyin.delete(0, "end")
        self.entry_pinyin.insert(0, self.generate_pinyin(h))

    def _speak_manage_hanzi(self):
        h = self.entry_hanzi.get().strip()
        if h: self.tts.speak(h)

    def refresh_table(self, data=None):
        for i in self.tree.get_children(): self.tree.delete(i)
        if data is None:
            m = self.sort_var.get()
            if   "Moi" in m:   data = self.df.sort_values("Date",  ascending=False)
            elif "Cu"  in m:   data = self.df.sort_values("Date",  ascending=True)
            elif "Thap" in m:  data = self.df.sort_values("Level", ascending=True)
            elif "Cao"  in m:  data = self.df.sort_values("Level", ascending=False)
            else:               data = self.df
        for _, row in data.iterrows():
            py = row.get("Pinyin", "")
            if pd.isna(py): py = ""
            self.tree.insert("", "end", values=(
                row["Hanzi"], py, row["Meaning"],
                row["Date"].strftime("%d/%m/%Y"), row["Level"]))

    def filter_table(self, _=None):
        q = self.entry_search.get().lower()
        if not q: self.refresh_table(); return
        f = self.df[
            self.df["Hanzi"].str.contains(q, case=False, na=False) |
            self.df["Meaning"].str.contains(q, case=False, na=False) |
            self.df["Pinyin"].str.contains(q, case=False, na=False)]
        self.refresh_table(f)

    def on_tree_select(self, _=None):
        sel = self.tree.selection()
        if not sel: return
        v = self.tree.item(sel[0], "values")
        for entry, val in [(self.entry_hanzi, v[0]),
                            (self.entry_pinyin, v[1]),
                            (self.entry_meaning, v[2])]:
            entry.delete(0, "end"); entry.insert(0, val)

    def add_word(self):
        h = self.entry_hanzi.get().strip()
        m = self.entry_meaning.get().strip()
        p = self.entry_pinyin.get().strip()
        if not h or not m:
            messagebox.showwarning("Chu y", "Vui long nhap day du Han tu va Nghia.")
            return
        if not p: p = self.generate_pinyin(h)
        t = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.df = pd.concat([self.df, pd.DataFrame([{
            "Hanzi":h,"Pinyin":p,"Meaning":m,
            "Date":t,"Level":0,"Next_Review":t}])], ignore_index=True)
        self.save_data(); self.refresh_table(); self.clear_inputs()

    def update_word(self):
        h = self.entry_hanzi.get().strip()
        if h not in self.df["Hanzi"].values:
            messagebox.showwarning("Khong tim thay", f"Khong co tu '{h}'.")
            return
        idx = self.df.index[self.df["Hanzi"] == h].tolist()[0]
        self.df.at[idx, "Meaning"] = self.entry_meaning.get().strip()
        self.df.at[idx, "Pinyin"]  = self.entry_pinyin.get().strip()
        self.save_data(); self.refresh_table()
        messagebox.showinfo("Xong", "Da cap nhat!")

    def delete_word(self):
        h = self.entry_hanzi.get().strip()
        if h in self.df["Hanzi"].values:
            if messagebox.askyesno("Xoa", f"Xoa '{h}'?"):
                self.df = self.df[self.df.Hanzi != h]
                self.save_data(); self.refresh_table(); self.clear_inputs()

    def clear_inputs(self):
        for e in (self.entry_hanzi, self.entry_pinyin, self.entry_meaning):
            e.delete(0, "end")

    # ════════════════════════════════════════════════════════
    #  TAB 3 - DASHBOARD
    # ════════════════════════════════════════════════════════
    def setup_dashboard_tab(self):
        if not MPL_AVAILABLE:
            ctk.CTkLabel(
                self.tab_dash,
                text="Cai matplotlib de dung Dashboard:\n  pip install matplotlib",
                font=("Arial", 20)
            ).pack(expand=True)
            return

        top = ctk.CTkFrame(self.tab_dash, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 0))
        ctk.CTkLabel(top, text="Dashboard - Thong ke hoc tap",
                     font=("Arial", 24, "bold")).pack(side="left")
        ctk.CTkButton(top, text="Lam moi", width=130, height=36,
                      command=self.draw_dashboard,
                      font=("Arial", 15)).pack(side="right")

        self.dash_cards_frame = ctk.CTkFrame(self.tab_dash, fg_color="transparent")
        self.dash_cards_frame.pack(fill="x", padx=20, pady=(12, 0))

        self.dash_plot_frame = ctk.CTkFrame(self.tab_dash)
        self.dash_plot_frame.pack(fill="both", expand=True, padx=20, pady=12)

        self._dash_canvas = None

    def _on_tab_change(self):
        if self.tabview.get() == "Dashboard":
            self.draw_dashboard()

    def draw_dashboard(self):
        if not MPL_AVAILABLE or self.df.empty:
            return

        df   = self.df.copy()
        dark = ctk.get_appearance_mode() == "Dark"

        bg_fig = "#1a1a2e" if dark else "#f7f7f7"
        bg_ax  = "#16213e" if dark else "#ffffff"
        tc     = "#e0e0e0" if dark else "#2c2c2c"
        gc     = "#2a2a4a" if dark else "#e5e5e5"
        C_BLUE, C_GREEN, C_RED, C_AMBER = "#3498db","#2ecc71","#e74c3c","#f39c12"

        # KPI cards
        for w in self.dash_cards_frame.winfo_children():
            w.destroy()
        total     = len(df)
        due_today = int((df["Next_Review"].dt.date <= datetime.now().date()).sum())
        mastered  = int((df["Level"] >= 5).sum())
        avg_lv    = round(df["Level"].mean(), 1)

        for label, val, color in [
            ("Tong tu",          str(total),     "#2980b9"),
            ("Den han hom nay",  str(due_today), "#e74c3c"),
            ("Da thanh thao (5+)", str(mastered), "#27ae60"),
            ("Level trung binh", str(avg_lv),    "#d68910"),
        ]:
            card = ctk.CTkFrame(self.dash_cards_frame, fg_color=color, corner_radius=12)
            card.pack(side="left", expand=True, fill="both", padx=6)
            ctk.CTkLabel(card, text=val,   font=("Arial", 34, "bold"), text_color="white").pack(pady=(14, 0))
            ctk.CTkLabel(card, text=label, font=("Arial", 13),         text_color="#cccccc").pack(pady=(0, 14))

        # Figure matplotlib 2x2
        if self._dash_canvas:
            self._dash_canvas.get_tk_widget().destroy()
            plt.close("all")

        fig, axes = plt.subplots(2, 2, figsize=(14, 7))
        fig.patch.set_facecolor(bg_fig)
        fig.subplots_adjust(hspace=0.45, wspace=0.32,
                            left=0.07, right=0.97, top=0.93, bottom=0.10)

        def sa(ax, title):
            ax.set_facecolor(bg_ax)
            ax.set_title(title, color=tc, fontsize=12, pad=8, fontweight="bold")
            ax.tick_params(colors=tc, labelsize=9)
            ax.spines[:].set_color(gc)
            ax.yaxis.grid(True, color=gc, linewidth=0.5, linestyle="--")
            ax.set_axisbelow(True)

        # -- 1) Phan bo Level --
        ax1 = axes[0][0]
        lvc = df["Level"].value_counts().sort_index()
        bars = ax1.bar(lvc.index.astype(str), lvc.values,
                       color=C_BLUE, edgecolor="none", width=0.6)
        for b in bars:
            ax1.text(b.get_x()+b.get_width()/2, b.get_height()+0.3,
                     str(int(b.get_height())), ha="center", va="bottom",
                     fontsize=8, color=tc)
        ax1.set_xlabel("Level", color=tc, fontsize=9)
        ax1.set_ylabel("So tu",  color=tc, fontsize=9)
        sa(ax1, "Phan bo Level")

        # -- 2) Tu them theo ngay (30 ngay) --
        ax2 = axes[0][1]
        today  = pd.Timestamp(datetime.now().date())
        cutoff = today - pd.Timedelta(days=29)
        recent = df[df["Date"] >= cutoff].copy()
        recent["day"] = recent["Date"].dt.date
        daily = recent.groupby("day").size().reindex(
            pd.date_range(cutoff, today, freq="D").date, fill_value=0)
        ax2.bar(range(len(daily)), daily.values, color=C_GREEN, edgecolor="none", width=0.8)
        ticks = [0, len(daily)//2, len(daily)-1]
        ax2.set_xticks(ticks)
        ax2.set_xticklabels([daily.index[i].strftime("%d/%m") for i in ticks])
        ax2.set_ylabel("So tu them", color=tc, fontsize=9)
        sa(ax2, "Tu them (30 ngay gan nhat)")

        # -- 3) Lich on tap phia truoc --
        ax3 = axes[1][0]
        future = df[df["Next_Review"] >= today].copy()
        future["delta"] = (future["Next_Review"].dt.normalize() - today).dt.days
        if not future.empty:
            max_d = min(int(future["delta"].max()) + 2, 32)
            ax3.hist(future["delta"], bins=range(0, max_d),
                     color=C_AMBER, edgecolor="none", rwidth=0.8)
        ax3.set_xlabel("Ngay nua", color=tc, fontsize=9)
        ax3.set_ylabel("So tu",    color=tc, fontsize=9)
        ax3.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        sa(ax3, "Lich on tap phia truoc")

        # -- 4) Banh - Trang thai --
        ax4 = axes[1][1]
        lvs = df["Level"]
        segs = {
            "Moi (0)":          int((lvs == 0).sum()),
            "Dang hoc (1-4)":   int(((lvs >= 1) & (lvs < 5)).sum()),
            "Thanh thao (5+)":  int((lvs >= 5).sum()),
        }
        nz = {k:v for k,v in segs.items() if v > 0}
        if nz:
            _, _, autotexts = ax4.pie(
                nz.values(), labels=nz.keys(),
                autopct="%1.0f%%",
                colors=[C_RED, C_BLUE, C_GREEN],
                startangle=90,
                wedgeprops={"edgecolor": bg_fig, "linewidth": 1.5},
                textprops={"color": tc, "fontsize": 9},
            )
            for at in autotexts:
                at.set_fontsize(9); at.set_color("white")
        ax4.set_facecolor(bg_ax)
        ax4.set_title("Trang thai tu vung", color=tc, fontsize=12, pad=8, fontweight="bold")

        self._dash_canvas = FigureCanvasTkAgg(fig, master=self.dash_plot_frame)
        self._dash_canvas.draw()
        self._dash_canvas.get_tk_widget().pack(fill="both", expand=True)


# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not TTS_AVAILABLE:
        print("[Canh bao] pip install gtts pygame")
    if not MPL_AVAILABLE:
        print("[Canh bao] pip install matplotlib")
    ChineseLearningApp().mainloop()
