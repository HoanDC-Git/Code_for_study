"""
main.py — Ứng dụng Học Tiếng Trung v3
======================================
Kiến trúc tổng quan:
  ┌─────────────────────────────────────────────────────────┐
  │  ChineseLearningApp (CTk root window)                   │
  │                                                         │
  │   DB Layer     : SQLAlchemy Session (data/app_db.db)    │
  │   Service      : TTSPlayer, pypinyin                    │
  │                                                         │
  │   Tabs:                                                 │
  │     [1] Ôn Tập      — flashcard SRS                     │
  │     [2] Quản Lý     — Treeview CRUD + Tạo ghi chú       │
  │     [3] Dashboard   — Matplotlib 2x2                    │
  │     [4] Sổ Tay      — GrammarTab (Master-Detail)        │
  └─────────────────────────────────────────────────────────┘

Kết nối DB → UI:
  - Một Session duy nhất được tạo khi app khởi động.
  - Session được truyền vào GrammarTab và tất cả hàm CRUD.
  - Tab Ôn Tập và Quản Lý gọi crud.* trực tiếp thông qua self.session.
  - Dashboard đọc từ crud.get_flashcard_stats() → vẽ matplotlib.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

import customtkinter as ctk
from pypinyin import Style, pinyin
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# ── DB / CRUD ──────────────────────────────────────────────────
from database.models import Base, Flashcard
from database import crud
from ui.grammar_tab import GrammarTab

# ── Matplotlib ─────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MPL_AVAILABLE = True
except ImportError:
    MPL_AVAILABLE = False

# ── TTS ────────────────────────────────────────────────────────
try:
    from gtts import gTTS
    import pygame
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

# ── Hằng số cấu hình ──────────────────────────────────────────
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

DB_DIR            = "data"
DB_PATH           = os.path.join(DB_DIR, "app_database.db")
AUDIO_CACHE_DIR   = "audio_cache"
MAX_HANZI_SIZE    = 300
MEANING_FONT_SIZE = 50
PINYIN_FONT_SIZE  = 40
UI_FONT_SIZE      = 18
TABLE_FONT_SIZE   = 16
TABLE_ROW_HEIGHT  = 50
HANZI_FONT_NAME   = "AR PL UKai CN"
FADE_STEPS        = 12
FADE_MS           = 18

os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════
#  TTS PLAYER
# ══════════════════════════════════════════════════════════════

def _init_pygame() -> None:
    if TTS_AVAILABLE:
        try:
            pygame.mixer.init()
        except Exception:
            pass


class TTSPlayer:
    """Phát âm thanh tiếng Trung qua gTTS với cache MP3 cục bộ."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        if TTS_AVAILABLE:
            _init_pygame()

    def speak(self, text: str) -> None:
        if not TTS_AVAILABLE or not text:
            return
        threading.Thread(target=self._play, args=(text,), daemon=True).start()

    def _play(self, text: str) -> None:
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


# ══════════════════════════════════════════════════════════════
#  APP CHÍNH
# ══════════════════════════════════════════════════════════════

