import streamlit as st

st.title("Yuaan Post")


# 2. สร้างที่เก็บข้อมูลชั่วคราว (กล่องความทรงจำ)
# เช็คว่ามีกล่องเก็บไดอารี่หรือยัง ถ้ายังไม่มีให้สร้างกล่องเปล่าๆ ขึ้นมา
if "diary_entries" not in st.session_state:
    st.session_state.diary_entries = []

# 3. สร้างฟอร์มสำหรับอัพโหลดและเขียนโน้ต
with st.form("diary_form"):
    st.write("Come and post your Story")
    # ช่องอัพโหลดไฟล์ รองรับรูปภาพและวิดีโอ (เพิ่ม mp4 และ mov แล้ว)
    uploaded_file = st.file_uploader("Select Photo or Video", type=["png", "jpg", "jpeg", "mp4", "mov"])
    # ช่องพิมพ์ข้อความ
    note = st.text_area("Your description.....")
    # ปุ่มสำหรับกดส่งข้อมูล
    submit_button = st.form_submit_button("Save")
    # 4. ตรวจสอบเงื่อนไขเมื่อมีการกดปุ่มบันทึก
    if submit_button:
        # เช็คว่าใส่ไฟล์และข้อความมาครบไหม
        if uploaded_file is not None and note:
            
            # เอาข้อมูลใส่ลงไปในกล่อง
            st.session_state.diary_entries.append({
                "file_data": uploaded_file.getvalue(), # เก็บข้อมูลเนื้อหาไฟล์ทั้งหมด
                "file_type": uploaded_file.type,       # แปะป้ายบอกชนิดไฟล์ (ว่าเป็นรูปภาพหรือวิดีโอ)
                "note": note                           # เก็บข้อความ
            })
            st.success("Saved! 🎉")
        else:
            # ถ้าใส่มาไม่ครบ ให้เตือน
            st.warning("Don't forget to add all desciptions and add a photo!")

# 5. ส่วนแสดงผลไดอารี่
st.write("---")
st.header("My Posts")

# วนลูปหยิบของในกล่องมาโชว์ทีละอัน (ใช้ reversed เพื่อให้เรื่องใหม่ล่าสุดอยู่ข้างบน)
for entry in reversed(st.session_state.diary_entries):
    
    # ถ้าป้ายบอกว่าเป็นวิดีโอ ให้เปิดด้วยเครื่องเล่นวิดีโอ
    if "video" in entry["file_type"]:
        st.video(entry["file_data"])
        
    # ถ้าไม่ใช่ (แปลว่าเป็นรูปภาพ) ให้ใส่กรอบรูป
    else:
        st.image(entry["file_data"], use_container_width=True)
        
    st.write(f"**Description:** {entry['note']}")
    st.write("---")