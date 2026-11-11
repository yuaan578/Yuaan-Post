import streamlit as st
import uuid
import json
import os
import re
import html
import io
import random
import hashlib
import hmac
import time
import requests
import psycopg2
from urllib.parse import quote, unquote
import psycopg2.pool
from psycopg2.pool import ThreadedConnectionPool
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageOps
import streamlit.components.v1 as components

def utc_now():
    """Times are stored in UTC (the same on any server) and shown in Thai time."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def thai_time(iso, fmt):
    return (datetime.fromisoformat(iso) + timedelta(hours=7)).strftime(fmt)


# ==========================================
# 1. Setup
# ==========================================
st.set_page_config(page_title="Yuaan Post", page_icon="📸", layout="centered")
_script_start = time.perf_counter()
st.session_state["_dbq"] = 0
st.session_state["_dbt"] = 0.0

BUCKET = "uploads"   # name of the Supabase Storage bucket for photos, reels and profile pictures
ADMINS = {"yuaan.admin"}   # accounts that see the extra 🛡 Admin page (reports). Add more with ADMIN_USERS in Secrets.
SESSION_DAYS = 30    # how long "stay logged in" lasts
MAX_REEL_MB = 50     # biggest reel video allowed (Supabase's free plan allows 50 MB per file)
MAX_VIDEO_MB = 50    # biggest video allowed in a post


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
            "yuaan": (d(accents[2]), d(accents[3], 0.24)),
            "foryou": (d(accents[3]), d(accents[1])),
            "profile": (d(accents[3]), d(accents[2])),
            "search": (d(accents[2]), d(accents[0])),
            "alerts": (d(accents[1]), d(accents[3])),
            "admin": (d(accents[0]), d(accents[2])),
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

/* very big menu buttons in the sidebar: Feed, Reels, Friends, Chats */
section[data-testid="stSidebar"][aria-expanded="true"] { width: 360px !important; min-width: 360px !important; }
[data-testid="stSidebar"] .stButton > button {
    min-height: 110px; border-radius: 30px; box-shadow: 0 8px 0 __SHADOW__;
}
[data-testid="stSidebar"] .stButton > button p { font-size: 2.2rem !important; font-weight: 800; line-height: 1.15; }
[data-testid="stSidebar"] .stButton > button:hover { transform: translateY(-3px); }
/* buttons inside the settings boxes stay normal size */
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button { min-height: 0; border-radius: 999px; box-shadow: none; }
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button p { font-size: 1rem !important; font-weight: 700; }
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button:hover { transform: translateY(-2px); }

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

/* videos: always shown whole (letterboxed if needed), never taller than the screen */
[data-testid="stVideo"] video { width: 100%; max-height: 75vh; object-fit: contain; background: #000; border-radius: 16px; }

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
def get_secret(name):
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.environ.get(name)


DB_URL = get_secret("SUPABASE_DB_URL")
SUPABASE_URL = (get_secret("SUPABASE_URL") or "").strip().rstrip("/")
SUPABASE_KEY = (get_secret("SUPABASE_KEY") or "").strip()

_missing = [n for n, v in (("SUPABASE_DB_URL", DB_URL), ("SUPABASE_URL", SUPABASE_URL), ("SUPABASE_KEY", SUPABASE_KEY)) if not v]
if _missing:
    st.error("This app isn't connected to Supabase yet. Missing in Secrets: " + ", ".join(_missing) +
             ". Open Manage app → ⋮ → Settings → Secrets, check the spelling and the straight quote marks, "
             "click Save, then reboot the app.")
    if len(_missing) == 3:
        st.caption("All three are missing, so the Secrets box may have a typing mistake somewhere (for example a curly quote mark "
                   "or a missing closing quote), which makes the whole box unreadable.")
    st.stop()


def _fix_dsn(url):
    """If the password has symbols like @ # / ?, they must be percent-encoded. Do it here so a pasted link still works."""
    m = re.match(r"^(postgres(?:ql)?://)([^:/@]+):(.*)@([^@]+)$", url.strip())
    if not m:
        return url.strip()
    scheme, user, password, rest = m.groups()
    return f"{scheme}{user}:{quote(unquote(password), safe='')}@{rest}"


@st.cache_resource
def get_pool():
    return ThreadedConnectionPool(1, 8, dsn=_fix_dsn(DB_URL), connect_timeout=10, keepalives=1, keepalives_idle=30)


def _to_pg(sql):
    """The SQL below is written with ? placeholders; Postgres wants %s."""
    sql = sql.replace("?", "%s")
    if re.match(r"\s*INSERT OR IGNORE INTO", sql, re.I):
        sql = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", sql, count=1, flags=re.I).rstrip().rstrip(";")
        sql += " ON CONFLICT DO NOTHING"
    return sql


def _execute(sql, params, fetch):
    t_start = time.perf_counter()
    try:
        return _execute_inner(sql, params, fetch)
    finally:
        try:  # shown to the admin only: how many database trips this page needed and how long they took
            st.session_state["_dbq"] = st.session_state.get("_dbq", 0) + 1
            st.session_state["_dbt"] = st.session_state.get("_dbt", 0.0) + (time.perf_counter() - t_start)
        except Exception:
            pass


def _execute_inner(sql, params, fetch):
    sql = _to_pg(sql)
    for attempt in (1, 2):
        pool = get_pool()
        conn = None
        for _ in range(20):  # all connections busy: wait a moment for one to free up
            try:
                conn = pool.getconn()
                break
            except psycopg2.pool.PoolError:
                time.sleep(0.25)
        if conn is None:
            raise RuntimeError("The database is busy, please try again.")
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql, params)
                result = cur.fetchall() if fetch == "all" else cur.fetchone() if fetch == "one" else None
            pool.putconn(conn)
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # the connection went stale (Supabase closes idle ones): drop it and try once more with a fresh pool
            try:
                pool.putconn(conn, close=True)
                pool.closeall()
            except Exception:
                pass
            get_pool.clear()
            if attempt == 2:
                raise
        except Exception:
            pool.putconn(conn)
            raise


def run(sql, params=(), fetch=None):
    """Run one SQL statement and return rows ('all'), one row ('one') or nothing."""
    result = _execute(sql, tuple(params), fetch)
    # names, pictures, friendships and follows are cached for a few seconds, so forget them whenever they change
    if re.match(r"\s*(INSERT|UPDATE|DELETE)\b.*\b(users|friendships|follows)\b", sql, re.I | re.S):
        st.cache_data.clear()
        st.session_state.pop("_ttl", None)
    return result


def ttl_cache(key, seconds, fn):
    """Remembers fn()'s answer for a few seconds in this person's session, so one click doesn't repeat the same
    database question many times (every question costs a trip to the database server)."""
    box = st.session_state.setdefault("_ttl", {})
    hit = box.get(key)
    if hit and time.time() - hit[0] < seconds:
        return hit[1]
    value = fn()
    box[key] = (time.time(), value)
    return value


@st.cache_data(ttl=20, show_spinner=False)
def _cached_query(sql, params, fetch):
    return _execute(sql, params, fetch)


def cached_run(sql, params=(), fetch="one"):
    """Like run(), for things read many times per page (names, pictures, friend status)."""
    return _cached_query(sql, tuple(params), fetch)


@st.cache_resource(show_spinner="Setting up the database...")
def init_db():
    tables = [
        "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL, display_name TEXT NOT NULL, avatar_path TEXT, theme TEXT, bio TEXT, notif_seen_at TEXT, last_seen TEXT)",
        "CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, author_username TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL, song TEXT)",
        'CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL, "position" INTEGER NOT NULL)',
        # comments are used for both posts and reels (post_id holds either id)
        "CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, author_username TEXT NOT NULL, comment_text TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS friendships (id TEXT PRIMARY KEY, requester TEXT NOT NULL, addressee TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, sender TEXT NOT NULL, receiver TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS reels (id TEXT PRIMARY KEY, author_username TEXT NOT NULL, video_path TEXT NOT NULL, caption TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS reel_likes (reel_id TEXT NOT NULL, username TEXT NOT NULL, PRIMARY KEY (reel_id, username))",
        "CREATE TABLE IF NOT EXISTS follows (follower TEXT NOT NULL, followee TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (follower, followee))",
        # each person's private conversation with Yuaan
        "CREATE TABLE IF NOT EXISTS ai_messages (id TEXT PRIMARY KEY, username TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)",
        # group chats
        "CREATE TABLE IF NOT EXISTS group_chats (id TEXT PRIMARY KEY, name TEXT NOT NULL, creator TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS group_members (group_id TEXT NOT NULL, username TEXT NOT NULL, PRIMARY KEY (group_id, username))",
        "CREATE TABLE IF NOT EXISTS group_messages (id TEXT PRIMARY KEY, group_id TEXT NOT NULL, sender TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL)",
        # likes on feed posts
        "CREATE TABLE IF NOT EXISTS post_likes (post_id TEXT NOT NULL, username TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (post_id, username))",
        # stories (disappear after 24 hours), saved posts, blocking and reports
        "CREATE TABLE IF NOT EXISTS stories (id TEXT PRIMARY KEY, author_username TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL, caption TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS post_saves (post_id TEXT NOT NULL, username TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (post_id, username))",
        "CREATE TABLE IF NOT EXISTS blocks (blocker TEXT NOT NULL, blocked TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (blocker, blocked))",
        "CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, reporter TEXT NOT NULL, reported TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL)",
        # alerts a person has cleared away
        "CREATE TABLE IF NOT EXISTS alert_dismissed (username TEXT NOT NULL, alert_key TEXT NOT NULL, PRIMARY KEY (username, alert_key))",
        # when each member last opened each group (drives read / unread and "seen by")
        "CREATE TABLE IF NOT EXISTS group_reads (group_id TEXT NOT NULL, username TEXT NOT NULL, last_read_at TEXT NOT NULL, PRIMARY KEY (group_id, username))",
    ]
    for sql in tables:
        run(sql)
    # columns added later (older databases don't have them yet)
    for sql in ("ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_seen_at TEXT",
                "ALTER TABLE posts ADD COLUMN IF NOT EXISTS song TEXT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TEXT"):
        try:
            run(sql)
        except Exception:
            pass
    # keeps pages quick
    for sql in ("CREATE INDEX IF NOT EXISTS idx_posts_created ON posts (created_at)",
                "CREATE INDEX IF NOT EXISTS idx_media_post ON media (post_id)",
                "CREATE INDEX IF NOT EXISTS idx_comments_post ON comments (post_id)",
                "CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages (sender, receiver)",
                "CREATE INDEX IF NOT EXISTS idx_messages_receiver ON messages (receiver, is_read)",
                "CREATE INDEX IF NOT EXISTS idx_post_likes_post ON post_likes (post_id)",
                "CREATE INDEX IF NOT EXISTS idx_stories_created ON stories (created_at)",
                "CREATE INDEX IF NOT EXISTS idx_group_members_user ON group_members (username)",
                "CREATE INDEX IF NOT EXISTS idx_group_messages_group ON group_messages (group_id, created_at)"):
        run(sql)
    # Supabase also exposes tables through a public web API. Turning row security on (with no rules)
    # shuts that door; this app talks to the database directly, so it is not affected.
    for name in ("users", "posts", "media", "comments", "sessions", "friendships", "messages", "reels", "reel_likes", "follows", "ai_messages",
                 "group_chats", "group_members", "group_messages", "group_reads", "post_likes", "alert_dismissed", "stories", "post_saves", "blocks", "reports"):
        run(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    return True


try:
    init_db()
except Exception as e:
    st.error("Couldn't connect to the database. Check that SUPABASE_DB_URL in Secrets is the Session pooler link "
             "with your real password in it (no square brackets), then reboot the app.")
    if isinstance(e, psycopg2.OperationalError):
        st.caption(str(e).strip()[:300])
    else:
        st.caption(f"({type(e).__name__})")
    st.stop()


# --- file storage (Supabase Storage). The database keeps only each file's name; the file itself lives in the bucket. ---
def _storage_headers(content_type=None):
    h = {"apikey": SUPABASE_KEY}
    if SUPABASE_KEY.startswith("eyJ"):  # older style keys are also sent as a bearer token
        h["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if content_type:
        h["Content-Type"] = content_type
    return h


def upload_file(data, folder, ext, content_type):
    """Saves bytes in the bucket and returns the file's name (key)."""
    ext = re.sub(r"[^.a-z0-9]", "", (ext or "").lower())[:8]
    key = f"{folder}/{uuid.uuid4().hex}{ext}"
    resp = requests.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}",
                         headers={**_storage_headers(content_type), "x-upsert": "true"}, data=data, timeout=180)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed ({resp.status_code})")
    return key


def file_url(key):
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{key}"


def delete_file(key):
    try:
        requests.delete(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}", headers=_storage_headers(), timeout=30)
    except Exception:
        pass


def download_file(key):
    resp = requests.get(file_url(key), timeout=60)
    resp.raise_for_status()
    return resp.content


# --- passwords: only a scrambled (hashed) version is stored ---
PBKDF_ROUNDS = 200_000


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF_ROUNDS)
    return f"pbkdf2${PBKDF_ROUNDS}${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    if stored.startswith("pbkdf2$"):
        try:
            _, rounds, salt, digest = stored.split("$")
            calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
            return hmac.compare_digest(calc.hex(), digest)
        except Exception:
            return False
    return hmac.compare_digest(stored.encode(), password.encode())  # an old plain-text password


# ==========================================
# 4. Helper functions
# ==========================================
def people_cache():
    return ttl_cache("people", 20, dict)   # {username: (display name, picture key)} filled in bulk by prefetch_people


def prefetch_people(names):
    """Looks up many people's names and pictures in ONE query, before a page draws their posts."""
    cache = people_cache()
    missing = [n for n in set(names) if n and n not in cache]
    if missing:
        marks = ",".join("?" * len(missing))
        for u, dn, ap in run(f"SELECT username, display_name, avatar_path FROM users WHERE username IN ({marks})", tuple(missing), "all"):
            cache[u] = (dn, ap)


def get_display_name(username):
    hit = people_cache().get(username)
    if hit:
        return hit[0]
    row = cached_run("SELECT display_name FROM users WHERE username = ?", (username,), "one")
    return row[0] if row else username


def presence_text(username):
    row = run("SELECT last_seen FROM users WHERE username = ?", (username,), "one")
    if not row or not row[0]:
        return "⚪ Offline"
    age = (utc_now() - datetime.fromisoformat(row[0])).total_seconds()
    return "🟢 Online" if age < 100 else f"⚪ Last seen {thai_time(row[0], '%d %b, %H:%M')}"


def get_bio(username):
    row = run("SELECT bio FROM users WHERE username = ?", (username,), "one")
    return (row[0] or "") if row else ""


def cb_save_bio():
    me = st.session_state.username
    run("UPDATE users SET bio = ? WHERE username = ?", ((st.session_state.get("bio_text") or "").strip()[:150], me))
    st.toast("Bio saved", icon="✍️")


EPOCH = "1970-01-01T00:00:00"


def get_seen_at(me):
    row = run("SELECT notif_seen_at FROM users WHERE username = ?", (me,), "one")
    return (row[0] if row and row[0] else EPOCH)


