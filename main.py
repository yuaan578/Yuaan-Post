import streamlit as st
import sqlite3
import uuid
import os
import re
import html
import base64
from datetime import datetime, timedelta
from PIL import Image, ImageOps

# ==========================================
# 1. Setup: folders and database
# ==========================================
st.set_page_config(page_title="Yuaan Post", page_icon="📸", layout="centered")

UPLOAD_DIR = "uploads"
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")
REEL_DIR = os.path.join(UPLOAD_DIR, "reels")
DB_PATH = "diary.db"
SESSION_DAYS = 30   # how long "stay logged in" lasts
MAX_REEL_MB = 100   # biggest reel video allowed

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(AVATAR_DIR, exist_ok=True)
os.makedirs(REEL_DIR, exist_ok=True)


# ==========================================
# 2. Themes (colours for the whole app)
# ==========================================
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(c))) for c in rgb)


def mix(a, b, t):
    """Blend colour a towards colour b by t (0 to 1)."""
    return _hex(tuple(x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))))


def luminance(h):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def darken_for_white_text(h, max_lum=0.2):
    """Darkens a colour until white text on top of it is easy to read."""
    for _ in range(25):
        if luminance(h) <= max_lum:
            break
        h = mix(h, "#000000", 0.12)
    return h


def make_theme(bg, primary, secondary, ink=None, accents=None):
    dark = luminance(bg) < 0.25
    if dark:
        surface = mix(bg, "#FFFFFF", 0.07)
        surface2 = mix(bg, "#FFFFFF", 0.13)
        border = mix(bg, "#FFFFFF", 0.24)
        ink = ink or "#F3F0FF"
        outline = secondary if luminance(secondary) > 0.25 else mix(secondary, "#FFFFFF", 0.5)
    else:
        surface = "#FFFFFF"
        surface2 = mix(bg, primary, 0.16)
        border = mix(bg, primary, 0.28)
        ink = ink or "#1A1530"
        outline = darken_for_white_text(secondary, 0.3)
    accents = accents or [primary, secondary, mix(primary, secondary, 0.5), "#F59E0B"]
    d = darken_for_white_text
    return {
        "dark": dark, "bg": bg, "surface": surface, "surface2": surface2, "border": border, "ink": ink,
        "primary": primary, "outline": outline, "accents": accents,
        "btn": (d(primary), d(accents[3], 0.26)), "btn_hover": (d(secondary), d(primary)),
        "bubble": (mix(primary, surface, 0.8), mix(secondary, surface, 0.8)),
        "banners": {
            "feed": (d(accents[0]), d(accents[1])),
            "reels": (d(accents[1]), d(accents[0])),
            "friends": (d(accents[2]), d(accents[1])),
            "chats": (d(accents[3]), d(accents[0])),
        },
    }


THEMES = {
    "Pop":      make_theme("#F6F1FF", "#E91E78", "#6C3DFF", "#1B1340", ["#E91E78", "#6C3DFF", "#00A896", "#F26B1D"]),
    "Ocean":    make_theme("#EAF6FF", "#0A6CD6", "#0A9396", "#0B2545", ["#0A6CD6", "#0A9396", "#5B5BD6", "#F59E0B"]),
    "Sunset":   make_theme("#FFF1F2", "#E8590C", "#C2185B", "#3B0A1E", ["#E8590C", "#C2185B", "#7B2CBF", "#F4A300"]),
    "Mint":     make_theme("#E9FBF3", "#0E9F6E", "#2563EB", "#0A3326", ["#0E9F6E", "#2563EB", "#EC4899", "#F59E0B"]),
    "Midnight": make_theme("#0F0B24", "#FF4FA3", "#8B7BFF", None, ["#FF4FA3", "#8B7BFF", "#2DD4BF", "#FFD166"]),
}
THEME_NAMES = list(THEMES.keys()) + ["Custom"]
DEFAULT_CUSTOM = ("#F6F1FF", "#E91E78", "#6C3DFF")  # background, main colour, second colour
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def parse_theme(value):
    """A saved theme is either a preset name or 'custom|#background|#main|#second'."""
    if value and value.startswith("custom|"):
        parts = value.split("|")
        if len(parts) == 4 and all(HEX_RE.match(p) for p in parts[1:]):
            return make_theme(*parts[1:])
    return THEMES.get(value, THEMES["Pop"])