class ChineseLearningApp(ctk.CTk):
    """
    Root window của ứng dụng.

    Trách nhiệm:
      - Khởi tạo kết nối SQLite qua SQLAlchemy (self.session).
      - Tạo và bố trí 4 tab.
      - Là nơi chứa logic Tab Ôn Tập, Quản Lý, Dashboard.
      - Uỷ quyền Tab Sổ Tay Ngữ Pháp cho GrammarTab widget.
    """

    # ── Khởi tạo ──────────────────────────────────────────────

    def __init__(self) -> None:
        super().__init__()
        self.title("Học Tiếng Trung")

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}")
        self.after(
            0,
            lambda: self.state("zoomed")
            if os.name == "nt"
            else self.attributes("-zoomed", True),
        )

        # ── Khởi tạo CSDL ──
        self.session: Session = self._init_db()

        # ── Dịch vụ ──
        self.tts = TTSPlayer()

        # ── Trạng thái phiên ôn tập ──
        self._review_cards: list[Flashcard] = []
        self._review_index  = 0
        self._review_step   = 0          # 0=câu hỏi, 1=pinyin, 2=hanzi+đánh giá
        self._is_cram_mode  = False
        self._undo_stack: list[dict] = []
        self._session_ok     = 0
        self._session_forgot = 0

        # Giữ phím mũi tên
        self._arrow_press_start: dict = {}
        self._arrow_hold_threshold   = 2.0

        # ── Tạo giao diện ──
        self._build_tabview()

        # ── Bind phím toàn cục ──
        self.bind("<KeyPress-Right>",  self._on_right_press)
        self.bind("<KeyRelease-Right>", self._on_right_release)
        self.bind("<KeyPress-Left>",   self._on_left_press)
        self.bind("<KeyRelease-Left>",  self._on_left_release)
        self.bind("<z>", lambda _: self.undo_last())
        self.bind("<Z>", lambda _: self.undo_last())

        self.tabview.configure(command=self._on_tab_change)

        # Đảm bảo session đóng khi thoát app
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Kết nối CSDL ──────────────────────────────────────────

    def _init_db(self) -> Session:
        """
        Tạo engine SQLite, đảm bảo bảng tồn tại, trả về Session.
        Nếu file DB chưa có, SQLAlchemy sẽ tự tạo.
        """
        engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},   # cần cho tkinter
        )
        Base.metadata.create_all(engine)   # tạo bảng nếu chưa có
        SessionLocal = sessionmaker(bind=engine)
        return SessionLocal()

    def _on_close(self) -> None:
        """Đóng session DB trước khi thoát app."""
        try:
            self.session.close()
        except Exception:
            pass
        self.quit()

        self.destroy()

        sys.exit(0)

    # ── Build tabs ────────────────────────────────────────────

    def _build_tabview(self) -> None:
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=20, fill="both", expand=True)
        self.tabview._segmented_button.configure(font=("Arial", 20, "bold"))

        self.tab_review  = self.tabview.add("Ôn Tập")
        self.tab_manage  = self.tabview.add("Quản Lý")
        self.tab_dash    = self.tabview.add("Dashboard")
        self.tab_grammar = self.tabview.add("Sổ Tay Ngữ Pháp")

        self._setup_review_tab()
        self._setup_manage_tab()
        self._setup_dashboard_tab()
        self._setup_grammar_tab()

    # ════════════════════════════════════════════════════════
    #  TAB 1 — ÔN TẬP (FLASHCARD SRS)
    # ════════════════════════════════════════════════════════

    def _setup_review_tab(self) -> None:
        # Thanh điều khiển trên cùng
        ctrl = ctk.CTkFrame(self.tab_review, height=80)
        ctrl.pack(pady=10, fill="x", padx=10)

        ctk.CTkButton(
            ctrl, text="Học từ theo ngày",
            command=self._start_smart_review,
            fg_color="#2ecc71", text_color="black",
            font=("Arial", UI_FONT_SIZE, "bold"), height=50, width=300,
        ).pack(side="left", padx=20, pady=10)

        self._cram_option_var = ctk.StringVar(value="10")
        ctk.CTkOptionMenu(
            ctrl, values=["10", "50", "100", "200", "500", "1000"],
            variable=self._cram_option_var,
            width=100, height=40, font=("Arial", UI_FONT_SIZE),
        ).pack(side="right", pady=10)
        ctk.CTkLabel(ctrl, text="SL:", font=("Arial", UI_FONT_SIZE)).pack(
            side="right", padx=10)
        ctk.CTkButton(
            ctrl, text="Ôn cấp tốc",
            command=self._start_cram_review,
            fg_color="#e74c3c", font=("Arial", UI_FONT_SIZE, "bold"),
            height=50, width=200,
        ).pack(side="right", padx=(0, 10), pady=10)

        # Progress bar
        pf = ctk.CTkFrame(self.tab_review, fg_color="transparent")
        pf.pack(pady=(10, 0), fill="x", padx=50)
        self._progress_bar = ctk.CTkProgressBar(
            pf, height=10, corner_radius=8, progress_color="#094297")
        self._progress_bar.pack(fill="x")
        self._progress_bar.set(0)
        self._lbl_progress = ctk.CTkLabel(pf, text="0 / 0", font=("Arial", 16))
        self._lbl_progress.pack(pady=5)

        # Flashcard area
        card_frame = ctk.CTkFrame(self.tab_review, fg_color="transparent")
        card_frame.pack(pady=10, expand=True, fill="both")
        self._card_frame = card_frame

        # Nghĩa + loa
        mr = ctk.CTkFrame(card_frame, fg_color="transparent")
        mr.pack(pady=(20, 0))
        self._lbl_meaning = ctk.CTkLabel(
            mr, text="Sẵn sàng?",
            font=("Arial", MEANING_FONT_SIZE, "bold"),
            text_color="#1f6aa5", wraplength=1000,
        )
        self._lbl_meaning.pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            mr, text="🔊", width=50, height=50, font=("Arial", 24),
            fg_color="transparent", hover_color="#2a2a2a",
            command=self._speak_current_card,
        ).pack(side="left")

        self._lbl_pinyin = ctk.CTkLabel(
            card_frame, text="---",
            font=("Arial", PINYIN_FONT_SIZE),
            text_color="#d68910", wraplength=1000,
        )
        self._lbl_pinyin.pack(pady=10)

        self._lbl_hanzi = ctk.CTkLabel(
            card_frame, text="---",
            font=(HANZI_FONT_NAME, MAX_HANZI_SIZE),
        )
        self._lbl_hanzi.pack(pady=20, expand=True)

        # Bottom buttons
        bottom = ctk.CTkFrame(self.tab_review, fg_color="transparent", height=120)
        bottom.pack(pady=(10, 20), fill="x")
        self._bottom_frame = bottom

        top_row = ctk.CTkFrame(bottom, fg_color="transparent")
        top_row.pack(pady=(0, 10))

        self._btn_next_step = ctk.CTkButton(
            top_row, text="Hiện đáp án  [Space]",
            width=400, height=70, command=self._next_step,
            font=("Arial", 24, "bold"),
        )
        self._btn_next_step.pack(side="left", padx=(0, 16))

        self._btn_undo = ctk.CTkButton(
            top_row, text="Hoàn tác  [Z]",
            width=180, height=70, command=self.undo_last,
            fg_color="#7f8c8d", hover_color="#5d6d7e",
            font=("Arial", 18, "bold"),
        )
        self._btn_undo.pack(side="left")
        self._btn_undo.pack_forget()

        self._btn_forgot = ctk.CTkButton(
            bottom, text="QUÊN",
            fg_color="#e74c3c", command=lambda: self._rate_word("forgot"),
            width=300, height=70, font=("Arial", 22, "bold"),
        )
        self._btn_ok = ctk.CTkButton(
            bottom, text="NHỚ",
            fg_color="#2ecc71", command=lambda: self._rate_word("ok"),
            width=300, height=70, font=("Arial", 22, "bold"),
        )

        self.bind("<space>", lambda _: self._next_step())
        self._toggle_eval_buttons(False)

    # ── Speak ──────────────────────────────────────────────────
    def _speak_current_card(self) -> None:
        if not self._review_cards:
            return
        self.tts.speak(self._review_cards[self._review_index].hanzi)

    # ── Auto font size ──────────────────────────────────────────
    def _update_hanzi_display(self, text: str) -> None:
        sw    = self.winfo_width() or self.winfo_screenwidth()
        avail = sw - 200
        n     = len(text) or 1
        size  = min(MAX_HANZI_SIZE, int(avail / (n * 1.1)))
        if size < 80:
            size = 100
            self._lbl_hanzi.configure(wraplength=avail)
        else:
            self._lbl_hanzi.configure(wraplength=9999)
        self._lbl_hanzi.configure(text=text, font=(HANZI_FONT_NAME, size))

    # ── Fade animation ──────────────────────────────────────────
    def _fade_in(self, widget, final_text, final_font=None,
                 final_color=None, step=0) -> None:
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

        alpha   = (step + 1) / FADE_STEPS
        tc      = final_color or self._get_label_color(widget)
        blended = self._blend_hex(self._fade_bg, tc, alpha)
        widget.configure(text_color=blended)

        if step < FADE_STEPS - 1:
            self.after(FADE_MS,
                       lambda: self._fade_in(widget, None, None, final_color, step + 1))
        else:
            widget.configure(text_color=tc)

    def _get_label_color(self, lbl) -> str:
        try:
            c = lbl.cget("text_color")
            if isinstance(c, (list, tuple)):
                return c[0] if ctk.get_appearance_mode() == "Light" else c[1]
            return c or "#ffffff"
        except Exception:
            return "#ffffff"

    @staticmethod
    def _blend_hex(c1: str, c2: str, t: float) -> str:
        def parse(h):
            h = h.strip("#")
            if len(h) == 3:
                h = "".join(x * 2 for x in h)
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        try:
            r1, g1, b1 = parse(c1)
            r2, g2, b2 = parse(c2)
            return "#{:02x}{:02x}{:02x}".format(
                int(r1 + (r2 - r1) * t),
                int(g1 + (g2 - g1) * t),
                int(b1 + (b2 - b1) * t),
            )
        except Exception:
            return c2

    # ── Arrow key hold ──────────────────────────────────────────
    def _on_right_press(self, _) -> None:
        if "right" not in self._arrow_press_start:
            self._arrow_press_start["right"] = time.time()
            self._schedule_hold("right")

    def _on_right_release(self, _) -> None:
        self._arrow_press_start.pop("right", None)

    def _on_left_press(self, _) -> None:
        if "left" not in self._arrow_press_start:
            self._arrow_press_start["left"] = time.time()
            self._schedule_hold("left")

    def _on_left_release(self, _) -> None:
        self._arrow_press_start.pop("left", None)

    def _schedule_hold(self, direction: str) -> None:
        def check():
            t0 = self._arrow_press_start.get(direction)
            if t0 is None:
                return
            if time.time() - t0 >= self._arrow_hold_threshold:
                self._arrow_press_start.pop(direction, None)
                if self._review_step == 2:
                    self.after(0, lambda: self._rate_word(
                        "ok" if direction == "right" else "forgot"))
            else:
                self.after(100, check)
        self.after(100, check)

    # ── Session logic ───────────────────────────────────────────
    def _start_smart_review(self) -> None:
        """Lấy từ đến hạn từ DB rồi bắt đầu phiên SRS."""
        cards = crud.get_due_flashcards(self.session)
        if not cards:
            messagebox.showinfo("Tuyệt vời!", "Bạn đã ôn hết từ cần học hôm nay!")
            return
        self._is_cram_mode = False
        self._review_cards = cards
        self._begin_session(len(cards))

    def _start_cram_review(self) -> None:
        """Lấy n từ ngẫu nhiên từ DB để ôn cấp tốc."""
        try:
            n = int(self._cram_option_var.get())
        except Exception:
            n = 10
        cards = crud.get_random_flashcards(self.session, n)
        if not cards:
            messagebox.showwarning("Trống", "Chưa có từ vựng nào trong CSDL.")
            return
        self._is_cram_mode = True
        self._review_cards = cards
        self._begin_session(len(cards))

    def _begin_session(self, count: int) -> None:
        self._review_index   = 0
        self._review_step    = 0
        self._session_ok     = 0
        self._session_forgot = 0
        self._undo_stack.clear()
        self._update_undo_btn()

        mode = "CẤP TỐC" if self._is_cram_mode else "Theo ngày"
        self._progress_bar.set(1 / count)
        self._lbl_progress.configure(text=f"1 / {count}")
        messagebox.showinfo("Bắt đầu", f"Chế độ: {mode}\nSố lượng: {count} từ.")
        self._show_card_question()

    def _show_card_question(self) -> None:
        card = self._review_cards[self._review_index]
        self._lbl_meaning.configure(text=card.meaning.upper() if card.meaning else "")
        self._fade_in(self._lbl_meaning, card.meaning.upper() if card.meaning else "",
                      final_color="#1f6aa5")
        self._lbl_pinyin.configure(text="???")
        self._lbl_hanzi.configure(text="?", font=("Arial", 200), wraplength=9999)
        self._toggle_eval_buttons(False)
        self._btn_next_step.pack(side="left", padx=(0, 16))

    def _next_step(self) -> None:
        if not self._review_cards:
            return
        card = self._review_cards[self._review_index]

        if self._review_step == 0:
            self._review_step = 1
            py = card.pinyin or self._generate_pinyin(card.hanzi)
            self._fade_in(self._lbl_pinyin, py, final_color="#d68910")

        elif self._review_step == 1:
            self._review_step = 2
            self._update_hanzi_display(card.hanzi)
            self._fade_in(self._lbl_hanzi, card.hanzi,
                          final_color=self._get_label_color(self._lbl_hanzi))
            self._btn_next_step.pack_forget()
            self._toggle_eval_buttons(True)

    def _toggle_eval_buttons(self, show: bool) -> None:
        if show:
            self._btn_forgot.pack(side="left",  padx=20, expand=True)
            self._btn_ok.pack(    side="right", padx=20, expand=True)
        else:
            self._btn_forgot.pack_forget()
            self._btn_ok.pack_forget()

    def _rate_word(self, rating: str) -> None:
        """
        Đánh giá từ: gọi crud.update_flashcard_after_review() để lưu vào DB.
        Snapshot trước đó được đẩy vào _undo_stack để hỗ trợ undo.
        """
        if not self._review_cards:
            return

        card     = self._review_cards[self._review_index]
        old_lv   = card.level
        old_rev  = card.next_review

        # Lưu snapshot cho undo
        self._undo_stack.append({
            "card_index": self._review_index,
            "card":       card,
            "old_level":  old_lv,
            "old_review": old_rev,
            "snap_ok":     self._session_ok,
            "snap_forgot": self._session_forgot,
        })
        self._update_undo_btn()

        # Ghi vào DB thông qua crud
        remembered = (rating == "ok")
        if self._is_cram_mode and remembered:
            pass   # chế độ cấp tốc: chỉ reset nếu quên
        else:
            try:
                crud.update_flashcard_after_review(
                    self.session, card, remembered=(rating == "ok"))
            except Exception as e:
                messagebox.showerror("Lỗi DB", f"Không thể lưu kết quả:\n{e}")
                return

        if rating == "ok":
            self._session_ok += 1
        else:
            self._session_forgot += 1

        self._review_step = 0
        total = len(self._review_cards)

        if self._review_index < total - 1:
            self._review_index += 1
            self._progress_bar.set((self._review_index + 1) / total)
            self._lbl_progress.configure(
                text=f"{self._review_index + 1} / {total}")
            self._show_card_question()
        else:
            self._finish_session(total)

    def _finish_session(self, total: int) -> None:
        self._progress_bar.set(1.0)
        self._lbl_progress.configure(text=f"{total} / {total} (HOÀN THÀNH)")
        acc = round(self._session_ok / total * 100) if total else 0
        msg = (
            f"Số từ ôn:   {total}\n"
            f"✅ Nhớ:     {self._session_ok}  ({acc}%)\n"
            f"❌ Quên:    {self._session_forgot}\n\n"
            + ("Tuyệt vời! Tiếp tục phát huy! 💪"
               if acc >= 80 else "Cố lên! Ôn thêm những từ chưa nhớ nhé.")
        )
        messagebox.showinfo("Hoàn thành! 🎉", msg)
        self._lbl_meaning.configure(text="HẾT PHIÊN")
        self._lbl_pinyin.configure(text="---")
        self._lbl_hanzi.configure(text="---", font=("Arial", 100))
        self._toggle_eval_buttons(False)
        self._undo_stack.clear()
        self._update_undo_btn()

    def undo_last(self) -> None:
        """
        Hoàn tác thao tác đánh giá cuối cùng:
          1. Lấy snapshot từ stack
          2. Gọi crud.undo_flashcard_review() để khôi phục DB
          3. Khôi phục trạng thái UI
        """
        if not self._undo_stack:
            return
        snap = self._undo_stack.pop()
        self._update_undo_btn()

        try:
            crud.undo_flashcard_review(
                self.session,
                snap["card"],
                snap["old_level"],
                snap["old_review"],
            )
        except Exception as e:
            messagebox.showerror("Lỗi DB", f"Không thể hoàn tác:\n{e}")
            return

        self._session_ok     = snap["snap_ok"]
        self._session_forgot = snap["snap_forgot"]
        self._review_index   = snap["card_index"]
        self._review_step    = 0

        total = len(self._review_cards)
        self._progress_bar.set((self._review_index + 1) / total)
        self._lbl_progress.configure(text=f"{self._review_index + 1} / {total}")
        self._toggle_eval_buttons(False)
        self._show_card_question()

    def _update_undo_btn(self) -> None:
        if self._undo_stack:
            self._btn_undo.pack(side="left")
        else:
            self._btn_undo.pack_forget()

    # ════════════════════════════════════════════════════════
    #  TAB 2 — QUẢN LÝ TỪ VỰNG
    # ════════════════════════════════════════════════════════

    def _setup_manage_tab(self) -> None:
        inp = ctk.CTkFrame(self.tab_manage)
        inp.pack(pady=20, padx=20, fill="x")

        # Cột trái: form nhập liệu
        lf = ctk.CTkFrame(inp, fg_color="transparent")
        lf.pack(side="left", fill="both", expand=True)
        fi = ("Arial", UI_FONT_SIZE)

        ctk.CTkLabel(lf, text="Hán tự:",   font=fi).grid(row=0, column=0, padx=10, pady=10)
        self._entry_hanzi = ctk.CTkEntry(lf, font=fi, height=40, width=200)
        self._entry_hanzi.grid(row=0, column=1, padx=10, pady=10)

        ctk.CTkLabel(lf, text="Pinyin:", font=fi).grid(row=1, column=0, padx=10, pady=10)
        pr = ctk.CTkFrame(lf, fg_color="transparent")
        pr.grid(row=1, column=1, padx=10, pady=10, sticky="w")
        self._entry_pinyin = ctk.CTkEntry(pr, font=fi, height=40, width=320)
        self._entry_pinyin.pack(side="left", padx=(0, 6))
        ctk.CTkButton(pr, text="🗘", width=40, height=40, font=("Arial", 20),
                      fg_color="#2980b9", hover_color="#1a5276",
                      command=self._regen_pinyin).pack(side="left")
        ctk.CTkButton(pr, text="🔊", width=40, height=40, font=("Arial", 20),
                      fg_color="transparent", hover_color="#2a2a2a",
                      command=lambda: self.tts.speak(
                          self._entry_hanzi.get().strip())).pack(
            side="left", padx=(4, 0))

        ctk.CTkLabel(lf, text="Nghĩa TV:", font=fi).grid(row=2, column=0, padx=10, pady=10)
        self._entry_meaning = ctk.CTkEntry(lf, font=fi, height=40, width=400)
        self._entry_meaning.grid(row=2, column=1, padx=10, pady=10)

        bf = ctk.CTkFrame(lf, fg_color="transparent")
        bf.grid(row=3, column=0, columnspan=2, pady=16)
        btn_cfg = {"font": fi, "height": 40, "width": 120}

        ctk.CTkButton(bf, text="Thêm",
                      command=self._add_flashcard, **btn_cfg).pack(side="left", padx=8)
        ctk.CTkButton(bf, text="Cập nhật",
                      command=self._update_flashcard,
                      fg_color="#d68910", **btn_cfg).pack(side="left", padx=8)
        ctk.CTkButton(bf, text="Xóa",
                      command=self._delete_flashcard,
                      fg_color="#c0392b", **btn_cfg).pack(side="left", padx=8)

        # ── Nút Tạo ghi chú ngữ pháp ──────────────────────────
        # Khi nhấn: lấy Hán tự đang chọn → chuyển sang tab Sổ Tay → prefill tiêu đề
        ctk.CTkButton(
            bf, text="📝 Tạo ghi chú ngữ pháp",
            command=self._goto_grammar_from_manage,
            fg_color="#8e44ad", font=fi, height=40, width=230,
        ).pack(side="left", padx=8)

        # Cột phải: tìm kiếm + sắp xếp
        rf = ctk.CTkFrame(inp)
        rf.pack(side="right", fill="y", padx=20, pady=10)

        self._entry_search = ctk.CTkEntry(
            rf, placeholder_text="Tìm kiếm...", font=fi, height=40, width=250)
        self._entry_search.pack(padx=10, pady=20)
        self._entry_search.bind("<KeyRelease>", self._filter_table)

        self._sort_var = ctk.StringVar(value="Ngày thêm (Mới → Cũ)")
        ctk.CTkOptionMenu(
            rf,
            values=["Ngày thêm (Mới → Cũ)", "Ngày thêm (Cũ → Mới)",
                    "Level (Thấp → Cao)",    "Level (Cao → Thấp)"],
            variable=self._sort_var,
            command=lambda _: self._refresh_table(),
            width=250, height=40, font=fi,
        ).pack(padx=10, pady=10)

        # Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        font=("Arial", TABLE_FONT_SIZE), rowheight=TABLE_ROW_HEIGHT)
        style.configure("Treeview.Heading",
                        font=("Arial", TABLE_FONT_SIZE + 2, "bold"), rowheight=40)

        self._tree = ttk.Treeview(
            self.tab_manage,
            columns=("Hanzi", "Pinyin", "Meaning", "Date", "Level"),
            show="headings",
        )
        col_cfg = {
            "Hanzi":   ("Hán Tự",   150, "center"),
            "Pinyin":  ("Pinyin",   200, "w"),
            "Meaning": ("Nghĩa",    300, "w"),
            "Date":    ("Ngày",     150, "center"),
            "Level":   ("Level",    80,  "center"),
        }
        for col, (label, w, anchor) in col_cfg.items():
            self._tree.heading(col, text=label)
            self._tree.column(col, width=w, anchor=anchor)

        self._tree.pack(expand=True, fill="both", padx=20, pady=20)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._refresh_table()

    # ── Helpers Quản Lý ─────────────────────────────────────────

    def _generate_pinyin(self, text: str) -> str:
        if not isinstance(text, str):
            return ""
        return " ".join(
            item[0] for item in pinyin(text, style=Style.TONE, heteronym=False))

    def _regen_pinyin(self) -> None:
        h = self._entry_hanzi.get().strip()
        if not h:
            messagebox.showwarning("Chú ý", "Vui lòng nhập Hán tự trước.")
            return
        self._entry_pinyin.delete(0, "end")
        self._entry_pinyin.insert(0, self._generate_pinyin(h))

    def _refresh_table(self, cards: list[Flashcard] | None = None) -> None:
        """
        Vẽ lại Treeview từ danh sách Flashcard.
        Nếu cards=None → lấy tất cả từ DB theo sort hiện tại.
        """
        for i in self._tree.get_children():
            self._tree.delete(i)

        if cards is None:
            sort_map = {
                "Ngày thêm (Mới → Cũ)": "date_desc",
                "Ngày thêm (Cũ → Mới)": "date_asc",
                "Level (Thấp → Cao)":   "level_asc",
                "Level (Cao → Thấp)":   "level_desc",
            }
            sort_key = sort_map.get(self._sort_var.get(), "date_desc")
            cards    = crud.get_all_flashcards(self.session, sort_by=sort_key)

        for card in cards:
            date_str = card.date_added.strftime("%d/%m/%Y") if card.date_added else ""
            py       = card.pinyin or ""
            self._tree.insert("", "end", iid=str(card.id), values=(
                card.hanzi, py, card.meaning or "", date_str, card.level))

    def _filter_table(self, _=None) -> None:
        q = self._entry_search.get().strip()
        if not q:
            self._refresh_table()
            return
        cards = crud.search_flashcards(self.session, q)
        self._refresh_table(cards)

    def _on_tree_select(self, _=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        values = self._tree.item(sel[0], "values")
        # values = (hanzi, pinyin, meaning, date, level)
        for entry, val in [
            (self._entry_hanzi,   values[0]),
            (self._entry_pinyin,  values[1]),
            (self._entry_meaning, values[2]),
        ]:
            entry.delete(0, "end")
            entry.insert(0, val)

    def _add_flashcard(self) -> None:
        h = self._entry_hanzi.get().strip()
        m = self._entry_meaning.get().strip()
        p = self._entry_pinyin.get().strip() or self._generate_pinyin(h)
        if not h or not m:
            messagebox.showwarning("Chú ý", "Vui lòng nhập Hán tự và Nghĩa.")
            return
        try:
            crud.create_flashcard(self.session, hanzi=h, pinyin=p, meaning=m)
        except Exception as e:
            messagebox.showerror("Lỗi DB", str(e))
            return
        self._refresh_table()
        self._clear_manage_inputs()

    def _update_flashcard(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Chưa chọn", "Hãy chọn một từ trong bảng.")
            return
        card_id = int(sel[0])
        card    = crud.get_flashcard_by_id(self.session, card_id)
        if not card:
            messagebox.showerror("Lỗi", "Không tìm thấy từ trong CSDL.")
            return
        try:
            crud.update_flashcard(
                self.session, card,
                pinyin=self._entry_pinyin.get().strip(),
                meaning=self._entry_meaning.get().strip(),
            )
        except Exception as e:
            messagebox.showerror("Lỗi DB", str(e))
            return
        self._refresh_table()
        messagebox.showinfo("Xong", "Đã cập nhật!")

    def _delete_flashcard(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("Chưa chọn", "Hãy chọn một từ cần xoá.")
            return
        card_id = int(sel[0])
        card    = crud.get_flashcard_by_id(self.session, card_id)
        if not card:
            return
        if messagebox.askyesno("Xoá", f"Xoá từ '{card.hanzi}'?"):
            try:
                crud.delete_flashcard(self.session, card)
            except Exception as e:
                messagebox.showerror("Lỗi DB", str(e))
                return
            self._refresh_table()
            self._clear_manage_inputs()

    def _clear_manage_inputs(self) -> None:
        for e in (self._entry_hanzi, self._entry_pinyin, self._entry_meaning):
            e.delete(0, "end")

    def _goto_grammar_from_manage(self) -> None:
        """
        Tích hợp xuyên tab: lấy Hán tự đang chọn → chuyển sang
        Tab Sổ Tay Ngữ Pháp → điền Hán tự vào ô Tiêu đề.

        Luồng:
          1. Đọc Hán tự từ ô nhập hoặc hàng đang chọn trong Treeview.
          2. Gọi grammar_tab.prefill_title(hanzi).
          3. Chuyển tabview sang tab Sổ Tay Ngữ Pháp.
        """
        hanzi = self._entry_hanzi.get().strip()
        if not hanzi:
            sel = self._tree.selection()
            if sel:
                hanzi = self._tree.item(sel[0], "values")[0]

        if not hanzi:
            messagebox.showwarning(
                "Chưa chọn từ",
                "Hãy chọn hoặc nhập một Hán tự để tạo ghi chú.",
            )
            return

        # Điền vào form Grammar tab rồi chuyển sang đó
        self._grammar_tab_widget.prefill_title(hanzi)
        self.tabview.set("Sổ Tay Ngữ Pháp")

    # ════════════════════════════════════════════════════════
    #  TAB 3 — DASHBOARD
    # ════════════════════════════════════════════════════════

    def _setup_dashboard_tab(self) -> None:
        if not MPL_AVAILABLE:
            ctk.CTkLabel(
                self.tab_dash,
                text="Cài matplotlib để dùng Dashboard:\n  pip install matplotlib",
                font=("Arial", 20),
            ).pack(expand=True)
            return

        top = ctk.CTkFrame(self.tab_dash, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 0))
        ctk.CTkLabel(top, text="Dashboard — Thống kê học tập",
                     font=("Arial", 24, "bold")).pack(side="left")
        ctk.CTkButton(top, text="🔄 Làm mới", width=130, height=36,
                      command=self._draw_dashboard,
                      font=("Arial", 15)).pack(side="right")

        self._dash_cards_frame = ctk.CTkFrame(self.tab_dash, fg_color="transparent")
        self._dash_cards_frame.pack(fill="x", padx=20, pady=(12, 0))

        self._dash_plot_frame = ctk.CTkFrame(self.tab_dash)
        self._dash_plot_frame.pack(fill="both", expand=True, padx=20, pady=12)

        self._dash_canvas = None

    def _draw_dashboard(self) -> None:
        """
        Vẽ lại toàn bộ dashboard từ dữ liệu mới nhất trong DB.
        Dữ liệu lấy qua crud.get_flashcard_stats() → không truy cập DB trực tiếp.
        """
        if not MPL_AVAILABLE:
            return

        stats = crud.get_flashcard_stats(self.session)
        if stats["total"] == 0:
            return

        dark   = ctk.get_appearance_mode() == "Dark"
        bg_fig = "#1a1a2e" if dark else "#f7f7f7"
        bg_ax  = "#16213e" if dark else "#ffffff"
        tc     = "#e0e0e0" if dark else "#2c2c2c"
        gc     = "#2a2a4a" if dark else "#e5e5e5"
        C_B, C_G, C_R, C_A = "#3498db", "#2ecc71", "#e74c3c", "#f39c12"

        # ── KPI cards ──
        for w in self._dash_cards_frame.winfo_children():
            w.destroy()
        for label, val, color in [
            ("Tổng từ",            str(stats["total"]),     "#2980b9"),
            ("Đến hạn hôm nay",    str(stats["due_today"]), "#e74c3c"),
            ("Thành thạo (≥5)",    str(stats["mastered"]),  "#27ae60"),
            ("Level trung bình",   str(stats["avg_level"]), "#d68910"),
        ]:
            card = ctk.CTkFrame(
                self._dash_cards_frame, fg_color=color, corner_radius=12)
            card.pack(side="left", expand=True, fill="both", padx=6)
            ctk.CTkLabel(card, text=val,   font=("Arial", 34, "bold"),
                         text_color="white").pack(pady=(14, 0))
            ctk.CTkLabel(card, text=label, font=("Arial", 13),
                         text_color="#cccccc").pack(pady=(0, 14))

        # ── Matplotlib 2×2 ──
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

        # 1) Phân bổ Level
        ax1  = axes[0][0]
        dist = stats["level_distribution"]
        if dist:
            keys = [str(k) for k in sorted(dist)]
            vals = [dist[int(k)] for k in keys]
            bars = ax1.bar(keys, vals, color=C_B, edgecolor="none", width=0.6)
            for b in bars:
                ax1.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.3,
                         str(int(b.get_height())), ha="center", va="bottom",
                         fontsize=8, color=tc)
        ax1.set_xlabel("Level", color=tc, fontsize=9)
        ax1.set_ylabel("Số từ",  color=tc, fontsize=9)
        sa(ax1, "Phân bổ Level")

        # 2) Từ thêm theo ngày (30 ngày)
        ax2 = axes[0][1]
        daily = stats["daily_added"]
        if daily:
            xs = range(len(daily))
            ys = [v for _, v in daily]
            ax2.bar(xs, ys, color=C_G, edgecolor="none", width=0.8)
            ticks = [0, len(daily) // 2, len(daily) - 1]
            ax2.set_xticks(ticks)
            ax2.set_xticklabels(
                [daily[i][0].strftime("%d/%m") for i in ticks])
        ax2.set_ylabel("Số từ thêm", color=tc, fontsize=9)
        sa(ax2, "Từ thêm (30 ngày gần nhất)")

        # 3) Lịch ôn tập phía trước
        ax3   = axes[1][0]
        today = datetime.now().date()
        all_c = stats.get("all_cards", [])
        deltas = [
            (c.next_review.date() - today).days
            for c in all_c
            if c.next_review and c.next_review.date() >= today
        ]
        if deltas:
            max_d = min(max(deltas) + 2, 32)
            ax3.hist(deltas, bins=range(0, max_d),
                     color=C_A, edgecolor="none", rwidth=0.8)
        ax3.set_xlabel("Ngày nữa", color=tc, fontsize=9)
        ax3.set_ylabel("Số từ",    color=tc, fontsize=9)
        ax3.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        sa(ax3, "Lịch ôn tập phía trước")

        # 4) Bánh — trạng thái
        ax4 = axes[1][1]
        lvs = [c.level for c in all_c]
        segs = {
            "Mới (0)":          sum(1 for l in lvs if l == 0),
            "Đang học (1–4)":   sum(1 for l in lvs if 1 <= l < 5),
            "Thành thạo (≥5)":  sum(1 for l in lvs if l >= 5),
        }
        nz = {k: v for k, v in segs.items() if v > 0}
        if nz:
            _, _, autotexts = ax4.pie(
                nz.values(), labels=nz.keys(),
                autopct="%1.0f%%",
                colors=[C_R, C_B, C_G],
                startangle=90,
                wedgeprops={"edgecolor": bg_fig, "linewidth": 1.5},
                textprops={"color": tc, "fontsize": 9},
            )
            for at in autotexts:
                at.set_fontsize(9); at.set_color("white")
        ax4.set_facecolor(bg_ax)
        ax4.set_title("Trạng thái từ vựng", color=tc,
                      fontsize=12, pad=8, fontweight="bold")

        self._dash_canvas = FigureCanvasTkAgg(fig, master=self._dash_plot_frame)
        self._dash_canvas.draw()
        self._dash_canvas.get_tk_widget().pack(fill="both", expand=True)

    # ════════════════════════════════════════════════════════
    #  TAB 4 — SỔ TAY NGỮ PHÁP
    # ════════════════════════════════════════════════════════

    def _setup_grammar_tab(self) -> None:
        """
        Nhúng GrammarTab widget vào tab_grammar.
        GrammarTab nhận session và tts dùng chung từ app.
        Tham chiếu self._grammar_tab_widget để gọi prefill_title() từ Tab Quản Lý.
        """
        self._grammar_tab_widget = GrammarTab(
            parent=self.tab_grammar,
            session=self.session,
            tts=self.tts,
        )
        self._grammar_tab_widget.pack(fill="both", expand=True, padx=12, pady=12)

    # ════════════════════════════════════════════════════════
    #  TAB CHANGE CALLBACK
    # ════════════════════════════════════════════════════════

    def _on_tab_change(self) -> None:
        current = self.tabview.get()
        if current == "Dashboard":
            self._draw_dashboard()
        elif current == "Sổ Tay Ngữ Pháp":
            # Reload danh sách ghi chú mỗi khi chuyển sang tab
            self._grammar_tab_widget.reload()


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not TTS_AVAILABLE:
        print("[Cảnh báo] Cài TTS: pip install gtts pygame")
    if not MPL_AVAILABLE:
        print("[Cảnh báo] Cài Dashboard: pip install matplotlib")

    ChineseLearningApp().mainloop()
