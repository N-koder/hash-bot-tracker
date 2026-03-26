import re
import os
import asyncio
import requests
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from pymongo import MongoClient


import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


# =========================
# 🔐 LOAD ENV
# =========================
load_dotenv()

# web-service free hack

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web():
    server = HTTPServer(('0.0.0.0', 10000), Handler)
    server.serve_forever()

threading.Thread(target=run_web).start()








API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHANNEL = os.getenv("CHANNEL")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# =========================
# 👤 USER CLIENT (READ CHANNEL)
# =========================
user_client = TelegramClient("user_session", API_ID, API_HASH)

# =========================
# 🤖 BOT CLIENT (PUBLIC BOT)
# =========================
bot_client = TelegramClient("bot_session", API_ID, API_HASH)

# =========================
# 🍃 DATABASE
# =========================
mongo = MongoClient(MONGO_URI)
db = mongo["telegram_bot"]
collection = db["hashes"]
users_collection = db["users"]

# =========================
# 🧠 DB HELPERS
# =========================
def hash_exists(h):
    return collection.find_one({"hash": h}) is not None

def add_hash(h, user):
    if hash_exists(h):
        return False

    collection.insert_one({
        "hash": h,
        "added_by": user.id,
        "username": user.username if user.username else "NoUsername",
        "first_name": user.first_name if user.first_name else "",
        "created_at": datetime.utcnow()
    })
    return True

def get_hashes(limit=20):
    return [x["hash"] for x in collection.find().limit(limit)]

def delete_hash(h):
    return collection.delete_one({"hash": h}).deleted_count > 0

def save_user(user):
    user_id = user.id
    username = user.username if user.username else "NoUsername"
    first_name = user.first_name if user.first_name else ""

    if not users_collection.find_one({"user_id": user_id}):
        users_collection.insert_one({
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "first_seen": datetime.utcnow()
        })

def get_all_users():
    return [u["user_id"] for u in users_collection.find()]

# =========================
# 📢 BROADCAST ALERT
# =========================
def broadcast_alert(text):
    users = get_all_users()

    for user_id in users:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, data={
                "chat_id": user_id,
                "text": text,
                "parse_mode": "Markdown"
            })
        except:
            continue


def send_to_user(user_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": user_id,
            "text": text,
            "parse_mode": "Markdown"
        })
    except:
        pass

# =========================
# 🤖 BOT COMMANDS
# =========================

@bot_client.on(events.NewMessage(pattern="/start"))
async def start(event):
    user = await event.get_sender()
    save_user(user)

    await event.respond(
        "🚀 *Hash Tracker Bot*\n\n"
        "✔ Live monitoring enabled\n"
        "✔ Multi-user alerts\n\n"
        "/addhash #hash\n"
        "/delete #hash\n"
        "/listhash\n"
        "/help",
        buttons=[
            [Button.inline("➕ Add Hash", b"add")],
            [Button.inline("📜 View Hashes", b"list")]
        ],
        parse_mode="Markdown"
    )

@bot_client.on(events.NewMessage(pattern=r"/addhash (.+)"))
async def addhash_cmd(event):
    user = await event.get_sender()
    save_user(user)

    h = event.pattern_match.group(1).strip()

    if not h.startswith("#"):
        await event.reply("⚠️ Use: /addhash #abc123")
        return

    if add_hash(h, user):
        await event.reply(f"✅ Added: `{h}`", parse_mode="Markdown")
    else:
        await event.reply("⚠️ Already exists")
@bot_client.on(events.NewMessage(pattern=r"/delete (.+)"))
async def delete_cmd(event):
    user = await event.get_sender()
    h = event.pattern_match.group(1).strip()

    if not h.startswith("#"):
        await event.reply("⚠️ Use: /delete #abc123")
        return

    data = collection.find_one({"hash": h})

    if not data:
        await event.reply("❌ Hash not found")
        return

    # optional: only owner can delete
    if data["added_by"] != user.id:
        await event.reply("⛔ You can only delete your own hashes")
        return

    if delete_hash(h):
        await event.reply(f"🗑 Deleted `{h}`", parse_mode="Markdown")
    else:
        await event.reply("❌ Failed to delete")

@bot_client.on(events.NewMessage(pattern="/listhash"))
async def listhash(event):
    user = await event.get_sender()
    user_id = user.id

    hashes = list(collection.find({"added_by": user_id}))

    if not hashes:
        await event.reply("📭 You have no hashes saved")
        return

    text = "📜 *Your Hashes:*\n\n"

    for h in hashes:
        text += f"🔹 `{h['hash']}`\n"

    await event.reply(text, parse_mode="Markdown")

@bot_client.on(events.NewMessage(pattern="/help"))
async def help_cmd(event):
    user = await event.get_sender()
    save_user(user)

    await event.reply(
        "🛠 *Help Menu*\n\n"
        "➕ /addhash #hash\n"
        "➖ /delete #hash\n"
        "📜 /listhash\n"
        "❓ /help",
        parse_mode="Markdown"
    )

@bot_client.on(events.NewMessage(pattern="/users"))
async def users_cmd(event):

    total = users_collection.count_documents({})
    last_users = users_collection.find().sort("_id", -1).limit(10)

    text = (
        f"👥 *Bot Users*\n\n"
        f"📊 Total Users: {total}\n\n"
        f"🧾 Last Users:\n"
    )

    for u in last_users:
        username = u.get("username", "NoUsername")
        first_name = u.get("first_name", "")

        if username != "NoUsername":
            text += f"- @{username}\n"
        else:
            text += f"- {first_name} (no username)\n"

    await event.reply(text, parse_mode="Markdown")

@bot_client.on(events.CallbackQuery)
async def buttons(event):
    data = event.data.decode()

    if data == "add":
        await event.respond("➕ Send: /addhash #yourhash")

    elif data == "list":
        await event.respond("📜 Hashes:\n\n" + "\n".join(get_hashes(10)))

# =========================
# 📡 CHANNEL LISTENER (USER CLIENT)
# =========================
@user_client.on(events.NewMessage(chats=CHANNEL_ID))
async def listener(event):
    try:
        message = event.message.message
        print("📩 CHANNEL:", message)

        found = re.findall(r"#\w+", message)

        if not found:
            return

        for h in found:
            data = collection.find_one({"hash": h})

            if data:
                user_id = data["added_by"]

                alert = (
                    "🚨 *ALPHA DETECTED*\n\n"
                    f"🔑 Hash: `{h}`\n"
                    f"📡 Channel: {CHANNEL}\n"
                    f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
                    f"{message}"
                )

                print(f"🚨 Sending to {user_id}")

                send_to_user(user_id, alert)

    except Exception as e:
        print("❌ Error:", e)

# =========================
# 🚀 RUN BOTH CLIENTS
# =========================
async def main():
    print("STEP 1 reached")
    await user_client.start()  # will ask OTP first time
    print("STEP 2 user started")
    await bot_client.start(bot_token=BOT_TOKEN)
    print("STEP 3 bot started")

    print("🚀 Bot is running...")
    broadcast_alert("🚀 Bot is running...")

    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot_client.run_until_disconnected()
    )

if __name__ == "__main__":
    asyncio.run(main())