T = THEMES["Pop"]  # the theme in use; replaced after login with the user's own choice

CSS_TEMPLATE = """
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600..800&family=DM+Sans:wght@400;500;700&display=swap');

html, body, .stApp, [data-testid="stMarkdownContainer"], input, textarea, button { font-family: 'DM Sans', sans-serif; }
h1, h2, h3, .yp-banner-title { font-family: 'Bricolage Grotesque', sans-serif !important; letter-spacing: -0.02em; }

.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: __BG__ !important; color: __INK__; }
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stBottom"] > div { background: __BG__ !important; }
.stApp p, .stApp label, .stApp li, .stApp span, [data-testid="stCaptionContainer"] { color: __INK__ !important; }
h1, h2, h3 { color: __INK__ !important; }
hr { border-color: __BORDER__ !important; }

[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child { background: __SURFACE2__ !important; }
[data-testid="stSidebar"] { border-right: 4px solid __PRIMARY__; }

/* big menu tabs in the sidebar: Feed, Reels, Friends, Chats */
[data-testid="stSidebar"] [role="radiogroup"] { gap: 12px; }
[data-testid="stSidebar"] [role="radiogroup"] > label {
    width: 100%; padding: 16px 20px; border-radius: 20px; cursor: pointer;
    background: __SURFACE__; border: 2px solid __BORDER__; box-shadow: 0 4px 0 __SHADOW__;
    transition: transform .12s ease, border-color .12s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] > label > div:first-child:not([data-testid="stMarkdownContainer"]) { display: none; }
[data-testid="stSidebar"] [role="radiogroup"] > label p { font-size: 1.4rem !important; font-weight: 700; margin: 0; line-height: 1.3; }
[data-testid="stSidebar"] [role="radiogroup"] > label:hover { border-color: __PRIMARY__; transform: translateX(4px); }
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {
    background: linear-gradient(90deg, __BTN1__, __BTN2__); border-color: transparent;
}
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) p { color: #fff !important; }

/* buttons */
.stButton > button, .stFormSubmitButton > button {
    border-radius: 999px; border: 2px solid __OUTLINE__; background: __SURFACE__; color: __OUTLINE__;
    font-weight: 700; padding: 0.35rem 1.1rem; transition: transform .12s ease, background .12s ease, color .12s ease;
}
.stButton > button:hover, .stFormSubmitButton > button:hover { background: __OUTLINE__; color: __SURFACE__; transform: translateY(-2px); }
.stButton > button:active, .stFormSubmitButton > button:active { transform: translateY(0); }
.stButton > button[kind="primary"], .stFormSubmitButton > button {
    background: linear-gradient(90deg, __BTN1__, __BTN2__); border: none; color: #fff;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover { background: linear-gradient(90deg, __HOV1__, __HOV2__); color: #fff; }
.stButton > button p, .stFormSubmitButton > button p { color: inherit !important; }
[data-testid="stFileUploaderDropzone"] button {
    background: __SURFACE__; border: 2px solid __OUTLINE__; border-radius: 999px;
}
[data-testid="stFileUploaderDropzone"] button, [data-testid="stFileUploaderDropzone"] button * { color: __OUTLINE__ !important; }
[data-testid="stFileUploaderDropzone"] { background: __SURFACE2__; border-radius: 16px; }

/* inputs */
.stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div {
    background: __SURFACE__ !important; color: __INK__ !important; border-radius: 14px !important; border: 2px solid __BORDER__ !important;
}
.stTextInput input:focus, .stTextArea textarea:focus { border-color: __PRIMARY__ !important; }

/* cards */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: __SURFACE__; border: 2px solid __BORDER__; border-radius: 22px; box-shadow: 0 8px 0 __SHADOW__;
}
[data-testid="stForm"] { background: __SURFACE__; border: 2px dashed __BORDER__; border-radius: 22px; }
[data-testid="stExpander"] { border: 2px solid __BORDER__; border-radius: 16px; background: __SURFACE2__; }
[data-testid="stAlert"] { background: __SURFACE2__; border: 2px solid __BORDER__; border-radius: 16px; }
[data-testid="stAlert"] * { color: __INK__ !important; }
video { border-radius: 18px; max-height: 68vh; background: #000; }

/* tabs on the login page */
button[data-baseweb="tab"] { font-weight: 700; font-size: 1.05rem; }
button[data-baseweb="tab"][aria-selected="true"], button[data-baseweb="tab"][aria-selected="true"] p { color: __PRIMARY__ !important; }
[data-baseweb="tab-highlight"] { background-color: __PRIMARY__ !important; height: 4px !important; border-radius: 4px; }

/* chat bubbles */
[data-testid="stChatMessage"] { border-radius: 20px; padding: 0.7rem 1rem; margin-bottom: 0.5rem; background: __SURFACE2__; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background: linear-gradient(90deg, __BUB1__, __BUB2__); }
[data-testid="stChatInput"] { border-radius: 999px; border: 2px solid __OUTLINE__; background: __SURFACE__; }
[data-testid="stChatInput"] textarea { color: __INK__ !important; }

/* banners at the top of each page */
.yp-banner { border-radius: 26px; padding: 26px 28px; margin-bottom: 22px; color: #fff; box-shadow: 0 8px 0 rgba(0,0,0,.16); }
.yp-banner-title { font-size: 2.4rem; font-weight: 800; line-height: 1.05; color: #fff; }
.yp-banner-sub { font-size: 1.05rem; margin-top: 6px; color: #fff; opacity: .95; }

@media (prefers-reduced-motion: reduce) { .stButton > button, .stFormSubmitButton > button { transition: none; } }
"""


