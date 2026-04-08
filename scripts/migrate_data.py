import os
import sys
import pandas as pd
from datetime import datetime

# Thêm đường dẫn thư mục gốc vào hệ thống để import được module database
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, Flashcard

# Định nghĩa đường dẫn
EXCEL_PATH = os.path.join("OldVersion", "library.xlsx")
DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "app_database.db")

def migrate():
    print(f"[*] Bắt đầu đọc dữ liệu từ: {EXCEL_PATH}")
    if not os.path.exists(EXCEL_PATH):
        print("[!] Không tìm thấy file library.xlsx trong thư mục OldVersion.")
        return

    # Đọc Excel
    df = pd.read_excel(EXCEL_PATH)
    total_words = len(df)
    print(f"[*] Tìm thấy {total_words} từ vựng.")

    # Xử lý các giá trị rỗng (NaN/NaT) của pandas
    df = df.where(pd.notnull(df), None)

    # Tạo thư mục data/ nếu chưa có
    os.makedirs(DB_DIR, exist_ok=True)

    # Kết nối SQLite và tạo bảng
    engine = create_engine(f'sqlite:///{DB_PATH}')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    print(f"[*] Đang chuyển đổi và nạp vào database: {DB_PATH}")

    # Nạp dữ liệu
    try:
        for index, row in df.iterrows():
            # Xử lý ngày tháng an toàn
            date_added = row.get('Date')
            if isinstance(date_added, str):
                date_added = datetime.strptime(date_added[:10], "%Y-%m-%d")

            next_rev = row.get('Next_Review')
            if isinstance(next_rev, str):
                next_rev = datetime.strptime(next_rev[:10], "%Y-%m-%d")

            flashcard = Flashcard(
                hanzi=row.get('Hanzi', ''),
                pinyin=row.get('Pinyin', ''),
                meaning=row.get('Meaning', ''),
                date_added=date_added,
                level=int(row.get('Level', 0)) if row.get('Level') is not None else 0,
                next_review=next_rev
            )
            session.add(flashcard)

        session.commit()
        print("[*] THÀNH CÔNG! Đã nạp xong toàn bộ dữ liệu vào SQLite.")
    except Exception as e:
        session.rollback()
        print(f"[!] Lỗi trong quá trình nạp dữ liệu: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    migrate()