def alert_count(me):
    seen = get_seen_at(me)
    row = run('''SELECT
        (SELECT COUNT(*) FROM follows WHERE followee = ? AND created_at > ?)
      + (SELECT COUNT(*) FROM friendships WHERE addressee = ? AND status = 'pending' AND created_at > ?)
      + (SELECT COUNT(*) FROM post_likes l JOIN posts p ON p.id = l.post_id
         WHERE p.author_username = ? AND l.username <> ? AND l.created_at > ?)
      + (SELECT COUNT(*) FROM comments c JOIN posts p ON p.id = c.post_id
         WHERE p.author_username = ? AND c.author_username <> ? AND c.created_at > ?)
      + (SELECT COUNT(*) FROM messages WHERE receiver = ? AND is_read = 0 AND created_at > ? AND text NOT LIKE ?)
      + (SELECT COUNT(*) FROM group_messages m JOIN group_members gm ON gm.group_id = m.group_id AND gm.username = ?
         WHERE m.sender <> ? AND m.created_at > ? AND m.text NOT LIKE ?)''',
        (me, seen, me, seen, me, me, seen, me, me, seen, me, seen, CALL_TAG + "%", me, me, seen, CALL_TAG + "%"), "one")
    return row[0] if row else 0


def sidebar_counts(me):
    """Friend requests, unread messages and new alerts in ONE database question: (pending, unread, alerts)."""
    row = run('''WITH s AS (SELECT COALESCE(notif_seen_at, '1970-01-01T00:00:00') AS seen FROM users WHERE username = ?)
        SELECT
          (SELECT COUNT(*) FROM friendships WHERE addressee = ? AND status = 'pending'),
          (SELECT COUNT(*) FROM messages WHERE receiver = ? AND is_read = 0),
          (SELECT COUNT(*) FROM follows WHERE followee = ? AND created_at > (SELECT seen FROM s))
        + (SELECT COUNT(*) FROM friendships WHERE addressee = ? AND status = 'pending' AND created_at > (SELECT seen FROM s))
        + (SELECT COUNT(*) FROM post_likes l JOIN posts p ON p.id = l.post_id
           WHERE p.author_username = ? AND l.username <> ? AND l.created_at > (SELECT seen FROM s))
        + (SELECT COUNT(*) FROM comments c JOIN posts p ON p.id = c.post_id
           WHERE p.author_username = ? AND c.author_username <> ? AND c.created_at > (SELECT seen FROM s))
        + (SELECT COUNT(*) FROM messages WHERE receiver = ? AND is_read = 0 AND created_at > (SELECT seen FROM s) AND text NOT LIKE ?)
        + (SELECT COUNT(*) FROM group_messages m JOIN group_members gm ON gm.group_id = m.group_id AND gm.username = ?
           WHERE m.sender <> ? AND m.created_at > (SELECT seen FROM s) AND m.text NOT LIKE ?)''',
        (me, me, me, me, me, me, me, me, me, me, CALL_TAG + "%", me, me, CALL_TAG + "%"), "one")
    return (row[0], row[1], row[2]) if row else (0, 0, 0)


def alert_items(me, limit=40):
    """[(created_at, who, text, kind, ref)] newest first: followers, friend requests, likes, comments and unread messages."""
    items = []
    for who, at in run("SELECT follower, created_at FROM follows WHERE followee = ? ORDER BY created_at DESC LIMIT 30", (me,), "all"):
        items.append((at, who, "started following you", "person", None))
    for who, at in run("SELECT requester, created_at FROM friendships WHERE addressee = ? AND status = 'pending' "
                       "ORDER BY created_at DESC LIMIT 30", (me,), "all"):
        items.append((at, who, "sent you a friend request", "request", None))
    for who, at, note in run('''SELECT l.username, l.created_at, p.note FROM post_likes l JOIN posts p ON p.id = l.post_id
                             WHERE p.author_username = ? AND l.username <> ? ORDER BY l.created_at DESC LIMIT 30''', (me, me), "all"):
        items.append((at, who, f"liked your post “{note[:40]}”", "person", None))
    for who, at, note in run('''SELECT c.author_username, c.created_at, p.note FROM comments c JOIN posts p ON p.id = c.post_id
                             WHERE p.author_username = ? AND c.author_username <> ? ORDER BY c.created_at DESC LIMIT 30''', (me, me), "all"):
        items.append((at, who, f"commented on your post “{note[:40]}”", "person", None))
    for who, n, at in run('''SELECT sender, COUNT(*), MAX(created_at) FROM messages
                          WHERE receiver = ? AND is_read = 0 AND text NOT LIKE ? GROUP BY sender''', (me, CALL_TAG + "%"), "all"):
        items.append((at, who, f"sent you {n} unread message{'s' if n != 1 else ''}", "dm", who))
    for gid, name, n, at in run('''SELECT g.id, g.name, COUNT(*), MAX(m.created_at)
                                FROM group_messages m
                                JOIN group_members gm ON gm.group_id = m.group_id AND gm.username = ?
                                JOIN group_chats g ON g.id = m.group_id
                                LEFT JOIN group_reads r ON r.group_id = m.group_id AND r.username = ?
                                WHERE m.sender <> ? AND m.text NOT LIKE ? AND (r.last_read_at IS NULL OR m.created_at > r.last_read_at)
                                GROUP BY g.id, g.name''', (me, me, me, CALL_TAG + "%"), "all"):
        items.append((at, name, f"{n} unread message{'s' if n != 1 else ''} in this group", "group", gid))
    gone = {r[0] for r in run("SELECT alert_key FROM alert_dismissed WHERE username = ?", (me,), "all")}
    items = [it for it in items if alert_key(it) not in gone]
    items.sort(key=lambda x: x[0], reverse=True)
    return items[:limit]


def alert_key(item):
    """A short fingerprint of one alert. A new message changes it, so a dismissed chat alert returns when there is news."""
    at, who, text, kind, ref = item
    return hashlib.md5(f"{kind}|{who}|{at}|{text}".encode()).hexdigest()[:16]


def cb_dismiss_alert(me, key):
    run("INSERT OR IGNORE INTO alert_dismissed (username, alert_key) VALUES (?, ?)", (me, key))


def cb_dismiss_all_alerts(me):
    for item in alert_items(me, limit=200):
        run("INSERT OR IGNORE INTO alert_dismissed (username, alert_key) VALUES (?, ?)", (me, alert_key(item)))
    st.toast("Alerts cleared", icon="🧹")


def cb_open_group(gid):
    st.session_state.page = "chats"
    st.session_state.chat_mode = "👥 Groups"
    st.session_state.chat_group = gid


# --- stories ---
STORY_HOURS = 24


def story_cutoff():
    return (utc_now() - timedelta(hours=STORY_HOURS)).isoformat()


def cb_story_open(user):
    st.session_state.story_user = user
    st.session_state.story_i = 0


def cb_story_close():
    st.session_state.pop("story_user", None)
    st.session_state.pop("story_i", None)


def cb_story_step(delta, n):
    st.session_state.story_i = min(max(st.session_state.get("story_i", 0) + delta, 0), n - 1)


def cb_story_delete(story_id, me):
    row = run("SELECT file_path FROM stories WHERE id = ? AND author_username = ?", (story_id, me), "one")
    if row:
        run("DELETE FROM stories WHERE id = ? AND author_username = ?", (story_id, me))
        try:
            delete_file(row[0])
        except Exception:
            pass
    st.session_state.story_i = 0