def build_css(t):
    r, g, b = _rgb(t["primary"])
    shadow = "rgba(0,0,0,.45)" if t["dark"] else f"rgba({r},{g},{b},.18)"
    tokens = {
        "__BG__": t["bg"], "__SURFACE__": t["surface"], "__SURFACE2__": t["surface2"], "__BORDER__": t["border"],
        "__INK__": t["ink"], "__PRIMARY__": t["primary"], "__OUTLINE__": t["outline"], "__SHADOW__": shadow,
        "__BTN1__": t["btn"][0], "__BTN2__": t["btn"][1], "__HOV1__": t["btn_hover"][0], "__HOV2__": t["btn_hover"][1],
        "__BUB1__": t["bubble"][0], "__BUB2__": t["bubble"][1],
    }
    css = CSS_TEMPLATE
    for key, val in tokens.items():
        css = css.replace(key, val)
    return css


def banner(title, subtitle, page_key):
    c1, c2 = T["banners"][page_key]
    st.markdown(
        f'<div class="yp-banner" style="background: linear-gradient(120deg, {c1}, {c2});">'
        f'<div class="yp-banner-title">{html.escape(title)}</div>'
        f'<div class="yp-banner-sub">{html.escape(subtitle)}</div></div>',
        unsafe_allow_html=True)


# ==========================================
# 3. Database
# ==========================================
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
    # comments are used for both posts and reels (post_id holds either id)
    conn.execute('''CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, author_username TEXT NOT NULL, comment_text TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS friendships (id TEXT PRIMARY KEY, requester TEXT NOT NULL, addressee TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, sender TEXT NOT NULL, receiver TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS reels (id TEXT PRIMARY KEY, author_username TEXT NOT NULL, video_path TEXT NOT NULL, caption TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS reel_likes (reel_id TEXT NOT NULL, username TEXT NOT NULL, PRIMARY KEY (reel_id, username))''')
    # add new columns to an existing users table (safe to run every time)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    if "avatar_path" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_path TEXT")
    if "theme" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN theme TEXT")
    conn.commit()
    conn.close()


init_db()

# ==========================================
# 4. Helper functions
# ==========================================
def get_display_name(username):
    row = run("SELECT display_name FROM users WHERE username = ?", (username,), "one")
    return row[0] if row else username


