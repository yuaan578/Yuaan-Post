import streamlit as st
import sqlite3
import uuid
import os
from datetime import datetime

st.title("Yuaan Post")

# ---------------------------------------------------------------------------
# 1. ที่เก็บข้อมูลแบบถาวร (persistent storage)
#    - ไฟล์รูป/วิดีโอ -> เก็บลงโฟลเดอร์ "uploads" บนดิสก์
#    - ข้อมูลโพสต์ (คำอธิบาย, ชื่อไฟล์, เวลาโพสต์) -> เก็บใน SQLite "diary.db"
#    วิธีนี้ทำให้ข้อมูลยังอยู่แม้ refresh หน้าเว็บ หรือเข้าจากเครื่อง/มือถือเครื่องอื่น
#    เพราะข้อมูลอยู่บนฝั่งเซิร์ฟเวอร์ ไม่ใช่ใน session ของ browser แต่ละคน
# ---------------------------------------------------------------------------
UPLOAD_DIR = "uploads"
DB_PATH = "diary.db"

os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def save_entry(file_bytes, file_type, file_ext, note):
    entry_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{entry_id}{file_ext}")
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    conn = get_conn()
    conn.execute(
        "INSERT INTO entries (id, file_path, file_type, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (entry_id, file_path, file_type, note, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def load_entries():
    conn = get_conn()
    cur = conn.execute(
        "SELECT file_path, file_type, note, created_at FROM entries ORDER BY created_at DESC"
    )
    rows = cur.fetchall()
    conn.close()
    return rows


init_db()

# ---------------------------------------------------------------------------
# 2. ฟอร์มสำหรับอัพโหลดและเขียนโน้ต
# ---------------------------------------------------------------------------
with st.form("diary_form", clear_on_submit=True):
    st.write("Come and post your Story")
    uploaded_file = st.file_uploader(
        "Select Photo or Video", type=["png", "jpg", "jpeg", "mp4", "mov"]
    )
    note = st.text_area("Your description.....")
    submit_button = st.form_submit_button("Save")

    if submit_button:
        if uploaded_file is not None and note:
            file_ext = os.path.splitext(uploaded_file.name)[1]
            save_entry(
                file_bytes=uploaded_file.getvalue(),
                file_type=uploaded_file.type,
                file_ext=file_ext,
                note=note,
            )
            st.success("Saved! 🎉")
        else:
            st.warning("Don't forget to add all desciptions and add a photo!")

# ---------------------------------------------------------------------------
# 3. ส่วนแสดงผลไดอารี่ (โหลดจากฐานข้อมูลทุกครั้งที่หน้าเว็บ refresh)
# ---------------------------------------------------------------------------
st.write("---")
st.header("My Posts")

for file_path, file_type, note, created_at in load_entries():
    if not os.path.exists(file_path):
        continue

    if "video" in file_type:
        st.video(file_path)
    else:
        st.image(file_path, use_container_width=True)

    st.write(f"**Description:** {note}")
    st.caption(created_at)
    st.write("---")