def add_story_ui(me):
    with st.expander("➕ Add to your story (disappears after 24 hours)"):
        with st.form("story_form", clear_on_submit=True):
            sfile = st.file_uploader("Photo or video", type=["png", "jpg", "jpeg", "mp4", "mov"], key="story_file")
            scaption = st.text_input("Caption (optional)", max_chars=120)
            if st.form_submit_button("Share to story"):
                if not sfile:
                    st.warning("Choose a photo or video first.")
                else:
                    ext = os.path.splitext(sfile.name)[1].lower()
                    try:
                        if "video" in (sfile.type or "") or ext in (".mp4", ".mov"):
                            if sfile.size > MAX_VIDEO_MB * 1024 * 1024:
                                st.error(f"That video is bigger than {MAX_VIDEO_MB} MB.")
                                return
                            mime = "video/quicktime" if ext == ".mov" else (sfile.type or "video/mp4")
                            key = upload_file(sfile.getvalue(), "stories", ext or ".mp4", mime)
                        else:
                            mime = "image/jpeg"
                            key = upload_file(prepare_photo(sfile.getvalue()), "stories", ".jpg", mime)
                        run("INSERT INTO stories (id, author_username, file_path, file_type, caption, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (str(uuid.uuid4()), me, key, mime, scaption.strip(), utc_now().isoformat()))
                        # tidy up my own stories that have expired (their files too)
                        for sid, fp in run("SELECT id, file_path FROM stories WHERE author_username = ? AND created_at <= ?",
                                           (me, story_cutoff()), "all"):
                            run("DELETE FROM stories WHERE id = ?", (sid,))
                            try:
                                delete_file(fp)
                            except Exception:
                                pass
                        st.rerun()
                    except (RuntimeError, requests.RequestException):
                        st.error("The story couldn't be uploaded. Please try again.")


def stories_strip(me, circle):
    people_ids = list(set(circle) | {me})
    hidden = blocked_set(me)
    marks = ",".join("?" * len(people_ids))
    rows = run(f"SELECT author_username, MAX(created_at) FROM stories WHERE created_at > ? AND author_username IN ({marks}) "
               "GROUP BY author_username ORDER BY MAX(created_at) DESC", (story_cutoff(), *people_ids), "all")
    rows = [r for r in rows if r[0] not in hidden][:8]
    if rows:
        prefetch_people([r[0] for r in rows])
        st.caption("📖 Stories")
        cols = st.columns(min(4, len(rows)))
        for i, (u, _) in enumerate(rows):
            label = "🟣 Your story" if u == me else f"🟣 {get_display_name(u)}"
            cols[i % len(cols)].button(label[:18], key=f"story_btn_{u}", on_click=cb_story_open, args=(u,), use_container_width=True)


def story_viewer(me):
    user = st.session_state.get("story_user")
    if not user:
        return
    if user != me and user in blocked_set(me):
        cb_story_close()
        return
    items = run("SELECT id, file_path, file_type, caption, created_at FROM stories WHERE author_username = ? AND created_at > ? "
                "ORDER BY created_at ASC", (user, story_cutoff()), "all")
    if not items:
        cb_story_close()
        return
    i = min(max(st.session_state.get("story_i", 0), 0), len(items) - 1)
    sid, fp, ftype, cap, at = items[i]
    with st.container(border=True):
        st.markdown(person_html(user, size=40, subtitle=f"🕒 {thai_time(at, '%d %b, %H:%M')} · {i + 1}/{len(items)}"), unsafe_allow_html=True)
        if (ftype or "").startswith("video"):
            st.video(file_url(fp))
        else:
            st.image(file_url(fp), use_container_width=True)
        if cap:
            st.write(cap)
        b1, b2, b3, b4 = st.columns(4)
        b1.button("◀", key="story_prev", on_click=cb_story_step, args=(-1, len(items)), use_container_width=True, disabled=(i == 0))
        b2.button("▶", key="story_next", on_click=cb_story_step, args=(1, len(items)), use_container_width=True, disabled=(i == len(items) - 1))
        b3.button("✖ Close", key="story_close", on_click=cb_story_close, use_container_width=True)
        if user == me:
            b4.button("🗑", key="story_del", on_click=cb_story_delete, args=(sid, me), use_container_width=True)


def cb_open_alerts(me):
    st.session_state.pop("_ttl", None)
    st.session_state.alerts_prev_seen = get_seen_at(me)
    run("UPDATE users SET notif_seen_at = ? WHERE username = ?", (utc_now().isoformat(), me))
    st.session_state.page = "alerts"


def get_theme_value(username):
    if not username:
        return "Pop"
    row = ttl_cache(f"theme_{username}", 30, lambda: run("SELECT theme FROM users WHERE username = ?", (username,), "one"))
    return row[0] if row and row[0] else "Pop"


# --- login sessions (keeps you logged in after refresh) ---
def create_session(username):
    token = uuid.uuid4().hex + uuid.uuid4().hex
    expires_at = (utc_now() + timedelta(days=SESSION_DAYS)).isoformat()
    run("DELETE FROM sessions WHERE expires_at < ?", (utc_now().isoformat(),))
    run("INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)", (token, username, expires_at))
    return token


def get_session_user(token):
    row = run("SELECT username FROM sessions WHERE token = ? AND expires_at > ?", (token, utc_now().isoformat()), "one")
    return row[0] if row else None


def delete_session(token):
    run("DELETE FROM sessions WHERE token = ?", (token,))


# --- profile pictures ---
def get_avatar_path(username):
    """Web address of someone's profile picture, or None if they haven't set one."""
    hit = people_cache().get(username)
    if hit:
        return file_url(hit[1]) if hit[1] else None
    row = cached_run("SELECT avatar_path FROM users WHERE username = ?", (username,), "one")
    return file_url(row[0]) if row and row[0] else None


def avatar_html(username, size=40):
    """Round profile picture with a gradient ring; without a picture, a coloured circle with the first letter."""
    inner = size - 10  # room for the gradient ring (3px) and a gap (2px) on each side
    url = get_avatar_path(username)
    acc = T["accents"]
    if url:
        face = (f'<img src="{url}" '
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


def prepare_photo(data, side=1600, quality=85):
    """Upright, web-sized JPEG of a photo (turns sideways phone photos the right way up)."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def cb_rotate_photo(key):
    """Turns a photo a quarter-turn clockwise (used by the Rotate button on your own posts)."""
    try:
        img = Image.open(io.BytesIO(download_file(key))).convert("RGB").rotate(-90, expand=True)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        new_key = upload_file(buf.getvalue(), "posts", ".jpg", "image/jpeg")  # a new name, so no one sees the old cached picture
        run("UPDATE media SET file_path = ? WHERE file_path = ?", (new_key, key))
        delete_file(key)
    except Exception:
        st.toast("Couldn't rotate that photo", icon="⚠️")


def show_image(key):
    """Portrait photos stay portrait, landscape stay landscape. Nothing is cropped or stretched."""
    st.markdown(f'<img src="{file_url(key)}" style="display:block;margin:6px auto;max-width:100%;'
                f'max-height:75vh;width:auto;height:auto;border-radius:16px;">', unsafe_allow_html=True)


def show_media(rows, can_edit=False, key_prefix=""):
    """rows = [(file_key, file_type), ...]. One photo: shown whole. Several: Facebook-style grid with +N on the last tile."""
    images = [p for p, t in rows if "video" not in t]
    videos = [p for p, t in rows if "video" in t]

    def rotate_button(i, path):
        if can_edit:
            st.button("🔄 Rotate", key=f"{key_prefix}_rot_{i}", on_click=cb_rotate_photo, args=(path,))

    if len(images) == 1:
        show_image(images[0])
        rotate_button(0, images[0])
    elif len(images) > 1:
        n = len(images)
        cells = []
        for i, path in enumerate(images[:4]):
            if n == 3 and i == 0:
                ratio, span = "16 / 10", "grid-column:1 / -1;"
            elif n == 2:
                ratio, span = "3 / 4", ""
            else:
                ratio, span = "1 / 1", ""
            extra = ""
            if i == 3 and n > 4:
                extra = ('<div style="position:absolute;inset:0;background:rgba(0,0,0,.55);color:#fff;display:flex;'
                         f'align-items:center;justify-content:center;font-size:2.4rem;font-weight:800;">+{n - 4}</div>')
            cells.append(f'<div style="position:relative;aspect-ratio:{ratio};{span}overflow:hidden;">'
                         f'<img src="{file_url(path)}" style="width:100%;height:100%;object-fit:cover;display:block;">{extra}</div>')
        st.markdown('<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;border-radius:16px;overflow:hidden;margin:6px 0;">'
                    + "".join(cells) + "</div>", unsafe_allow_html=True)
        with st.expander(f"📷 See all {n} photos"):
            for i, path in enumerate(images):
                show_image(path)
                rotate_button(i, path)

    for path in videos:
        st.video(file_url(path))


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
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    new_key = upload_file(buf.getvalue(), "avatars", ".jpg", "image/jpeg")
    row = run("SELECT avatar_path FROM users WHERE username = ?", (username,), "one")
    old = row[0] if row else None
    run("UPDATE users SET avatar_path = ? WHERE username = ?", (new_key, username))
    if old:
        delete_file(old)


# --- friends ---
def my_relations(me):
    """({other person: (who asked, status)}, {people I follow}) in two queries, remembered for a few seconds."""
    def load():
        friends = {}
        for req, addr, status in run("SELECT requester, addressee, status FROM friendships WHERE requester = ? OR addressee = ?",
                                     (me, me), "all"):
            friends[addr if req == me else req] = (req, status)
        following = {r[0] for r in run("SELECT followee FROM follows WHERE follower = ?", (me,), "all")}
        return friends, following
    return ttl_cache(f"rel_{me}", 8, load)


def friendship_status(me, other):
    """Returns 'friends', 'sent' (I asked them), 'received' (they asked me) or 'none'."""
    row = my_relations(me)[0].get(other)
    if not row:
        return "none"
    if row[1] == "accepted":
        return "friends"
    return "sent" if row[0] == me else "received"


def get_friends(me):
    if me == st.session_state.get("username"):   # my own friends: already loaded for this page
        people = [o for o, (_, status) in my_relations(me)[0].items() if status == "accepted"]
    else:
        rows = run('''SELECT CASE WHEN requester = ? THEN addressee ELSE requester END
                      FROM friendships WHERE status = 'accepted' AND (requester = ? OR addressee = ?)''',
                   (me, me, me), "all")
        people = [r[0] for r in rows]
    return sorted(people, key=lambda u: get_display_name(u).lower())


def get_incoming_requests(me):
    rows = run("SELECT requester FROM friendships WHERE addressee = ? AND status = 'pending' ORDER BY created_at DESC", (me,), "all")
    return [r[0] for r in rows]


def is_admin(username):
    extra = {u.strip() for u in (get_secret("ADMIN_USERS") or "").split(",") if u.strip()}
    return username in ADMINS or username in extra


def cb_speed_test():
    """Times 5 tiny database questions: the answer is the round trip to the database server."""
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        _execute("SELECT 1", (), "one")
        times.append((time.perf_counter() - t0) * 1000)
    st.session_state["speed_result"] = (min(times), sum(times) / len(times), max(times))


def cb_resolve_report(report_id, me):
    if is_admin(me):
        run("DELETE FROM reports WHERE id = ?", (report_id,))
        st.session_state.pop("_ttl", None)
        st.toast("Report cleared", icon="✅")


def block_sets(me):
    """(people I blocked, people who blocked me) from one database question."""
    def load():
        mine, theirs = set(), set()
        for a, b in run("SELECT blocker, blocked FROM blocks WHERE blocker = ? OR blocked = ?", (me, me), "all"):
            if a == me:
                mine.add(b)
            else:
                theirs.add(a)
        return mine, theirs
    return ttl_cache(f"blk_{me}", 15, load)


def blocked_set(me):
    """Everyone I blocked plus everyone who blocked me (neither side sees the other)."""
    mine, theirs = block_sets(me)
    return mine | theirs


def cb_block_user(me, other):
    if me == other:
        return
    run("INSERT OR IGNORE INTO blocks (blocker, blocked, created_at) VALUES (?, ?, ?)", (me, other, utc_now().isoformat()))
    run("DELETE FROM friendships WHERE (requester = ? AND addressee = ?) OR (requester = ? AND addressee = ?)", (me, other, other, me))
    run("DELETE FROM follows WHERE (follower = ? AND followee = ?) OR (follower = ? AND followee = ?)", (me, other, other, me))
    st.session_state.pop("_ttl", None)
    st.toast("Blocked. You won't see each other's posts.", icon="🚫")


def cb_unblock_user(me, other):
    run("DELETE FROM blocks WHERE blocker = ? AND blocked = ?", (me, other))
    st.session_state.pop("_ttl", None)
    st.toast("Unblocked", icon="✅")


def cb_report_user(me, other):
    reason = (st.session_state.get(f"report_reason_{other}") or "").strip()[:300]
    run("INSERT INTO reports (id, reporter, reported, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), me, other, reason, utc_now().isoformat()))
    st.session_state[f"report_reason_{other}"] = ""
    st.toast("Thanks, your report was sent.", icon="🚩")


def cb_send_request(me, other):
    if other in blocked_set(me):
        st.toast("You can't do that with this person.", icon="🚫")
        return
    if friendship_status(me, other) == "none":
        run("INSERT INTO friendships (id, requester, addressee, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (str(uuid.uuid4()), me, other, utc_now().isoformat()))


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


# --- followers (one-way: the other person doesn't have to accept) ---
def is_following(me, other):
    return other in my_relations(me)[1]


def follower_count(user):
    return run("SELECT COUNT(*) FROM follows WHERE followee = ?", (user,), "one")[0]


def following_count(user):
    return run("SELECT COUNT(*) FROM follows WHERE follower = ?", (user,), "one")[0]


def get_followers(user):
    return [r[0] for r in run("SELECT follower FROM follows WHERE followee = ? ORDER BY created_at DESC", (user,), "all")]


def get_following(user):
    return [r[0] for r in run("SELECT followee FROM follows WHERE follower = ? ORDER BY created_at DESC", (user,), "all")]


def cb_toggle_follow(me, other):
    if me == other or other in blocked_set(me):
        return
    if run("SELECT 1 FROM follows WHERE follower = ? AND followee = ?", (me, other), "one"):
        run("DELETE FROM follows WHERE follower = ? AND followee = ?", (me, other))
    else:
        run("INSERT OR IGNORE INTO follows (follower, followee, created_at) VALUES (?, ?, ?)",
            (me, other, utc_now().isoformat()))


def follow_button(container, me, other, key):
    """➕ Follow / ✓ Following next to someone's post or reel."""
    if other == me:
        return
    if is_following(me, other):
        container.button("✓ Following", key=key, on_click=cb_toggle_follow, args=(me, other), use_container_width=True)
    else:
        container.button("➕ Follow", key=key, type="primary", on_click=cb_toggle_follow, args=(me, other), use_container_width=True)


# --- delete your own posts, and profile pages ---
def cb_delete_post(post_id, me):
    row = run("SELECT author_username FROM posts WHERE id = ?", (post_id,), "one")
    if not row or row[0] != me:  # only the author can delete
        return
    for (path,) in run("SELECT file_path FROM media WHERE post_id = ?", (post_id,), "all"):
        delete_file(path)
    run("DELETE FROM media WHERE post_id = ?", (post_id,))
    run("DELETE FROM comments WHERE post_id = ?", (post_id,))
    run("DELETE FROM posts WHERE id = ?", (post_id,))
    st.toast("Post deleted", icon="🗑️")


def cb_view_profile(username):
    st.session_state.page = "profile"
    st.session_state.profile_user = username


# --- songs on posts ---
SPOTIFY_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist|episode)/([A-Za-z0-9]{10,30})")
YOUTUBE_RE = re.compile(r"(?:youtube\.com/watch\?(?:[^ ]*&)?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})")
SAFE_HOSTS = (".apple.com", ".mzstatic.com")


def song_from_link(text):
    """A Spotify or YouTube link -> a song dict, or None."""
    text = (text or "").strip()
    m = SPOTIFY_RE.search(text)
    if m:
        return {"t": "spotify", "k": m.group(1), "id": m.group(2)}
    m = YOUTUBE_RE.search(text)
    if m:
        return {"t": "youtube", "id": m.group(1)}
    return None


def search_songs(term):
    """Free Apple/iTunes song search (no key needed). Returns up to 6 songs with a 30-second preview."""
    try:
        r = requests.get("https://itunes.apple.com/search", timeout=8,
                         params={"term": term, "media": "music", "entity": "song", "limit": 6})
        out = []
        for x in r.json().get("results", []):
            if x.get("previewUrl") and x.get("trackName"):
                out.append({"t": "preview", "title": x["trackName"][:80], "artist": (x.get("artistName") or "")[:80],
                            "art": x.get("artworkUrl100", ""), "url": x["previewUrl"]})
        return out
    except Exception:
        return None


def _safe_url(u):
    m = re.match(r"https://([^/]+)/", u or "")
    return bool(m) and any(m.group(1).endswith(h) for h in SAFE_HOSTS)


def parse_song(raw):
    """Reads a stored song and checks it, so nothing odd is ever shown. Returns a dict or None."""
    try:
        sg = json.loads(raw) if raw else None
    except Exception:
        return None
    if not isinstance(sg, dict):
        return None
    t = sg.get("t")
    if t == "spotify" and sg.get("k") in ("track", "album", "playlist", "episode") and re.fullmatch(r"[A-Za-z0-9]{10,30}", str(sg.get("id", ""))):
        return sg
    if t == "youtube" and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(sg.get("id", ""))):
        return sg
    if t == "preview" and _safe_url(sg.get("url")) and str(sg.get("title", "")):
        if sg.get("art") and not _safe_url(sg["art"]):
            sg["art"] = ""
        return sg
    return None


def render_song(raw):
    sg = parse_song(raw)
    if not sg:
        return
    if sg["t"] == "spotify":
        components.iframe(f"https://open.spotify.com/embed/{sg['k']}/{sg['id']}",
                          height=152 if sg["k"] in ("track", "episode") else 352)
    elif sg["t"] == "youtube":
        st.video(f"https://www.youtube.com/watch?v={sg['id']}")
    else:
        c1, c2 = st.columns([1, 5])
        if sg.get("art"):
            c1.image(sg["art"], width=56)
        c2.markdown(f"🎵 **{html.escape(sg['title'])}**  \n{html.escape(sg.get('artist', ''))}", unsafe_allow_html=True)
        st.audio(sg["url"])


def cb_song_search():
    term = (st.session_state.get("song_q") or "").strip()
    if term:
        st.session_state.song_results = search_songs(term) or []
        st.session_state.song_searched = True


def cb_song_pick(i):
    results = st.session_state.get("song_results", [])
    if 0 <= i < len(results):
        st.session_state.post_song = json.dumps(results[i])
        st.session_state.song_results = []


def cb_song_link():
    sg = song_from_link(st.session_state.get("song_link"))
    if sg:
        st.session_state.post_song = json.dumps(sg)
        st.session_state.song_link = ""
    else:
        st.toast("That isn't a Spotify or YouTube link.", icon="⚠️")


def cb_song_remove():
    st.session_state.pop("post_song", None)


def share_targets(me):
    """Friends and groups a post can be sent to: [(code, label)]; codes are 'u:username' or 'g:group_id'."""
    def load():
        out = [(f"u:{u}", f"{get_display_name(u)} (@{u})") for u in get_friends(me)]
        out += [(f"g:{gid}", f"👥 {name}") for gid, name in my_groups(me)]
        return out
    return ttl_cache(f"share_{me}", 20, load)


def cb_share_post(post_id, prefix, me):
    code = st.session_state.get(f"{prefix}_shto_{post_id}")
    targets = dict(share_targets(me))   # checked again here, so only friends and my own groups work
    if code not in targets:
        st.toast("Pick someone to send it to.", icon="⚠️")
        return
    kind, ref = code.split(":", 1)
    if kind == "u":
        send_message(me, ref, POST_TAG + post_id)
    else:
        send_group_message(me, ref, POST_TAG + post_id)
    st.toast(f"Shared with {targets[code].replace('👥 ', '')}", icon="📤")


def load_likes(post_ids, me):
    """Likes, saves and songs for many posts in ONE question; post_actions and the post cards read them from here."""
    info = {pid: (0, False) for pid in post_ids}
    songs, saved = {}, set()
    if post_ids:
        marks = ",".join("?" * len(post_ids))
        for pid, n, mine, sv, song in run(f"""SELECT p.id,
                (SELECT COUNT(*) FROM post_likes l WHERE l.post_id = p.id),
                (SELECT COUNT(*) FROM post_likes l2 WHERE l2.post_id = p.id AND l2.username = ?),
                (SELECT COUNT(*) FROM post_saves sv WHERE sv.post_id = p.id AND sv.username = ?),
                p.song FROM posts p WHERE p.id IN ({marks})""", (me, me, *post_ids), "all"):
            info[pid] = (n, bool(mine))
            if sv:
                saved.add(pid)
            if song:
                songs[pid] = song
    st.session_state["_likes"] = info
    st.session_state["_songs"] = songs
    st.session_state["_saved"] = saved
    st.session_state["_share_targets"] = share_targets(me) if post_ids else []


def cb_toggle_save(post_id, me):
    if run("SELECT 1 FROM post_saves WHERE post_id = ? AND username = ?", (post_id, me), "one"):
        run("DELETE FROM post_saves WHERE post_id = ? AND username = ?", (post_id, me))
        st.toast("Removed from saved", icon="🔖")
    else:
        run("INSERT OR IGNORE INTO post_saves (post_id, username, created_at) VALUES (?, ?, ?)", (post_id, me, utc_now().isoformat()))
        st.toast("Saved. Find it on your profile under 🔖 Saved.", icon="🔖")


def cb_toggle_post_like(post_id, me):
    if run("SELECT 1 FROM post_likes WHERE post_id = ? AND username = ?", (post_id, me), "one"):
        run("DELETE FROM post_likes WHERE post_id = ? AND username = ?", (post_id, me))
    else:
        run("INSERT OR IGNORE INTO post_likes (post_id, username, created_at) VALUES (?, ?, ?)",
            (post_id, me, utc_now().isoformat()))


def post_actions(post_id, author, me, prefix, show_profile=True):
    """Like, save and share; then Profile and (on your own posts) Delete."""
    count, mine = st.session_state.get("_likes", {}).get(post_id, (0, False))
    is_saved = post_id in st.session_state.get("_saved", set())
    c1, c2, c3 = st.columns(3)
    c1.button(f"{'❤️' if mine else '🤍'} {count}", key=f"{prefix}_like_{post_id}", on_click=cb_toggle_post_like,
              args=(post_id, me), use_container_width=True)
    c2.button("🔖 Saved" if is_saved else "🔖 Save", key=f"{prefix}_save_{post_id}", on_click=cb_toggle_save,
              args=(post_id, me), use_container_width=True, type="primary" if is_saved else "secondary")
    with c3.popover("📤 Share", use_container_width=True):
        targets = st.session_state.get("_share_targets", [])
        if not targets:
            st.caption("Add a friend first, then you can share posts with them.")
        else:
            st.selectbox("Send to", [t[0] for t in targets], format_func=dict(targets).get,
                         key=f"{prefix}_shto_{post_id}")
            st.button("Send", key=f"{prefix}_shsend_{post_id}", on_click=cb_share_post, args=(post_id, prefix, me))
    if show_profile or author == me:
        d1, d2 = st.columns(2)
        if show_profile:
            d1.button("👤 Profile", key=f"{prefix}_prof_{post_id}", on_click=cb_view_profile, args=(author,), use_container_width=True)
        if author == me:
            d2.button("🗑️ Delete", key=f"{prefix}_del_{post_id}", on_click=cb_delete_post, args=(post_id, me), use_container_width=True)


