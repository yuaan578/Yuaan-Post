import streamlit as st # นำเข้าไลบรารี streamlit สำหรับสร้างเว็บแอปพลิเคชัน
import sqlite3 # นำเข้าไลบรารี sqlite3 สำหรับใช้งานระบบฐานข้อมูลขนาดเล็ก
import uuid # นำเข้าไลบรารี uuid สำหรับสร้างรหัสสุ่มแบบไม่ซ้ำกัน
import os # นำเข้าไลบรารี os สำหรับจัดการโฟลเดอร์และไฟล์บนระบบปฏิบัติการ
from datetime import datetime # นำเข้าไลบรารี datetime สำหรับดึงค่าวันและเวลาปัจจุบัน

# ==========================================
# 2. การตั้งค่าเริ่มต้นของระบบและฐานข้อมูล
# ==========================================
st.set_page_config(page_title="Yuaan Post", layout="centered") # ตั้งค่าหน้าเว็บให้ชื่อ Yuaan Post และจัดให้อยู่กึ่งกลางหน้าจอ

UPLOAD_DIR = "uploads" # กำหนดชื่อโฟลเดอร์สำหรับเก็บไฟล์รูปหรือวิดีโอที่ผู้ใช้อัปโหลด
DB_PATH = "diary.db" # กำหนดชื่อไฟล์ฐานข้อมูลสำหรับเก็บข้อความโพสต์

os.makedirs(UPLOAD_DIR, exist_ok=True) # คำสั่งสร้างโฟลเดอร์ uploads ถ้าโฟลเดอร์นี้ยังไม่มีอยู่ในระบบ

def init_db(): # สร้างฟังก์ชันสำหรับเริ่มต้นตารางฐานข้อมูล
    conn = sqlite3.connect(DB_PATH) # เชื่อมต่อหรือสร้างไฟล์ฐานข้อมูล diary.db
    conn.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, note TEXT NOT NULL, created_at TEXT NOT NULL)''') # สร้างตารางชื่อ posts เพื่อเก็บรหัสโพสต์, ข้อความ, และเวลา หากยังไม่มีตารางนี้
    conn.execute('''CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL, position INTEGER NOT NULL)''') # สร้างตารางชื่อ media เพื่อเก็บรายละเอียดไฟล์รูป/วิดีโอที่พ่วงกับโพสต์
    conn.execute('''CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, author_username TEXT NOT NULL, comment_text TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.commit()

    conn.close() # ปิดการเชื่อมต่อฐานข้อมูล

init_db() # เรียกใช้งานฟังก์ชัน init_db() ทันทีเมื่อรันสคริปต์นี้

def get_display_name(username):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT display_name FROM users WHERE username = ?", (username)).fetchone()
    conn.close()
    return row[0] if row else username
# ==========================================
# 3. ระบบหน้าแรก (เข้าสู่ระบบ / Login)
# ==========================================
if "logged_in" not in st.session_state: # ตรวจสอบว่าในหน่วยความจำชั่วคราว (session) มีตัวแปร logged_in หรือยัง
    st.session_state.logged_in = False # ถ้ายังไม่มี ให้กำหนดสถานะเป็น False แปลว่ายังไม่ได้ล็อกอิน

if not st.session_state.logged_in: # ถ้าสถานะผู้ใช้คือยังไม่ได้ล็อกอิน ให้ทำคำสั่งในบล็อกนี้
    st.title("🔒 Login for Yuaan Post") # แสดงหัวข้อหน้าล็อกอิน
    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        login_user = st.text_input("Username", key="Login_user")
        login_pass = st.text_input("Password", type="password",key="Login_pass")
        if st.button("Login"):
            conn = sqlite3.connect(DB_PATH)
            user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (login_user, login_pass)).fetchone()
            conn.close()
            if user:
                st.session_state.logged_in = True
                st.session_state.username = login_user
                st.rerun()
            else:
                st.error("Username or Password is Incorrect!")

    with tab2:
        reg_user = st.text_input("Set a New Username", key="reg_user")
        reg_pass = st.text_input("Set a New Password", type="password", key="reg_pass")
        reg_name = st.text_input("Set a Display Name", key="reg_name")
        if st.button("Sign Up"):
            if reg_user and reg_pass and reg_name:
                conn = sqlite3.connect(DB_PATH)
                try:
                    conn.execute("INSERT INTO users (username, password, display_name) VALUES (?, ?, ?)", (reg_user, reg_pass, reg_name))
                    conn.commit()
                    st.success("Sign up success! please go to the Log In page to access your account")
                except sqlite3.IntegrityError:
                    st.error("This username has been taken please select a new one!")
                finally:
                    conn.close()
            else:
                st.warning("Insert all data")
    st.stop()