def get_theme_value(username):
    if not username:
        return "Pop"
    row = run("SELECT theme FROM users WHERE username = ?", (username,), "one")
    return row[0] if row and row[0] else "Pop"


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
    """Round profile picture with a gradient ring; without a picture, a coloured circle with the first letter."""
    inner = size - 10  # room for the gradient ring (3px) and a gap (2px) on each side
    path = get_avatar_path(username)
    acc = T["accents"]
    if path:
        face = (f'<img src="data:image/jpeg;base64,{_file_b64(path)}" '
                f'style="width:{inner}px;height:{inner}px;border-radius:50%;object-fit:cover;display:block;">')
    else:
        colour = acc[sum(ord(ch) for ch in username) % len(acc)]  # each person gets their own colour
        initial = html.escape((get_display_name(username) or "?")[:1].upper())
        text_colour = "#1A1530" if luminance(colour) > 0.4 else "#FFFFFF"
        face = (f'<div style="width:{inner}px;height:{inner}px;border-radius:50%;background:{colour};color:{text_colour};'
                f'display:flex;align-items:center;justify-content:center;font-weight:800;'
                f'font-size:{max(inner // 2, 12)}px;">{initial}</div>')
    ring = f"linear-gradient(45deg, {acc[3]}, {acc[0]}, {acc[1]})"
    return (f'<div style="padding:3px;border-radius:50%;background:{ring};display:inline-flex;flex-shrink:0;">'
            f'<div style="padding:2px;border-radius:50%;background:{T["surface"]};display:flex;">{face}</div></div>')


def person_html(username, size=44, subtitle=None):
    name = html.escape(get_display_name(username))
    sub = subtitle if subtitle is not None else f"@{html.escape(username)}"
    return (f'<div style="display:flex;align-items:center;gap:12px;">{avatar_html(username, size)}'
            f'<div><div style="font-weight:700;font-size:16px;">{name}</div>'
            f'<div style="font-size:12px;opacity:0.7;">{sub}</div></div></div>')


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


def friend_button(container, me, other, key):
    """Shows the right friend button next to someone's post or reel."""
    if other == me:
        return
    status = friendship_status(me, other)
    if status == "none":
        container.button("➕ Add friend", key=key, on_click=cb_send_request, args=(me, other), use_container_width=True)
    elif status == "sent":
        container.button("Request sent", key=key, disabled=True, use_container_width=True)
    elif status == "received":
        container.button("Accept", key=key, type="primary", on_click=cb_accept_request, args=(me, other), use_container_width=True)
    else:
        container.button("✓ Friends", key=key, disabled=True, use_container_width=True)


def cb_sign_out():
    """Runs before the page re-renders, so it may safely reset widget values like 'page'."""
    delete_session(st.session_state.get("token", ""))
    st.query_params.clear()
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.token = ""
    st.session_state.page = "feed"
    for key in ("chat_with", "theme_choice", "theme_bg", "theme_main", "theme_second", "reel_idx"):
        st.session_state.pop(key, None)


def cb_open_chat(other):
    st.session_state.page = "chats"
    st.session_state.chat_with = other


# --- themes ---
def cb_save_theme():
    me = st.session_state.username
    choice = st.session_state.get("theme_choice", "Pop")
    if choice == "Custom":
        bg, main, second = DEFAULT_CUSTOM
        value = "custom|%s|%s|%s" % (st.session_state.get("theme_bg", bg),
                                     st.session_state.get("theme_main", main),
                                     st.session_state.get("theme_second", second))
    else:
        value = choice
    run("UPDATE users SET theme = ? WHERE username = ?", (value, me))
    st.toast(f"Theme saved: {choice}", icon="🎨")


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


# --- reels ---
def get_reels():
    rows = run("SELECT id, author_username, video_path, caption, created_at FROM reels ORDER BY created_at DESC", fetch="all")
    return [r for r in rows if os.path.exists(r[2])]


def reel_likes(reel_id, me):
    count = run("SELECT COUNT(*) FROM reel_likes WHERE reel_id = ?", (reel_id,), "one")[0]
    mine = run("SELECT 1 FROM reel_likes WHERE reel_id = ? AND username = ?", (reel_id, me), "one") is not None
    return count, mine


def cb_toggle_like(reel_id, me):
    _, mine = reel_likes(reel_id, me)
    if mine:
        run("DELETE FROM reel_likes WHERE reel_id = ? AND username = ?", (reel_id, me))
    else:
        run("INSERT OR IGNORE INTO reel_likes (reel_id, username) VALUES (?, ?)", (reel_id, me))


