import re
import os
import sys
import time
import asyncio
import logging
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request

from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession, MemorySession
from telethon.errors import (
    UserIsBlockedError,
    PeerIdInvalidError,
    FloodWaitError,
    ChatWriteForbiddenError
)
from pymongo import MongoClient, ASCENDING

# =========================
# ⚙️ LOGGING & ENV
# =========================
logging.basicConfig(
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("HashTrackerBot")

load_dotenv()

START_TIME = time.time()
BOT_VERSION = "2.0.0"

# =========================
# 🔐 CONFIGURATION
# =========================
API_ID_RAW = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()

if not all([API_ID_RAW, API_HASH, BOT_TOKEN, MONGO_URI]):
    logger.critical("Missing required environment variables: API_ID, API_HASH, BOT_TOKEN, MONGO_URI")
    sys.exit(1)

try:
    API_ID = int(API_ID_RAW)
except ValueError:
    logger.critical("API_ID must be an integer!")
    sys.exit(1)

# Admin IDs configuration (comma-separated support)
DEFAULT_ADMIN = 1947158378
admin_env = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID", str(DEFAULT_ADMIN))
ADMIN_IDS = set()
for a in admin_env.split(","):
    a = a.strip()
    if a.isdigit():
        ADMIN_IDS.add(int(a))
if not ADMIN_IDS:
    ADMIN_IDS.add(DEFAULT_ADMIN)

# Channel configuration (supports single or multiple channels: IDs or usernames)
CHANNEL_NAME = os.getenv("CHANNEL", "Monitored Channel")
channels_raw = os.getenv("CHANNEL_IDS") or os.getenv("CHANNEL_ID", "")
MONITORED_CHANNELS = []
for ch in channels_raw.split(","):
    ch = ch.strip()
    if not ch:
        continue
    if ch.startswith("-") or ch.isdigit():
        try:
            MONITORED_CHANNELS.append(int(ch))
        except ValueError:
            pass
    else:
        MONITORED_CHANNELS.append(ch)

logger.info(f"Loaded config: Admin IDs: {ADMIN_IDS}, Monitored Channels: {MONITORED_CHANNELS}")

# =========================
# 🍃 MONGODB & IN-MEMORY CACHE
# =========================
try:
    mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = mongo["telegram_bot"]
    collection = db["hashes"]
    users_collection = db["users"]
    blocked_collection = db["blocked_users"]
    mongo.server_info()  # trigger connection check
    logger.info("MongoDB connected successfully.")
except Exception as e:
    logger.critical(f"Failed to connect to MongoDB: {e}")
    sys.exit(1)

# Create DB Indexes for maximum read/write performance
try:
    collection.create_index([("hash_lower", ASCENDING), ("added_by", ASCENDING)], unique=True)
    collection.create_index([("hash_lower", ASCENDING)])
    users_collection.create_index([("user_id", ASCENDING)], unique=True)
    blocked_collection.create_index([("user_id", ASCENDING)], unique=True)
    logger.info("Database indexes verified/created.")
except Exception as e:
    logger.warning(f"Could not build indexes: {e}")

# High-speed in-memory caches to eliminate DB latency during live channel stream
# Hash map: normalized lowercase hash -> set of (user_id, nickname, original_hash)
HASH_CACHE = {}
BLOCKED_CACHE = set()

def reload_caches():
    """Reloads active hashes and blocked users into RAM for 0.1ms matching."""
    global HASH_CACHE, BLOCKED_CACHE
    try:
        new_hash_cache = {}
        for doc in collection.find():
            h_raw = doc.get("hash", "")
            h_lower = doc.get("hash_lower") or h_raw.lower()
            user_id = doc.get("added_by")
            nickname = doc.get("nickname", "")
            if not h_lower or not user_id:
                continue
            if h_lower not in new_hash_cache:
                new_hash_cache[h_lower] = []
            new_hash_cache[h_lower].append({
                "user_id": user_id,
                "nickname": nickname,
                "hash": h_raw
            })
        HASH_CACHE = new_hash_cache

        new_blocked = {b["user_id"] for b in blocked_collection.find()}
        BLOCKED_CACHE = new_blocked
        logger.info(f"Cache refreshed: {sum(len(v) for v in HASH_CACHE.values())} hash subscriptions, {len(BLOCKED_CACHE)} blocked users.")
    except Exception as e:
        logger.error(f"Error refreshing cache: {e}")

reload_caches()

def is_blocked(user_id: int) -> bool:
    return user_id in BLOCKED_CACHE

def block_user(user_id: int, username: str = "", first_name: str = ""):
    BLOCKED_CACHE.add(user_id)
    blocked_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "username": username or "NoUsername",
            "first_name": first_name or "",
            "blocked_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )

def unblock_user(user_id: int):
    BLOCKED_CACHE.discard(user_id)
    blocked_collection.delete_one({"user_id": user_id})

def save_user(user):
    try:
        user_id = user.id
        username = user.username or "NoUsername"
        first_name = user.first_name or ""
        users_collection.update_one(
            {"user_id": user_id},
            {"$setOnInsert": {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "first_seen": datetime.now(timezone.utc)
            }},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving user {user.id}: {e}")

def add_hash(h: str, user, nickname: str = "") -> bool:
    h_lower = h.lower()
    exists = collection.find_one({"hash_lower": h_lower, "added_by": user.id})
    if exists:
        return False

    collection.insert_one({
        "hash": h,
        "hash_lower": h_lower,
        "added_by": user.id,
        "username": user.username or "NoUsername",
        "first_name": user.first_name or "",
        "nickname": nickname,
        "created_at": datetime.now(timezone.utc)
    })

    # Update memory cache immediately
    if h_lower not in HASH_CACHE:
        HASH_CACHE[h_lower] = []
    HASH_CACHE[h_lower].append({
        "user_id": user.id,
        "nickname": nickname,
        "hash": h
    })
    logger.info(f"Added hash {h} for user {user.id} (@{user.username})")
    return True

def delete_hash(h: str, user_id: int) -> bool:
    h_lower = h.lower()
    res = collection.delete_one({"hash_lower": h_lower, "added_by": user_id})
    if res.deleted_count > 0:
        if h_lower in HASH_CACHE:
            HASH_CACHE[h_lower] = [item for item in HASH_CACHE[h_lower] if item["user_id"] != user_id]
            if not HASH_CACHE[h_lower]:
                del HASH_CACHE[h_lower]
        logger.info(f"Deleted hash {h} for user {user_id}")
        return True
    return False

def clear_user_hashes(user_id: int) -> int:
    res = collection.delete_many({"added_by": user_id})
    reload_caches()
    return res.deleted_count

def parse_bulk_hashes(text: str):
    """
    Parses a string that can contain one or more lines of hashtags with nicknames.
    Handles formats like:
      #BTC Bitcoin
      #ETH Ethereum
      🔹 #SOL Solana Alpha
      1. #ADA (Cardano L1)
      #PEPE - Meme coin
      #DOGE and #SHIB
    Returns a list of dicts: [{"hash": "#BTC", "nickname": "Bitcoin"}, ...]
    """
    items = []
    seen_lower = set()

    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        all_tags = re.findall(r"#[\w-]+", line)
        if len(all_tags) > 1:
            # If line has multiple hashtags, extract them without confusing them with nicknames
            for t in all_tags:
                t_lower = t.lower()
                if t_lower not in seen_lower:
                    seen_lower.add(t_lower)
                    items.append({"hash": t, "nickname": ""})
            continue

        # Single hashtag on this line: check for optional nickname / description
        match = re.search(r"(#[\w-]+)(?:\s+[-–—:]*\s*(.+))?", line)
        if match:
            tag = match.group(1)
            raw_nick = match.group(2).strip() if match.group(2) else ""
            # Strip outer brackets or quotes
            if (raw_nick.startswith("(") and raw_nick.endswith(")")) or \
               (raw_nick.startswith("[") and raw_nick.endswith("]")) or \
               (raw_nick.startswith('"') and raw_nick.endswith('"')) or \
               (raw_nick.startswith("'") and raw_nick.endswith("'")):
                raw_nick = raw_nick[1:-1].strip()

            tag_lower = tag.lower()
            if tag_lower not in seen_lower:
                seen_lower.add(tag_lower)
                items.append({"hash": tag, "nickname": raw_nick})

    return items

def add_hashes_bulk(items: list, user):
    """
    Bulk adds a list of parsed hashtag dictionaries for a user.
    Returns: (added_list, skipped_list)
    """
    if not items:
        return [], []

    tags_lower = [i["hash"].lower() for i in items]
    existing = set(
        doc["hash_lower"]
        for doc in collection.find({
            "hash_lower": {"$in": tags_lower},
            "added_by": user.id
        })
    )

    docs_to_insert = []
    added = []
    skipped = []

    for item in items:
        h = item["hash"]
        h_lower = h.lower()
        nick = item.get("nickname", "")

        if h_lower in existing:
            skipped.append(h)
            continue

        docs_to_insert.append({
            "hash": h,
            "hash_lower": h_lower,
            "added_by": user.id,
            "username": user.username or "NoUsername",
            "first_name": user.first_name or "",
            "nickname": nick,
            "created_at": datetime.now(timezone.utc)
        })

        if h_lower not in HASH_CACHE:
            HASH_CACHE[h_lower] = []
        HASH_CACHE[h_lower].append({
            "user_id": user.id,
            "nickname": nick,
            "hash": h
        })

        added.append({"hash": h, "nickname": nick})
        existing.add(h_lower)

    if docs_to_insert:
        collection.insert_many(docs_to_insert)
        logger.info(f"Bulk added {len(docs_to_insert)} hashes for user {user.id} (@{user.username})")

    return added, skipped

async def reply_bulk_result(event, added: list, skipped: list, title: str = "Bulk Hashes Processed"):
    lines = [f"📋 **{title}**\n"]
    if added:
        lines.append(f"✅ **Added {len(added)} tag(s):**")
        for item in added[:30]:
            nick = f" (*{item['nickname']}*)" if item.get("nickname") else ""
            lines.append(f"• `{item['hash']}`{nick}")
        if len(added) > 30:
            lines.append(f"• ...and {len(added) - 30} more.")
        lines.append("")

    if skipped:
        lines.append(f"⚠️ **Skipped {len(skipped)} (already tracked):**")
        for tag in skipped[:15]:
            lines.append(f"• `{tag}`")
        if len(skipped) > 15:
            lines.append(f"• ...and {len(skipped) - 15} more.")

    if not added and not skipped:
        lines.append("⚠️ No valid hashtags found.")

    await event.reply("\n".join(lines), parse_mode="md")

# =========================
# 🌐 RENDER HEALTH & WEB SERVER
# =========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        uptime_sec = int(time.time() - START_TIME)
        hours, remainder = divmod(uptime_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        if self.path in ["/health", "/healthz"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = (
                f'{{"status":"healthy","uptime":"{uptime_str}","version":"{BOT_VERSION}",'
                f'"channels":{len(MONITORED_CHANNELS)},"tracked_hashes":{len(HASH_CACHE)}}}'
            )
            self.wfile.write(body.encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Hash Tracker Telegram Bot</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #1e293b; padding: 2.5rem; border-radius: 1rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5); max-width: 450px; text-align: center; border: 1px solid #334155; }}
        .badge {{ display: inline-block; padding: 0.35rem 0.8rem; border-radius: 9999px; background: #10b981; color: #022c22; font-weight: bold; font-size: 0.85rem; margin-bottom: 1rem; }}
        h1 {{ margin: 0.5rem 0; font-size: 1.6rem; color: #38bdf8; }}
        p {{ color: #94a3b8; font-size: 0.95rem; margin: 0.4rem 0; }}
        .stats {{ display: flex; justify-content: space-around; margin-top: 1.5rem; border-top: 1px solid #334155; padding-top: 1rem; }}
        .stat-item {{ display: flex; flex-direction: column; }}
        .stat-val {{ font-size: 1.3rem; font-weight: bold; color: #f1f5f9; }}
        .stat-lbl {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="badge">ONLINE &amp; MONITORING</div>
        <h1>Telegram Hash Tracker</h1>
        <p>Ultra-fast real-time channel hashtag detection &amp; notification bot.</p>
        <div class="stats">
            <div class="stat-item"><span class="stat-val">{uptime_str}</span><span class="stat-lbl">Uptime</span></div>
            <div class="stat-item"><span class="stat-val">{len(HASH_CACHE)}</span><span class="stat-lbl">Unique Tags</span></div>
            <div class="stat-item"><span class="stat-val">{len(MONITORED_CHANNELS)}</span><span class="stat-lbl">Channels</span></div>
        </div>
    </div>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        # Silence default standard access logs to keep bot console clean
        return

def run_web():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Render HTTP Web Service listening on 0.0.0.0:{port}")
    server.serve_forever()

# Start HTTP Web Service in background daemon thread
threading.Thread(target=run_web, daemon=True).start()

# Keep-Alive Self-Ping Coroutine (Prevents Render Free Tier from sleeping)
async def keep_alive_worker():
    # Render automatically sets RENDER_EXTERNAL_URL if deployed as a web service
    ping_url = os.getenv("KEEP_ALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not ping_url:
        logger.info("KEEP_ALIVE_URL not configured. (To keep Render free tier awake 24/7, set KEEP_ALIVE_URL or use UptimeRobot).")
        return

    if not ping_url.startswith("http"):
        ping_url = f"https://{ping_url}"
    health_endpoint = f"{ping_url.rstrip('/')}/health"
    logger.info(f"Keep-Alive service initialized for: {health_endpoint}")

    while True:
        await asyncio.sleep(600)  # Ping every 10 minutes (Render sleeps after 15 mins)
        try:
            req = urllib.request.Request(
                health_endpoint,
                headers={"User-Agent": "HashTracker-KeepAlive/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(f"Keep-Alive ping successful: code {resp.status}")
        except Exception as e:
            logger.warning(f"Keep-Alive ping failed: {e}")

# =========================
# 👤 USER & 🤖 BOT CLIENTS
# =========================
is_headless = os.getenv("RENDER") or not sys.stdin.isatty()

if SESSION_STRING:
    logger.info("Initializing User Client with StringSession...")
    user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    if is_headless:
        logger.critical(
            "\n" + "=" * 70 + "\n"
            "🚨 CRITICAL ERROR: SESSION_STRING environment variable is MISSING!\n"
            "On Render (or headless servers), Telethon cannot prompt for your phone number.\n"
            "Run 'python generate_session.py' locally, copy the output, and add it to\n"
            "your Render Environment Variables as SESSION_STRING.\n" + "=" * 70
        )
        sys.exit(1)
    else:
        logger.info("No SESSION_STRING provided. Falling back to local file session 'user_session'...")
        user_client = TelegramClient("user_session", API_ID, API_HASH)

# Bot Client: uses MemorySession or bot_session so it doesn't fail on ephemeral disk
bot_client = TelegramClient(MemorySession(), API_ID, API_HASH)

# =========================
# ⚡ ASYNC FAST DISPATCHER
# =========================
async def async_send_to_user(user_id: int, text: str):
    """Asynchronously dispatches Telegram alerts using Telethon's native connection."""
    if is_blocked(user_id):
        return

    try:
        await bot_client.send_message(user_id, text, parse_mode="md")
    except UserIsBlockedError:
        logger.warning(f"User {user_id} has blocked the bot. Auto-blocking locally.")
        block_user(user_id)
    except FloodWaitError as e:
        logger.warning(f"Flood wait on sending to {user_id}: sleeping {e.seconds}s")
        await asyncio.sleep(e.seconds)
        try:
            await bot_client.send_message(user_id, text, parse_mode="md")
        except Exception:
            pass
    except (PeerIdInvalidError, ChatWriteForbiddenError) as e:
        logger.warning(f"Cannot send to user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending alert to {user_id}: {e}")

# =========================
# 🤖 BOT COMMANDS & UI
# =========================
async def check_user_blocked(event) -> bool:
    if is_blocked(event.sender_id):
        await event.reply("⛔ Your access to this bot is currently restricted.")
        return True
    return False

@bot_client.on(events.NewMessage(pattern=r"^/start$"))
async def start_cmd(event):
    if await check_user_blocked(event):
        return

    user = await event.get_sender()
    save_user(user)

    user_hashes_count = collection.count_documents({"added_by": user.id})

    text = (
        "🚀 **Welcome to Alpha Hash Tracker Bot!**\n\n"
        "I monitor designated Telegram channels in real-time and alert you "
        "the **exact millisecond** a matching hashtag (#alpha, #token, #ca) is mentioned.\n\n"
        f"📊 **Your active tracked hashes:** `{user_hashes_count}`\n\n"
        "**Quick Commands:**\n"
        "• `/addhash #tag [nickname]` — Add a hashtag to track\n"
        "• `/addbulk` — Add multiple hashtags & nicknames at once\n"
        "• `/delete #tag` — Stop tracking a hashtag\n"
        "• `/listhash` — View all your tracked tags\n"
        "• `/stats` — Bot & system status\n"
        "• `/help` — Full command guide\n\n"
        "💡 **Pro Tip:** Simply **forward** any post with hashtags to this bot to automatically track them with their nicknames!"
    )

    buttons = [
        [Button.inline("➕ Add Hash", b"action:add"), Button.inline("📜 My Hashes", b"action:list")],
        [Button.inline("📊 Statistics", b"action:stats"), Button.inline("❓ Help Guide", b"action:help")]
    ]
    await event.respond(text, buttons=buttons, parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/addhash(?:\s+([\s\S]+))?$"))
async def addhash_cmd(event):
    if await check_user_blocked(event):
        return

    user = await event.get_sender()
    save_user(user)

    raw = event.pattern_match.group(1)
    if not raw or not raw.strip():
        await event.reply(
            "⚠️ **Usage:** `/addhash #tag [optional nickname]`\n"
            "Example: `/addhash #SOL Solana Main`\n"
            "Example: `/addhash #0x1234abcd Contract`\n\n"
            "💡 For multiple tags at once, use `/addbulk` or send multiple lines!",
            parse_mode="md"
        )
        return

    raw = raw.strip()

    # If multiple lines or multiple hashtags exist, use bulk processor
    if "\n" in raw or len(re.findall(r"#[\w-]+", raw)) > 1:
        parsed = parse_bulk_hashes(raw)
        if parsed:
            added, skipped = add_hashes_bulk(parsed, user)
            await reply_bulk_result(event, added, skipped, title="Bulk Hashes Added")
            return

    match = re.search(r"(#[\w-]+)(?:\s+(.+))?", raw)
    if not match:
        tokens = raw.split(maxsplit=1)
        tag = "#" + tokens[0].lstrip("#")
        nickname = tokens[1].strip() if len(tokens) > 1 else ""
    else:
        tag = match.group(1)
        nickname = match.group(2).strip() if match.group(2) else ""

    if add_hash(tag, user, nickname):
        nick_str = f" (*{nickname}*)" if nickname else ""
        await event.reply(
            f"✅ **Tracking Enabled:** `{tag}`{nick_str}\n"
            f"You will receive immediate alerts when this hash is detected in monitored channels!",
            parse_mode="md"
        )
    else:
        await event.reply(f"⚠️ You are already tracking `{tag}`.", parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/(?:addbulk|bulk)(?:\s+([\s\S]+))?$"))
async def addbulk_cmd(event):
    if await check_user_blocked(event):
        return

    user = await event.get_sender()
    save_user(user)

    raw = event.pattern_match.group(1)
    if not raw or not raw.strip():
        if event.is_reply:
            reply = await event.get_reply_message()
            if reply:
                raw = reply.raw_text or reply.message or ""

    if not raw or not raw.strip():
        await event.reply(
            "📋 **Bulk Hash Add Guide**\n\n"
            "Send or reply with `/addbulk` followed by your list of hashtags & nicknames:\n\n"
            "```\n"
            "/addbulk\n"
            "#BTC Bitcoin\n"
            "#ETH Ethereum\n"
            "#SOL Solana Main\n"
            "#PEPE Meme Token\n"
            "```\n"
            "💡 You can also simply **forward any message** containing hashtags directly to this bot!",
            parse_mode="md"
        )
        return

    parsed = parse_bulk_hashes(raw)
    if not parsed:
        await event.reply("⚠️ No valid hashtags found. Ensure tags start with `#`.", parse_mode="md")
        return

    added, skipped = add_hashes_bulk(parsed, user)
    await reply_bulk_result(event, added, skipped, title="Bulk Hashes Added")

# =========================
# 📥 FORWARDED MESSAGE HANDLER
# =========================
@bot_client.on(events.NewMessage(func=lambda e: e.is_private and e.fwd_from is not None))
async def handle_forwarded_hashes(event):
    if await check_user_blocked(event):
        return

    text = event.raw_text or event.message.message or ""
    if not text or "#" not in text:
        return

    parsed = parse_bulk_hashes(text)
    if not parsed:
        return

    user = await event.get_sender()
    save_user(user)

    added, skipped = add_hashes_bulk(parsed, user)
    await reply_bulk_result(event, added, skipped, title="Forwarded Hashes Extracted & Saved")

@bot_client.on(events.NewMessage(pattern=r"^/delete(?: (.+))?$"))
async def delete_cmd(event):
    if await check_user_blocked(event):
        return

    user = await event.get_sender()
    raw = event.pattern_match.group(1)
    if not raw or not raw.strip():
        await event.reply("⚠️ **Usage:** `/delete #tag`\nExample: `/delete #SOL`", parse_mode="md")
        return

    tag = raw.strip().split()[0]
    if not tag.startswith("#"):
        tag = "#" + tag

    if delete_hash(tag, user.id):
        await event.reply(f"🗑 **Deleted:** `{tag}` will no longer trigger alerts for you.", parse_mode="md")
    else:
        await event.reply(f"❌ Hash `{tag}` was not found in your tracking list.", parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/listhash$"))
async def listhash_cmd(event):
    if await check_user_blocked(event):
        return

    user = await event.get_sender()
    hashes = list(collection.find({"added_by": user.id}).sort("created_at", -1))

    if not hashes:
        await event.reply(
            "📭 **You have no tracked hashes yet.**\nUse `/addhash #tag [nickname]` to start tracking.",
            buttons=[[Button.inline("➕ Add Your First Hash", b"action:add")]],
            parse_mode="md"
        )
        return

    text = f"📜 **Your Tracked Hashes ({len(hashes)}):**\n\n"
    for i, h in enumerate(hashes, 1):
        nick = f" — *{h.get('nickname')}*" if h.get("nickname") else ""
        text += f"`{i}.` `{h['hash']}`{nick}\n"

    text += "\nTo delete: `/delete #tag` | Clear all: `/clear`"
    await event.reply(text, parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/clear$"))
async def clear_cmd(event):
    if await check_user_blocked(event):
        return

    user = await event.get_sender()
    count = collection.count_documents({"added_by": user.id})
    if count == 0:
        await event.reply("📭 You don't have any hashes to clear.")
        return

    buttons = [
        [
            Button.inline("⚠️ Yes, Delete All", b"action:confirm_clear"),
            Button.inline("❌ Cancel", b"action:cancel_clear")
        ]
    ]
    await event.reply(f"⚠️ Are you sure you want to remove all **{count}** of your tracked hashes?", buttons=buttons, parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/stats$"))
async def stats_cmd(event):
    if await check_user_blocked(event):
        return

    user = await event.get_sender()
    user_count = collection.count_documents({"added_by": user.id})
    total_users = users_collection.count_documents({})
    total_active_hashes = len(HASH_CACHE)

    uptime_sec = int(time.time() - START_TIME)
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(remainder, 60)

    text = (
        "📊 **Bot Status & Statistics**\n\n"
        f"• **Your Tracked Hashes:** `{user_count}`\n"
        f"• **Total Active Tags in System:** `{total_active_hashes}`\n"
        f"• **Registered Users:** `{total_users}`\n"
        f"• **Monitored Channels:** `{len(MONITORED_CHANNELS)}`\n"
        f"• **System Uptime:** `{hours}h {minutes}m {seconds}s`\n"
        f"• **Bot Engine:** `Telethon MTProto + Async In-Memory Cache` ⚡"
    )
    await event.reply(text, parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/ping$"))
async def ping_cmd(event):
    t0 = time.time()
    msg = await event.reply("🏓 Pong...")
    latency = round((time.time() - t0) * 1000, 2)
    await msg.edit(f"🏓 **Pong!** `Latency: {latency} ms` ⚡")

@bot_client.on(events.NewMessage(pattern=r"^/help$"))
async def help_cmd(event):
    if await check_user_blocked(event):
        return

    text = (
        "🛠 **Hash Tracker Bot — Help Menu**\n\n"
        "**User Commands:**\n"
        "• `/addhash #tag [nickname]` — Add a single hash (or multiple lines) to watch list\n"
        "• `/addbulk` — Add a bulk list of hashtags & nicknames at once\n"
        "• `/delete #tag` — Remove a hash from your watch list\n"
        "• `/listhash` — View all your currently tracked hashes\n"
        "• `/clear` — Delete all of your tracked hashes\n"
        "• `/stats` — View bot performance and tracking metrics\n"
        "• `/ping` — Measure bot reaction latency\n"
        "• `/help` — Show this help message\n\n"
        "**Bulk & Forwarding Features:**\n"
        "• **Forward Messages:** Forward any post or list with `#hashtags` to this bot, and it will extract and save every hash and nickname automatically!\n"
        "• **Bulk Command:** Send `/addbulk` followed by:\n"
        "  `#BTC Bitcoin`\n"
        "  `#ETH Ethereum`\n"
        "  `#SOL Solana Main`\n\n"
        "**Tips:**\n"
        "• Hash matching is case-insensitive: `#BTC` matches `#btc` and `#Btc`.\n"
        "• Add a nickname to keep tags organized: `/addhash #0x839d Uniswap Pool`."
    )
    await event.reply(text, parse_mode="md")

# =========================
# 🔘 INLINE BUTTON HANDLERS
# =========================
@bot_client.on(events.CallbackQuery)
async def inline_buttons_handler(event):
    data = event.data.decode("utf-8", errors="ignore")
    user_id = event.sender_id

    if is_blocked(user_id):
        await event.answer("Access restricted.", alert=True)
        return

    if data == "action:add":
        await event.answer()
        await event.respond("➕ Send: `/addhash #yourtag [optional nickname]`", parse_mode="md")

    elif data == "action:list":
        await event.answer()
        hashes = list(collection.find({"added_by": user_id}).sort("created_at", -1))
        if not hashes:
            await event.respond("📭 You have no saved hashes.", parse_mode="md")
            return
        text = f"📜 **Your Tracked Hashes ({len(hashes)}):**\n\n"
        for i, h in enumerate(hashes[:25], 1):
            nick = f" ({h.get('nickname')})" if h.get("nickname") else ""
            text += f"`{i}.` `{h['hash']}`{nick}\n"
        if len(hashes) > 25:
            text += f"\n...and {len(hashes) - 25} more."
        await event.respond(text, parse_mode="md")

    elif data == "action:stats":
        await event.answer()
        user_count = collection.count_documents({"added_by": user_id})
        await event.respond(f"📊 You are currently monitoring **{user_count}** hashtags.", parse_mode="md")

    elif data == "action:help":
        await event.answer()
        await event.respond("💡 Use `/addhash #tag` to monitor tags or `/listhash` to see your list.")

    elif data == "action:confirm_clear":
        deleted = clear_user_hashes(user_id)
        await event.answer(f"Cleared {deleted} hashes!", alert=True)
        await event.edit(f"✅ Successfully deleted all **{deleted}** tracked hashes.")

    elif data == "action:cancel_clear":
        await event.answer("Cancelled")
        await event.edit("❌ Clear operation cancelled.")

# =========================
# 👑 ADMIN COMMANDS
# =========================
async def get_target_user(event, arg: str):
    if event.is_reply:
        reply = await event.get_reply_message()
        return await reply.get_sender()
    if arg:
        arg = arg.strip()
        if arg.startswith("@") or arg.lstrip("-").isdigit():
            try:
                entity_id = int(arg) if arg.lstrip("-").isdigit() else arg
                return await bot_client.get_entity(entity_id)
            except Exception:
                return None
    return None

@bot_client.on(events.NewMessage(pattern=r"^/admin$"))
async def admin_panel(event):
    if event.sender_id not in ADMIN_IDS:
        return
    text = (
        "👑 **Admin Control Panel**\n\n"
        "• `/users` — Show total & recent registered users\n"
        "• `/broadcast <message>` — Send alert/message to all users\n"
        "• `/block <@user|id>` — Restrict user from using bot\n"
        "• `/unblock <@user|id>` — Remove restriction\n"
        "• `/blocked` — View blocked users list\n"
        "• `/allhashes` — View unique tracked hashtags overview"
    )
    await event.reply(text, parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/users$"))
async def admin_users(event):
    if event.sender_id not in ADMIN_IDS:
        return

    total = users_collection.count_documents({})
    recent = list(users_collection.find().sort("_id", -1).limit(10))

    text = f"👥 **Bot User Statistics**\n\n📊 **Total Users:** `{total}`\n\n**Recent Users:**\n"
    for u in recent:
        uname = f"@{u['username']}" if u.get("username") and u['username'] != "NoUsername" else f"ID: `{u['user_id']}`"
        name = u.get("first_name", "")
        text += f"• {uname} ({name})\n"

    await event.reply(text, parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/broadcast(?: (.+))?$"))
async def admin_broadcast(event):
    if event.sender_id not in ADMIN_IDS:
        return

    msg = event.pattern_match.group(1)
    if not msg:
        await event.reply("⚠️ Usage: `/broadcast Your message here`", parse_mode="md")
        return

    users = [u["user_id"] for u in users_collection.find()]
    status_msg = await event.reply(f"📢 Broadcasting to {len(users)} users...")

    sent, failed = 0, 0
    broadcast_text = f"📢 **Announcement**\n\n{msg}"

    for uid in users:
        if is_blocked(uid):
            continue
        try:
            await bot_client.send_message(uid, broadcast_text, parse_mode="md")
            sent += 1
            await asyncio.sleep(0.05)  # slight spacing to avoid flood limit
        except Exception:
            failed += 1

    await status_msg.edit(f"✅ **Broadcast complete!**\n• Delivered: `{sent}`\n• Failed: `{failed}`")

@bot_client.on(events.NewMessage(pattern=r"^/block(?: (.+))?$"))
async def admin_block(event):
    if event.sender_id not in ADMIN_IDS:
        return

    arg = event.pattern_match.group(1)
    target = await get_target_user(event, arg)
    if not target:
        await event.reply("❌ Target user not found. Reply to user or use `/block @username` or user ID.")
        return

    block_user(target.id, getattr(target, "username", ""), getattr(target, "first_name", ""))
    await event.reply(f"🚫 User `{target.id}` (@{getattr(target, 'username', 'none')}) has been blocked.")

@bot_client.on(events.NewMessage(pattern=r"^/unblock(?: (.+))?$"))
async def admin_unblock(event):
    if event.sender_id not in ADMIN_IDS:
        return

    arg = event.pattern_match.group(1)
    target = await get_target_user(event, arg)
    if not target:
        if arg and arg.strip().isdigit():
            uid = int(arg.strip())
            unblock_user(uid)
            await event.reply(f"✅ Unblocked ID `{uid}`.")
            return
        await event.reply("❌ User not found.")
        return

    unblock_user(target.id)
    await event.reply(f"✅ User `{target.id}` unblocked.")

@bot_client.on(events.NewMessage(pattern=r"^/blocked$"))
async def admin_blocked_list(event):
    if event.sender_id not in ADMIN_IDS:
        return

    blocked = list(blocked_collection.find())
    if not blocked:
        await event.reply("✅ No users are currently blocked.")
        return

    text = f"🚫 **Blocked Users ({len(blocked)}):**\n\n"
    for b in blocked:
        uname = f"@{b['username']}" if b.get("username") and b['username'] != "NoUsername" else f"ID: `{b['user_id']}`"
        text += f"• {uname} ({b.get('first_name', '')})\n"

    await event.reply(text, parse_mode="md")

@bot_client.on(events.NewMessage(pattern=r"^/allhashes$"))
async def admin_all_hashes(event):
    if event.sender_id not in ADMIN_IDS:
        return

    text = f"🔑 **Active Tracked Hashtags ({len(HASH_CACHE)} unique):**\n\n"
    for tag_lower, subscribers in list(HASH_CACHE.items())[:30]:
        text += f"• `{tag_lower}` — {len(subscribers)} subscribers\n"

    await event.reply(text, parse_mode="md")

# =========================
# 📡 ULTRA-FAST CHANNEL LISTENER
# =========================
listener_filter = events.NewMessage(chats=MONITORED_CHANNELS) if MONITORED_CHANNELS else events.NewMessage()

@user_client.on(listener_filter)
async def channel_listener(event):
    try:
        raw_text = event.raw_text or event.message.message or ""
        if not raw_text:
            return

        # Fast regex extraction of all hashtags
        found_tags = re.findall(r"#[\w-]+", raw_text)
        if not found_tags:
            return

        now_str = datetime.now().strftime("%H:%M:%S UTC")
        chat_title = getattr(event.chat, "title", CHANNEL_NAME) or CHANNEL_NAME
        chat_username = getattr(event.chat, "username", None)

        # Message link if available
        msg_link = f"https://t.me/{chat_username}/{event.id}" if chat_username else None
        link_str = f"\n🔗 [View Original Message]({msg_link})" if msg_link else ""

        # Collect unique subscribers to notify concurrently
        notified_users = set()
        tasks = []

        for tag in found_tags:
            tag_lower = tag.lower()
            subscribers = HASH_CACHE.get(tag_lower)
            if not subscribers:
                continue

            for sub in subscribers:
                user_id = sub["user_id"]
                if user_id in notified_users or is_blocked(user_id):
                    continue

                notified_users.add(user_id)
                nickname = sub.get("nickname")
                hash_display = f"`{tag}` (*{nickname}*)" if nickname else f"`{tag}`"

                alert = (
                    "🚨 **ALPHA DETECTED**\n\n"
                    f"🔑 **Hashtag:** {hash_display}\n"
                    f"📡 **Source:** {chat_title}\n"
                    f"⏰ **Time:** `{now_str}`\n\n"
                    f"💬 **Message Content:**\n{raw_text}\n"
                    f"{link_str}"
                )

                # Fire concurrent non-blocking async send tasks
                tasks.append(async_send_to_user(user_id, alert))

        if tasks:
            logger.info(f"⚡ Matched tags {found_tags}. Dispatching {len(tasks)} notifications...")
            await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        logger.error(f"Error in channel listener: {e}", exc_info=True)

# =========================
# 🚀 MAIN RUNNER
# =========================
async def main():
    logger.info("Starting Telegram clients...")

    # Start User Client
    try:
        await user_client.start()
        user_me = await user_client.get_me()
        logger.info(f"✅ User Client connected as: {user_me.first_name} (ID: {user_me.id})")
    except Exception as e:
        logger.critical(f"Failed to start User Client: {e}")
        sys.exit(1)

    # Start Bot Client
    try:
        await bot_client.start(bot_token=BOT_TOKEN)
        bot_me = await bot_client.get_me()
        logger.info(f"✅ Bot Client connected as: @{bot_me.username} (ID: {bot_me.id})")
    except Exception as e:
        logger.critical(f"Failed to start Bot Client: {e}")
        sys.exit(1)

    logger.info("🚀 Hash Tracker is LIVE and actively monitoring channels!")

    # Start Keep-Alive loop in background task
    asyncio.create_task(keep_alive_worker())

    # Keep both clients running
    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot_client.run_until_disconnected()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped cleanly.")