current_user = st.seesion_state.username
display_name = get_display_name(current_user)

with st.sidebar:
    st.write("Profile settings")
    new_display_name = st.text_input("Change display name", value=display_name)
    if st.button("set new display name"):
        if new_display_name:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE users SET display_name = ? WHERE username = ?", (new_display_name, current_user))
            conn.commit()
            conn.close()
            st.success("Successfully changed name!")
            st.rerun()


    st.divider()
    if st.button("Log Out"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.rerun()


st.title("📷 Yuaan Post") # แสดงหัวข้อใหญ่ของหน้าหลัก

# --- ส่วนของการเขียนโพสต์ ---
with st.form("diary_form", clear_on_submit=True): # สร้างแบบฟอร์มรับข้อมูล และตั้งค่า clear_on_submit=True เพื่อล้างฟอร์มเวลาบันทึกเสร็จ
    st.write("Come and post your Story") # พิมพ์ข้อความเชิญชวนเขียนเรื่องราว
    uploaded_files = st.file_uploader("Select Photos or Videos", type=["png", "jpg", "jpeg", "mp4", "mov"], accept_multiple_files=True) # สร้างกล่องอัปโหลดไฟล์ที่รับเฉพาะรูปและวิดีโอ และเลือกได้หลายไฟล์
    note = st.text_area("Your description.....") # สร้างกล่องข้อความขนาดใหญ่สำหรับพิมพ์คำบรรยาย
    submit_button = st.form_submit_button("Save") # สร้างปุ่มสำหรับกดยืนยันเพื่อบันทึกข้อมูลในฟอร์ม

    if submit_button: # ถ้าปุ่ม Save ถูกกด
        if note: # ตรวจสอบเงื่อนไขว่าต้องมีการพิมพ์ข้อความ (note) อย่างน้อย 1 ตัวอักษร
            post_id = str(uuid.uuid4()) # สร้างรหัสไอดีแบบสุ่มสำหรับโพสต์นี้
            created_at = datetime.now().isoformat() # ดึงเวลาปัจจุบันในรูปแบบตัวอักษรเพื่อเก็บบันทึก
            
            conn = sqlite3.connect(DB_PATH) # เชื่อมต่อฐานข้อมูล
            conn.execute("INSERT INTO posts (id, note, created_at) VALUES (?, ?, ?)", (post_id, note, created_at)) # นำรหัสโพสต์, ข้อความ, และเวลาไปบันทึกลงตาราง posts
            
            for position, file in enumerate(uploaded_files): # ใช้ลูปวนตามจำนวนไฟล์ที่แนบมา (position คือลำดับ, file คือข้อมูลไฟล์)
                media_id = str(uuid.uuid4()) # สร้างรหัสสุ่มให้แต่ละไฟล์
                file_ext = os.path.splitext(file.name)[1] # แยกนามสกุลไฟล์ (.jpg, .mp4) ออกมาจากชื่อเดิม
                file_path = os.path.join(UPLOAD_DIR, f"{media_id}{file_ext}") # ต่อข้อความสร้างพาธที่อยู่ไฟล์เช่น uploads/random-id.jpg
                
                with open(file_path, "wb") as f: # เปิดโหมดเขียนไฟล์แบบไบนารีบนระบบปฏิบัติการ
                    f.write(file.getvalue()) # บันทึกก้อนข้อมูลไฟล์ลงในโฟลเดอร์ uploads ที่ระบุไว้
                
                conn.execute("INSERT INTO media (id, post_id, file_path, file_type, position) VALUES (?, ?, ?, ?, ?)", (media_id, post_id, file_path, file.type, position)) # บันทึกข้อมูลที่อยู่ไฟล์และประเภทไฟล์ลงฐานข้อมูลตาราง media
            
            conn.commit() # ยืนยันการเขียนข้อมูลลงไฟล์ฐานข้อมูลจริง
            conn.close() # ปิดการเชื่อมต่อฐานข้อมูล
            st.success("บันทึกโพสต์สำเร็จ! 🎉") # แจ้งเตือนสีเขียวว่าทำการบันทึกข้อมูลเรียบร้อยแล้ว
        else: # ถ้าไม่ได้พิมพ์ข้อความในกล่อง note
            st.warning("กรุณาใส่ข้อความคำบรรยายก่อนบันทึก!") # แจ้งเตือนสีเหลืองว่าลืมกรอกข้อความ

# --- ส่วนของการดึงข้อมูลมาแสดงเป็นหน้า Feed ---
st.write("") # เว้นบรรทัด 1 บรรทัด
st.header("My Posts") # แสดงหัวข้อย่อยคำว่า My Posts

conn = sqlite3.connect(DB_PATH) # เชื่อมต่อฐานข้อมูลเพื่อดึงข้อความมาแสดง
posts = conn.execute("SELECT id, note, created_at FROM posts ORDER BY created_at DESC").fetchall() # สั่งดึงข้อมูลรหัส, ข้อความ, และเวลาของทุกโพสต์ เรียงจากเวลาล่าสุดไปเก่าสุด

if not posts: # ตรวจสอบว่าลิสต์ข้อมูลโพสต์ว่างเปล่าหรือไม่ (ยังไม่มีการโพสต์เลย)
    st.caption("No posts yet — be the first to share something!") # แสดงตัวอักษรจางๆ แจ้งว่ายังไม่มีโพสต์

for post_id, note, created_at in posts: # วนลูปตามจำนวนโพสต์ที่ดึงมาได้
    # ดึงไฟล์ที่แนบมากับโพสต์นั้นๆ จากตาราง media โดยอ้างอิงจาก post_id
    media_rows = conn.execute("SELECT file_path, file_type FROM media WHERE post_id = ? ORDER BY position", (post_id,)).fetchall() 
    
    dt = datetime.fromisoformat(created_at) # แปลงข้อความเวลาจากฐานข้อมูลกลับมาเป็นข้อมูลเวลาคอมพิวเตอร์
    time_str = dt.strftime("%d %b %Y, %H:%M") # จัดรูปเวลาให้เป็นข้อความสวยงาม เช่น 12 Mar 2026, 14:30

    # สร้างการ์ดแสดงผลด้วย HTML คล้ายกับของเดิมเพื่อให้ดูเรียบร้อย
    st.markdown(f'''
        <div style="background: white; padding: 15px; border-radius: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.15); margin-bottom: 20px; border: 1px solid #e4e6ea;">
            <div style="font-weight: 600; font-size: 15px;">👤 {MY_USERNAME}</div>
            <div style="font-size: 12.5px; color: #65676b; margin-bottom: 10px;">🕒 {time_str}</div>
            <div style="font-size: 15px; margin-bottom: 15px; white-space: pre-wrap;">{note}</div>
    ''', unsafe_allow_html=True) # คำสั่ง st.markdown ครอบเปิด div เพื่อสร้างการ์ดพร้อมใส่ข้อมูลผู้โพสต์ เวลา และข้อความ
    
    for file_path, ftype in media_rows: # วนลูปนำไฟล์ในโพสต์มาแสดง
        if os.path.exists(file_path): # เช็คก่อนว่ามีไฟล์ภาพหรือวิดีโอนี้อยู่จริงในระบบปฏิบัติการหรือไม่
            if "video" in ftype: # ตรวจสอบว่าเป็นไฟล์วิดีโอหรือไม่
                st.video(file_path) # ถ้าใช่ให้แสดงเครื่องเล่นวิดีโอ
            else: # ถ้าไม่ใช่ (แปลว่าเป็นรูปภาพ)
                st.image(file_path, use_container_width=True) # ถ้าใช่ให้แสดงรูปภาพ และปรับขนาดให้พอดีกับความกว้างหน้าจอ
    
    st.markdown("</div>", unsafe_allow_html=True) # ปิดแท็ก </div> ของกล่อง HTML หลังจากแสดงไฟล์เสร็จสิ้น

conn.close() # ปิดการเชื่อมต่อฐานข้อมูลในส่วนแสดงผล