import customtkinter as ctk
import pandas as pd
from pypinyin import pinyin, Style
from datetime import datetime, timedelta
import os
from tkinter import messagebox, ttk
import threading
import time

# --- TTS: Dùng gtts + pygame ---
try:
    from gtts import gTTS
    import pygame
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

# --- CẤU HÌNH GIAO DIỆN ---
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# --- TÊN FILE DỮ LIỆU ---
DATA_FILE = 'library.xlsx'

# --- CẤU HÌNH CỠ CHỮ MẶC ĐỊNH ---
MAX_HANZI_SIZE = 300
MEANING_FONT_SIZE = 50
PINYIN_FONT_SIZE = 40
UI_FONT_SIZE = 18
TABLE_FONT_SIZE = 16
TABLE_ROW_HEIGHT = 50

# Font chữ
HANZI_FONT_NAME = "Ma Shan Zheng"

# Thư mục cache âm thanh
AUDIO_CACHE_DIR = "audio_cache"
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)


def init_pygame():
    """Khởi tạo pygame mixer an toàn."""
    if TTS_AVAILABLE:
        try:
            pygame.mixer.init()
        except Exception:
            pass


class TTSPlayer:
    """Phát âm thanh tiếng Trung bằng gTTS (offline cache)."""

    def __init__(self):
        self._lock = threading.Lock()
        if TTS_AVAILABLE:
            init_pygame()

    def speak(self, text: str):
        if not TTS_AVAILABLE or not text:
            return
        threading.Thread(target=self._play, args=(text,), daemon=True).start()

    def _play(self, text: str):
        with self._lock:
            try:
                safe_name = "".join(c if c.isalnum() else "_" for c in text[:30])
                cache_path = os.path.join(AUDIO_CACHE_DIR, f"{safe_name}.mp3")

                if not os.path.exists(cache_path):
                    tts = gTTS(text=text, lang="zh-CN", slow=False)
                    tts.save(cache_path)

                pygame.mixer.music.load(cache_path)
                pygame.mixer.music.play()

                # Chờ phát xong
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
            except Exception as e:
                print(f"[TTS Error] {e}")


class ChineseLearningApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Ôn Tập Tiếng Trung")

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}")
        self.after(
            0,
            lambda: self.state("zoomed")
            if os.name == "nt"
            else self.attributes("-zoomed", True),
        )

        self.df = self.load_data()
        self.current_review_list = pd.DataFrame()
        self.current_index = 0
        self.step = 0
        self.is_cram_mode = False

        # TTS
        self.tts = TTSPlayer()

        # Trạng thái giữ phím mũi tên
        self._arrow_press_start = {}
        self._arrow_hold_threshold = 2.0  # giây

        # TẠO TAB
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=20, fill="both", expand=True)
        self.tabview._segmented_button.configure(font=("Arial", 20, "bold"))

        self.tab_review = self.tabview.add("Ôn Tập")
        self.tab_manage = self.tabview.add("Quản Lý & Tra Cứu")

        self.setup_review_tab()
        self.setup_manage_tab()

        # Bind phím mũi tên
        self.bind("<KeyPress-Right>", self._on_right_press)
        self.bind("<KeyRelease-Right>", self._on_right_release)
        self.bind("<KeyPress-Left>", self._on_left_press)
        self.bind("<KeyRelease-Left>", self._on_left_release)

    # ========================= DỮ LIỆU =========================

    def load_data(self):
        required_columns = ["Hanzi", "Pinyin", "Meaning", "Date", "Level", "Next_Review"]
        if not os.path.exists(DATA_FILE):
            df = pd.DataFrame(columns=required_columns)
            df.to_excel(DATA_FILE, index=False)
            return df
        try:
            df = pd.read_excel(DATA_FILE)
            if "Pinyin" not in df.columns:
                df["Pinyin"] = df["Hanzi"].apply(self.generate_pinyin)
            if "Level" not in df.columns:
                df["Level"] = 0
            if "Next_Review" not in df.columns:
                df["Next_Review"] = pd.to_datetime(df["Date"])
            df["Date"] = pd.to_datetime(df["Date"])
            df["Next_Review"] = pd.to_datetime(df["Next_Review"])
            df.to_excel(DATA_FILE, index=False)
            return df
        except Exception as e:
            messagebox.showerror("Lỗi", f"Lỗi file: {e}")
            return pd.DataFrame(columns=required_columns)

    def save_data(self):
        self.df.to_excel(DATA_FILE, index=False)

    def generate_pinyin(self, text):
        if not isinstance(text, str):
            return ""
        py_list = pinyin(text, style=Style.TONE, heteronym=False)
        return " ".join([item[0] for item in py_list])

    # ========================= TAB 1: ÔN TẬP =========================

    def setup_review_tab(self):
        self.control_frame = ctk.CTkFrame(self.tab_review, height=80)
        self.control_frame.pack(pady=10, fill="x", padx=10)

        self.btn_smart_review = ctk.CTkButton(
            self.control_frame,
            text="Học từ theo ngày",
            command=self.start_smart_review,
            fg_color="#2ecc71",
            text_color="black",
            font=("Arial", UI_FONT_SIZE, "bold"),
            height=50,
            width=300,
        )
        self.btn_smart_review.pack(side="left", padx=20, pady=10)

        self.btn_cram = ctk.CTkButton(
            self.control_frame,
            text="Ôn cấp tốc",
            command=self.start_cram_review,
            fg_color="#e74c3c",
            font=("Arial", UI_FONT_SIZE, "bold"),
            height=50,
            width=200,
        )
        self.btn_cram.pack(side="right", padx=(10, 20), pady=10)

        self.cram_option_var = ctk.StringVar(value="10")
        self.cram_option = ctk.CTkOptionMenu(
            self.control_frame,
            values=["10", "50", "100", "200", "500", "1000"],
            variable=self.cram_option_var,
            width=100,
            height=40,
            font=("Arial", UI_FONT_SIZE),
        )
        self.cram_option.pack(side="right", padx=0, pady=10)
        ctk.CTkLabel(
            self.control_frame, text="SL:", font=("Arial", UI_FONT_SIZE)
        ).pack(side="right", padx=10)

        # Progress
        self.progress_frame = ctk.CTkFrame(self.tab_review, fg_color="transparent")
        self.progress_frame.pack(pady=(10, 0), fill="x", padx=50)
        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame, height=10, corner_radius=8
        )
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)
        self.progress_bar.configure(progress_color="#094297")
        self.lbl_progress_text = ctk.CTkLabel(
            self.progress_frame, text="0 / 0", font=("Arial", 16)
        )
        self.lbl_progress_text.pack(pady=5)

        # Flashcard Area
        self.card_frame = ctk.CTkFrame(self.tab_review, fg_color="transparent")
        self.card_frame.pack(pady=10, expand=True, fill="both")

        # --- HÀNG NGHĨA + NÚT LOA ---
        meaning_row = ctk.CTkFrame(self.card_frame, fg_color="transparent")
        meaning_row.pack(pady=(20, 0))

        self.lbl_meaning = ctk.CTkLabel(
            meaning_row,
            text="Sẵn sàng?",
            font=("Arial", MEANING_FONT_SIZE, "bold"),
            text_color="#1f6aa5",
            wraplength=1000,
        )
        self.lbl_meaning.pack(side="left", padx=(0, 10))

        self.btn_tts_meaning = ctk.CTkButton(
            meaning_row,
            text="🔊",
            width=50,
            height=50,
            font=("Arial", 24),
            fg_color="transparent",
            hover_color="#2a2a2a",
            command=self._speak_current_hanzi,
        )
        self.btn_tts_meaning.pack(side="left")

        # Pinyin
        self.lbl_pinyin = ctk.CTkLabel(
            self.card_frame,
            text="---",
            font=("Arial", PINYIN_FONT_SIZE),
            text_color="#d68910",
            wraplength=1000,
        )
        self.lbl_pinyin.pack(pady=10)

        # Hán tự
        self.lbl_hanzi = ctk.CTkLabel(
            self.card_frame, text="---", font=(HANZI_FONT_NAME, MAX_HANZI_SIZE)
        )
        self.lbl_hanzi.pack(pady=20, expand=True)

        # Buttons
        self.bottom_frame = ctk.CTkFrame(
            self.tab_review, fg_color="transparent", height=100
        )
        self.bottom_frame.pack(pady=30, fill="x")

        self.btn_next_step = ctk.CTkButton(
            self.bottom_frame,
            text="Hiện đáp án",
            width=400,
            height=70,
            command=self.next_step,
            font=("Arial", 24, "bold"),
        )
        self.btn_next_step.pack(pady=10)

        self.btn_forgot = ctk.CTkButton(
            self.bottom_frame,
            text="QUÊN",
            fg_color="#e74c3c",
            command=lambda: self.rate_word("forgot"),
            width=300,
            height=70,
            font=("Arial", 22, "bold"),
        )
        self.btn_ok = ctk.CTkButton(
            self.bottom_frame,
            text="NHỚ",
            fg_color="#2ecc71",
            command=lambda: self.rate_word("ok"),
            width=300,
            height=70,
            font=("Arial", 22, "bold"),
        )

        self.bind("<space>", lambda event: self.next_step())
        self.toggle_eval_buttons(False)

    # --- Loa ---
    def _speak_current_hanzi(self):
        if self.current_review_list.empty:
            return
        row = self.current_review_list.iloc[self.current_index]
        self.tts.speak(row["Hanzi"])

    # --- Tự động chỉnh cỡ chữ ---
    def update_hanzi_display(self, text):
        screen_width = self.winfo_width()
        if screen_width < 100:
            screen_width = self.winfo_screenwidth()

        available_width = screen_width - 200
        char_count = len(text)
        if char_count == 0:
            return

        calculated_size = int(available_width / (char_count * 1.1))
        final_size = min(MAX_HANZI_SIZE, calculated_size)

        if final_size < 80:
            final_size = 100
            self.lbl_hanzi.configure(wraplength=available_width)
        else:
            self.lbl_hanzi.configure(wraplength=9999)

        self.lbl_hanzi.configure(text=text, font=(HANZI_FONT_NAME, final_size))

    # ========================= ARROW KEY HOLD =========================

    def _on_right_press(self, event):
        if "right" not in self._arrow_press_start:
            self._arrow_press_start["right"] = time.time()
            self._schedule_hold_check("right")

    def _on_right_release(self, event):
        self._arrow_press_start.pop("right", None)

    def _on_left_press(self, event):
        if "left" not in self._arrow_press_start:
            self._arrow_press_start["left"] = time.time()
            self._schedule_hold_check("left")

    def _on_left_release(self, event):
        self._arrow_press_start.pop("left", None)

    def _schedule_hold_check(self, direction):
        def check():
            start = self._arrow_press_start.get(direction)
            if start is None:
                return  # Đã nhả phím
            elapsed = time.time() - start
            if elapsed >= self._arrow_hold_threshold:
                self._arrow_press_start.pop(direction, None)
                # Chỉ kích hoạt nếu đang ở trạng thái đánh giá (step == 2)
                if self.step == 2:
                    if direction == "right":
                        self.after(0, lambda: self.rate_word("ok"))
                    else:
                        self.after(0, lambda: self.rate_word("forgot"))
            else:
                # Kiểm tra lại sau 100ms
                self.after(100, check)

        self.after(100, check)

    # ========================= SESSION =========================

    def start_smart_review(self):
        self.is_cram_mode = False
        today_date = datetime.now().date()
        mask = self.df["Next_Review"].dt.date <= today_date
        due_words = self.df[mask]
        if due_words.empty:
            messagebox.showinfo("Tuyệt vời", "Bạn đã hoàn thành hết các từ cần ôn hôm nay!")
            return
        self.current_review_list = due_words.sample(frac=1).reset_index(drop=True)
        self.setup_session(len(self.current_review_list))

    def start_cram_review(self):
        self.is_cram_mode = True
        try:
            amount = int(self.cram_option_var.get())
        except Exception:
            amount = 10
        if self.df.empty:
            return
        n = min(amount, len(self.df))
        self.current_review_list = self.df.sample(n).reset_index(drop=True)
        self.setup_session(n)

    def setup_session(self, count):
        self.current_index = 0
        self.step = 0
        mode_text = "CẤP TỐC" if self.is_cram_mode else "Theo ngày"
        self.progress_bar.set(1 / count)
        self.lbl_progress_text.configure(text=f"1 / {count}")
        messagebox.showinfo("Bắt đầu", f"Chế độ: {mode_text}\nSố lượng: {count} từ.")
        self.show_card_state()

    def show_card_state(self):
        row = self.current_review_list.iloc[self.current_index]
        self.lbl_meaning.configure(text=row["Meaning"].upper())
        self.lbl_pinyin.configure(text="???")
        self.lbl_hanzi.configure(text="?", font=("Arial", 200), wraplength=9999)
        self.toggle_eval_buttons(False)
        self.btn_next_step.pack(pady=10)

    def next_step(self):
        if self.current_review_list.empty:
            return
        row = self.current_review_list.iloc[self.current_index]

        if self.step == 0:
            self.step = 1
            py_text = row.get("Pinyin")
            if pd.isna(py_text) or py_text == "":
                py_text = self.generate_pinyin(row["Hanzi"])
            self.lbl_pinyin.configure(text=py_text)

        elif self.step == 1:
            self.step = 2
            self.update_hanzi_display(row["Hanzi"])
            self.btn_next_step.pack_forget()
            self.toggle_eval_buttons(True)

            if self.is_cram_mode:
                self.btn_ok.configure(text="NHỚ ")
                self.btn_forgot.configure(text="QUÊN")
            else:
                self.btn_ok.configure(text="NHỚ")
                self.btn_forgot.configure(text="QUÊN")

    def toggle_eval_buttons(self, show):
        if show:
            self.btn_forgot.pack(side="left", padx=20, expand=True)
            self.btn_ok.pack(side="right", padx=20, expand=True)
        else:
            self.btn_forgot.pack_forget()
            self.btn_ok.pack_forget()

    def rate_word(self, rating):
        if self.current_review_list.empty:
            return
        current_word_hanzi = self.current_review_list.iloc[self.current_index]["Hanzi"]
        idx = self.df.index[self.df["Hanzi"] == current_word_hanzi].tolist()[0]
        current_level = int(self.df.at[idx, "Level"])
        should_save = False
        now_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if self.is_cram_mode:
            if rating == "forgot":
                self.df.at[idx, "Level"] = 0
                self.df.at[idx, "Next_Review"] = now_midnight
                should_save = True
        else:
            if rating == "ok":
                new_level = current_level + 1
                days_add = 1 if current_level == 1 else 2 ** (new_level - 1)
            else:
                new_level = 0
                days_add = 0

            self.df.at[idx, "Level"] = new_level
            next_date = now_midnight + timedelta(days=days_add)
            self.df.at[idx, "Next_Review"] = next_date
            should_save = True

        if should_save:
            self.save_data()

        self.step = 0
        total_words = len(self.current_review_list)

        if self.current_index < total_words - 1:
            self.current_index += 1
            current_num = self.current_index + 1
            progress_val = current_num / total_words
            self.progress_bar.set(progress_val)
            self.lbl_progress_text.configure(text=f"{current_num} / {total_words}")
            self.show_card_state()
        else:
            self.progress_bar.set(1.0)
            self.lbl_progress_text.configure(
                text=f"{total_words} / {total_words} (HOÀN THÀNH)"
            )
            messagebox.showinfo("Hoàn thành", "Đã ôn xong danh sách!")
            self.lbl_meaning.configure(text="HẾT")
            self.lbl_pinyin.configure(text="---")
            self.lbl_hanzi.configure(text="---", font=("Arial", 100))
            self.toggle_eval_buttons(False)

    # ========================= TAB 2: QUẢN LÝ =========================

    def setup_manage_tab(self):
        input_frame = ctk.CTkFrame(self.tab_manage)
        input_frame.pack(pady=20, padx=20, fill="x")

        left_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True)
        font_input = ("Arial", UI_FONT_SIZE)

        # --- Hán tự ---
        ctk.CTkLabel(left_frame, text="Hán tự:", font=font_input).grid(
            row=0, column=0, padx=10, pady=10
        )
        self.entry_hanzi = ctk.CTkEntry(
            left_frame, font=font_input, height=40, width=200
        )
        self.entry_hanzi.grid(row=0, column=1, padx=10, pady=10)
        # KHÔNG bind FocusOut tự động nữa — dùng nút làm mới

        # --- Pinyin + nút làm mới ---
        ctk.CTkLabel(left_frame, text="Pinyin:", font=font_input).grid(
            row=1, column=0, padx=10, pady=10
        )

        pinyin_row = ctk.CTkFrame(left_frame, fg_color="transparent")
        pinyin_row.grid(row=1, column=1, padx=10, pady=10, sticky="w")

        self.entry_pinyin = ctk.CTkEntry(
            pinyin_row, font=font_input, height=40, width=350
        )
        self.entry_pinyin.pack(side="left", padx=(0, 8))

        self.btn_regen_pinyin = ctk.CTkButton(
            pinyin_row,
            text="🗘",
            width=44,
            height=40,
            font=("Arial", 20),
            fg_color="#2980b9",
            hover_color="#1a5276",
            command=self.regen_pinyin
        )
        self.btn_regen_pinyin.pack(side="left")

        self.btn_tts_manage = ctk.CTkButton(
            pinyin_row,
            text="🔊",
            width=44,
            height=40,
            font=("Arial", 20),
            fg_color="transparent",
            hover_color="#2a2a2a",
            command=self._speak_manage_hanzi,
        )
        self.btn_tts_manage.pack(side="left", padx=(4, 0))

        # --- Nghĩa ---
        ctk.CTkLabel(left_frame, text="Nghĩa TV:", font=font_input).grid(
            row=2, column=0, padx=10, pady=10
        )
        self.entry_meaning = ctk.CTkEntry(
            left_frame, font=font_input, height=40, width=400
        )
        self.entry_meaning.grid(row=2, column=1, padx=10, pady=10)

        btn_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)

        ctk.CTkButton(
            btn_frame,
            text="Thêm",
            command=self.add_word,
            width=120,
            height=40,
            font=font_input,
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            btn_frame,
            text="Cập Nhật",
            command=self.update_word,
            fg_color="#d68910",
            width=120,
            height=40,
            font=font_input,
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            btn_frame,
            text="Xóa",
            command=self.delete_word,
            fg_color="#c0392b",
            width=120,
            height=40,
            font=font_input,
        ).pack(side="left", padx=10)

        right_frame = ctk.CTkFrame(input_frame)
        right_frame.pack(side="right", fill="y", padx=20, pady=10)

        self.entry_search = ctk.CTkEntry(
            right_frame,
            placeholder_text="Tìm kiếm...",
            font=font_input,
            height=40,
            width=250,
        )
        self.entry_search.pack(padx=10, pady=20)
        self.entry_search.bind("<KeyRelease>", self.filter_table)

        self.sort_var = ctk.StringVar(value="Ngày thêm (Mới -> Cũ)")
        self.sort_menu = ctk.CTkOptionMenu(
            right_frame,
            values=[
                "Ngày thêm (Mới -> Cũ)",
                "Ngày thêm (Cũ -> Mới)",
                "Level (Thấp -> Cao)",
                "Level (Cao -> Thấp)",
            ],
            variable=self.sort_var,
            command=self.on_sort_change,
            width=250,
            height=40,
            font=font_input,
        )
        self.sort_menu.pack(padx=10, pady=10)

        # Bảng
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview", font=("Arial", TABLE_FONT_SIZE), rowheight=TABLE_ROW_HEIGHT
        )
        style.configure(
            "Treeview.Heading",
            font=("Arial", TABLE_FONT_SIZE + 2, "bold"),
            rowheight=40,
        )

        self.tree = ttk.Treeview(
            self.tab_manage,
            columns=("Hanzi", "Pinyin", "Meaning", "Date", "Level"),
            show="headings",
        )
        self.tree.heading("Hanzi", text="Hán Tự")
        self.tree.heading("Pinyin", text="Pinyin")
        self.tree.heading("Meaning", text="Nghĩa")
        self.tree.heading("Date", text="Ngày")
        self.tree.heading("Level", text="Level")
        self.tree.column("Hanzi", width=150, anchor="center")
        self.tree.column("Pinyin", width=200)
        self.tree.column("Meaning", width=300)
        self.tree.column("Date", width=150, anchor="center")
        self.tree.column("Level", width=80, anchor="center")

        self.tree.pack(expand=True, fill="both", padx=20, pady=20)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        self.refresh_table()

    def regen_pinyin(self):
        """Tạo lại Pinyin từ Hán tự hiện tại trong ô nhập."""
        hanzi = self.entry_hanzi.get().strip()
        if not hanzi:
            messagebox.showwarning("Chú ý", "Vui lòng nhập Hán tự trước.")
            return
        generated = self.generate_pinyin(hanzi)
        self.entry_pinyin.delete(0, "end")
        self.entry_pinyin.insert(0, generated)

    def _speak_manage_hanzi(self):
        hanzi = self.entry_hanzi.get().strip()
        if hanzi:
            self.tts.speak(hanzi)

    def on_sort_change(self, choice):
        self.refresh_table()

    def refresh_table(self, data=None):
        for item in self.tree.get_children():
            self.tree.delete(item)
        if data is None:
            sort_mode = self.sort_var.get()
            if sort_mode == "Ngày thêm (Mới -> Cũ)":
                data = self.df.sort_values(by="Date", ascending=False)
            elif sort_mode == "Ngày thêm (Cũ -> Mới)":
                data = self.df.sort_values(by="Date", ascending=True)
            elif sort_mode == "Level (Thấp -> Cao)":
                data = self.df.sort_values(by="Level", ascending=True)
            elif sort_mode == "Level (Cao -> Thấp)":
                data = self.df.sort_values(by="Level", ascending=False)
            else:
                data = self.df
        for index, row in data.iterrows():
            date_str = row["Date"].strftime("%d/%m/%Y")
            pinyin_show = row.get("Pinyin", "")
            if pd.isna(pinyin_show):
                pinyin_show = ""
            self.tree.insert(
                "",
                "end",
                values=(row["Hanzi"], pinyin_show, row["Meaning"], date_str, row["Level"]),
            )

    def filter_table(self, event):
        query = self.entry_search.get().lower()
        if not query:
            self.refresh_table()
            return
        filtered = self.df[
            self.df["Hanzi"].str.contains(query, case=False, na=False)
            | self.df["Meaning"].str.contains(query, case=False, na=False)
            | self.df["Pinyin"].str.contains(query, case=False, na=False)
        ]
        self.refresh_table(filtered)

    def on_tree_select(self, event):
        selected_item = self.tree.selection()
        if not selected_item:
            return
        values = self.tree.item(selected_item[0], "values")
        self.entry_hanzi.delete(0, "end")
        self.entry_hanzi.insert(0, values[0])
        self.entry_pinyin.delete(0, "end")
        self.entry_pinyin.insert(0, values[1])
        self.entry_meaning.delete(0, "end")
        self.entry_meaning.insert(0, values[2])

    def add_word(self):
        hanzi = self.entry_hanzi.get().strip()
        meaning = self.entry_meaning.get().strip()
        pinyin_text = self.entry_pinyin.get().strip()
        if not hanzi or not meaning:
            messagebox.showwarning("Chú ý", "Vui lòng nhập đầy đủ Hán tự và Nghĩa.")
            return
        if not pinyin_text:
            pinyin_text = self.generate_pinyin(hanzi)
        now_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        new_row = {
            "Hanzi": hanzi,
            "Pinyin": pinyin_text,
            "Meaning": meaning,
            "Date": now_midnight,
            "Level": 0,
            "Next_Review": now_midnight,
        }
        self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)
        self.save_data()
        self.refresh_table()
        self.clear_inputs()

    def update_word(self):
        hanzi = self.entry_hanzi.get().strip()
        meaning = self.entry_meaning.get().strip()
        pinyin_text = self.entry_pinyin.get().strip()
        if hanzi not in self.df["Hanzi"].values:
            messagebox.showwarning("Không tìm thấy", f"Không có từ '{hanzi}' trong danh sách.")
            return
        idx = self.df.index[self.df["Hanzi"] == hanzi].tolist()[0]
        self.df.at[idx, "Meaning"] = meaning
        self.df.at[idx, "Pinyin"] = pinyin_text
        self.save_data()
        self.refresh_table()
        messagebox.showinfo("Xong", "Đã cập nhật!")

    def delete_word(self):
        hanzi = self.entry_hanzi.get().strip()
        if hanzi in self.df["Hanzi"].values:
            if messagebox.askyesno("Xóa", f"Xóa từ '{hanzi}'?"):
                self.df = self.df[self.df.Hanzi != hanzi]
                self.save_data()
                self.refresh_table()
                self.clear_inputs()

    def clear_inputs(self):
        self.entry_hanzi.delete(0, "end")
        self.entry_pinyin.delete(0, "end")
        self.entry_meaning.delete(0, "end")


if __name__ == "__main__":
    if not TTS_AVAILABLE:
        print(
            "[Cảnh báo] Chưa cài gtts hoặc pygame. Tính năng đọc sẽ bị tắt.\n"
            "Cài bằng: pip install gtts pygame"
        )
    app = ChineseLearningApp()
    app.mainloop()
