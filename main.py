import streamlit as st # นำเข้าไลบรารี streamlit สำหรับสร้างเว็บแอปพลิเคชัน
import sqlite3 # นำเข้าไลบรารี sqlite3 สำหรับใช้งานฐานข้อมูล
import uuid # นำเข้าไลบรารี uuid สำหรับสร้างรหัสสุ่มที่ไม่ซ้ำกัน
import os # นำเข้าไลบรารี os สำหรับจัดการไฟล์และโฟลเดอร์
from datetime import datetime # นำเข้าไลบรารี datetime สำหรับจัดการวันเวลา

# ==========================================
# 1. การตั้งค่าระบบโฟลเดอร์และฐานข้อมูล
# ==========================================
st.set_page_config(page_title="Yuaan Post", layout="centered") # ตั้งค่าหน้าเว็บให้ชื่อ Yuaan Post และจัดเนื้อหาให้อยู่กึ่งกลาง

UPLOAD_DIR = "uploads" # กำหนดตัวแปรชื่อโฟลเดอร์สำหรับเก็บไฟล์รูปภาพ/วิดีโอ
DB_PATH = "diary.db" # กำหนดตัวแปรชื่อไฟล์ฐานข้อมูล

os.makedirs(UPLOAD_DIR, exist_ok=True) # สร้างโฟลเดอร์ uploads ถ้ายังไม่มีอยู่ในระบบปฏิบัติการ

def init_db(): # สร้างฟังก์ชันสำหรับเตรียมโครงสร้างฐานข้อมูล
    conn = sqlite3.connect(DB_PATH) # เชื่อมต่อไฟล์ฐานข้อมูล diary.db
    # สร้างตาราง users สำหรับเก็บข้อมูลบัญชีผู้ใช้งาน (มี username เป็นคีย์หลัก)
    conn.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL, display_name TEXT NOT NULL)''')
    # สร้างตาราง posts โดยเพิ่มช่อง author_username เพื่อระบุว่าใครเป็นคนโพสต์
    conn.execute('''CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, author_username TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL)''')
    # สร้างตาราง media สำหรับเก็บที่อยู่ไฟล์รูป/วิดีโอที่พ่วงกับโพสต์
    conn.execute('''CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL, position INTEGER NOT NULL)''')
    # สร้างตาราง comments สำหรับเก็บข้อมูลคอมเมนต์ของแต่ละโพสต์
    conn.execute('''CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, author_username TEXT NOT NULL, comment_text TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.commit() # ยืนยันการสร้างตารางทั้งหมดลงฐานข้อมูล
    conn.close() # ปิดการเชื่อมต่อฐานข้อมูล

init_db() # เรียกใช้งานฟังก์ชันสร้างตารางทันทีเมื่อเปิดเว็บ

# ==========================================
# 2. ฟังก์ชันตัวช่วยดึงข้อมูลจากฐานข้อมูล
# ==========================================
def get_display_name(username): # ฟังก์ชันสำหรับดึงชื่อโปรไฟล์ที่ใช้แสดงผล
    conn = sqlite3.connect(DB_PATH) # เชื่อมต่อฐานข้อมูล
    row = conn.execute("SELECT display_name FROM users WHERE username = ?", (username,)).fetchone() # ค้นหาชื่อที่ตั้งไว้จากตาราง users
    conn.close() # ปิดการเชื่อมต่อ
    return row[0] if row else username # คืนค่าชื่อที่ตั้งไว้ ถ้าไม่มีให้คืนค่า username แทน

# ==========================================
# 3. ระบบเข้าสู่ระบบ (Login) และ สมัครสมาชิก (Register)
# ==========================================
if "logged_in" not in st.session_state: # ตรวจสอบว่ามีสถานะล็อกอินในความจำเว็บหรือยัง
    st.session_state.logged_in = False # ถ้ายัง ให้ตั้งค่าเริ่มต้นเป็น False (ยังไม่ล็อกอิน)
if "username" not in st.session_state: # ตรวจสอบว่ามีข้อมูล username ในความจำเว็บหรือยัง
    st.session_state.username = "" # ถ้ายัง ให้ตั้งค่าเป็นค่าว่าง

