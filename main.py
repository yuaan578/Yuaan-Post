import streamlit as st
import sqlite3
import uuid
import os
from datetime import datetime

st.set_page_config(page_title="Yuaan Post", layout="centered")

# ---------------------------------------------------------------------------
# Persistent storage
#   - Media files (photos/videos) -> saved to disk in "uploads/"
#   - Post data (description, timestamp) -> "posts" table in SQLite
#   - Each post can have MANY media files -> "media" table, linked by post_id
# This survives page refreshes and shows the same feed on any device, since
# everything lives on the server rather than in the browser session.
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
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media (
            id TEXT PRIMARY KEY,
            post_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            position INTEGER NOT NULL,
            FOREIGN KEY (post_id) REFERENCES posts (id)
        )
        """
    )
    conn.commit()
    conn.close()


def save_post(note, uploaded_files):
    post_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()

    conn = get_conn()
    conn.execute(
        "INSERT INTO posts (id, note, created_at) VALUES (?, ?, ?)",
        (post_id, note, created_at),
    )

    for position, uploaded_file in enumerate(uploaded_files):
        media_id = str(uuid.uuid4())
        file_ext = os.path.splitext(uploaded_file.name)[1]
        file_path = os.path.join(UPLOAD_DIR, f"{media_id}{file_ext}")
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getvalue())

        conn.execute(
            "INSERT INTO media (id, post_id, file_path, file_type, position) VALUES (?, ?, ?, ?, ?)",
            (media_id, post_id, file_path, uploaded_file.type, position),
        )

    conn.commit()
    conn.close()


def load_posts():
    conn = get_conn()
    posts = conn.execute(
        "SELECT id, note, created_at FROM posts ORDER BY created_at DESC"
    ).fetchall()

    result = []
    for post_id, note, created_at in posts:
        media_rows = conn.execute(
            "SELECT file_path, file_type FROM media WHERE post_id = ? ORDER BY position",
            (post_id,),
        ).fetchall()
        result.append(
            {
                "note": note,
                "created_at": created_at,
                "media": [m for m in media_rows if os.path.exists(m[0])],
            }
        )
    conn.close()
    return result


def pretty_time(iso_str):
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%d %b %Y, %H:%M")


init_db()

# ---------------------------------------------------------------------------
# Facebook-like card styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container { max-width: 620px; padding-top: 2rem; }
    .fb-card {
        background: #ffffff;
        border-radius: 10px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.15);
        padding: 14px 16px 6px 16px;
        margin-bottom: 18px;
        border: 1px solid #e4e6ea;
    }
    .fb-header { display: flex; align-items: center; margin-bottom: 10px; }
    .fb-avatar {
        width: 40px; height: 40px; border-radius: 50%;
        background: linear-gradient(135deg, #1877f2, #42a5f5);
        color: white; display: flex; align-items: center; justify-content: center;
        font-weight: 700; font-size: 18px; margin-right: 10px; flex-shrink: 0;
    }
    .fb-name { font-weight: 600; font-size: 15px; color: #050505; line-height: 1.2; }
    .fb-time { font-size: 12.5px; color: #65676b; }
    .fb-note { font-size: 15px; color: #050505; margin: 6px 0 10px 0; white-space: pre-wrap; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📷 Yuaan Post")

# ---------------------------------------------------------------------------
# Post composer
# ---------------------------------------------------------------------------
with st.form("diary_form", clear_on_submit=True):
    st.write("Come and post your Story")
    uploaded_files = st.file_uploader(
        "Select Photos or Videos",
        type=["png", "jpg", "jpeg", "mp4", "mov"],
        accept_multiple_files=True,
    )
    note = st.text_area("Your description.....")
    submit_button = st.form_submit_button("Save")

    if submit_button:
        if uploaded_files and note:
            save_post(note, uploaded_files)
            st.success("Saved! 🎉")
        else:
            st.warning("Don't forget to add a description and at least one photo or video!")

# ---------------------------------------------------------------------------
# Feed — Facebook-style cards with a media grid
# ---------------------------------------------------------------------------
st.write("")
st.header("My Posts")


def render_media_grid(media):
    count = len(media)
    if count == 0:
        return

    if count == 1:
        path, ftype = media[0]
        if "video" in ftype:
            st.video(path)
        else:
            st.image(path, use_container_width=True)
        return

    # 2+ items: lay out in a responsive 2-column photo grid
    for i in range(0, count, 2):
        row = media[i:i + 2]
        cols = st.columns(len(row))
        for col, (path, ftype) in zip(cols, row):
            with col:
                if "video" in ftype:
                    st.video(path)
                else:
                    st.image(path, use_container_width=True)


posts = load_posts()

if not posts:
    st.caption("No posts yet — be the first to share something!")

for post in posts:
    st.markdown('<div class="fb-card">', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="fb-header">
            <div class="fb-avatar">Y</div>
            <div>
                <div class="fb-name">Yuaan Post</div>
                <div class="fb-time">{pretty_time(post['created_at'])}</div>
            </div>
        </div>
        <div class="fb-note">{post['note']}</div>
        """,
        unsafe_allow_html=True,
    )
    render_media_grid(post["media"])
    st.markdown("</div>", unsafe_allow_html=True)