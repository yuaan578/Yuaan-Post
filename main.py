import streamlit as st # นำเข้าไลบรารี streamlit สำหรับสร้างเว็บแอปพลิเคชัน
import sqlite3 # นำเข้าไลบรารี sqlite3 สำหรับใช้งานฐานข้อมูล
import uuid # นำเข้าไลบรารี uuid สำหรับสร้างรหัสสุ่มที่ไม่ซ้ำกัน
import os # นำเข้าไลบรารี os สำหรับจัดการไฟล์และโฟลเดอร์
from datetime import datetime, timedelta # นำเข้าไลบรารี datetime สำหรับจัดการวันเวลา

# ==========================================
# 1. การตั้งค่าระบบโฟลเดอร์และฐานข้อมูล
# ==========================================
st.set_page_config(page_title="Yuaan Post", layout="centered") # ตั้งค่าหน้าเว็บ

UPLOAD_DIR = "uploads" # โฟลเดอร์เก็บไฟล์รูปภาพ/วิดีโอ
DB_PATH = "diary.db" # ชื่อไฟล์ฐานข้อมูล

os.makedirs(UPLOAD_DIR, exist_ok=True) # สร้างโฟลเดอร์ uploads ถ้ายังไม่มี

def init_db(): # เตรียมโครงสร้างฐานข้อมูล
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL, display_name TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, author_username TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL, position INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, author_username TEXT NOT NULL, comment_text TEXT NOT NULL, created_at TEXT NOT NULL)''')
    # ตาราง sessions เก็บโทเคนล็อกอิน เพื่อให้รีเฟรชหน้าแล้วยังอยู่ในระบบ
    conn.execute('''CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at TEXT NOT NULL)''')
    conn.commit()
    conn.close()

init_db() # สร้างตารางเมื่อเปิดเว็บ

# ==========================================
# 2. ฟังก์ชันตัวช่วยดึงข้อมูลจากฐานข้อมูล
# ==========================================
def get_display_name(username): # ดึงชื่อโปรไฟล์ที่ใช้แสดงผล
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT display_name FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row[0] if row else username

SESSION_DAYS = 7 # จำนวนวันที่โทเคนล็อกอินใช้งานได้

def create_session(username): # สร้างโทเคนล็อกอินใหม่และบันทึกลงฐานข้อมูล
    token = uuid.uuid4().hex + uuid.uuid4().hex # โทเคนสุ่มที่เดายาก
    expires_at = (datetime.now() + timedelta(days=SESSION_DAYS)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(),)) # ลบโทเคนที่หมดอายุ
    conn.execute("INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)", (token, username, expires_at))
    conn.commit()
    conn.close()
    return token

def get_session_user(token): # ตรวจโทเคน ถ้ายังใช้ได้คืนค่า username
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT username FROM sessions WHERE token = ? AND expires_at > ?", (token, datetime.now().isoformat())).fetchone()
    conn.close()
    return row[0] if row else None

def delete_session(token): # ลบโทเคนเมื่อออกจากระบบ
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()

# ==========================================
# 3. ระบบเข้าสู่ระบบ (Login) และ สมัครสมาชิก (Register)
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""

# ถ้ารีเฟรชหน้าเว็บ session_state จะหาย แต่โทเคนใน URL (?s=...) ยังอยู่ จึงใช้กู้สถานะล็อกอินกลับมา
if not st.session_state.logged_in:
    url_token = st.query_params.get("s") # อ่านโทเคนจาก URL
    if url_token:
        restored_user = get_session_user(url_token)
        if restored_user:
            st.session_state.logged_in = True
            st.session_state.username = restored_user
            st.session_state.token = url_token
        else:
            del st.query_params["s"] # โทเคนหมดอายุหรือไม่ถูกต้อง ลบทิ้ง

if not st.session_state.logged_in: # ถ้ายังไม่ล็อกอิน แสดงหน้าเข้าสู่ระบบ/สมัครสมาชิก
    st.title("🔒 Login to YuaanPost")
    
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    
    with tab1:
        login_user = st.text_input("Username", key="login_user")
        login_pass = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            conn = sqlite3.connect(DB_PATH)
            user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (login_user, login_pass)).fetchone()
            conn.close()
            if user:
                st.session_state.logged_in = True
                st.session_state.username = login_user
                token = create_session(login_user) # สร้างโทเคนล็อกอิน
                st.session_state.token = token
                st.query_params["s"] = token # เก็บโทเคนไว้ใน URL เพื่อให้รีเฟรชแล้วไม่หลุด
                st.rerun()
            else:
                st.error("Username or Password is incorrect!")
                
    with tab2:
        reg_user = st.text_input("Username", key="reg_user")
        reg_pass = st.text_input("Password", type="password", key="reg_pass")
        reg_name = st.text_input("Display name", key="reg_name")
        if st.button("Sign Up"):
            if reg_user and reg_pass and reg_name:
                conn = sqlite3.connect(DB_PATH)
                try:
                    conn.execute("INSERT INTO users (username, password, display_name) VALUES (?, ?, ?)", (reg_user, reg_pass, reg_name))
                    conn.commit()
                    st.success("success! go to the login page to start")
                except sqlite3.IntegrityError:
                    st.error("This username has been taken please select a new one!")
                finally:
                    conn.close()
            else:
                st.warning("Add all infromation")
    st.stop() # หยุดโค้ดตรงนี้ ถ้ายังไม่ล็อกอิน

# ==========================================
# 4. หน้าหลักไดอารี่ (หลังล็อกอินสำเร็จ)
# ==========================================
current_user = st.session_state.username
display_name = get_display_name(current_user)

with st.sidebar:
    st.write(f"Welcome to Yuaan Post, **{display_name}**")
    
    st.divider()
    st.write("⚙️ Profile Settings")
    new_display_name = st.text_input("change display name", value=display_name)
    if st.button("set new name"):
        if new_display_name:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE users SET display_name = ? WHERE username = ?", (new_display_name, current_user))
            conn.commit()
            conn.close()
            st.success("Name changed!")
            st.rerun()
            
    st.divider()
    if st.button("Sign out"):
        delete_session(st.session_state.get("token", "")) # ลบโทเคนออกจากฐานข้อมูล
        st.query_params.clear() # ลบโทเคนออกจาก URL
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.rerun()

st.title("📷 Yuaan Post")

# --- ส่วนกล่องเขียนโพสต์ ---
with st.form("diary_form", clear_on_submit=True):
    note = st.text_area("Your description...")
    
    with st.expander("📁 click to select photos or videos"):
        uploaded_files = st.file_uploader("select your file", type=["png", "jpg", "jpeg", "mp4", "mov"], accept_multiple_files=True)
        
    submit_button = st.form_submit_button("Post!")

    if submit_button:
        if note:
            post_id = str(uuid.uuid4())
            created_at = datetime.now().isoformat()
            
            conn = sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO posts (id, author_username, note, created_at) VALUES (?, ?, ?, ?)", (post_id, current_user, note, created_at))
            
            if uploaded_files:
                for position, file in enumerate(uploaded_files):
                    media_id = str(uuid.uuid4())
                    file_ext = os.path.splitext(file.name)[1]
                    file_path = os.path.join(UPLOAD_DIR, f"{media_id}{file_ext}")
                    with open(file_path, "wb") as f:
                        f.write(file.getvalue())
                    conn.execute("INSERT INTO media (id, post_id, file_path, file_type, position) VALUES (?, ?, ?, ?, ?)", (media_id, post_id, file_path, file.type, position))
            
            conn.commit()
            conn.close()
            st.success("success! 🎉")
            st.rerun()
        else:
            st.warning("Add a description(can be anything)!")

# --- ส่วนของการแสดงผล Feed และ คอมเมนต์ ---
st.write("")
st.header("All posts")

conn = sqlite3.connect(DB_PATH)
posts = conn.execute('''
    SELECT posts.id, posts.note, posts.created_at, users.display_name 
    FROM posts 
    LEFT JOIN users ON posts.author_username = users.username 
    ORDER BY posts.created_at DESC
