import streamlit as st
import sqlite3
import uuid
import os
import html
import base64
from datetime import datetime, timedelta
from PIL import Image, ImageOps

# ==========================================
# 1. Setup: folders and database
# ==========================================
st.set_page_config(page_title="Yuaan Post", layout="centered")

UPLOAD_DIR = "uploads"
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")
DB_PATH = "diary.db"
SESSION_DAYS = 30  # how long "stay logged in" lasts

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(AVATAR_DIR, exist_ok=True)


def run(sql, params=(), fetch=None):
    """Run one SQL statement and return rows ('all'), one row ('one') or nothing."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        if fetch == "all":
            return cur.fetchall()
        if fetch == "one":
            return cur.fetchone()
    finally:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL, display_name TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, author_username TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL, position INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, author_username TEXT NOT NULL, comment_text TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at TEXT NOT NULL)''')
    # friendships: requester -> addressee, status is 'pending' or 'accepted'
    conn.execute('''CREATE TABLE IF NOT EXISTS friendships (id TEXT PRIMARY KEY, requester TEXT NOT NULL, addressee TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)''')
    # direct messages
    conn.execute('''CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, sender TEXT NOT NULL, receiver TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0)''')
    # add the avatar column to an existing users table (safe to run every time)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    if "avatar_path" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_path TEXT")
    conn.commit()
    conn.close()


init_db()

# ==========================================
# 2. Helper functions
# ==========================================
def get_display_name(username):
    row = run("SELECT display_name FROM users WHERE username = ?", (username,), "one")
    return row[0] if row else username


# --- login sessions (keeps you logged in after refresh) ---
def create_session(username):
    token = uuid.uuid4().hex + uuid.uuid4().hex
    expires_at = (datetime.now() + timedelta(days=SESSION_DAYS)).isoformat()
    run("DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(),))
    run("INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)", (token, username, expires_at))
    return token


def get_session_user(token):
    row = run("SELECT username FROM sessions WHERE token = ? AND expires_at > ?", (token, datetime.now().isoformat()), "one")
    return row[0] if row else None


def delete_session(token):
    run("DELETE FROM sessions WHERE token = ?", (token,))


# --- profile pictures ---
def get_avatar_path(username):
    row = run("SELECT avatar_path FROM users WHERE username = ?", (username,), "one")
    if row and row[0] and os.path.exists(row[0]):
        return row[0]
    return None


@st.cache_data(show_spinner=False)
def _file_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def avatar_html(username, size=40):
    """Round profile picture as HTML; falls back to a coloured circle with the first letter."""
    path = get_avatar_path(username)
    if path:
        return (f'<img src="data:image/jpeg;base64,{_file_b64(path)}" '
                f'style="width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;flex-shrink:0;">')
    initial = html.escape((get_display_name(username) or "?")[:1].upper())
    return (f'<div style="width:{size}px;height:{size}px;border-radius:50%;background:#7c83fd;color:white;'
            f'display:flex;align-items:center;justify-content:center;font-weight:600;'
            f'font-size:{size // 2}px;flex-shrink:0;">{initial}</div>')


def person_html(username, size=44, subtitle=None):
    name = html.escape(get_display_name(username))
    sub = subtitle if subtitle is not None else f"@{html.escape(username)}"
    return (f'<div style="display:flex;align-items:center;gap:12px;">{avatar_html(username, size)}'
            f'<div><div style="font-weight:600;">{name}</div>'
            f'<div style="font-size:12px;opacity:0.65;">{sub}</div></div></div>')


def save_avatar(username, uploaded):
    img = Image.open(uploaded)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (300, 300))  # centre-crop to a square
    new_path = os.path.join(AVATAR_DIR, f"{uuid.uuid4().hex}.jpg")
    img.save(new_path, "JPEG", quality=88)
    old = get_avatar_path(username)
    run("UPDATE users SET avatar_path = ? WHERE username = ?", (new_path, username))
    if old:
        try:
            os.remove(old)
        except OSError:
            pass


# --- friends ---
def friendship_status(me, other):
    """Returns 'friends', 'sent' (I asked them), 'received' (they asked me) or 'none'."""
    row = run("SELECT requester, status FROM friendships WHERE (requester = ? AND addressee = ?) OR (requester = ? AND addressee = ?)",
              (me, other, other, me), "one")
    if not row:
        return "none"
    if row[1] == "accepted":
        return "friends"
    return "sent" if row[0] == me else "received"


def get_friends(me):
    rows = run('''SELECT CASE WHEN requester = ? THEN addressee ELSE requester END
                  FROM friendships WHERE status = 'accepted' AND (requester = ? OR addressee = ?)''',
               (me, me, me), "all")
    return sorted([r[0] for r in rows], key=lambda u: get_display_name(u).lower())


def get_incoming_requests(me):
    rows = run("SELECT requester FROM friendships WHERE addressee = ? AND status = 'pending' ORDER BY created_at DESC", (me,), "all")
    return [r[0] for r in rows]


def cb_send_request(me, other):
    if friendship_status(me, other) == "none":
        run("INSERT INTO friendships (id, requester, addressee, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (str(uuid.uuid4()), me, other, datetime.now().isoformat()))


def cb_accept_request(me, other):
    run("UPDATE friendships SET status = 'accepted' WHERE requester = ? AND addressee = ? AND status = 'pending'", (other, me))


def cb_remove_friendship(me, other):
    """Used for decline, cancel request and unfriend."""
    run("DELETE FROM friendships WHERE (requester = ? AND addressee = ?) OR (requester = ? AND addressee = ?)",
        (me, other, other, me))


def cb_open_chat(other):
    st.session_state.page = "chats"
    st.session_state.chat_with = other


# --- messages ---
def count_unread(me):
    return run("SELECT COUNT(*) FROM messages WHERE receiver = ? AND is_read = 0", (me,), "one")[0]


def send_message(me, other, text):
    run("INSERT INTO messages (id, sender, receiver, text, created_at, is_read) VALUES (?, ?, ?, ?, ?, 0)",
        (str(uuid.uuid4()), me, other, text, datetime.now().isoformat()))


@st.fragment(run_every=3)
def render_messages(me, other):
    """Re-runs every 3 seconds on its own so new messages appear without a full refresh."""
    run("UPDATE messages SET is_read = 1 WHERE sender = ? AND receiver = ? AND is_read = 0", (other, me))
    rows = run('''SELECT sender, text, created_at FROM messages
                  WHERE (sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?)
                  ORDER BY created_at DESC LIMIT 60''', (me, other, other, me), "all")
    rows.reverse()
    box = st.container(height=420)
    with box:
        if not rows:
            st.caption("No messages yet. Say hi! 👋")
        for sender, text, created_at in rows:
            avatar = get_avatar_path(sender) or "👤"
            role = "user" if sender == me else "assistant"
            with st.chat_message(role, avatar=avatar):
                time_str = datetime.fromisoformat(created_at).strftime("%d %b, %H:%M")
                st.caption(f"{get_display_name(sender)} · {time_str}")
                st.write(text)


# ==========================================
# 3. Login / Sign up
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""

# After a browser refresh session_state is empty, so restore the login from the token in the URL
if not st.session_state.logged_in:
    url_token = st.query_params.get("s")
    if url_token:
        restored_user = get_session_user(url_token)
        if restored_user:
            st.session_state.logged_in = True
            st.session_state.username = restored_user
            st.session_state.token = url_token
        else:
            del st.query_params["s"]

if not st.session_state.logged_in:
    st.title("🔒 Login to YuaanPost")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        login_user = st.text_input("Username", key="login_user")
        login_pass = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            user = run("SELECT * FROM users WHERE username = ? AND password = ?", (login_user, login_pass), "one")
            if user:
                st.session_state.logged_in = True
                st.session_state.username = login_user
                token = create_session(login_user)
                st.session_state.token = token
                st.query_params["s"] = token
                st.rerun()
            else:
                st.error("Username or Password is incorrect!")

    with tab2:
        reg_user = st.text_input("Username", key="reg_user")
        reg_pass = st.text_input("Password", type="password", key="reg_pass")
        reg_name = st.text_input("Display name", key="reg_name")
        if st.button("Sign Up"):
            if reg_user and reg_pass and reg_name:
                try:
                    run("INSERT INTO users (username, password, display_name) VALUES (?, ?, ?)", (reg_user.strip(), reg_pass, reg_name))
                    st.success("success! go to the login page to start")
                except sqlite3.IntegrityError:
                    st.error("This username has been taken please select a new one!")
            else:
                st.warning("Add all information")
    st.stop()

# ==========================================
# 4. Main app (after login)
# ==========================================
current_user = st.session_state.username
display_name = get_display_name(current_user)

if "page" not in st.session_state:
    st.session_state.page = "feed"
if "avatar_nonce" not in st.session_state:
    st.session_state.avatar_nonce = 0

pending_count = len(get_incoming_requests(current_user))
unread_count = count_unread(current_user)

PAGE_LABELS = {
    "feed": "🏠 Feed",
    "friends": "👥 Friends" + (f" ({pending_count} new)" if pending_count else ""),
    "chats": "💬 Chats" + (f" ({unread_count} new)" if unread_count else ""),
}

with st.sidebar:
    st.markdown(person_html(current_user, size=56, subtitle="Welcome to Yuaan Post"), unsafe_allow_html=True)
    st.write("")
    st.radio("Go to", list(PAGE_LABELS.keys()), format_func=lambda k: PAGE_LABELS[k], key="page", label_visibility="collapsed")

    st.divider()
    with st.expander("⚙️ Profile Settings"):
        pic = st.file_uploader("Profile picture", type=["png", "jpg", "jpeg"],
                               key=f"avatar_upload_{st.session_state.avatar_nonce}")
        if st.button("Save picture"):
            if pic:
                save_avatar(current_user, pic)
                st.session_state.avatar_nonce += 1  # resets the uploader
                st.rerun()
            else:
                st.warning("Choose a picture first")

        new_display_name = st.text_input("Change display name", value=display_name)
        if st.button("Set new name"):
            if new_display_name:
                run("UPDATE users SET display_name = ? WHERE username = ?", (new_display_name, current_user))
                st.rerun()

    st.divider()
    if st.button("Sign out"):
        delete_session(st.session_state.get("token", ""))
        st.query_params.clear()
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.page = "feed"
        st.rerun()

# ------------------------------------------
# PAGE: Feed
# ------------------------------------------
if st.session_state.page == "feed":
    st.title("📷 Yuaan Post")

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

    st.write("")
    st.header("All posts")

    conn = sqlite3.connect(DB_PATH)
    posts = conn.execute('''
        SELECT posts.id, posts.note, posts.created_at, posts.author_username
        FROM posts
        ORDER BY posts.created_at DESC
    ''').fetchall()

    if not posts:
        st.caption("No Posts — Be the first to share!")

    for post_id, note, created_at, author_username in posts:
        media_rows = conn.execute("SELECT file_path, file_type FROM media WHERE post_id = ? ORDER BY position", (post_id,)).fetchall()
        time_str = datetime.fromisoformat(created_at).strftime("%d %b %Y, %H:%M")

        with st.container(border=True):
            st.markdown(person_html(author_username, size=42, subtitle=f"🕒 {time_str}"), unsafe_allow_html=True)
            st.markdown(f'<div style="white-space: pre-wrap; margin: 10px 0;">{html.escape(note)}</div>', unsafe_allow_html=True)

            for file_path, ftype in media_rows:
                if os.path.exists(file_path):
                    if "video" in ftype:
                        st.video(file_path)
                    else:
                        st.image(file_path, use_container_width=True)

            comments = conn.execute('''
                SELECT users.display_name, comments.comment_text
                FROM comments
                LEFT JOIN users ON comments.author_username = users.username
                WHERE comments.post_id = ?
                ORDER BY comments.created_at ASC
            ''', (post_id,)).fetchall()

            with st.expander(f"💬 comment ({len(comments)} comment)"):
                for c_author, c_text in comments:
                    st.markdown(f"**{c_author or 'Unknown'}**: {c_text}")

                with st.form(f"comment_form_{post_id}", clear_on_submit=True):
                    new_comment = st.text_input("comment...")
                    if st.form_submit_button("send"):
                        if new_comment:
                            conn.execute("INSERT INTO comments (id, post_id, author_username, comment_text, created_at) VALUES (?, ?, ?, ?, ?)",
                                         (str(uuid.uuid4()), post_id, current_user, new_comment, datetime.now().isoformat()))
                            conn.commit()
                            st.rerun()
    conn.close()

# ------------------------------------------
# PAGE: Friends (requests, search, friend list)
# ------------------------------------------
elif st.session_state.page == "friends":
    st.title("👥 Friends")

    # 1) incoming requests
    incoming = get_incoming_requests(current_user)
    if incoming:
        st.subheader(f"Friend requests ({len(incoming)})")
        for other in incoming:
            c1, c2, c3 = st.columns([5, 2, 2])
            c1.markdown(person_html(other), unsafe_allow_html=True)
            c2.button("Accept", key=f"acc_{other}", type="primary", on_click=cb_accept_request, args=(current_user, other))
            c3.button("Decline", key=f"dec_{other}", on_click=cb_remove_friendship, args=(current_user, other))
        st.divider()

    # 2) search by username or display name
    st.subheader("Find people")
    query = st.text_input("Search by username or name", placeholder="e.g. yuaan", key="friend_search")
    if query.strip():
        like = f"%{query.strip()}%"
        results = run('''SELECT username FROM users
                         WHERE username != ? AND (username LIKE ? OR display_name LIKE ?)
                         ORDER BY username LIMIT 20''', (current_user, like, like), "all")
        if not results:
            st.caption("No users found.")
        for (other,) in results:
            status = friendship_status(current_user, other)
            c1, c2 = st.columns([6, 3])
            c1.markdown(person_html(other), unsafe_allow_html=True)
            if status == "none":
                c2.button("➕ Add friend", key=f"add_{other}", on_click=cb_send_request, args=(current_user, other))
            elif status == "sent":
                c2.button("Cancel request", key=f"cancel_{other}", on_click=cb_remove_friendship, args=(current_user, other))
            elif status == "received":
                c2.button("Accept", key=f"sacc_{other}", type="primary", on_click=cb_accept_request, args=(current_user, other))
            else:
                c2.button("💬 Message", key=f"smsg_{other}", on_click=cb_open_chat, args=(other,))
        st.divider()

    # 3) my friends
    friends = get_friends(current_user)
    st.subheader(f"My friends ({len(friends)})")
    if not friends:
        st.caption("No friends yet. Search for a username above to add someone.")
    for other in friends:
        c1, c2, c3 = st.columns([5, 2, 2])
        c1.markdown(person_html(other), unsafe_allow_html=True)
        c2.button("💬 Message", key=f"fmsg_{other}", on_click=cb_open_chat, args=(other,))
        c3.button("Unfriend", key=f"unf_{other}", on_click=cb_remove_friendship, args=(current_user, other))

# ------------------------------------------
# PAGE: Chats
# ------------------------------------------
elif st.session_state.page == "chats":
    st.title("💬 Chats")
    friends = get_friends(current_user)

    if not friends:
        st.info("You need a friend to chat with. Go to 👥 Friends and add someone by username.")
    else:
        if st.session_state.get("chat_with") not in friends:
            st.session_state.pop("chat_with", None)

        unread_by = dict(run("SELECT sender, COUNT(*) FROM messages WHERE receiver = ? AND is_read = 0 GROUP BY sender", (current_user,), "all"))

        def friend_label(u):
            n = unread_by.get(u, 0)
            return f"{get_display_name(u)} (@{u})" + (f"  •  {n} new" if n else "")

        other = st.selectbox("Chat with", friends, format_func=friend_label, key="chat_with")

        st.markdown(person_html(other, size=36), unsafe_allow_html=True)
        render_messages(current_user, other)

        prompt = st.chat_input(f"Message {get_display_name(other)}...")
        if prompt and prompt.strip():
            send_message(current_user, other, prompt.strip())
            st.rerun()