if not st.session_state.logged_in: # ถ้าผู้ใช้ยังไม่ล็อกอิน ให้แสดงหน้าเข้าสู่ระบบ/สมัครสมาชิก
    st.title("🔒 Login to YuaanPost") # แสดงหัวข้อหน้าล็อกอิน
    
    tab1, tab2 = st.tabs(["Login", "Sign Up"]) # สร้างแท็บ 2 หน้าต่างให้เลือกใช้งาน
    
    with tab1: # ส่วนของแท็บ "เข้าสู่ระบบ"
        login_user = st.text_input("Username", key="login_user") # กล่องกรอกชื่อผู้ใช้สำหรับล็อกอิน
        login_pass = st.text_input("Password", type="password", key="login_pass") # กล่องกรอกรหัสผ่านแบบซ่อนตัวอักษร
        if st.button("Login"): # ถ้ากดปุ่มเข้าสู่ระบบ
            conn = sqlite3.connect(DB_PATH) # เชื่อมต่อฐานข้อมูล
            # เช็คว่ามีผู้ใช้นี้ที่รหัสผ่านตรงกันในระบบหรือไม่
            user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (login_user, login_pass)).fetchone()
            conn.close() # ปิดการเชื่อมต่อ
            if user: # ถ้าค้นหาเจอ (ข้อมูลถูกต้อง)
                st.session_state.logged_in = True # เปลี่ยนสถานะล็อกอินเป็น True
                st.session_state.username = login_user # บันทึก username ของคนที่ล็อกอินไว้ในระบบ
                st.rerun() # โหลดหน้าเว็บใหม่เพื่อเข้าสู่หน้าหลัก
            else: # ถ้ากรอกผิด
                st.error("Username or Password is incorrect!") # แจ้งเตือนสีแดง
                
    with tab2: # ส่วนของแท็บ "สมัครบัญชีใหม่"
        reg_user = st.text_input("Username", key="reg_user") # กล่องตั้งชื่อผู้ใช้ใหม่
        reg_pass = st.text_input("Password", type="password", key="reg_pass") # กล่องตั้งรหัสผ่านใหม่
        reg_name = st.text_input("Display name", key="reg_name") # กล่องตั้งชื่อที่จะให้คนอื่นเห็น
        if st.button("Sign Up"): # ถ้ากดปุ่มสมัครสมาชิก
            if reg_user and reg_pass and reg_name: # เช็คว่ากรอกข้อมูลครบทุกช่องหรือไม่
                conn = sqlite3.connect(DB_PATH) # เชื่อมต่อฐานข้อมูล
                try: # ลองทำการบันทึกข้อมูล
                    conn.execute("INSERT INTO users (username, password, display_name) VALUES (?, ?, ?)", (reg_user, reg_pass, reg_name)) # บันทึกบัญชีใหม่ลงตาราง users
                    conn.commit() # ยืนยันการบันทึก
                    st.success("success! go to the login page to start") # แจ้งเตือนสีเขียวว่าสมัครเสร็จแล้ว
                except sqlite3.IntegrityError: # ถ้าเกิดข้อผิดพลาดชื่อผู้ใช้ซ้ำ (เพราะ username เป็นคีย์หลัก)
                    st.error("This username has been taken please select a new one!") # แจ้งเตือนให้เปลี่ยนชื่อ
                finally: # ทำงานส่วนนี้เสมอ
                    conn.close() # ปิดการเชื่อมต่อฐานข้อมูล
            else: # ถ้ากรอกข้อมูลไม่ครบ
                st.warning("Add all infromation") # แจ้งเตือนสีเหลือง
    st.stop() # หยุดโค้ดแค่ตรงนี้ ไม่ให้หน้าไดอารี่โผล่มาถ้ายังไม่ล็อกอิน

# ==========================================
# 4. หน้าหลักไดอารี่ (หลังล็อกอินสำเร็จ)
# ==========================================
current_user = st.session_state.username # ดึงชื่อผู้ใช้ที่กำลังล็อกอินอยู่มาเก็บไว้ในตัวแปร
display_name = get_display_name(current_user) # ดึงชื่อโปรไฟล์ที่จะใช้แสดงผลของคนคนนั้น

with st.sidebar: # เรียกใช้แถบเมนูด้านซ้าย
    st.write(f"Welcome to Yuaan Post, **{display_name}**") # แสดงข้อความต้อนรับพร้อมชื่อโปรไฟล์
    
    st.divider() # เส้นขีดคั่น
    st.write("⚙️ Profile Settings") # หัวข้อตั้งค่าโปรไฟล์
    new_display_name = st.text_input("change display name", value=display_name) # กล่องแก้ไขชื่อโปรไฟล์ โดยมีค่าเริ่มต้นเป็นชื่อเดิม
    if st.button("set new name"): # ถ้ากดปุ่มบันทึกชื่อ
        if new_display_name: # ถ้าไม่ได้ปล่อยช่องว่างไว้
            conn = sqlite3.connect(DB_PATH) # เชื่อมต่อฐานข้อมูล
            conn.execute("UPDATE users SET display_name = ? WHERE username = ?", (new_display_name, current_user)) # อัปเดตชื่อแสดงผลใหม่ในฐานข้อมูล
            conn.commit() # ยืนยันการบันทึก
            conn.close() # ปิดการเชื่อมต่อ
            st.success("Name changed!") # แจ้งเตือนว่าเสร็จสิ้น
            st.rerun() # โหลดหน้าเว็บใหม่เพื่อโชว์ชื่ออัปเดต
            
    st.divider() # เส้นขีดคั่น
    if st.button("Sign out"): # ถ้ากดปุ่มออกจากระบบ
        st.session_state.logged_in = False # ล้างค่าสถานะล็อกอิน
        st.session_state.username = "" # ล้างค่าข้อมูลผู้ใช้
        st.rerun() # โหลดเว็บใหม่เด้งกลับไปหน้าล็อกอิน

