from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Flashcard(Base):
    __tablename__ = 'flashcards'

    id = Column(Integer, primary_key=True, autoincrement=True)
    hanzi = Column(String(100), nullable=False)
    pinyin = Column(String(200))
    meaning = Column(String(500))
    date_added = Column(DateTime)
    level = Column(Integer, default=0)
    next_review = Column(DateTime)

class GrammarNote(Base):
    __tablename__ = 'grammar_notes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_type = Column(String(50))    # 'grammar' hoặc 'comparison'
    title = Column(String(200))
    level = Column(Integer)
    formula = Column(String(500))
    explanation = Column(Text)
    examples = Column(Text)