def cb_change_password():
    me = st.session_state.username
    cur, new, new2 = (st.session_state.get(k) or "" for k in ("pw_cur", "pw_new", "pw_new2"))
    row = run("SELECT password FROM users WHERE username = ?", (me,), "one")
    if not row or not check_password(cur, row[0]):
        st.toast("Your current password isn't right.", icon="⚠️")
    elif len(new) < 6:
        st.toast("The new password needs at least 6 characters.", icon="⚠️")
    elif new != new2:
        st.toast("The two new passwords don't match.", icon="⚠️")
    else:
        run("UPDATE users SET password = ? WHERE username = ?", (hash_password(new), me))
        for k in ("pw_cur", "pw_new", "pw_new2"):
            st.session_state[k] = ""
        st.toast("Password changed.", icon="🔑")


def cb_sign_out():
    """Runs before the page re-renders, so it may safely reset widget values like 'page'."""
    delete_session(st.session_state.get("token", ""))
    st.query_params.clear()
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.token = ""
    st.session_state.page = "feed"
    for key in ("chat_with", "bio_text", "theme_choice", "theme_bg", "theme_main", "theme_second", "reel_idx", "profile_user"):
        st.session_state.pop(key, None)


def cb_go_page(page):
    st.session_state.page = page


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


CALL_TAG = "[[CALL]]"
POST_TAG = "[[POST]]"   # a shared post inside a chat message
REEL_TAG = "[[REEL]]"   # a shared reel inside a chat message


def render_shared_reel(reel_id, key):
    row = run("SELECT author_username, video_path, caption FROM reels WHERE id = ?", (reel_id,), "one")
    with st.container(border=True):
        if not row:
            st.caption("📤 This reel is no longer available.")
            return
        author, vpath, cap = row
        st.caption(f"📤 Shared reel by {get_display_name(author)}")
        st.video(file_url(vpath))
        if cap:
            st.write(cap if len(cap) <= 160 else cap[:160] + "…")
        st.button("👤 View profile", key=f"sr_{key}", on_click=cb_view_profile, args=(author,))


def render_shared_post(post_id, key):
    """Small preview card for a post somebody shared in a chat."""
    row = run("SELECT note, author_username FROM posts WHERE id = ?", (post_id,), "one")
    with st.container(border=True):
        if not row:
            st.caption("📤 This post is no longer available.")
            return
        note, author = row
        st.caption(f"📤 Shared post by {get_display_name(author)}")
        if note:
            st.write(note if len(note) <= 220 else note[:220] + "…")
        first = run('SELECT file_path, file_type FROM media WHERE post_id = ? ORDER BY "position" LIMIT 1', (post_id,), "one")
        if first and (first[1] or "").startswith("image"):
            st.image(file_url(first[0]), use_container_width=True)
        elif first:
            st.caption("🎬 Has a video")
        st.button("👤 View profile", key=f"sp_{key}", on_click=cb_view_profile, args=(author,))


def cb_unsend(table, msg_id, me):
    """Removes one of my own messages (or call invites) completely: no 'deleted' note is left behind."""
    if table in ("messages", "group_messages"):
        run(f"DELETE FROM {table} WHERE id = ? AND sender = ?", (msg_id, me))


MEET_NEW_URL = "https://meet.google.com/new"


def new_call_url():
    """One-tap call: a fresh private Jitsi room. meet.jit.si makes guests wait for a logged-in moderator,
    so the default is a community server without that rule. Change it with JITSI_SERVER in Streamlit Secrets."""
    server = (get_secret("JITSI_SERVER") or "meet.ffmuc.net").strip().replace("https://", "").strip("/")
    return (f"https://{server}/YuaanPost{uuid.uuid4().hex}"
            "#config.startWithVideoMuted=true&config.prejoinPageEnabled=false&config.disableDeepLinking=true")


def clean_meet_link(text):
    """Accepts a pasted Google Meet link (https://meet.google.com/abc-defg-hij) and returns it, else None."""
    m = re.search(r"(?:https?://)?(meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3})\b", (text or "").strip().lower())
    return "https://" + m.group(1) if m else None


def start_call(me, other, link):
    send_message(me, other, CALL_TAG + link)


def send_message(me, other, text):
    if other in blocked_set(me):
        return
    run("INSERT INTO messages (id, sender, receiver, text, created_at, is_read) VALUES (?, ?, ?, ?, ?, 0)",
        (str(uuid.uuid4()), me, other, text, utc_now().isoformat()))


@st.fragment(run_every=3)
def render_messages(me, other):
    """Re-runs every 3 seconds on its own so new messages appear without a full refresh."""
    run("UPDATE messages SET is_read = 1 WHERE sender = ? AND receiver = ? AND is_read = 0", (other, me))
    rows = run('''SELECT sender, text, created_at, id FROM messages
                  WHERE (sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?)
                  ORDER BY created_at DESC LIMIT 60''', (me, other, other, me), "all")
    rows.reverse()
    box = st.container(height=420)
    with box:
        if not rows:
            st.caption("No messages yet. Say hi! 👋")
        for sender, text, created_at, msg_id in rows:
            avatar = get_avatar_path(sender) or "👤"
            role = "user" if sender == me else "assistant"
            with st.chat_message(role, avatar=avatar):
                time_str = thai_time(created_at, "%d %b, %H:%M")
                st.caption(f"{get_display_name(sender)} · {time_str}")
                if text.startswith(CALL_TAG):
                    age_min = (utc_now() - datetime.fromisoformat(created_at)).total_seconds() / 60
                    if age_min <= 30:
                        who = "You started" if sender == me else f"{get_display_name(sender)} is starting"
                        st.write(f"📞 {who} a voice call")
                        st.link_button("📞 Join call", text[len(CALL_TAG):], key=f"join_{sender}_{created_at}")
                    else:
                        st.write("📞 Voice call (ended)")
                elif text.startswith(REEL_TAG):
                    render_shared_reel(text[len(REEL_TAG):], f"dm_{msg_id}")
                elif text.startswith(POST_TAG):
                    render_shared_post(text[len(POST_TAG):], f"dm_{msg_id}")
                else:
                    st.write(text)
                if sender == me:
                    st.button("🗑 Unsend", key=f"unsend_dm_{msg_id}", on_click=cb_unsend, args=("messages", msg_id, me))


# --- group chats ---
def my_groups(me):
    return run('''SELECT g.id, g.name FROM group_chats g JOIN group_members m ON m.group_id = g.id
                  WHERE m.username = ? ORDER BY g.created_at DESC''', (me,), "all")


def group_members(gid):
    return [r[0] for r in run("SELECT username FROM group_members WHERE group_id = ? ORDER BY username", (gid,), "all")]


