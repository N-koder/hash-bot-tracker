import re
import os
import asyncio
import requests
from datetime import datetime, UTC
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
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
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), Handler)
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
SESSION_STRING = os.getenv("SESSION_STRING")
if SESSION_STRING:
    user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
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
blocked_collection = db["blocked_users"]

# =========================
# 🧠 DB HELPERS
# =========================
def hash_exists(h):
    return collection.find_one({"hash": h}) is not None

def add_hash(h, user):
    # ✅ check only for THIS user
    exists = collection.find_one({
        "hash": h,
        "added_by": user.id
    })

    if exists:
        return False

    collection.insert_one({
        "hash": h,
        "added_by": user.id,
        "username": user.username if user.username else "NoUsername",
        "first_name": user.first_name if user.first_name else "",
        "created_at": datetime.now(UTC)
    })
    print("hash added : ",h , "by user : " , user.username)
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
            "first_seen": datetime.now(UTC)
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
     # 🚫 skip blocked users
    if is_blocked(user_id):
        print(f"⛔ Skipped blocked user {user_id}")
        return
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": user_id,
            "text": text,
            "parse_mode": "Markdown"
        })
    except:
        pass


 # Helper to get user

async def get_user_from_input(event, arg):
    # case 1: reply
    if event.is_reply:
        reply = await event.get_reply_message()
        return await reply.get_sender()

    # case 2: username
    if arg.startswith("@"):
        try:
            return await bot_client.get_entity(arg)
        except:
            return None

    # case 3: user_id
    if arg.isdigit():
        try:
            return await bot_client.get_entity(int(arg))
        except:
            return None

    return None


def is_blocked(user_id):
    return blocked_collection.find_one({"user_id" : user_id}) is not None

def block_user(user):
    if not is_blocked(user.id):
        blocked_collection.insert_one({
            "user_id": user.id,
            "username": user.username if user.username else "NoUsername",
            "first_name": user.first_name if user.first_name else "",
            "blocked_at": datetime.now(UTC)
        })

def unblock_user(user_id):
    blocked_collection.delete_one({"user_id" : user_id})



# =========================
# Global check
# =========================

async def check_block(event):
    print(f"Checking if user {event.sender_id} is blocked...", flush=True)
    if is_blocked(event.sender_id):
        await event.reply("SORRY! we are out of service :(")
        return True
    return False

# =========================
# 🤖 BOT COMMANDS
# =========================

@bot_client.on(events.NewMessage(pattern="/start"))
async def start(event):
    print("Received /start command!", flush=True)
    if await check_block(event):
        return
    
    print("User is not blocked, saving user to DB...", flush=True)
    user = await event.get_sender()
    save_user(user)
    
    print("Responding to /start command...", flush=True)

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
    if await check_block(event):
        return
    
    user = await event.get_sender()
    save_user(user)

    raw = event.pattern_match.group(1).strip()

    # ✅ extract only hash
    match = re.search(r"#\w+", raw)

    if not match:
        await event.reply("⚠️ Invalid format. Use: /addhash #abc123")
        return

    h = match.group(0)

    if add_hash(h, user):
        await event.reply(f"✅ Added: `{h}`", parse_mode="Markdown")
    else:
        await event.reply("⚠️ Already exists")


@bot_client.on(events.NewMessage(pattern=r"/delete (.+)"))
async def delete_cmd(event):
    if await check_block(event):
        return
    
    user = await event.get_sender()

    raw = event.pattern_match.group(1).strip()

    # ✅ extract only hash (same as add)
    match = re.search(r"#\w+", raw)

    if not match:
        await event.reply("⚠️ Use: /delete #abc123")
        return

    h = match.group(0)

    # 🔥 find ALL entries for this hash
    data = collection.find_one({
        "hash": h,
        "added_by": user.id
    })

    if not data:
        await event.reply("❌ Hash not found or not yours")
        return

    # ✅ delete ONLY user's own hash
    result = collection.delete_one({
        "hash": h,
        "added_by": user.id
    })

    if result.deleted_count > 0:
        await event.reply(f"🗑 Deleted `{h}`", parse_mode="Markdown")
    else:
        await event.reply("❌ Failed to delete")

@bot_client.on(events.NewMessage(pattern="/listhash"))
async def listhash(event):
    if await check_block(event):
        return
    
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
    if await check_block(event):
        return
    
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

    if await check_block(event):
        return

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



@bot_client.on(events.NewMessage(pattern=r"/block(?: (.+))?"))
async def block_cmd(event):
    if(event.sender_id != 1947158378):
        return
    
    arg = event.pattern_match.group(1)
    user = await get_user_from_input(event, arg if arg else "")

    if not user:
        await event.reply("❌ User not found\nUse: /block @username")
        return

    block_user(user)

    name = f"@{user.username}" if user.username else user.first_name
    await event.reply(f"🚫 Blocked {name}")


@bot_client.on(events.NewMessage(pattern=r"/unblock(?: (.+))?"))
async def unblock_cmd(event):
    if(event.sender_id != 1947158378):
        return
    
    arg = event.pattern_match.group(1)

    user = await get_user_from_input(event, arg if arg else "")

    if not user:
        await event.reply("❌ User not found\nUse: /unblock @username or reply")
        return

    unblock_user(user.id)

    name = f"@{user.username}" if user.username else user.first_name
    await event.reply(f"✅ Unblocked {name}")

@bot_client.on(events.NewMessage(pattern="/blocked"))
async def blocked_list(event):
    if event.sender_id != 1947158378:
        return

    users = blocked_collection.find()

    text = "🚫 *Blocked Users:*\n\n"

    for u in users:
        if u["username"] != "NoUsername":
            text += f"- @{u['username']}\n"
        else:
            text += f"- {u['first_name']} ({u['user_id']})\n"

    await event.reply(text, parse_mode="Markdown")

# =========================
# 📡 CHANNEL LISTENER (USER CLIENT)
# =========================
@user_client.on(events.NewMessage(chats=CHANNEL_ID))
async def listener(event):
    try:
        message = event.message.message
        print("📩 CHANNEL:", message)

        # extract hashes
        found = re.findall(r"#\w+", message)

        if not found:
            return

        sent_users = set()  # prevent duplicate alerts

        for h in found:
            # 🔥 get ALL users who added this hash
            users = collection.find({"hash": h})

            for data in users:
                user_id = data["added_by"]

                # 🧠 avoid duplicate send
                if user_id in sent_users:
                    continue

                sent_users.add(user_id)

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
    print("STEP 1 reached", flush=True)
    await user_client.start()  # Make sure session string is set for Render, or this will block waiting for OTP
    print("STEP 2 user started", flush=True)
    await bot_client.start(bot_token=BOT_TOKEN)
    print("🚀 Bot is running...", flush=True)
    # broadcast_alert("🚀 Bot is running...")

    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot_client.run_until_disconnected()
    )

if __name__ == "__main__":
    asyncio.run(main())