st.title("📷 Yuaan Post") # แสดงชื่อแอปพลิเคชันหน้าแรก

# --- ส่วนกล่องเขียนโพสต์ ---
with st.form("diary_form", clear_on_submit=True): # สร้างแบบฟอร์มให้เขียนโพสต์และตั้งค่าเคลียร์ช่องหลังกดส่ง
    note = st.text_area("Your description...") # กล่องพิมพ์ข้อความโพสต์
    
    # ซ่อนกล่องอัปโหลดรูปด้วย expander แบบปุ่มกดขยาย (ป้องกันหน้าเว็บรก)
    with st.expander("📁 click to select photos or videos"): # สร้างกล่องที่พับเก็บได้
        uploaded_files = st.file_uploader("select your file", type=["png", "jpg", "jpeg", "mp4", "mov"], accept_multiple_files=True) # กล่องให้อัปโหลดไฟล์รูป/วิดีโอ
        
    submit_button = st.form_submit_button("Post!") # ปุ่มกดยืนยันการโพสต์

    if submit_button: # เมื่อผู้ใช้กดปุ่มโพสต์เลย
        if note: # ตรวจสอบว่ามีการพิมพ์ข้อความมาด้วย
            post_id = str(uuid.uuid4()) # สร้างรหัสไอดีโพสต์
            created_at = datetime.now().isoformat() # บันทึกเวลาที่โพสต์
            
            conn = sqlite3.connect(DB_PATH) # เชื่อมต่อฐานข้อมูล
            conn.execute("INSERT INTO posts (id, author_username, note, created_at) VALUES (?, ?, ?, ?)", (post_id, current_user, note, created_at)) # บันทึกข้อความพร้อมรหัสคนโพสต์
            
            if uploaded_files: # ถ้ามีการแนบไฟล์มาด้วย
                for position, file in enumerate(uploaded_files): # วนลูปเซฟไฟล์ทีละไฟล์
                    media_id = str(uuid.uuid4()) # สร้างไอดีไฟล์
                    file_ext = os.path.splitext(file.name)[1] # ดึงนามสกุลไฟล์
                    file_path = os.path.join(UPLOAD_DIR, f"{media_id}{file_ext}") # ต่อเป็นชื่อเส้นทางที่อยู่ไฟล์
                    with open(file_path, "wb") as f: # เปิดโหมดเขียนไฟล์บนระบบปฏิบัติการ
                        f.write(file.getvalue()) # เอาข้อมูลไบนารีบันทึกลงไป
                    conn.execute("INSERT INTO media (id, post_id, file_path, file_type, position) VALUES (?, ?, ?, ?, ?)", (media_id, post_id, file_path, file.type, position)) # บันทึกประวัติไฟล์ลงฐานข้อมูล
            
            conn.commit() # ยืนยันการเปลี่ยนแปลงข้อมูล
            conn.close() # ปิดการเชื่อมต่อ
            st.success("success! 🎉") # แจ้งข้อความสำเร็จ
            st.rerun() # รีโหลดหน้าเพื่อนำโพสต์ใหม่มาโชว์ใน Feed
        else: # กรณีไม่ได้พิมพ์อะไรเลย
            st.warning("Add a description(can be anything)!") # แจ้งเตือน

# --- ส่วนของการแสดงผล Feed และ คอมเมนต์ ---
st.write("") # เว้นบรรทัด
st.header("All posts") # หัวข้อ Feed

conn = sqlite3.connect(DB_PATH) # เชื่อมต่อฐานข้อมูลเพื่อดึงโพสต์
# ดึงโพสต์ทั้งหมดจากตาราง พร้อมหาชื่อโปรไฟล์ของผู้โพสต์จากตาราง users
posts = conn.execute('''
    SELECT posts.id, posts.note, posts.created_at, users.display_name 
    FROM posts 
    LEFT JOIN users ON posts.author_username = users.username 
    ORDER BY posts.created_at DESC
''').fetchall() # จัดเรียงจากเวลาใหม่สุดไปเก่าสุด