def send_group_message(me, gid, text):
    if me in group_members(gid):
        run("INSERT INTO group_messages (id, group_id, sender, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), gid, me, text, utc_now().isoformat()))


def start_group_call(me, gid, link):
    send_group_message(me, gid, CALL_TAG + link)


def cb_send_meet_link(key, send):
    """Runs before the page redraws, so it may safely clear the text box."""
    link = clean_meet_link(st.session_state.get(f"{key}_link"))
    if link:
        send(link)
        st.session_state[f"{key}_link"] = ""
        st.toast("Call sent. Now tap 'Join call' in the chat.", icon="📞")
    else:
        st.session_state[f"{key}_err"] = True


def call_ui(key, send):
    """Instant call, or two steps: open Google Meet to make a meeting, then paste its link so friends get a Join button."""
    if st.button("⚡ Instant call (one tap, nobody needs an account)", key=f"{key}_instant", use_container_width=True):
        send(new_call_url())
        st.toast("Calling... tap 'Join call' in the chat.", icon="📞")
        st.rerun()
    st.caption("Or use Google Meet:")
    st.link_button("1️⃣ Open Google Meet (makes a new meeting)", MEET_NEW_URL, use_container_width=True)
    link_in = st.text_input("2️⃣ Paste the meeting link here", key=f"{key}_link", placeholder="https://meet.google.com/abc-defg-hij")
    st.button("📞 Send call to chat", key=f"{key}_send", on_click=cb_send_meet_link, args=(key, send))
    if st.session_state.pop(f"{key}_err", False):
        st.warning("That doesn't look like a Google Meet link. It should look like meet.google.com/abc-defg-hij")


def cb_create_group(me):
    name = (st.session_state.get("new_group_name") or "").strip()[:40]
    picked = [u for u in st.session_state.get("new_group_members", []) if u in get_friends(me)]
    if not name:
        st.toast("Give the group a name first.", icon="⚠️")
        return
    if not picked:
        st.toast("Pick at least one friend.", icon="⚠️")
        return
    gid = str(uuid.uuid4())
    run("INSERT INTO group_chats (id, name, creator, created_at) VALUES (?, ?, ?, ?)",
        (gid, name, me, utc_now().isoformat()))
    for u in [me] + picked:
        run("INSERT OR IGNORE INTO group_members (group_id, username) VALUES (?, ?)", (gid, u))
    st.session_state.pop("_ttl", None)
    st.session_state.new_group_name = ""
    st.session_state.new_group_members = []
    st.session_state.chat_group = gid
    st.toast(f"Group “{name}” created", icon="👥")


def cb_add_group_members(me, gid):
    if me not in group_members(gid):
        return
    for u in st.session_state.get(f"add_members_{gid}", []):
        if u in get_friends(me):
            run("INSERT OR IGNORE INTO group_members (group_id, username) VALUES (?, ?)", (gid, u))
    st.session_state[f"add_members_{gid}"] = []
    st.toast("Added to the group", icon="➕")


def cb_leave_group(me, gid):
    run("DELETE FROM group_members WHERE group_id = ? AND username = ?", (gid, me))
    run("DELETE FROM group_reads WHERE group_id = ? AND username = ?", (gid, me))
    if not group_members(gid):   # last person left: remove the group
        run("DELETE FROM group_messages WHERE group_id = ?", (gid,))
        run("DELETE FROM group_chats WHERE id = ?", (gid,))
    st.session_state.pop("chat_group", None)
    st.session_state.pop("_ttl", None)
    st.toast("You left the group", icon="👋")


def group_unread_counts(me):
    """{group_id: number of messages from others that I haven't opened yet}"""
    rows = run('''SELECT m.group_id, COUNT(*) FROM group_messages m
                  JOIN group_members gm ON gm.group_id = m.group_id AND gm.username = ?
                  LEFT JOIN group_reads r ON r.group_id = m.group_id AND r.username = ?
                  WHERE m.sender <> ? AND (r.last_read_at IS NULL OR m.created_at > r.last_read_at)
                  GROUP BY m.group_id''', (me, me, me), "all")
    return dict(rows)


def mark_group_read(me, gid):
    run('''INSERT INTO group_reads (group_id, username, last_read_at) VALUES (?, ?, ?)
           ON CONFLICT (group_id, username) DO UPDATE SET last_read_at = excluded.last_read_at''',
        (gid, me, utc_now().isoformat()))


@st.fragment(run_every=3)
def render_group_messages(me, gid):
    mark_group_read(me, gid)   # opening the chat counts as reading everything in it
    members = group_members(gid)
    seen_at = dict(run("SELECT username, last_read_at FROM group_reads WHERE group_id = ?", (gid,), "all"))
    rows = run('''SELECT sender, text, created_at, id FROM group_messages WHERE group_id = ?
                  ORDER BY created_at DESC LIMIT 80''', (gid,), "all")
    rows.reverse()
    with st.container(height=420):
        if not rows:
            st.caption("No messages yet. Say hi to the group! 👋")
        for sender, text, created_at, msg_id in rows:
            avatar = get_avatar_path(sender) or "👤"
            readers = [u for u in members if u != sender and seen_at.get(u, "") >= created_at]
            others = len(members) - 1
            with st.chat_message("user" if sender == me else "assistant", avatar=avatar):
                st.caption(f"{get_display_name(sender)} · {thai_time(created_at, '%d %b, %H:%M')}")
                if text.startswith(CALL_TAG):
                    age_min = (utc_now() - datetime.fromisoformat(created_at)).total_seconds() / 60
                    if age_min <= 30:
                        st.write("📞 Group voice call")
                        st.link_button("📞 Join call", text[len(CALL_TAG):], key=f"gjoin_{gid}_{sender}_{created_at}")
                    else:
                        st.write("📞 Voice call (ended)")
                elif text.startswith(REEL_TAG):
                    render_shared_reel(text[len(REEL_TAG):], f"g_{msg_id}")
                elif text.startswith(POST_TAG):
                    render_shared_post(text[len(POST_TAG):], f"g_{msg_id}")
                else:
                    st.write(text)
                if others > 0:
                    if sender == me:
                        names = ", ".join(get_display_name(u) for u in readers)
                        label = f"✓✓ Read by {len(readers)} of {others}" if readers else "✓ Sent · not read yet"
                        st.caption(label + (f" ({names})" if readers and len(readers) < 6 else ""))
                    else:
                        st.caption(f"👁 Read by {len(readers)} of {others}")
                if sender == me:
                    st.button("🗑 Unsend", key=f"unsend_g_{msg_id}", on_click=cb_unsend, args=("group_messages", msg_id, me))


# --- reels ---
def get_reels():
    return run("SELECT id, author_username, video_path, caption, created_at FROM reels ORDER BY created_at DESC", fetch="all")


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


REELS_CSS = """<style>
/* Reels: swipe up and down; each reel snaps into place, with its buttons down the right-hand side */
[data-testid="stMain"], section.main { scroll-snap-type: y proximity; }
[class*="st-key-rlcard_"] {
    position: relative; height: 80vh; height: min(80dvh, 780px); min-height: 460px;
    background: #000; border-radius: 18px; overflow: hidden; margin: 0 0 14px 0;
    scroll-snap-align: start; scroll-margin-top: 10px;
}
[class*="st-key-rlcard_"] [data-testid="stElementContainer"]:has(video) { position: absolute; inset: 0; z-index: 1; }
[class*="st-key-rlcard_"] [data-testid="stVideo"], [class*="st-key-rlcard_"] video {
    width: 100% !important; height: 100% !important; object-fit: contain; background: #000; }
[class*="st-key-rlinfo_"] { position: absolute; left: 12px; right: 84px; bottom: 58px; z-index: 5; pointer-events: none; gap: 4px; }
[class*="st-key-rlinfo_"], [class*="st-key-rlinfo_"] * { color: #fff !important; text-shadow: 0 1px 4px rgba(0,0,0,0.7); }
[class*="st-key-rlinfo_"] p { margin: 0; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
[class*="st-key-rlrail_"] { position: absolute; right: 6px; bottom: 64px; width: 62px; z-index: 6; gap: 4px; align-items: stretch; }
[class*="st-key-rlrail_"] > * { width: 100% !important; }
[class*="st-key-rlrail_"] button {
    background: rgba(0,0,0,0.38) !important; color: #fff !important; border: none !important; border-radius: 26px !important;
    min-height: 44px; padding: 2px 4px !important; width: 100% !important; backdrop-filter: blur(6px); box-shadow: none !important; }
[class*="st-key-rlrail_"] button p, [class*="st-key-rlrail_"] button span { color: #fff !important; font-size: 14px !important; margin: 0; line-height: 1.1; }
[class*="st-key-rlrail_"] [data-testid="stIconMaterial"], [class*="st-key-rlrail_"] button svg { display: none !important; }
</style>"""

REELS_JS = """<script>
(function () {
  var pwin = window.parent, pdoc = pwin.document, token = Math.random();
  function loud() { try { return !!(pwin.navigator.userActivation && pwin.navigator.userActivation.hasBeenActive); } catch (e) { return false; } }
  function play(v) {
    v.muted = !loud();
    var p = v.play();
    if (p && p.catch) p.catch(function () { v.muted = true; var q = v.play(); if (q && q.catch) q.catch(function () {}); });
  }
  var io = new pwin.IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      var v = e.target;
      if (e.isIntersecting && e.intersectionRatio >= 0.6) { play(v); } else { try { v.pause(); } catch (x) {} }
    });
  }, { threshold: [0, 0.6, 1] });
  function setup() {
    pdoc.querySelectorAll('[class*="st-key-rlcard_"] video').forEach(function (v) {
      if (v.__reelsToken === token) return;
      v.__reelsToken = token; v.loop = true; v.setAttribute('playsinline', ''); v.preload = 'metadata'; io.observe(v);
    });
  }
  setup();
  var timer = null;
  new pwin.MutationObserver(function () { clearTimeout(timer); timer = setTimeout(setup, 150); })
    .observe(pdoc.body, { childList: true, subtree: true });
})();
</script>"""


def short_count(n):
    return f"{n/1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def load_reel_extras(ids, me):
    """Likes, comments and saves for many reels in three queries."""
    likes = {rid: (0, False) for rid in ids}
    comments = {rid: [] for rid in ids}
    saved = set()
    if ids:
        marks = ",".join("?" * len(ids))
        for rid, n, mine in run(f"SELECT reel_id, COUNT(*), MAX(CASE WHEN username = ? THEN 1 ELSE 0 END) FROM reel_likes "
                                f"WHERE reel_id IN ({marks}) GROUP BY reel_id", (me, *ids), "all"):
            likes[rid] = (n, bool(mine))
        for rid, name, text in run(f"""SELECT comments.post_id, users.display_name, comments.comment_text FROM comments
                                       LEFT JOIN users ON comments.author_username = users.username
                                       WHERE comments.post_id IN ({marks}) ORDER BY comments.created_at ASC""", tuple(ids), "all"):
            comments.setdefault(rid, []).append((name, text))
        saved = {r[0] for r in run(f"SELECT post_id FROM post_saves WHERE username = ? AND post_id IN ({marks})", (me, *ids), "all")}
    return likes, comments, saved


def cb_more_reels():
    st.session_state.reel_limit = st.session_state.get("reel_limit", 8) + 8


def cb_share_reel(reel_id, me):
    code = st.session_state.get(f"rl_shto_{reel_id}")
    targets = dict(share_targets(me))
    if code not in targets:
        st.toast("Pick someone to send it to.", icon="⚠️")
        return
    kind, ref = code.split(":", 1)
    if kind == "u":
        send_message(me, ref, REEL_TAG + reel_id)
    else:
        send_group_message(me, ref, REEL_TAG + reel_id)
    st.toast(f"Shared with {targets[code].replace('👥 ', '')}", icon="📤")


def cb_reel_step(step, total):
    st.session_state.reel_idx = (st.session_state.get("reel_idx", 0) + step) % max(total, 1)


def cb_delete_reel(reel_id, me):
    row = run("SELECT author_username, video_path FROM reels WHERE id = ?", (reel_id,), "one")
    if row and row[0] == me:  # only the author can delete
        run("DELETE FROM reels WHERE id = ?", (reel_id,))
        run("DELETE FROM reel_likes WHERE reel_id = ?", (reel_id,))
        run("DELETE FROM comments WHERE post_id = ?", (reel_id,))
        delete_file(row[1])
        st.session_state.reel_idx = 0


# --- Yuaan: a built-in helper. It needs no account, no key and no outside AI service. ---
AI_MAX_CHARS = 500   # longest message allowed
ASK_TOPIC = "What's the post about?"

CAPTION_TEMPLATES = [
    "{T} mood, loading... ✨",
    "Today's plot: {t}.",
    "No filter needed for {t}.",
    "{T}, but make it unforgettable.",
    "Good vibes only: {t} edition.",
    "Because {t} deserves a post.",
    "Living for {t} 💜",
    "Little moments, big feelings: {t}.",
    "POV: {t} and zero worries.",
    "{T}. That's the whole caption.",
]

POST_IDEAS = [
    "Show what's on your desk or table right now.",
    "Post your favourite snack and ask friends to rate it from 1 to 10.",
    "Share one thing that made you smile today.",
    "Take a photo of the sky where you are.",
    "Ask your friends: what song is on repeat for you this week?",
    "Share a then-and-now photo of something, like a place, a pet or a drawing.",
    "Recommend a game, show or book and say why you like it.",
    "Post a would-you-rather question and let friends answer in the comments.",
    "Show something you made, even if it's not finished.",
    "Share your three favourite apps and ask friends for theirs.",
    "Post a photo of your view right now.",
    "Tell a short story about the best thing that happened this week.",
    "Share a tip that you wish you knew earlier.",
    "Ask friends for one thing they're looking forward to.",
    "Post your morning or evening routine in a few photos.",
]

REEL_IDEAS = [
    "A 10-second 'day in my life' with a few quick clips.",
    "Teach one quick skill, like a drawing trick or a handshake, in under 15 seconds.",
    "Slowly pan across a view you love.",
    "A time-lapse of cooking, cleaning or drawing something.",
    "Say hello with your pet or a plant.",
    "Show a before and after of something you fixed or made.",
    "A short 'what's in my bag' reel.",
    "Film a small challenge and tag a friend to try it.",
    "Record a funny moment from your week (with permission from anyone in it).",
    "A quick tour of your favourite spot.",
]

JOKES = [
    "Why did the phone go to school? To get smarter!",
    "Why don't skeletons fight each other? They don't have the guts.",
    "What do you call a fake noodle? An impasta.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "What's a computer's favourite snack? Microchips.",
    "Why was the math book sad? It had too many problems.",
    "Why did the bicycle fall over? It was two tired.",
    "How does the moon cut its hair? Eclipse it.",
    "What's orange and sounds like a parrot? A carrot.",
    "Why can't you trust stairs? They're always up to something.",
    "What do you call a sleeping dinosaur? A dino-snore.",
    "Why did the cookie go to the doctor? It felt crummy.",
]

APP_HELP = [  # (words to look for, answer). The first match wins, so order matters.
    (("delete", "remove"), "You can delete your own reels with the 🗑️ Delete button on the 🎬 Reels page. Deleting posts isn't available yet."),
    (("sign out", "log out", "logout"), "Open ⚙️ Profile Settings in the left sidebar. The Sign out button is at the bottom of that box."),
    (("password",), "You can change your password in the sidebar under 🔒 Account & privacy."),
    (("friend", "friends", "follow"), "Open 👥 Friends, search for their username and tap ➕ Add friend. You can also tap Add friend next to anyone's post or reel. When they accept, you can chat in 💬 Chats."),
    (("profile picture", "profile pic", "avatar", "pfp"), "Open ⚙️ Profile Settings in the left sidebar, choose a picture, then tap Save picture."),
    (("theme", "themes", "colour", "colours", "color", "colors", "dark mode"), "Open 🎨 Theme in the left sidebar. Pick a preset, or choose Custom to pick your own three colours. It saves to your account."),
    (("reel", "reels"), "Open 🎬 Reels, tap ➕ Upload a reel, choose an MP4 video (up to 100 MB) and tap Share reel. Use the Previous and Next buttons to move between reels, and tap 🤍 to like."),
    (("comment", "comments"), "Under any post or reel, open the 💬 comment box, type your comment and tap send."),
    (("like", "likes"), "On the 🎬 Reels page, tap the 🤍 button under a reel to like it. Tap it again to unlike."),
    (("post", "posts", "feed"), "On 🏠 Feed, write something in the box, add photos or videos if you like, then tap Post!"),
    (("chat", "chats", "message", "messages", "dm"), "💬 Chats works with friends. Add someone in 👥 Friends first, then pick them in Chats and type your message."),
]

CRISIS_WORDS = ("kill myself", "suicide", "want to die", "end my life", "hurt myself", "self harm", "self-harm")
LOW_WORDS = ("sad", "lonely", "depressed", "stressed", "anxious", "upset", "bad day", "miserable")

CRISIS_REPLY = ("I'm really sorry you're hurting. I'm only a simple helper inside an app, and you deserve real support right now. "
                "Please tell a trusted adult or someone close to you straight away. If you're in danger, contact your local "
                "emergency number or a crisis line in your country. You don't have to go through this alone.")
LOW_REPLY = ("I'm sorry you're having a rough time. I'm only a simple helper, so I can't help the way a person can. "
             "Try talking to a friend (you can message them in 💬 Chats) or someone you trust, like family or a teacher. "
             "If you ever feel unsafe or think about hurting yourself, tell a trusted adult right away.")
CAN_DO_REPLY = ("Here's what I can do:\n\n"
                "- **Captions:** try \"caption for beach day\"\n"
                "- **Post ideas** and **reel ideas**\n"
                "- **Jokes:** try \"tell me a joke\"\n"
                "- **Simple maths:** try \"12 x 4\" or \"20% of 50\"\n"
                "- **App help:** try \"how do I add a friend?\"\n\n"
                "I'm a built-in helper, not a full AI, so I work best with these topics.")
FALLBACK_REPLY = ("I'm not sure about that one. I'm a built-in helper, so I work best with captions (try \"caption for my dog\"), "
                  "post ideas, reel ideas, jokes, simple maths (try \"12 x 4\") and app help (try \"how do I add a friend?\").")


def _has(text, *phrases):
    return any(re.search(r"\b" + re.escape(p) + r"\b", text) for p in phrases)


def _captions(topic):
    topic = re.sub(r"[*_`#<>\[\]{}]", "", topic).strip()
    topic = re.sub(r"[.!?\s]+$", "", topic)[:60]
    if not topic:
        return f"Happy to help with a caption! {ASK_TOPIC} For example: beach day, my dog, birthday."
    cap = topic[:1].upper() + topic[1:]
    picks = random.sample(CAPTION_TEMPLATES, 3)
    lines = "\n".join(f"- {p.format(t=topic, T=cap)}" for p in picks)
    return f"Here are some caption ideas for **{topic}**:\n\n{lines}\n\nWant more? Just ask again."


def _ideas(title, items, count=4):
    lines = "\n".join(f"- {i}" for i in random.sample(items, count))
    return f"{title}\n\n{lines}\n\nAsk again for a fresh set."


def _safe_eval(node):
    """Evaluates only numbers and + - * / ** %, nothing else, so it is safe on typed text."""
    import ast, operator
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _safe_eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in ops:
        a, b = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(b) > 100 or abs(a) > 1e6):
            raise ValueError("too big")
        return ops[type(node.op)](a, b)
    raise ValueError("not math")


def _fmt_num(v):
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("bad")
        v = round(v, 6)
        if v == int(v) and abs(v) < 1e15:
            v = int(v)
    return f"{v:,}" if isinstance(v, int) and abs(v) >= 10000 else str(v)


def try_math(text):
    """Returns a reply if the message is a simple sum, otherwise None."""
    t = text.lower().strip().rstrip("?=! .")
    t = re.sub(r"^(what is|what's|whats|what|calculate|calc|solve|compute|work out|how much is|how much|tell me|answer)\s+(?:is\s+)?", "", t).strip()
    if re.fullmatch(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}", t):
        return None  # looks like a date
    m = re.fullmatch(r"([\d.,]+)\s*%\s*of\s*([\d.,]+)", t)
    try:
        if m:
            a, b = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
            return f"{m.group(1)}% of {m.group(2)} = **{_fmt_num(a / 100 * b)}**"
        m = re.fullmatch(r"(?:square root|sqrt)\s*(?:of)?\s*([\d.]+)", t)
        if m:
            return f"The square root of {m.group(1)} is **{_fmt_num(float(m.group(1)) ** 0.5)}**"
        e = t
        for w, s in ((" divided by ", "/"), (" multiplied by ", "*"), (" times ", "*"), (" plus ", "+"),
                     (" minus ", "-"), (" to the power of ", "**"), (" mod ", "%")):
            e = e.replace(w, s)
        e = e.replace("x", "*").replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", "")
        if not re.fullmatch(r"[\d+\-*/().% ]+", e) or not re.search(r"\d\s*[-+*/%]+\s*[\d(.-]", e) or not re.search(r"\d", e):
            return None
        return f"{text.strip().rstrip('?=! .')} = **{_fmt_num(_safe_eval(compile(e, '<m>', 'eval', 0x400)))}**"
    except ZeroDivisionError:
        return "I can't divide by zero. Nobody can! 😄"
    except Exception:
        return None



def yuaan_reply(text, name, last_bot=""):
    """Works out what the person wants and answers from built-in tips. Returns the reply text."""
    t = text.lower().strip()

    # Yuaan just asked what the post is about, so a short answer is the topic
    if ASK_TOPIC in last_bot and len(t) <= 80 and not _has(t, "joke", "idea", "ideas", "how", "help", "thanks", "thank you", "bye", "reel"):
        return _captions(text)

    if any(w in t for w in CRISIS_WORDS):
        return CRISIS_REPLY

    sums = try_math(text)
    if sums:
        return sums

    if _has(t, "caption", "captions"):
        m = re.search(r"captions?\s*(?:ideas?|suggestions?)?\s*(?:for|about|on|of|:)?\s*(.*)$", text, re.I)
        topic = re.sub(r"\b(please|pls|thanks)\b", "", m.group(1) if m else "", flags=re.I).strip(" .!?,:;-")
        return _captions(topic)

    if _has(t, "how", "where", "can i", "help me", "steps", "upload"):
        for words, answer in APP_HELP:
            if _has(t, *words):
                return answer

    if _has(t, "reel", "reels") and _has(t, "idea", "ideas", "what", "film", "make", "inspiration", "should"):
        return _ideas("Reel ideas for you:", REEL_IDEAS)
    if _has(t, "idea", "ideas", "inspiration", "what should i post", "what to post", "post something"):
        return _ideas("Post ideas for you:", POST_IDEAS)
    if _has(t, "joke", "jokes", "funny", "laugh"):
        return random.choice(JOKES)
    if _has(t, "bored", "boring"):
        return "Bored? Try posting a photo of your view, uploading a quick reel, or sending a message to a friend in 💬 Chats."
    if any(_has(t, w) for w in LOW_WORDS):
        return LOW_REPLY
    if _has(t, "what can you do", "help", "commands", "features", "menu"):
        return CAN_DO_REPLY
    if _has(t, "who are you", "your name", "are you an ai", "are you ai", "are you real", "are you a bot", "are you human"):
        return ("I'm Yuaan, the helper inside Yuaan Post. I'm not a person, and I'm not a big AI chatbot either. "
                "I run on built-in tips and templates, so I'm best at captions, post and reel ideas, jokes and app help.")
    if _has(t, "how are you", "how r u", "what's up", "whats up", "sup"):
        return random.choice([f"I'm good, {name}! Want a caption, a post idea or a joke?",
                              "Doing great! What are we posting today?"])
    if "ขอบคุณ" in t or _has(t, "thanks", "thank you", "thx", "ty"):
        return random.choice(["Anytime! 💜", "You're welcome!", "Happy to help!"])
    if _has(t, "bye", "goodbye", "see you", "cya", "goodnight"):
        return "See you soon! 👋"
    if "สวัสดี" in t or _has(t, "hi", "hello", "hey", "yo", "hiya"):
        return random.choice([f"Hey {name}! 👋 Want caption ideas, a post idea or a joke?",
                              f"Hi {name}! What can I help with today?"])
    return FALLBACK_REPLY