def cb_reel_step(step, total):
    st.session_state.reel_idx = (st.session_state.get("reel_idx", 0) + step) % max(total, 1)


def cb_delete_reel(reel_id, me):
    row = run("SELECT author_username, video_path FROM reels WHERE id = ?", (reel_id,), "one")
    if row and row[0] == me:  # only the author can delete
        run("DELETE FROM reels WHERE id = ?", (reel_id,))
        run("DELETE FROM reel_likes WHERE reel_id = ?", (reel_id,))
        run("DELETE FROM comments WHERE post_id = ?", (reel_id,))
        try:
            os.remove(row[1])
        except OSError:
            pass
        st.session_state.reel_idx = 0


# ==========================================
# 5. Login / Sign up
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

# Apply the colours: the logged-in user's own theme, or the default on the login page
T = parse_theme(get_theme_value(st.session_state.username) if st.session_state.logged_in else "Pop")
st.markdown(f"<style>{build_css(T)}</style>", unsafe_allow_html=True)

if not st.session_state.logged_in:
    banner("Yuaan Post", "Log in or sign up to share moments with your friends.", "feed")
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
# 6. Main app (after login)
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
    "reels": "🎬 Reels",
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

    with st.expander("🎨 Theme"):
        saved = get_theme_value(current_user)
        saved_name = "Custom" if saved.startswith("custom|") else (saved if saved in THEMES else "Pop")
        st.selectbox("Choose a theme", THEME_NAMES, index=THEME_NAMES.index(saved_name), key="theme_choice", on_change=cb_save_theme)

        if st.session_state.theme_choice == "Custom":
            parts = saved.split("|")[1:] if saved.startswith("custom|") else list(DEFAULT_CUSTOM)
            if len(parts) != 3 or not all(HEX_RE.match(p) for p in parts):
                parts = list(DEFAULT_CUSTOM)
            st.color_picker("Background", parts[0], key="theme_bg", on_change=cb_save_theme)
            st.color_picker("Main colour", parts[1], key="theme_main", on_change=cb_save_theme)
            st.color_picker("Second colour", parts[2], key="theme_second", on_change=cb_save_theme)

        dots = "".join(f'<span style="display:inline-block;width:26px;height:26px;border-radius:50%;background:{c};margin-right:6px;"></span>'
                       for c in T["accents"])
        st.markdown(f'<div style="margin-top:6px;">{dots}</div>', unsafe_allow_html=True)

    st.divider()
    st.button("Sign out", on_click=cb_sign_out)