if not posts: # ถ้าไม่เจอโพสต์เลย
    st.caption("No Posts — Be the first to share!") # ข้อความสำหรับกรณีหน้าว่าง

for post_id, note, created_at, author_name in posts: # วนลูปโชว์การ์ดทีละโพสต์
    media_rows = conn.execute("SELECT file_path, file_type FROM media WHERE post_id = ? ORDER BY position", (post_id,)).fetchall() # ค้นหารูป/วิดีโอของโพสต์นี้
    
    dt = datetime.fromisoformat(created_at) # แปลงวันที่จากฐานข้อมูลกลับมาเป็นตัวแปร datetime
    time_str = dt.strftime("%d %b %Y, %H:%M") # จัดรูปวันที่ให้สวยงาม
    safe_author = author_name if author_name else "Unknown" # เซฟตี้กันเหนียวเผื่อชื่อว่าง

    # สร้างการ์ดแสดงข้อความโพสต์และชื่อผู้แต่ง
    st.markdown(f'''
        <div style="background: white; padding: 15px; border-radius: 10px; border: 1px solid #e4e6ea; margin-top: 15px;">
            <div style="font-weight: 600; font-size: 16px;">👤 {safe_author}</div>
            <div style="font-size: 12px; color: #65676b; margin-bottom: 10px;">🕒 {time_str}</div>
            <div style="font-size: 15px; margin-bottom: 10px; white-space: pre-wrap;">{note}</div>
    ''', unsafe_allow_html=True) # พิมพ์คำสั่งเปิด HTML
    
    for file_path, ftype in media_rows: # วนลูปโชว์ไฟล์ในโพสต์
        if os.path.exists(file_path): # เช็คว่ามีไฟล์จริง
            if "video" in ftype: # ถ้าเป็นวิดีโอ
                st.video(file_path) # ใช้คำสั่งโชว์วิดีโอ
            else: # ถ้าเป็นรูปภาพ
                st.image(file_path, use_container_width=True) # ใช้คำสั่งโชว์ภาพ
                
    st.markdown("</div>", unsafe_allow_html=True) # ปิดกล่องการ์ดโพสต์
    
    # โซนแสดงและรับคอมเมนต์ (อยู่ใต้การ์ดโพสต์)
    comments = conn.execute('''
        SELECT users.display_name, comments.comment_text 
        FROM comments 
        LEFT JOIN users ON comments.author_username = users.username 
        WHERE comments.post_id = ? 
        ORDER BY comments.created_at ASC
    ''', (post_id,)).fetchall() # ดึงคอมเมนต์ที่ผูกกับรหัสโพสต์นี้ เรียงจากเก่าไปใหม่
    
    # สร้างกล่องพับเก็บได้สำหรับแสดงและรับคอมเมนต์ (ช่วยให้หน้าเว็บสั้นลง)
    with st.expander(f"💬 comment ({len(comments)} comment)"): 
        for c_author, c_text in comments: # วนลูปคอมเมนต์ทั้งหมดของโพสต์นี้
            c_name = c_author if c_author else "Unknown" # เซฟตี้ชื่อผู้คอมเมนต์
            st.markdown(f"**{c_name}**: {c_text}") # แสดงบรรทัดคอมเมนต์ (ชื่อตัวหนา : ข้อความ)
            
        # แบบฟอร์มสำหรับพิมพ์คอมเมนต์ใหม่ (ใช้รหัสโพสต์เป็นคีย์เพื่อให้ระบบแยกออกว่าตอบโพสต์ไหน)
        with st.form(f"comment_form_{post_id}", clear_on_submit=True): 
            new_comment = st.text_input("comment...") # กล่องกรอกคอมเมนต์
            if st.form_submit_button("send"): # ถ้ากดปุ่มส่ง
                if new_comment: # ถ้ามีข้อความกรอกมาจริง
                    c_id = str(uuid.uuid4()) # สร้างรหัสคอมเมนต์
                    c_time = datetime.now().isoformat() # บันทึกเวลา
                    # บันทึกคอมเมนต์ลงตาราง
                    conn.execute("INSERT INTO comments (id, post_id, author_username, comment_text, created_at) VALUES (?, ?, ?, ?, ?)", (c_id, post_id, current_user, new_comment, c_time))
                    conn.commit() # ยืนยันการเปลี่ยนแปลง
                    st.rerun() # โหลดเว็บใหม่เพื่อโชว์คอมเมนต์ใหม่ที่เพิ่งพิมพ์ไป
                    
conn.close() # ปิดฐานข้อมูลตัวสุดท้ายเมื่อเรนเดอร์หน้าเว็บเสร็จ