# --- Optional real AI (Google Gemini). Only used if a key is saved in Streamlit secrets. ---
AI_DAILY_LIMIT = 40   # Gemini messages per person per day; after that Yuaan uses the built-in replies
AI_HISTORY = 20
YUAAN_SYSTEM = ("You are Yuaan, a friendly helper inside a small social app called Yuaan Post (feed, reels, friends, chats). "
                "Keep replies short, kind and safe for all ages. Help with captions, post ideas, simple questions and app tips. "
                "If someone seems upset or in danger, be gentle and tell them to talk to a trusted adult or local emergency services. "
                "Never ask for personal details like addresses, passwords or phone numbers.")


def ai_used_today(username):
    today = utc_now().strftime("%Y-%m-%d")
    row = run("SELECT COUNT(*) FROM ai_messages WHERE username = ? AND role = 'user' AND created_at >= ?",
              (username, today), "one")
    return row[0] if row else 0


def ask_gemini(turns, name):
    """turns = [(role, text), ...] with role 'user' or 'assistant'. Returns text, or None if anything goes wrong."""
    key = get_secret("GEMINI_API_KEY")
    if not key:
        st.session_state.yuaan_status = "No GEMINI_API_KEY found in this app's Secrets."
        return None
    contents = []
    for role, text in turns:
        r = "user" if role == "user" else "model"
        if contents and contents[-1]["role"] == r:
            contents[-1]["parts"][0]["text"] += "\n" + text
        else:
            contents.append({"role": r, "parts": [{"text": text}]})
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    if not contents:
        return None
    st.session_state.yuaan_status = ""
    try:
        resp = None
        # stable models first; if one is busy (503), over quota (429) or gone (404), try the next
        for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest"):
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"system_instruction": {"parts": [{"text": YUAAN_SYSTEM + f" The person's name is {name}."}]},
                      "contents": contents, "generationConfig": {"maxOutputTokens": 400}},
                timeout=12)
            if resp.status_code not in (429, 404, 500, 502, 503, 504):
                break
        if resp.status_code != 200:
            try:
                why = resp.json()["error"]["message"][:200]
            except Exception:
                why = ""
            st.session_state.yuaan_status = f"Gemini said no (code {resp.status_code}). {why}"
            return None
        out = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if not out:
            st.session_state.yuaan_status = "Gemini sent an empty answer."
        return out or None
    except Exception as e:
        st.session_state.yuaan_status = f"Could not reach Gemini ({type(e).__name__})."
        return None


def yuaan_answer(history, text, username, name):
    """Maths and safety replies stay built-in. Everything else tries Gemini if a key exists, else built-in."""
    last_bot = history[-1][1] if history and history[-1][0] == "assistant" else ""
    local = yuaan_reply(text, name, last_bot)
    t = text.lower()
    if try_math(text) or any(w in t for w in CRISIS_WORDS) or not get_secret("GEMINI_API_KEY"):
        if not get_secret("GEMINI_API_KEY"):
            st.session_state.yuaan_status = "No GEMINI_API_KEY found in this app's Secrets."
        return local
    if ai_used_today(username) >= AI_DAILY_LIMIT:
        return local
    turns = list(history[-AI_HISTORY:]) + [("user", text)]
    return ask_gemini(turns, name) or local


def cb_clear_ai(username):
    run("DELETE FROM ai_messages WHERE username = ?", (username,))


def cb_yuaan_quick(text):
    st.session_state.yuaan_quick = text


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
            login_user = login_user.strip()
            row = run("SELECT password FROM users WHERE username = ?", (login_user,), "one")
            if row and check_password(login_pass, row[0]):
                if not row[0].startswith("pbkdf2$"):  # an old plain-text password: scramble it now
                    run("UPDATE users SET password = ? WHERE username = ?", (hash_password(login_pass), login_user))
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
                    run("INSERT INTO users (username, password, display_name) VALUES (?, ?, ?)", (reg_user.strip(), hash_password(reg_pass), reg_name))
                    st.success("success! go to the login page to start")
                except psycopg2.IntegrityError:
                    st.error("This username has been taken please select a new one!")
            else:
                st.warning("Add all information")
    st.stop()

# ==========================================
# 6. Main app (after login)
# ==========================================
current_user = st.session_state.username
prefetch_people([current_user])
display_name = get_display_name(current_user)

if "page" not in st.session_state:
    st.session_state.page = "feed"
if "avatar_nonce" not in st.session_state:
    st.session_state.avatar_nonce = 0

pending_count, unread_count, alert_n = ttl_cache(f"side_{current_user}", 4, lambda: sidebar_counts(current_user))

admin_mode = is_admin(current_user)
open_reports = ttl_cache("open_reports", 10, lambda: run("SELECT COUNT(*) FROM reports", fetch="one")[0]) if admin_mode else 0

PAGE_LABELS = {
    "feed": "🏠 Feed",
    "foryou": "✨ For You",
    "search": "🔍 Search",
    "alerts": "🔔 Alerts" + (f" ({alert_n} new)" if alert_n else ""),
    "reels": "🎬 Reels",
    "friends": "👥 Friends" + (f" ({pending_count} new)" if pending_count else ""),
    "chats": "💬 Chats" + (f" ({unread_count} new)" if unread_count else ""),
    "yuaan": "🤖 Yuaan",
}
if admin_mode:
    PAGE_LABELS["admin"] = "🛡 Admin" + (f" ({open_reports} reports)" if open_reports else "")

with st.sidebar:
    st.markdown(person_html(current_user, size=56, subtitle="Welcome to Yuaan Post"), unsafe_allow_html=True)
    st.write("")
    for page_key, page_label in PAGE_LABELS.items():
        st.button(page_label, key=f"nav_{page_key}", use_container_width=True,
                  type="primary" if st.session_state.page == page_key else "secondary",
                  on_click=cb_open_alerts if page_key == "alerts" else cb_go_page,
                  args=(current_user,) if page_key == "alerts" else (page_key,))

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

        if "bio_text" not in st.session_state:
            st.session_state.bio_text = get_bio(current_user)
        st.text_area("Bio (up to 150 characters)", key="bio_text", max_chars=150, height=80)
        st.button("Save bio", key="save_bio_btn", on_click=cb_save_bio)

        st.button("👤 View my profile", key="view_my_profile", on_click=cb_view_profile, args=(current_user,))

        st.divider()
        st.button("Sign out", on_click=cb_sign_out)

    with st.expander("🔒 Account & privacy"):
        st.text_input("Current password", type="password", key="pw_cur")
        st.text_input("New password (6+ characters)", type="password", key="pw_new")
        st.text_input("New password again", type="password", key="pw_new2")
        st.button("Change password", key="pw_btn", on_click=cb_change_password)
        st.divider()
        mine_blocked = sorted(block_sets(current_user)[0])
        st.caption(f"Blocked people ({len(mine_blocked)})")
        for u in mine_blocked:
            c1, c2 = st.columns([3, 2])
            c1.write(get_display_name(u))
            c2.button("Unblock", key=f"unblock_{u}", on_click=cb_unblock_user, args=(current_user, u))

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
    st.caption("Design v43")
    perf_slot = st.empty() if admin_mode else None

# ------------------------------------------
# Shared by the Feed and For You pages
# ------------------------------------------
def fetch_post_extras(post_ids):
    """Photos and comments for many posts at once (two queries instead of two per post)."""
    media_by_post, comments_by_post = {}, {}
    load_likes(list(post_ids), current_user)
    if post_ids:
        marks = ",".join("?" * len(post_ids))
        ids = tuple(post_ids)
        for m_post, m_key, m_type in run(f'SELECT post_id, file_path, file_type FROM media WHERE post_id IN ({marks}) ORDER BY "position"', ids, "all"):
            media_by_post.setdefault(m_post, []).append((m_key, m_type))
        for c_post, c_author, c_text in run(f'''SELECT comments.post_id, users.display_name, comments.comment_text
                                               FROM comments LEFT JOIN users ON comments.author_username = users.username
                                               WHERE comments.post_id IN ({marks}) ORDER BY comments.created_at ASC''', ids, "all"):
            comments_by_post.setdefault(c_post, []).append((c_author, c_text))
    return media_by_post, comments_by_post


def render_post_card(idx, post, media_rows, comments, prefix, reason=None):
    """One post with its buttons and comments. prefix keeps button names unique when a page shows several lists."""
    post_id, note, created_at, author_username = post[:4]
    time_str = thai_time(created_at, "%d %b %Y, %H:%M")
    with st.container(border=True):
        st.markdown(f'<div style="height:8px;border-radius:8px;background:{T["accents"][idx % len(T["accents"])]};margin-bottom:12px;"></div>',
                    unsafe_allow_html=True)
        h_left, h_right, h_right2 = st.columns([4, 2, 2])
        h_left.markdown(person_html(author_username, size=48, subtitle=f"🕒 {time_str}"), unsafe_allow_html=True)
        friend_button(h_right, current_user, author_username, f"{prefix}_friend_{post_id}")
        follow_button(h_right2, current_user, author_username, f"{prefix}_follow_{post_id}")
        if reason:
            st.caption(f"✨ {reason}")
        st.markdown(f'<div style="white-space: pre-wrap; margin: 10px 0;">{html.escape(note)}</div>', unsafe_allow_html=True)

        show_media(media_rows, can_edit=(author_username == current_user), key_prefix=f"{prefix}_{post_id}")
        render_song(st.session_state.get("_songs", {}).get(post_id))

        post_actions(post_id, author_username, current_user, prefix)

        with st.expander(f"💬 comment ({len(comments)} comment)"):
            for c_author, c_text in comments:
                st.markdown(f"**{c_author or 'Unknown'}**: {c_text}")

            with st.form(f"comment_form_{prefix}_{post_id}", clear_on_submit=True):
                new_comment = st.text_input("comment...")
                if st.form_submit_button("send"):
                    if new_comment:
                        run("INSERT INTO comments (id, post_id, author_username, comment_text, created_at) VALUES (?, ?, ?, ?, ?)",
                            (str(uuid.uuid4()), post_id, current_user, new_comment, utc_now().isoformat()))
                        st.rerun()


def people_connected_to(circle, me):
    """People your friends are friends with, or that the people you follow follow."""
    if not circle:
        return set()
    marks = ",".join("?" * len(circle))
    c = tuple(circle)
    out = {r[0] for r in run(f"SELECT followee FROM follows WHERE follower IN ({marks})", c, "all")}
    for a, b in run(f"SELECT requester, addressee FROM friendships WHERE status = 'accepted' "
                    f"AND (requester IN ({marks}) OR addressee IN ({marks}))", c + c, "all"):
        out.add(a)
        out.add(b)
    return out - set(circle) - {me}


def recommend_posts(me, circle, limit=8):
    """Posts from people you don't know yet, best first: connected to your circle, talked about, with photos, and new.
    Returns [(post, reason), ...]."""
    rows = [r for r in run("SELECT id, note, created_at, author_username FROM posts WHERE author_username <> ? "
                           "ORDER BY created_at DESC LIMIT 100", (me,), "all") if r[3] not in circle and r[3] not in blocked_set(me)]
    if not rows:
        return []
    marks = ",".join("?" * len(rows))
    ids = tuple(r[0] for r in rows)
    counts = dict(run(f"SELECT post_id, COUNT(*) FROM comments WHERE post_id IN ({marks}) GROUP BY post_id", ids, "all"))
    with_media = {r[0] for r in run(f"SELECT DISTINCT post_id FROM media WHERE post_id IN ({marks})", ids, "all")}
    likes = dict(run(f"SELECT post_id, COUNT(*) FROM post_likes WHERE post_id IN ({marks}) GROUP BY post_id", ids, "all"))
    connected = people_connected_to(circle, me)
    now = utc_now()
    scored = []
    for row in rows:
        post_id, _, created_at, author = row
        age_hours = max((now - datetime.fromisoformat(created_at)).total_seconds() / 3600, 0)
        liked = likes.get(post_id, 0)
        talked = counts.get(post_id, 0)
        score = talked * 2 + liked * 1.5 + (1 if post_id in with_media else 0) + (4 if author in connected else 0) + 6 / (1 + age_hours / 24)
        if author in connected:
            reason = "From someone connected to people you know"
        elif liked or talked:
            reason = "People are liking and talking about this"
        else:
            reason = "New on Yuaan Post"
        scored.append((score, row, reason))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(row, reason) for _, row, reason in scored[:limit]]