# ------------------------------------------
# PAGE: Feed
# ------------------------------------------
if st.session_state.page == "feed":
    banner("Yuaan Post", "See what your friends are up to, or post something new.", "feed")

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
    st.header("Latest posts")

    conn = sqlite3.connect(DB_PATH)
    posts = conn.execute('''
        SELECT posts.id, posts.note, posts.created_at, posts.author_username
        FROM posts
        ORDER BY posts.created_at DESC
    ''').fetchall()

    if not posts:
        st.info("Nothing here yet. Write the first post above.")

    for idx, (post_id, note, created_at, author_username) in enumerate(posts):
        media_rows = conn.execute("SELECT file_path, file_type FROM media WHERE post_id = ? ORDER BY position", (post_id,)).fetchall()
        time_str = datetime.fromisoformat(created_at).strftime("%d %b %Y, %H:%M")

        with st.container(border=True):
            st.markdown(f'<div style="height:8px;border-radius:8px;background:{T["accents"][idx % len(T["accents"])]};margin-bottom:12px;"></div>',
                        unsafe_allow_html=True)
            h_left, h_right = st.columns([5, 2])
            h_left.markdown(person_html(author_username, size=48, subtitle=f"🕒 {time_str}"), unsafe_allow_html=True)
            friend_button(h_right, current_user, author_username, f"postfriend_{post_id}")
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
# PAGE: Reels (short videos, one at a time)
# ------------------------------------------
elif st.session_state.page == "reels":
    banner("Reels", "Short videos from everyone. Use the arrows to move between them.", "reels")

    with st.expander("➕ Upload a reel"):
        with st.form("reel_form", clear_on_submit=True):
            reel_file = st.file_uploader("Video (MP4 works best)", type=["mp4", "mov", "webm"])
            reel_caption = st.text_input("Caption")
            if st.form_submit_button("Share reel"):
                if not reel_file:
                    st.warning("Choose a video first.")
                elif reel_file.size > MAX_REEL_MB * 1024 * 1024:
                    st.error(f"That video is bigger than {MAX_REEL_MB} MB. Choose a shorter one.")
                else:
                    reel_id = str(uuid.uuid4())
                    ext = os.path.splitext(reel_file.name)[1].lower() or ".mp4"
                    reel_path = os.path.join(REEL_DIR, f"{reel_id}{ext}")
                    with open(reel_path, "wb") as f:
                        f.write(reel_file.getvalue())
                    run("INSERT INTO reels (id, author_username, video_path, caption, created_at) VALUES (?, ?, ?, ?, ?)",
                        (reel_id, current_user, reel_path, reel_caption.strip(), datetime.now().isoformat()))
                    st.session_state.reel_idx = 0  # show the new reel first
                    st.rerun()

    reels = get_reels()
    if not reels:
        st.info("No reels yet. Upload the first one above.")
    else:
        total = len(reels)
        idx = min(max(st.session_state.get("reel_idx", 0), 0), total - 1)
        st.session_state.reel_idx = idx
        reel_id, author, video_path, caption, created_at = reels[idx]
        like_count, liked = reel_likes(reel_id, current_user)
        time_str = datetime.fromisoformat(created_at).strftime("%d %b %Y, %H:%M")

        with st.container(border=True):
            h_left, h_right = st.columns([5, 2])
            h_left.markdown(person_html(author, size=48, subtitle=f"🕒 {time_str}"), unsafe_allow_html=True)
            friend_button(h_right, current_user, author, f"reelfriend_{reel_id}")
            st.video(video_path, loop=True, autoplay=True, muted=True)
            if caption:
                st.markdown(f'<div style="white-space: pre-wrap; margin: 6px 0;">{html.escape(caption)}</div>', unsafe_allow_html=True)

            c_prev, c_like, c_del, c_next = st.columns([2, 2, 2, 2])
            c_prev.button("⬆️ Previous", key="reel_prev", on_click=cb_reel_step, args=(-1, total), use_container_width=True)
            c_like.button(f"{'❤️' if liked else '🤍'} {like_count}", key="reel_like", on_click=cb_toggle_like,
                          args=(reel_id, current_user), type="primary" if liked else "secondary", use_container_width=True)
            if author == current_user:
                c_del.button("🗑️ Delete", key="reel_del", on_click=cb_delete_reel, args=(reel_id, current_user), use_container_width=True)
            c_next.button("Next ⬇️", key="reel_next", on_click=cb_reel_step, args=(1, total), use_container_width=True)
            st.caption(f"Reel {idx + 1} of {total}")

            reel_comments = run('''
                SELECT users.display_name, comments.comment_text
                FROM comments
                LEFT JOIN users ON comments.author_username = users.username
                WHERE comments.post_id = ?
                ORDER BY comments.created_at ASC
            ''', (reel_id,), "all")
            with st.expander(f"💬 comment ({len(reel_comments)} comment)"):
                for c_author, c_text in reel_comments:
                    st.markdown(f"**{c_author or 'Unknown'}**: {c_text}")
                with st.form(f"reel_comment_form_{reel_id}", clear_on_submit=True):
                    new_reel_comment = st.text_input("comment...")
                    if st.form_submit_button("send"):
                        if new_reel_comment:
                            run("INSERT INTO comments (id, post_id, author_username, comment_text, created_at) VALUES (?, ?, ?, ?, ?)",
                                (str(uuid.uuid4()), reel_id, current_user, new_reel_comment, datetime.now().isoformat()))
                            st.rerun()

# ------------------------------------------
# PAGE: Friends (requests, search, friend list)
# ------------------------------------------
elif st.session_state.page == "friends":
    banner("Friends", "Search by username to add someone, then start a chat.", "friends")

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
    banner("Chats", "Pick a friend and send a message.", "chats")
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
