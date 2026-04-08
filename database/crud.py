"""
database/crud.py
================
Tầng truy cập dữ liệu (Data Access Layer) cho toàn bộ ứng dụng.

Quy ước thiết kế:
  - Mỗi hàm nhận một `session: Session` làm tham số đầu tiên.
    → Việc quản lý vòng đời session (tạo / đóng) là trách nhiệm
      của lớp gọi (thường là UI hoặc main app).
  - Hàm trả về object hoặc list trực tiếp, KHÔNG commit bên trong
    trừ các hàm ghi (create / update / delete) — chúng tự commit.
  - Khi lỗi xảy ra trong hàm ghi, session được rollback và exception
    được re-raise để tầng UI có thể hiển thị thông báo.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import or_, func

# Import model từ cùng package
from database.models import Flashcard, GrammarNote


# ═══════════════════════════════════════════════════════════════
#  PHẦN 1 — FLASHCARD
# ═══════════════════════════════════════════════════════════════

# ── SRS (Spaced Repetition System) ──────────────────────────────

def get_due_flashcards(session: Session) -> list[Flashcard]:
    """
    Trả về danh sách từ cần ôn hôm nay (next_review <= ngày hiện tại).
    Kết quả được trộn ngẫu nhiên bằng hàm RANDOM() của SQLite.
    """
    today = datetime.now().replace(hour=23, minute=59, second=59)
    return (
        session.query(Flashcard)
        .filter(Flashcard.next_review <= today)
        .order_by(func.random())
        .all()
    )


def get_random_flashcards(session: Session, n: int) -> list[Flashcard]:
    """
    Trả về n từ bất kỳ (chế độ ôn cấp tốc).
    SQLite hỗ trợ ORDER BY RANDOM() nên không cần shuffle ở Python.
    """
    return (
        session.query(Flashcard)
        .order_by(func.random())
        .limit(n)
        .all()
    )


def update_flashcard_after_review(
    session: Session,
    flashcard: Flashcard,
    remembered: bool,
) -> None:
    """
    Cập nhật level và ngày ôn tiếp theo theo thuật toán SRS exponential.

    Công thức:
      - Nhớ (ok):  level += 1,  next_review = hôm nay + 2^(level-1) ngày
                   (level 1 → +1 ngày, level 2 → +2, level 3 → +4, ...)
      - Quên:      level = 0,   next_review = hôm nay (ôn lại ngay)
    """
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if remembered:
        new_level = flashcard.level + 1
        days_add  = 1 if flashcard.level <= 1 else 2 ** (new_level - 1)
        flashcard.level       = new_level
        flashcard.next_review = midnight + timedelta(days=days_add)
    else:
        flashcard.level       = 0
        flashcard.next_review = midnight

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def undo_flashcard_review(
    session: Session,
    flashcard: Flashcard,
    old_level: int,
    old_next_review: datetime,
) -> None:
    """
    Hoàn tác thao tác đánh giá: khôi phục level và next_review cũ.
    Snapshot (old_level, old_next_review) phải được lưu trước khi gọi
    update_flashcard_after_review().
    """
    flashcard.level       = old_level
    flashcard.next_review = old_next_review
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


# ── CRUD cơ bản cho Flashcard ────────────────────────────────────

def get_all_flashcards(
    session: Session,
    sort_by: str = "date_desc",
) -> list[Flashcard]:
    """
    Trả về tất cả Flashcard với tuỳ chọn sắp xếp.

    sort_by nhận một trong các giá trị:
      'date_desc' | 'date_asc' | 'level_asc' | 'level_desc'
    """
    order_map = {
        "date_desc":  Flashcard.date_added.desc(),
        "date_asc":   Flashcard.date_added.asc(),
        "level_asc":  Flashcard.level.asc(),
        "level_desc": Flashcard.level.desc(),
    }
    order_clause = order_map.get(sort_by, Flashcard.date_added.desc())
    return session.query(Flashcard).order_by(order_clause).all()


def search_flashcards(session: Session, query: str) -> list[Flashcard]:
    """
    Tìm kiếm Flashcard theo hanzi, pinyin hoặc meaning.
    Dùng LIKE case-insensitive (SQLite mặc định case-insensitive với ASCII).
    """
    q = f"%{query}%"
    return (
        session.query(Flashcard)
        .filter(
            or_(
                Flashcard.hanzi.ilike(q),
                Flashcard.pinyin.ilike(q),
                Flashcard.meaning.ilike(q),
            )
        )
        .all()
    )


def get_flashcard_by_id(session: Session, flashcard_id: int) -> Optional[Flashcard]:
    """Lấy một Flashcard theo primary key. Trả về None nếu không tìm thấy."""
    return session.get(Flashcard, flashcard_id)


def create_flashcard(
    session: Session,
    hanzi: str,
    pinyin: str,
    meaning: str,
) -> Flashcard:
    """
    Tạo Flashcard mới với level=0, next_review=hôm nay.
    Trả về object vừa tạo (đã có id sau khi commit).
    """
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    card = Flashcard(
        hanzi=hanzi.strip(),
        pinyin=pinyin.strip(),
        meaning=meaning.strip(),
        date_added=midnight,
        level=0,
        next_review=midnight,
    )
    session.add(card)
    try:
        session.commit()
        session.refresh(card)   # đảm bảo id được load từ DB
        return card
    except Exception:
        session.rollback()
        raise


def update_flashcard(
    session: Session,
    flashcard: Flashcard,
    pinyin: Optional[str] = None,
    meaning: Optional[str] = None,
) -> Flashcard:
    """
    Cập nhật pinyin và/hoặc meaning của một Flashcard.
    Chỉ cập nhật trường nào được truyền vào (không None).
    """
    if pinyin  is not None: flashcard.pinyin  = pinyin.strip()
    if meaning is not None: flashcard.meaning = meaning.strip()
    try:
        session.commit()
        return flashcard
    except Exception:
        session.rollback()
        raise


def delete_flashcard(session: Session, flashcard: Flashcard) -> None:
    """Xoá một Flashcard khỏi database."""
    session.delete(flashcard)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


# ── Thống kê cho Dashboard ───────────────────────────────────────

def get_flashcard_stats(session: Session) -> dict:
    """
    Trả về dict thống kê để vẽ Dashboard:
      total, due_today, mastered (level>=5), avg_level,
      level_distribution {level: count},
      daily_added [(date, count)] 30 ngày gần nhất
    """
    today = datetime.now().date()

    all_cards = session.query(Flashcard).all()
    total     = len(all_cards)

    if total == 0:
        return {
            "total": 0, "due_today": 0, "mastered": 0, "avg_level": 0.0,
            "level_distribution": {}, "daily_added": [],
        }

    due_today = sum(1 for c in all_cards
                    if c.next_review and c.next_review.date() <= today)
    mastered  = sum(1 for c in all_cards if c.level >= 5)
    avg_level = round(sum(c.level for c in all_cards) / total, 1)

    # Phân bổ level
    level_dist: dict[int, int] = {}
    for c in all_cards:
        level_dist[c.level] = level_dist.get(c.level, 0) + 1

    # Từ thêm theo ngày (30 ngày)
    cutoff = datetime.now() - timedelta(days=29)
    daily_counts: dict = {}
    for c in all_cards:
        if c.date_added and c.date_added >= cutoff:
            d = c.date_added.date()
            daily_counts[d] = daily_counts.get(d, 0) + 1

    return {
        "total":              total,
        "due_today":          due_today,
        "mastered":           mastered,
        "avg_level":          avg_level,
        "level_distribution": level_dist,
        "daily_added":        sorted(daily_counts.items()),   # [(date, n), ...]
        "all_cards":          all_cards,   # giữ nguyên để Dashboard dùng thêm
    }


# ═══════════════════════════════════════════════════════════════
#  PHẦN 2 — GRAMMAR NOTE
# ═══════════════════════════════════════════════════════════════

NOTE_TYPES = ("grammar", "comparison")   # hằng số dùng chung toàn app


def get_all_grammar_notes(
    session: Session,
    note_type: Optional[str] = None,
    sort_by: str = "level_asc",
) -> list[GrammarNote]:
    """
    Trả về danh sách GrammarNote.

    Tham số:
      note_type — 'grammar' | 'comparison' | None (lấy tất cả)
      sort_by   — 'level_asc' | 'level_desc' | 'title_asc'
    """
    q = session.query(GrammarNote)
    if note_type and note_type in NOTE_TYPES:
        q = q.filter(GrammarNote.note_type == note_type)

    order_map = {
        "level_asc":  GrammarNote.level.asc(),
        "level_desc": GrammarNote.level.desc(),
        "title_asc":  GrammarNote.title.asc(),
    }
    q = q.order_by(order_map.get(sort_by, GrammarNote.level.asc()))
    return q.all()


def search_grammar_notes(
    session: Session,
    query: str,
    note_type: Optional[str] = None,
) -> list[GrammarNote]:
    """
    Tìm kiếm GrammarNote theo title, formula hoặc explanation.
    Có thể kết hợp với bộ lọc note_type.
    """
    q_str = f"%{query}%"
    base  = session.query(GrammarNote).filter(
        or_(
            GrammarNote.title.ilike(q_str),
            GrammarNote.formula.ilike(q_str),
            GrammarNote.explanation.ilike(q_str),
        )
    )
    if note_type and note_type in NOTE_TYPES:
        base = base.filter(GrammarNote.note_type == note_type)
    return base.order_by(GrammarNote.level.asc()).all()


def get_grammar_note_by_id(
    session: Session, note_id: int
) -> Optional[GrammarNote]:
    """Lấy một GrammarNote theo id. Trả về None nếu không tìm thấy."""
    return session.get(GrammarNote, note_id)


def create_grammar_note(
    session: Session,
    note_type: str,
    title: str,
    level: int,
    formula: str,
    explanation: str,
    examples: str,
) -> GrammarNote:
    """
    Tạo GrammarNote mới.
    Tự động strip khoảng trắng thừa; note_type được chuẩn hoá lowercase.
    """
    note = GrammarNote(
        note_type=note_type.strip().lower(),
        title=title.strip(),
        level=int(level),
        formula=formula.strip(),
        explanation=explanation.strip(),
        examples=examples.strip(),
    )
    session.add(note)
    try:
        session.commit()
        session.refresh(note)
        return note
    except Exception:
        session.rollback()
        raise


def update_grammar_note(
    session: Session,
    note: GrammarNote,
    note_type: Optional[str] = None,
    title: Optional[str] = None,
    level: Optional[int] = None,
    formula: Optional[str] = None,
    explanation: Optional[str] = None,
    examples: Optional[str] = None,
) -> GrammarNote:
    """
    Cập nhật từng trường của GrammarNote (chỉ trường nào không None).
    """
    if note_type   is not None: note.note_type   = note_type.strip().lower()
    if title       is not None: note.title       = title.strip()
    if level       is not None: note.level       = int(level)
    if formula     is not None: note.formula     = formula.strip()
    if explanation is not None: note.explanation = explanation.strip()
    if examples    is not None: note.examples    = examples.strip()
    try:
        session.commit()
        return note
    except Exception:
        session.rollback()
        raise


def delete_grammar_note(session: Session, note: GrammarNote) -> None:
    """Xoá một GrammarNote khỏi database."""
    session.delete(note)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