# ------------------------------------------
# Incoming call: red banner + ringtone on any page
# ------------------------------------------
def make_ringtone():
    """A phone-style ring (two short bursts, then a pause) as WAV bytes."""
    import wave, math, struct
    rate = 8000
    frames = bytearray()
    def tone(freqs, secs):
        for i in range(int(rate * secs)):
            v = sum(math.sin(2 * math.pi * f * i / rate) for f in freqs) / len(freqs)
            frames.extend(struct.pack("<h", int(v * 0.6 * 32767)))
    def quiet(secs):
        frames.extend(b"\x00\x00" * int(rate * secs))
    for _ in range(2):
        tone((440, 480), 0.4)
        quiet(0.2)
    quiet(1.2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


@st.cache_resource
def ringtone_bytes():
    return make_ringtone()


def cb_decline_call(call_id):
    st.session_state.setdefault("dismissed_calls", set()).add(call_id)


@st.fragment(run_every=3)
def incoming_call_watcher(me):
    # this also works as a heartbeat: it records that I'm here, at most once every 45 seconds
    if time.time() - st.session_state.get("_hb", 0) > 45:
        st.session_state["_hb"] = time.time()
        try:
            _execute("UPDATE users SET last_seen = ? WHERE username = ?", (utc_now().isoformat(), me), None)
        except Exception:
            pass
    cutoff = (utc_now() - timedelta(seconds=45)).isoformat()
    dismissed = st.session_state.get("dismissed_calls", set())
    found = None
    rows = run('''SELECT id, sender, text, '' AS gname, created_at FROM messages
                  WHERE receiver = ? AND text LIKE ? AND created_at > ?
                  UNION ALL
                  SELECT m.id, m.sender, m.text, g.name, m.created_at FROM group_messages m
                  JOIN group_members gm ON gm.group_id = m.group_id
                  JOIN group_chats g ON g.id = m.group_id
                  WHERE gm.username = ? AND m.sender <> ? AND m.text LIKE ? AND m.created_at > ?
                  ORDER BY created_at DESC LIMIT 3''', (me, CALL_TAG + "%", cutoff, me, me, CALL_TAG + "%", cutoff), "all")
    for cid, sender, ctext, gname, _ in rows:
        if cid not in dismissed:
            who = get_display_name(sender)
            found = (cid, ctext, f"{who} started a call in {gname}" if gname else f"{who} is calling you...")
            break
    if not found:
        return
    call_id, text, title = found
    with st.container(border=True):
        st.markdown(f"### 📞 {title}")
        st.audio(ringtone_bytes(), format="audio/wav", autoplay=True, loop=True)
        c1, c2 = st.columns(2)
        with c1:
            st.link_button("✅ Answer", text[len(CALL_TAG):], use_container_width=True)
        with c2:
            st.button("❌ Decline", key=f"decline_{call_id}", on_click=cb_decline_call,
                      args=(call_id,), use_container_width=True)


incoming_call_watcher(current_user)


# ------------------------------------------
# PAGE: Feed
# ------------------------------------------
if st.session_state.page == "feed":
    banner("Yuaan Post", "See what your friends are up to, or post something new.", "feed")

    story_circle = set(get_friends(current_user)) | set(get_following(current_user))
    story_viewer(current_user)
    stories_strip(current_user, story_circle)
    add_story_ui(current_user)

    chosen = parse_song(st.session_state.get("post_song"))
    with st.expander("🎵 Add a song to your post" + (" ✅" if chosen else "")):
        if chosen:
            render_song(st.session_state.post_song)
            st.button("✖ Remove song", key="song_remove_btn", on_click=cb_song_remove)
        st.text_input("Search a song or artist", key="song_q", placeholder="e.g. Blinding Lights")
        st.button("🔍 Search", key="song_search_btn", on_click=cb_song_search)
        results = st.session_state.get("song_results", [])
        if st.session_state.get("song_searched") and not results:
            st.caption("No songs found (or search isn't reachable right now). You can paste a link below instead.")
        for i, sg in enumerate(results):
            c1, c2, c3 = st.columns([1, 4, 2])
            if sg.get("art"):
                c1.image(sg["art"], width=48)
            c2.markdown(f"**{html.escape(sg['title'])}**  \n{html.escape(sg['artist'])}", unsafe_allow_html=True)
            c3.button("Choose", key=f"song_pick_{i}", on_click=cb_song_pick, args=(i,))
        st.caption("Search plays a 30-second preview. Or paste a Spotify or YouTube link:")
        st.text_input("Spotify or YouTube link", key="song_link", placeholder="https://open.spotify.com/track/...")
        st.button("Use link", key="song_link_btn", on_click=cb_song_link)

    with st.form("diary_form", clear_on_submit=True):
        note = st.text_area("Your description...")
        with st.expander("📁 click to select photos or videos"):
            uploaded_files = st.file_uploader("select your file", type=["png", "jpg", "jpeg", "mp4", "mov"], accept_multiple_files=True)
        submit_button = st.form_submit_button("Post!")

        if submit_button:
            if note:
                post_id = str(uuid.uuid4())
                created_at = utc_now().isoformat()
                saved_files = []  # (key, mime type)
                problem = None
                with st.spinner("Posting..."):
                    try:
                        for file in (uploaded_files or []):
                            ext = os.path.splitext(file.name)[1].lower()
                            if "video" in (file.type or "") or ext in (".mp4", ".mov"):
                                if file.size > MAX_VIDEO_MB * 1024 * 1024:
                                    problem = f"A video is bigger than {MAX_VIDEO_MB} MB. Choose a shorter one."
                                    break
                                mime = "video/quicktime" if ext == ".mov" else (file.type or "video/mp4")
                                saved_files.append((upload_file(file.getvalue(), "posts", ext or ".mp4", mime), mime))
                            else:
                                saved_files.append((upload_file(prepare_photo(file.getvalue()), "posts", ".jpg", "image/jpeg"), "image/jpeg"))
                    except Exception:
                        problem = "A file couldn't be uploaded. Please try again."
                if problem:
                    for key, _ in saved_files:  # don't leave half a post behind
                        delete_file(key)
                    st.error(problem)
                else:
                    song_value = st.session_state.get("post_song") if parse_song(st.session_state.get("post_song")) else None
                    run("INSERT INTO posts (id, author_username, note, created_at, song) VALUES (?, ?, ?, ?, ?)",
                        (post_id, current_user, note, created_at, song_value))
                    for k in ("post_song", "song_results", "song_searched"):
                        st.session_state.pop(k, None)
                    for position, (key, mime) in enumerate(saved_files):
                        run('INSERT INTO media (id, post_id, file_path, file_type, "position") VALUES (?, ?, ?, ?, ?)',
                            (str(uuid.uuid4()), post_id, key, mime, position))
                    st.success("success! 🎉")
                    st.rerun()
            else:
                st.warning("Add a description(can be anything)!")

    st.write("")
    st.header("Latest posts")

    hidden = blocked_set(current_user)
    posts = [p for p in run("SELECT id, note, created_at, author_username FROM posts ORDER BY created_at DESC LIMIT 60", fetch="all")
             if p[3] not in hidden][:40]
    if not posts:
        st.info("Nothing here yet. Write the first post above.")
    prefetch_people([p[3] for p in posts])
    media_by_post, comments_by_post = fetch_post_extras([p[0] for p in posts])
    for idx, post in enumerate(posts):
        render_post_card(idx, post, media_by_post.get(post[0], []), comments_by_post.get(post[0], []), "feed")

# ------------------------------------------
# PAGE: For You (friends' and followed people's posts, plus posts you may like)
# ------------------------------------------
elif st.session_state.page == "foryou":
    banner("For You", "Posts from your friends and people you follow, plus posts you may like.", "foryou")

    circle = set(get_friends(current_user)) | set(get_following(current_user))
    circle.discard(current_user)

    friend_posts = []
    if circle:
        marks = ",".join("?" * len(circle))
        friend_posts = run(f"SELECT id, note, created_at, author_username FROM posts WHERE author_username IN ({marks}) "
                           "ORDER BY created_at DESC LIMIT 15", tuple(circle), "all")
    suggestions = recommend_posts(current_user, circle)

    prefetch_people([p[3] for p in friend_posts] + [p[0][3] for p in suggestions])
    media_by_post, comments_by_post = fetch_post_extras([p[0] for p in friend_posts] + [p[0][0] for p in suggestions])

    st.header("From your friends")
    if not circle:
        st.info("Add friends in 👥 Friends or tap ➕ Follow on a post, and their posts will show up here.")
    elif not friend_posts:
        st.caption("Your friends and the people you follow haven't posted yet.")
    for idx, post in enumerate(friend_posts):
        render_post_card(idx, post, media_by_post.get(post[0], []), comments_by_post.get(post[0], []), "fyf")

    st.header("Posts you may like")
    st.caption("A mix of new posts, posts people are talking about, and posts from people connected to your friends.")
    if not suggestions:
        st.caption("Nothing to suggest yet. Come back when more people have posted.")
    for idx, (post, reason) in enumerate(suggestions):
        render_post_card(idx, post, media_by_post.get(post[0], []), comments_by_post.get(post[0], []), "fyr", reason=reason)

# ------------------------------------------
# PAGE: Reels (short videos, one at a time)
# ------------------------------------------
elif st.session_state.page == "reels":
    banner("Reels", "Swipe up and down to watch. Your buttons are on the right.", "reels")

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
                    mime = {".mov": "video/quicktime", ".webm": "video/webm"}.get(ext, "video/mp4")
                    try:
                        with st.spinner("Uploading your reel..."):
                            reel_key = upload_file(reel_file.getvalue(), "reels", ext, mime)
                        run("INSERT INTO reels (id, author_username, video_path, caption, created_at) VALUES (?, ?, ?, ?, ?)",
                            (reel_id, current_user, reel_key, reel_caption.strip(), utc_now().isoformat()))
                        st.session_state.reel_idx = 0  # show the new reel first
                        st.rerun()
                    except (RuntimeError, requests.RequestException):
                        st.error("The reel couldn't be uploaded. Please try again.")

    hidden = blocked_set(current_user)
    all_reels = [r for r in get_reels() if r[1] not in hidden]
    reel_limit = st.session_state.get("reel_limit", 8)
    reels = all_reels[:reel_limit]
    if not reels:
        st.info("No reels yet. Upload the first one above.")
    else:
        st.markdown(REELS_CSS, unsafe_allow_html=True)
        prefetch_people([r[1] for r in reels])
        reel_likes_map, reel_comments_map, reel_saved = load_reel_extras([r[0] for r in reels], current_user)
        reel_targets = share_targets(current_user)
        i_follow = my_relations(current_user)[1]
        for reel_id, author, video_path, caption, created_at in reels:
            n_likes, liked = reel_likes_map.get(reel_id, (0, False))
            comments_here = reel_comments_map.get(reel_id, [])
            with st.container(key=f"rlcard_{reel_id}"):
                st.video(file_url(video_path), loop=True)
                with st.container(key=f"rlinfo_{reel_id}"):
                    st.markdown(person_html(author, size=34, subtitle=f"🕒 {thai_time(created_at, '%d %b, %H:%M')}"), unsafe_allow_html=True)
                    if caption:
                        st.markdown(html.escape(caption))
                with st.container(key=f"rlrail_{reel_id}"):
                    if author != current_user:
                        st.button("✅" if author in i_follow else "➕", key=f"rl_fol_{reel_id}", on_click=cb_toggle_follow,
                                  args=(current_user, author), help="Following" if author in i_follow else "Follow")
                    st.button(f"{'❤️' if liked else '🤍'} {short_count(n_likes)}", key=f"rl_like_{reel_id}",
                              on_click=cb_toggle_like, args=(reel_id, current_user))
                    with st.popover(f"💬 {short_count(len(comments_here))}", use_container_width=True):
                        if not comments_here:
                            st.caption("No comments yet.")
                        for c_author, c_text in comments_here:
                            st.markdown(f"**{c_author or 'Unknown'}**: {c_text}")
                        with st.form(f"reel_comment_form_{reel_id}", clear_on_submit=True):
                            new_reel_comment = st.text_input("comment...")
                            if st.form_submit_button("send"):
                                if new_reel_comment:
                                    run("INSERT INTO comments (id, post_id, author_username, comment_text, created_at) VALUES (?, ?, ?, ?, ?)",
                                        (str(uuid.uuid4()), reel_id, current_user, new_reel_comment, utc_now().isoformat()))
                                    st.rerun()
                    with st.popover("📤", use_container_width=True):
                        if not reel_targets:
                            st.caption("Add a friend first, then you can share reels with them.")
                        else:
                            st.selectbox("Send to", [t[0] for t in reel_targets], format_func=dict(reel_targets).get, key=f"rl_shto_{reel_id}")
                            st.button("Send", key=f"rl_shsend_{reel_id}", on_click=cb_share_reel, args=(reel_id, current_user))
                    st.button("🔖✓" if reel_id in reel_saved else "🔖", key=f"rl_save_{reel_id}", on_click=cb_toggle_save,
                              args=(reel_id, current_user), help="Saved" if reel_id in reel_saved else "Save")
                    with st.popover("⋯", use_container_width=True):
                        st.button("👤 Profile", key=f"rl_prof_{reel_id}", on_click=cb_view_profile, args=(author,))
                        if author == current_user:
                            st.button("🗑️ Delete reel", key=f"rl_del_{reel_id}", on_click=cb_delete_reel, args=(reel_id, current_user))
        if len(all_reels) > reel_limit:
            st.button("⬇ Load more reels", key="rl_more", on_click=cb_more_reels, use_container_width=True)
        components.html(REELS_JS, height=0)

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
                         WHERE username != ? AND (username ILIKE ? OR display_name ILIKE ?)
                         ORDER BY username LIMIT 20''', (current_user, like, like), "all")
        if not results:
            st.caption("No users found.")
        for (other,) in results:
            status = friendship_status(current_user, other)
            c1, c2, c2b = st.columns([5, 3, 2])
            c1.markdown(person_html(other), unsafe_allow_html=True)
            c2b.button("👤 Profile", key=f"sprof_{other}", on_click=cb_view_profile, args=(other,))
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
    banner("Chats", "Message a friend or make a group.", "chats")
    friends = get_friends(current_user)
    chat_mode = st.radio("Chat type", ["💬 Friends", "👥 Groups"], horizontal=True,
                         key="chat_mode", label_visibility="collapsed")

    if chat_mode == "👥 Groups":
        groups = my_groups(current_user)
        with st.expander("➕ New group", expanded=not groups):
            if not friends:
                st.info("Add a friend in 👥 Friends first, then you can make a group.")
            else:
                st.text_input("Group name", key="new_group_name", max_chars=40)
                st.multiselect("Add friends", friends, format_func=lambda u: f"{get_display_name(u)} (@{u})",
                               key="new_group_members")
                st.button("Create group", key="create_group_btn", on_click=cb_create_group, args=(current_user,))
        if groups:
            ids = [g[0] for g in groups]
            names = dict(groups)
            if st.session_state.get("chat_group") not in ids:
                st.session_state.pop("chat_group", None)
            unread_groups = group_unread_counts(current_user)
            open_group = st.session_state.get("chat_group")

            def group_label(i):
                n = 0 if i == open_group else unread_groups.get(i, 0)
                return names[i] + (f"  •  {n} new" if n else "")

            gid = st.selectbox("Group", ids, format_func=group_label, key="chat_group")
            members = group_members(gid)
            st.caption("Members: " + ", ".join(get_display_name(u) for u in members))
            st.button("🚪 Leave group", key=f"leave_{gid}", on_click=cb_leave_group, args=(current_user, gid))
            with st.expander("📞 Start a Google Meet call"):
                call_ui(f"gcall_{gid}", lambda link: start_group_call(current_user, gid, link))
            addable = [u for u in friends if u not in members]
            if addable:
                with st.expander("Add more friends"):
                    st.multiselect("Friends to add", addable, format_func=lambda u: f"{get_display_name(u)} (@{u})",
                                   key=f"add_members_{gid}")
                    st.button("Add", key=f"add_btn_{gid}", on_click=cb_add_group_members, args=(current_user, gid))
            render_group_messages(current_user, gid)
            gprompt = st.chat_input(f"Message {names[gid]}...")
            if gprompt and gprompt.strip():
                send_group_message(current_user, gid, gprompt.strip())
                st.rerun()
    elif not friends:
        st.info("You need a friend to chat with. Go to 👥 Friends and add someone by username.")
    else:
        if st.session_state.get("chat_with") not in friends:
            st.session_state.pop("chat_with", None)

        unread_by = dict(run("SELECT sender, COUNT(*) FROM messages WHERE receiver = ? AND is_read = 0 GROUP BY sender", (current_user,), "all"))

        def friend_label(u):
            n = unread_by.get(u, 0)
            return f"{get_display_name(u)} (@{u})" + (f"  •  {n} new" if n else "")

        other = st.selectbox("Chat with", friends, format_func=friend_label, key="chat_with")

        st.markdown(person_html(other, size=36, subtitle=f"@{html.escape(other)} · {presence_text(other)}"), unsafe_allow_html=True)
        with st.expander(f"📞 Start a Google Meet call with {get_display_name(other)}"):
            call_ui("dmcall", lambda link: start_call(current_user, other, link))
        render_messages(current_user, other)

        prompt = st.chat_input(f"Message {get_display_name(other)}...")
        if prompt and prompt.strip():
            send_message(current_user, other, prompt.strip())
            st.rerun()

# ------------------------------------------
# PAGE: Profile (someone's picture, counts, posts and reels)
# ------------------------------------------
elif st.session_state.page == "profile":
    target = st.session_state.get("profile_user")
    exists = bool(target) and run("SELECT 1 FROM users WHERE username = ?", (target,), "one") is not None
    st.button("← Back to Feed", key="profile_back", on_click=cb_go_page, args=("feed",))
    if not exists:
        st.info("That person wasn't found.")
    elif target != current_user and target in blocked_set(current_user):
        banner(get_display_name(target), f"@{target}", "profile")
        if run("SELECT 1 FROM blocks WHERE blocker = ? AND blocked = ?", (current_user, target), "one"):
            st.info("You blocked this person.")
            st.button("Unblock", key="prof_unblock", on_click=cb_unblock_user, args=(current_user, target))
        else:
            st.info("This profile isn't available.")
    else:
        banner(get_display_name(target), f"@{target}", "profile")
        st.markdown(avatar_html(target, size=96), unsafe_allow_html=True)
        if target == current_user or friendship_status(current_user, target) == "friends":
            st.caption(presence_text(target))
        bio = get_bio(target)
        if bio:
            st.markdown(f'<div style="white-space: pre-wrap; margin: 6px 0 10px;">{html.escape(bio)}</div>', unsafe_allow_html=True)

        their_posts = run("SELECT id, note, created_at FROM posts WHERE author_username = ? ORDER BY created_at DESC", (target,), "all")
        followers_list, following_list = get_followers(target), get_following(target)
        n_posts = len(their_posts)
        n_friends = len(get_friends(target))
        n_followers, n_following = len(followers_list), len(following_list)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Posts", n_posts)
        m2.metric("Followers", n_followers)
        m3.metric("Following", n_following)
        m4.metric("Friends", n_friends)

        if target != current_user:
            b1, b2, b3 = st.columns(3)
            follow_button(b1, current_user, target, "prof_follow")
            friend_button(b2, current_user, target, "prof_friend")
            if friendship_status(current_user, target) == "friends":
                b3.button("💬 Message", key="prof_msg", on_click=cb_open_chat, args=(target,), use_container_width=True)

        if target != current_user:
            with st.expander("⚙️ More"):
                st.button("🚫 Block this person", key="prof_block", on_click=cb_block_user, args=(current_user, target))
                st.text_input("Why are you reporting them? (optional)", key=f"report_reason_{target}", max_chars=300)
                st.button("🚩 Report this person", key="prof_report", on_click=cb_report_user, args=(current_user, target))

        with st.expander(f"Followers ({n_followers})"):
            people = followers_list
            if not people:
                st.caption("No followers yet.")
            for u in people:
                c1, c2 = st.columns([5, 2])
                c1.markdown(person_html(u), unsafe_allow_html=True)
                c2.button("👤 Profile", key=f"pf_fol_{u}", on_click=cb_view_profile, args=(u,))
        with st.expander(f"Following ({n_following})"):
            people = following_list
            if not people:
                st.caption("Not following anyone yet.")
            for u in people:
                c1, c2 = st.columns([5, 2])
                c1.markdown(person_html(u), unsafe_allow_html=True)
                c2.button("👤 Profile", key=f"pf_fng_{u}", on_click=cb_view_profile, args=(u,))

        profile_tabs = st.tabs(["Posts", "Reels"] + (["🔖 Saved"] if target == current_user else []))
        tab_posts, tab_reels = profile_tabs[0], profile_tabs[1]
        with tab_posts:
            if not their_posts:
                st.caption("No posts yet.")
            their_media, _unused = fetch_post_extras([p[0] for p in their_posts])
            for p_id, p_note, p_created in their_posts:
                with st.container(border=True):
                    st.caption(f"🕒 {thai_time(p_created, '%d %b %Y, %H:%M')}")
                    st.markdown(f'<div style="white-space: pre-wrap; margin: 6px 0;">{html.escape(p_note)}</div>', unsafe_allow_html=True)
                    show_media(their_media.get(p_id, []),
                               can_edit=(target == current_user), key_prefix=f"prof_{p_id}")
                    render_song(st.session_state.get("_songs", {}).get(p_id))
                    post_actions(p_id, target, current_user, "prof", show_profile=False)
        with tab_reels:
            their_reels = run("SELECT id, author_username, video_path, caption, created_at FROM reels "
                              "WHERE author_username = ? ORDER BY created_at DESC LIMIT 10", (target,), "all")
            if not their_reels:
                st.caption("No reels yet.")
            for r_id, _, r_path, r_caption, _ in their_reels:
                with st.container(border=True):
                    st.video(file_url(r_path))
                    if r_caption:
                        st.caption(r_caption)


        if len(profile_tabs) == 3:
            with profile_tabs[2]:
                saved_posts = run("""SELECT p.id, p.note, p.created_at, p.author_username FROM post_saves sv
                                     JOIN posts p ON p.id = sv.post_id WHERE sv.username = ?
                                     ORDER BY sv.created_at DESC LIMIT 40""", (current_user,), "all")
                saved_posts = [p for p in saved_posts if p[3] not in blocked_set(current_user)]
                if not saved_posts:
                    st.caption("Nothing saved yet. Tap 🔖 Save on a post to keep it here.")
                prefetch_people([p[3] for p in saved_posts])
                sv_media, sv_comments = fetch_post_extras([p[0] for p in saved_posts])
                for idx, post in enumerate(saved_posts):
                    render_post_card(idx, post, sv_media.get(post[0], []), sv_comments.get(post[0], []), "sv")
                saved_reels = [r for r in run("""SELECT r.id, r.author_username, r.video_path, r.caption FROM post_saves sv
                                                 JOIN reels r ON r.id = sv.post_id WHERE sv.username = ?
                                                 ORDER BY sv.created_at DESC LIMIT 20""", (current_user,), "all")
                               if r[1] not in blocked_set(current_user)]
                if saved_reels:
                    st.subheader("Saved reels")
                for r_id, r_author, r_path, r_cap in saved_reels:
                    with st.container(border=True):
                        st.caption(f"Reel by {get_display_name(r_author)}")
                        st.video(file_url(r_path))
                        if r_cap:
                            st.caption(r_cap)
                        st.button("🔖 Remove", key=f"svr_{r_id}", on_click=cb_toggle_save, args=(r_id, current_user))

# ------------------------------------------
# PAGE: Yuaan (built-in helper)
# ------------------------------------------
elif st.session_state.page == "search":
    banner("Search", "Find people, posts and #hashtags.", "search")

    def cb_pick_tag(tag):
        st.session_state.search_q = tag

    q = st.text_input("Search", key="search_q", placeholder="a name, @username, word or #hashtag", label_visibility="collapsed").strip()
    if not q:
        tags = {}
        for (note,) in run("SELECT note FROM posts ORDER BY created_at DESC LIMIT 150", fetch="all"):
            for t in set(re.findall(r"#\w+", (note or "").lower())):
                tags[t] = tags.get(t, 0) + 1
        top = sorted(tags.items(), key=lambda kv: kv[1], reverse=True)[:8]
        if top:
            st.subheader("🔥 Trending hashtags")
            cols = st.columns(2)
            for i, (t, n) in enumerate(top):
                cols[i % 2].button(f"{t}  ·  {n}", key=f"tag_{t}", on_click=cb_pick_tag, args=(t,), use_container_width=True)
        else:
            st.caption("Type a name or word above. Put #hashtags in your posts and they'll show up here as trends.")
    else:
        like = f"%{q.lstrip('@')}%"
        hidden = blocked_set(current_user)
        people = [r for r in run('''SELECT username FROM users WHERE username ILIKE ? OR display_name ILIKE ?
                       ORDER BY username LIMIT 25''', (like, like), "all") if r[0] not in hidden][:15]
        st.subheader(f"People ({len(people)})")
        if not people:
            st.caption("No people found.")
        for (u,) in people:
            c1, c2 = st.columns([5, 2])
            c1.markdown(person_html(u), unsafe_allow_html=True)
            c2.button("👤 Profile", key=f"sr_prof_{u}", on_click=cb_view_profile, args=(u,))
        posts = [p for p in run("SELECT id, note, created_at, author_username FROM posts WHERE note ILIKE ? "
                                "ORDER BY created_at DESC LIMIT 30", (f"%{q}%",), "all") if p[3] not in hidden][:20]
        st.subheader(f"Posts ({len(posts)})")
        if not posts:
            st.caption("No posts found.")
        prefetch_people([p[3] for p in posts])
        media_by_post, comments_by_post = fetch_post_extras([p[0] for p in posts])
        for idx, post in enumerate(posts):
            render_post_card(idx, post, media_by_post.get(post[0], []), comments_by_post.get(post[0], []), "srch")

elif st.session_state.page == "alerts":
    banner("Alerts", "Friend requests, followers, likes, comments and messages.", "alerts")
    prev_seen = st.session_state.get("alerts_prev_seen", get_seen_at(current_user))
    items = alert_items(current_user)
    if not items:
        st.info("Nothing yet. When people follow you, like or comment on your posts, it shows up here.")
    if items:
        st.button("🧹 Clear all", key="al_clear_all", on_click=cb_dismiss_all_alerts, args=(current_user,))
    for i, (at, who, text, kind, ref) in enumerate(items):
        akey = alert_key((at, who, text, kind, ref))
        fresh = at > prev_seen
        tag = " · 🆕" if fresh else ""
        with st.container(border=True):
            c1, c2 = st.columns([6, 2])
            if kind == "group":
                c1.markdown(f"**👥 {html.escape(who)}**<br><span style='opacity:0.7;font-size:13px;'>{html.escape(text)}{tag}</span>",
                            unsafe_allow_html=True)
                c2.button("💬 Open", key=f"al_g_{ref}", on_click=cb_open_group, args=(ref,))
            else:
                c1.markdown(person_html(who, size=36, subtitle=html.escape(text) + tag), unsafe_allow_html=True)
                if kind == "dm":
                    c2.button("💬 Open", key=f"al_dm_{who}", on_click=cb_open_chat, args=(who,))
                elif kind == "request":
                    c2.button("👥 Friends", key=f"al_rq_{who}", on_click=cb_go_page, args=("friends",))
                else:
                    c2.button("👤 Profile", key=f"al_p_{i}", on_click=cb_view_profile, args=(who,))
            c2.button("✖ Dismiss", key=f"al_x_{akey}", on_click=cb_dismiss_alert, args=(current_user, akey))
            st.caption(f"🕒 {thai_time(at, '%d %b, %H:%M')}")

elif st.session_state.page == "admin":
    banner("Admin", "Only accounts on the admin list can see this page.", "admin")
    if not is_admin(current_user):
        st.info("This page isn't available.")
    else:
        n_users = run("SELECT COUNT(*) FROM users", fetch="one")[0]
        n_posts = run("SELECT COUNT(*) FROM posts", fetch="one")[0]
        n_reels = run("SELECT COUNT(*) FROM reels", fetch="one")[0]
        n_new = run("SELECT COUNT(*) FROM users WHERE last_seen > ?", ((utc_now() - timedelta(days=1)).isoformat(),), "one")[0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("People", n_users)
        m2.metric("Posts", n_posts)
        m3.metric("Reels", n_reels)
        m4.metric("Active today", n_new)

        st.subheader("⏱ Speed check")
        st.button("Test database speed", key="speed_btn", on_click=cb_speed_test)
        sr = st.session_state.get("speed_result")
        if sr:
            lo, avg, hi = sr
            st.metric("Database round trip (average)", f"{avg:.0f} ms")
            st.caption(f"fastest {lo:.0f} ms · slowest {hi:.0f} ms. Under 30 ms is great, 30 to 100 is fine, over 100 ms feels slow, "
                       "and every page needs many trips.")
        st.caption(f"Last page: {st.session_state.get('_dbq', 0)} database trips took {st.session_state.get('_dbt', 0):.1f} s.")

        reports = run("SELECT id, reporter, reported, reason, created_at FROM reports ORDER BY created_at DESC LIMIT 100", fetch="all")
        times_reported = dict(run("SELECT reported, COUNT(*) FROM reports GROUP BY reported", fetch="all"))
        st.subheader(f"🚩 Reports ({len(reports)})")
        if not reports:
            st.success("No reports. All quiet.")
        for rid, reporter, reported, reason, at in reports:
            with st.container(border=True):
                st.markdown(f"**{html.escape(get_display_name(reported))}** (@{html.escape(reported)}) "
                            f"was reported by **{html.escape(get_display_name(reporter))}** (@{html.escape(reporter)})",
                            unsafe_allow_html=True)
                st.caption(f"🕒 {thai_time(at, '%d %b %Y, %H:%M')} · reported {times_reported.get(reported, 1)} time(s) in total")
                st.markdown(f"> {html.escape(reason)}" if reason else "_No reason given._")
                b1, b2 = st.columns(2)
                b1.button("👤 View profile", key=f"adm_prof_{rid}", on_click=cb_view_profile, args=(reported,), use_container_width=True)
                b2.button("✅ Clear report", key=f"adm_clear_{rid}", on_click=cb_resolve_report, args=(rid, current_user), use_container_width=True)

elif st.session_state.page == "yuaan":
    banner("Yuaan", "Your built-in helper for captions, ideas and app tips.", "yuaan")

    my_avatar = get_avatar_path(current_user) or "👤"
    history = run("SELECT role, content FROM ai_messages WHERE username = ? ORDER BY created_at ASC",
                  (current_user,), "all")

    quick = [("✍️ Caption ideas", "caption ideas"), ("💡 Post ideas", "post ideas"), ("🎬 Reel ideas", "reel ideas"),
             ("😂 Joke", "tell me a joke"), ("❓ What can you do?", "what can you do?")]
    for row in (quick[:3], quick[3:]):
        for col, (label, text) in zip(st.columns(len(row)), row):
            col.button(label, key=f"yuaan_quick_{text}", on_click=cb_yuaan_quick, args=(text,), use_container_width=True)

    if history:
        st.button("🗑️ Clear chat", key="ai_clear", on_click=cb_clear_ai, args=(current_user,))
    else:
        st.caption("Say hi, or tap a button above. Yuaan is a built-in helper, not a full AI, so it works best with these topics.")

    for role, content in history[-100:]:
        with st.chat_message(role, avatar="🤖" if role == "assistant" else my_avatar):
            st.write(content)

    typed = st.chat_input("Message Yuaan...")
    prompt = typed or st.session_state.pop("yuaan_quick", None)
    if prompt and prompt.strip():
        text = prompt.strip()[:AI_MAX_CHARS]
        reply = yuaan_answer(history, text, current_user, display_name)
        with st.chat_message("user", avatar=my_avatar):
            st.write(text)
        with st.chat_message("assistant", avatar="🤖"):
            st.write(reply)
        run("INSERT INTO ai_messages (id, username, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (str(uuid.uuid4()), current_user, text, utc_now().isoformat()))
        run("INSERT INTO ai_messages (id, username, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
            (str(uuid.uuid4()), current_user, reply, utc_now().isoformat()))

    if st.session_state.get("yuaan_status"):
        st.warning("Real AI is off for the last message. " + st.session_state.yuaan_status)


# admin only: how heavy was this page? (this line is filled in last, after the page has been drawn)
if admin_mode and perf_slot is not None:
    perf_slot.caption(f"⏱ {st.session_state.get('_dbq', 0)} DB trips · {st.session_state.get('_dbt', 0):.1f}s in DB · "
                      f"{time.perf_counter() - _script_start:.1f}s total")