''').fetchall()

if not posts:
    st.caption("No Posts — Be the first to share!")

for post_id, note, created_at, author_name in posts:
    media_rows = conn.execute("SELECT file_path, file_type FROM media WHERE post_id = ? ORDER BY position", (post_id,)).fetchall()
    
    dt = datetime.fromisoformat(created_at)
    time_str = dt.strftime("%d %b %Y, %H:%M")
    safe_author = author_name if author_name else "Unknown"

    st.markdown(f'''
        <div style="background: white; padding: 15px; border-radius: 10px; border: 1px solid #e4e6ea; margin-top: 15px;">
            <div style="font-weight: 600; font-size: 16px;">👤 {safe_author}</div>
            <div style="font-size: 12px; color: #65676b; margin-bottom: 10px;">🕒 {time_str}</div>
            <div style="font-size: 15px; margin-bottom: 10px; white-space: pre-wrap;">{note}</div>
    ''', unsafe_allow_html=True)
    
    for file_path, ftype in media_rows:
        if os.path.exists(file_path):
            if "video" in ftype:
                st.video(file_path)
            else:
                st.image(file_path, use_container_width=True)
                
    st.markdown("</div>", unsafe_allow_html=True)
    
    comments = conn.execute('''
        SELECT users.display_name, comments.comment_text 
        FROM comments 
        LEFT JOIN users ON comments.author_username = users.username 
        WHERE comments.post_id = ? 
        ORDER BY comments.created_at ASC
    ''', (post_id,)).fetchall()
    
    with st.expander(f"💬 comment ({len(comments)} comment)"): 
        for c_author, c_text in comments:
            c_name = c_author if c_author else "Unknown"
            st.markdown(f"**{c_name}**: {c_text}")
            
        with st.form(f"comment_form_{post_id}", clear_on_submit=True): 
            new_comment = st.text_input("comment...")
            if st.form_submit_button("send"):
                if new_comment:
                    c_id = str(uuid.uuid4())
                    c_time = datetime.now().isoformat()
                    conn.execute("INSERT INTO comments (id, post_id, author_username, comment_text, created_at) VALUES (?, ?, ?, ?, ?)", (c_id, post_id, current_user, new_comment, c_time))
                    conn.commit()
                    st.rerun()
                    
conn.close()