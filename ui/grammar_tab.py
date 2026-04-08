"""
ui/grammar_tab.py
=================
Tab "Sổ Tay Ngữ Pháp" — giao diện Master-Detail.

Kiến trúc kết nối DB → UI:
  ┌─────────────────────────────────────────────┐
  │  GrammarTab (CTkFrame)                      │
  │   ├── session      ← SQLAlchemy Session     │
  │   ├── _notes       ← list[GrammarNote]      │  (cache hiện tại)
  │   ├── _selected    ← GrammarNote | None     │  (đang chọn)
  │   └── tts          ← TTSPlayer              │
  └─────────────────────────────────────────────┘

Luồng dữ liệu:
  1. _load_notes()  → gọi crud → gán self._notes → _render_master_list()
  2. Người dùng click card → _on_note_selected() → _fill_detail()
  3. Người dùng nhấn Lưu/Cập nhật → _save() / _update() → gọi crud → _load_notes()
"""

from __future__ import annotations

import customtkinter as ctk
from tkinter import messagebox

# Import tầng dữ liệu
from database import crud
from database.models import GrammarNote

# Màu sắc nhất quán với phần còn lại của app
COLOR_GRAMMAR    = "#2980b9"   # xanh dương — loại "Ngữ pháp"
COLOR_COMPARISON = "#8e44ad"   # tím       — loại "So sánh"
COLOR_SAVE       = "#27ae60"
COLOR_UPDATE     = "#d68910"
COLOR_DELETE     = "#c0392b"
COLOR_CLEAR      = "#7f8c8d"

UI_FONT          = ("Arial", 16)
UI_FONT_BOLD     = ("Arial", 16, "bold")
LABEL_FONT       = ("Arial", 14)


class GrammarTab(ctk.CTkFrame):
    """
    Widget chính của tab Sổ Tay Ngữ Pháp.
    Được nhúng vào tabview của ChineseLearningApp.

    Tham số:
      parent  — widget cha (tab frame từ CTkTabview)
      session — SQLAlchemy session (chia sẻ từ app chính)
      tts     — instance TTSPlayer từ app chính
      on_back_to_manage — callback không bắt buộc, dùng khi cần
    """

    def __init__(
        self,
        parent,
        session,
        tts,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.session   = session
        self.tts       = tts
        self._notes: list[GrammarNote] = []
        self._selected: GrammarNote | None = None
        # Lưu các widget card để highlight
        self._card_widgets: dict[int, ctk.CTkFrame] = {}

        self._build_ui()
        self._load_notes()

    # ════════════════════════════════════════════════════════
    #  BUILD UI
    # ════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        """Tạo layout 2 cột: Master (trái) và Detail (phải)."""
        self.columnconfigure(0, weight=3)    # cột trái rộng hơn một chút
        self.columnconfigure(1, weight=5)    # cột phải rộng hơn
        self.rowconfigure(0, weight=1)

        self._build_master_panel()
        self._build_detail_panel()

    # ── CỘT TRÁI: MASTER LIST ────────────────────────────────

    def _build_master_panel(self) -> None:
        master = ctk.CTkFrame(self, corner_radius=12)
        master.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="nsew")
        master.rowconfigure(2, weight=1)
        master.columnconfigure(0, weight=1)

        # Tiêu đề
        ctk.CTkLabel(
            master,
            text="Danh sách ghi chú",
            font=("Arial", 18, "bold"),
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        # Thanh tìm kiếm + bộ lọc
        filter_frame = ctk.CTkFrame(master, fg_color="transparent")
        filter_frame.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        filter_frame.columnconfigure(0, weight=1)

        self.entry_search = ctk.CTkEntry(
            filter_frame,
            placeholder_text="Tìm kiếm...",
            font=UI_FONT,
            height=36,
        )
        self.entry_search.grid(row=0, column=0, columnspan=2,
                               padx=(0, 0), pady=(0, 6), sticky="ew")
        self.entry_search.bind("<KeyRelease>", self._on_search)

        # Combobox lọc loại
        ctk.CTkLabel(filter_frame, text="Lọc:", font=LABEL_FONT).grid(
            row=1, column=0, sticky="w")
        self.filter_var = ctk.StringVar(value="Tất cả")
        self.combo_filter = ctk.CTkComboBox(
            filter_frame,
            values=["Tất cả", "Ngữ pháp", "So sánh"],
            variable=self.filter_var,
            font=UI_FONT,
            height=34,
            command=self._on_filter_change,
        )
        self.combo_filter.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        filter_frame.columnconfigure(1, weight=1)

        # Scrollable list
        self.scroll_frame = ctk.CTkScrollableFrame(
            master,
            fg_color="transparent",
            corner_radius=0,
        )
        self.scroll_frame.grid(row=2, column=0, padx=8, pady=(0, 8),
                               sticky="nsew")
        self.scroll_frame.columnconfigure(0, weight=1)

    # ── CỘT PHẢI: DETAIL FORM ────────────────────────────────

    def _build_detail_panel(self) -> None:
        detail = ctk.CTkFrame(self, corner_radius=12)
        detail.grid(row=0, column=1, padx=(8, 0), pady=0, sticky="nsew")
        detail.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            detail,
            text="Chi tiết / Soạn thảo",
            font=("Arial", 18, "bold"),
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 10), sticky="w")

        fi = UI_FONT

        # ── Loại ghi chú ──
        ctk.CTkLabel(detail, text="Loại:", font=fi).grid(
            row=1, column=0, padx=(16, 8), pady=6, sticky="w")
        self.type_var = ctk.StringVar(value="Ngữ pháp")
        self.combo_type = ctk.CTkComboBox(
            detail,
            values=["Ngữ pháp", "So sánh"],
            variable=self.type_var,
            font=fi,
            height=36,
        )
        self.combo_type.grid(row=1, column=1, padx=(0, 16), pady=6, sticky="ew")

        # ── Tiêu đề ──
        ctk.CTkLabel(detail, text="Tiêu đề:", font=fi).grid(
            row=2, column=0, padx=(16, 8), pady=6, sticky="w")
        self.entry_title = ctk.CTkEntry(detail, font=fi, height=36)
        self.entry_title.grid(row=2, column=1, padx=(0, 16), pady=6, sticky="ew")

        # ── Level (HSK) ──
        ctk.CTkLabel(detail, text="Level (HSK):", font=fi).grid(
            row=3, column=0, padx=(16, 8), pady=6, sticky="w")
        self.entry_level = ctk.CTkEntry(detail, font=fi, height=36, width=80)
        self.entry_level.grid(row=3, column=1, padx=(0, 16), pady=6, sticky="w")
        self.entry_level.insert(0, "1")

        # ── Công thức ──
        ctk.CTkLabel(detail, text="Công thức:", font=fi).grid(
            row=4, column=0, padx=(16, 8), pady=6, sticky="w")
        self.entry_formula = ctk.CTkEntry(detail, font=fi, height=36)
        self.entry_formula.grid(row=4, column=1, padx=(0, 16), pady=6, sticky="ew")

        # ── Giải thích ──
        ctk.CTkLabel(detail, text="Giải thích:", font=fi).grid(
            row=5, column=0, padx=(16, 8), pady=(6, 0), sticky="nw")
        self.text_explanation = ctk.CTkTextbox(
            detail, font=fi, height=100, wrap="word")
        self.text_explanation.grid(row=5, column=1, padx=(0, 16),
                                   pady=(6, 0), sticky="ew")

        # ── Ví dụ + nút đọc ──
        example_label_row = ctk.CTkFrame(detail, fg_color="transparent")
        example_label_row.grid(row=6, column=0, padx=(16, 8), pady=(6, 0), sticky="nw")
        ctk.CTkLabel(example_label_row, text="Ví dụ:", font=fi).pack(side="left")
        # Nút đọc văn bản bôi đen — lấy selection từ textbox Examples
        ctk.CTkButton(
            example_label_row,
            text="🔊",
            width=36, height=28,
            font=("Arial", 16),
            fg_color="transparent",
            hover_color="#2a2a2a",
            command=self._speak_selected_text,
        ).pack(side="left", padx=(4, 0))

        self.text_examples = ctk.CTkTextbox(
            detail, font=fi, height=130, wrap="word")
        self.text_examples.grid(row=6, column=1, padx=(0, 16),
                                pady=(6, 0), sticky="ew")

        # ── Nút hành động ──
        btn_frame = ctk.CTkFrame(detail, fg_color="transparent")
        btn_frame.grid(row=7, column=0, columnspan=2,
                       padx=16, pady=16, sticky="ew")

        btn_cfg = {"font": UI_FONT_BOLD, "height": 42, "corner_radius": 8}

        ctk.CTkButton(
            btn_frame, text="💾 Lưu mới",
            fg_color=COLOR_SAVE,
            command=self._save_new,
            width=140, **btn_cfg,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="✏️ Cập nhật",
            fg_color=COLOR_UPDATE,
            command=self._update_note,
            width=140, **btn_cfg,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="🗑 Xóa",
            fg_color=COLOR_DELETE,
            command=self._delete_note,
            width=110, **btn_cfg,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="✖ Làm sạch",
            fg_color=COLOR_CLEAR,
            command=self._clear_form,
            width=130, **btn_cfg,
        ).pack(side="left")

    # ════════════════════════════════════════════════════════
    #  MASTER LIST — RENDER & EVENTS
    # ════════════════════════════════════════════════════════

    def _load_notes(self) -> None:
        """
        Lấy dữ liệu từ DB theo bộ lọc hiện tại rồi render lại danh sách.
        Đây là điểm kết nối chính giữa DB và UI master list.
        """
        q         = self.entry_search.get().strip()
        raw_type  = self.filter_var.get()
        note_type = self._ui_type_to_db(raw_type)

        if q:
            self._notes = crud.search_grammar_notes(
                self.session, q, note_type=note_type)
        else:
            self._notes = crud.get_all_grammar_notes(
                self.session, note_type=note_type)

        self._render_master_list()

    def _render_master_list(self) -> None:
        """
        Xoá toàn bộ card cũ rồi vẽ lại từ self._notes.
        Mỗi card là một CTkFrame bo góc, hiển thị title + type badge.
        """
        # Xoá card cũ
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        self._card_widgets.clear()

        if not self._notes:
            ctk.CTkLabel(
                self.scroll_frame,
                text="Không có ghi chú nào.",
                font=LABEL_FONT,
                text_color="gray",
            ).grid(row=0, column=0, pady=20)
            return

        for i, note in enumerate(self._notes):
            card = self._make_card(note)
            card.grid(row=i, column=0, padx=4, pady=4, sticky="ew")
            self._card_widgets[note.id] = card

        # Giữ highlight nếu đang chọn
        if self._selected:
            self._highlight_card(self._selected.id)

    def _make_card(self, note: GrammarNote) -> ctk.CTkFrame:
        """Tạo một card nhỏ trong master list cho một GrammarNote."""
        badge_color = (
            COLOR_GRAMMAR if note.note_type == "grammar" else COLOR_COMPARISON
        )
        card = ctk.CTkFrame(
            self.scroll_frame,
            corner_radius=10,
            border_width=1,
            border_color="#3a3a3a",
        )
        card.columnconfigure(0, weight=1)

        # Hàng 1: title + badge loại
        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.grid(row=0, column=0, padx=10, pady=(8, 2), sticky="ew")
        top_row.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top_row,
            text=note.title or "(Chưa có tiêu đề)",
            font=("Arial", 14, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        badge_text = "Ngữ pháp" if note.note_type == "grammar" else "So sánh"
        ctk.CTkLabel(
            top_row,
            text=badge_text,
            font=("Arial", 11),
            fg_color=badge_color,
            text_color="white",
            corner_radius=6,
            padx=8, pady=2,
        ).grid(row=0, column=1, sticky="e", padx=(4, 0))

        # Hàng 2: công thức (preview ngắn)
        if note.formula:
            ctk.CTkLabel(
                card,
                text=note.formula[:60] + ("…" if len(note.formula) > 60 else ""),
                font=("Arial", 12),
                text_color="#aaaaaa",
                anchor="w",
            ).grid(row=1, column=0, padx=10, pady=(0, 8), sticky="w")
        else:
            ctk.CTkFrame(card, height=6, fg_color="transparent").grid(row=1, column=0)

        # Bind click cho toàn bộ card và các widget con
        for widget in [card, top_row] + list(top_row.winfo_children()) + list(card.winfo_children()):
            try:
                widget.bind("<Button-1>",
                            lambda _, n=note: self._on_note_selected(n))
            except Exception:
                pass

        return card

    def _on_note_selected(self, note: GrammarNote) -> None:
        """
        Xử lý khi người dùng click vào một card.
        Cập nhật self._selected, highlight card và điền form Detail.
        """
        self._selected = note
        self._highlight_card(note.id)
        self._fill_detail(note)

    def _highlight_card(self, note_id: int) -> None:
        """Highlight card được chọn, bỏ highlight các card còn lại."""
        for nid, card in self._card_widgets.items():
            if nid == note_id:
                card.configure(border_color="#3498db", border_width=2)
            else:
                card.configure(border_color="#3a3a3a", border_width=1)

    # ════════════════════════════════════════════════════════
    #  DETAIL FORM — ĐIỀN VÀ LẤY DỮ LIỆU
    # ════════════════════════════════════════════════════════

    def _fill_detail(self, note: GrammarNote) -> None:
        """
        Điền toàn bộ form Detail từ một GrammarNote object.
        Đây là điểm kết nối DB object → widget UI.
        """
        self.type_var.set(
            "Ngữ pháp" if note.note_type == "grammar" else "So sánh"
        )

        self.entry_title.delete(0, "end")
        self.entry_title.insert(0, note.title or "")

        self.entry_level.delete(0, "end")
        self.entry_level.insert(0, str(note.level or 1))

        self.entry_formula.delete(0, "end")
        self.entry_formula.insert(0, note.formula or "")

        self.text_explanation.delete("1.0", "end")
        self.text_explanation.insert("1.0", note.explanation or "")

        self.text_examples.delete("1.0", "end")
        self.text_examples.insert("1.0", note.examples or "")

    def _read_form(self) -> dict:
        """
        Đọc giá trị từ toàn bộ form Detail, trả về dict.
        Validate cơ bản (title không rỗng, level là số nguyên).
        Raise ValueError nếu dữ liệu không hợp lệ.
        """
        note_type   = self._ui_type_to_db(self.type_var.get())
        title       = self.entry_title.get().strip()
        level_str   = self.entry_level.get().strip()
        formula     = self.entry_formula.get().strip()
        explanation = self.text_explanation.get("1.0", "end").strip()
        examples    = self.text_examples.get("1.0", "end").strip()

        if not title:
            raise ValueError("Tiêu đề không được để trống.")
        try:
            level = int(level_str)
        except ValueError:
            raise ValueError("Level phải là số nguyên (ví dụ: 1, 2, 3).")

        return dict(
            note_type=note_type,
            title=title,
            level=level,
            formula=formula,
            explanation=explanation,
            examples=examples,
        )

    # ════════════════════════════════════════════════════════
    #  CRUD ACTIONS (nối form → crud → DB)
    # ════════════════════════════════════════════════════════

    def _save_new(self) -> None:
        """
        Tạo GrammarNote mới từ dữ liệu trong form.
        Luồng: _read_form() → crud.create_grammar_note() → _load_notes()
        """
        try:
            data = self._read_form()
        except ValueError as e:
            messagebox.showwarning("Lỗi nhập liệu", str(e))
            return

        try:
            note = crud.create_grammar_note(self.session, **data)
        except Exception as e:
            messagebox.showerror("Lỗi CSDL", f"Không thể lưu ghi chú:\n{e}")
            return

        self._selected = note
        self._load_notes()
        messagebox.showinfo("Thành công", f"Đã lưu: '{note.title}'")

    def _update_note(self) -> None:
        """
        Cập nhật GrammarNote đang được chọn (self._selected).
        Luồng: validate → crud.update_grammar_note() → _load_notes()
        """
        if not self._selected:
            messagebox.showwarning("Chưa chọn", "Hãy chọn một ghi chú từ danh sách.")
            return

        try:
            data = self._read_form()
        except ValueError as e:
            messagebox.showwarning("Lỗi nhập liệu", str(e))
            return

        try:
            crud.update_grammar_note(self.session, self._selected, **data)
        except Exception as e:
            messagebox.showerror("Lỗi CSDL", f"Không thể cập nhật:\n{e}")
            return

        self._load_notes()
        messagebox.showinfo("Thành công", "Đã cập nhật ghi chú.")

    def _delete_note(self) -> None:
        """
        Xoá GrammarNote đang chọn sau khi xác nhận.
        Sau khi xoá: clear form, bỏ chọn, reload list.
        """
        if not self._selected:
            messagebox.showwarning("Chưa chọn", "Hãy chọn một ghi chú cần xoá.")
            return

        if not messagebox.askyesno(
            "Xác nhận xoá",
            f"Xoá ghi chú '{self._selected.title}'?\nThao tác này không thể hoàn tác."
        ):
            return

        try:
            crud.delete_grammar_note(self.session, self._selected)
        except Exception as e:
            messagebox.showerror("Lỗi CSDL", f"Không thể xoá:\n{e}")
            return

        self._selected = None
        self._clear_form()
        self._load_notes()

    def _clear_form(self) -> None:
        """Xoá sạch toàn bộ form Detail và bỏ highlight."""
        self._selected = None
        self.type_var.set("Ngữ pháp")
        self.entry_title.delete(0, "end")
        self.entry_level.delete(0, "end")
        self.entry_level.insert(0, "1")
        self.entry_formula.delete(0, "end")
        self.text_explanation.delete("1.0", "end")
        self.text_examples.delete("1.0", "end")
        # Bỏ highlight tất cả card
        for card in self._card_widgets.values():
            card.configure(border_color="#3a3a3a", border_width=1)

    # ════════════════════════════════════════════════════════
    #  TTS — ĐỌC VĂN BẢN BOI ĐEN
    # ════════════════════════════════════════════════════════

    def _speak_selected_text(self) -> None:
        """
        Lấy đoạn văn bản người dùng bôi đen trong text_examples
        rồi truyền vào TTSPlayer.speak().
        Nếu không có gì được bôi đen → đọc toàn bộ nội dung ô Examples.
        """
        try:
            text = self.text_examples.selection_get()
        except Exception:
            # Không có selection → lấy toàn bộ nội dung
            text = self.text_examples.get("1.0", "end").strip()

        if text:
            self.tts.speak(text)

    # ════════════════════════════════════════════════════════
    #  SEARCH & FILTER HANDLERS
    # ════════════════════════════════════════════════════════

    def _on_search(self, _event=None) -> None:
        self._load_notes()

    def _on_filter_change(self, _value=None) -> None:
        self._load_notes()

    # ════════════════════════════════════════════════════════
    #  PUBLIC API — gọi từ bên ngoài (main.py)
    # ════════════════════════════════════════════════════════

    def prefill_title(self, text: str) -> None:
        """
        Điền sẵn tiêu đề vào form Detail (từ Tab Quản lý từ vựng).
        Đồng thời clear form để bắt đầu soạn mới.
        """
        self._clear_form()
        self.entry_title.delete(0, "end")
        self.entry_title.insert(0, text)

    def reload(self) -> None:
        """Reload danh sách từ DB (gọi khi data bên ngoài thay đổi)."""
        self._load_notes()

    # ════════════════════════════════════════════════════════
    #  HELPER
    # ════════════════════════════════════════════════════════

    @staticmethod
    def _ui_type_to_db(ui_value: str) -> str | None:
        """Chuyển giá trị Combobox UI → giá trị DB ('grammar'/'comparison'/None)."""
        mapping = {"Ngữ pháp": "grammar", "So sánh": "comparison"}
        return mapping.get(ui_value, None)
