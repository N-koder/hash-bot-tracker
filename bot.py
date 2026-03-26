from telethon import TelegramClient, events, Button
from pymongo import MongoClient
import re
import requests
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# 🤖 BOT DETAILS
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

# 🔑 TELEGRAM USER CLIENT (Telethon)
api_id = int(os.getenv("API_ID"))        # from my.telegram.org
api_hash = os.getenv("API_HASH")

client = TelegramClient('session', api_id, api_hash)

# # Your database (can be file/db later)
# hash_db = {"#afebdd21", "#881a764b"}  

# 🍃 MongoDB connection
MONGO_URI = os.getenv("MONGO_URI")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client["telegram_bot"]
collection = db["hashes"]

# Channel username or ID
channel = os.getenv("CHANNEL")

# 🚀 Create client
client = TelegramClient("session", api_id, api_hash)

# -------------------------------
# 📩 SEND MESSAGE FUNCTION
# -------------------------------

def send_telegram_alert(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }

    requests.post(url, data=payload)

# -------------------------------
# 🧠 DB FUNCTIONS
# -------------------------------
def hash_exists(h):
    return collection.find_one({"hash": h}) is not None

def add_hash(h):
    if not hash_exists(h):
        collection.insert_one({"hash": h})
        return True
    return False

# -------------------------------
# 🚀 /start COMMAND
# -------------------------------
@client.on(events.NewMessage(pattern="/start"))
async def start(event):
    if event.is_private:
        await event.respond(
            "👋 *Welcome to Hash Tracker Bot*\n\n"
            "🚀 Track token hashes in real-time\n"
            "⚡ Get instant alerts instantly\n\n"
            "*Commands:*\n"
            "➕ /addhash #hash\n"
            "📜 /listhash\n"
            "❓ /help\n\n"
            "Stay ahead. Stay early. 📈",
            buttons=[
                [Button.inline("➕ Add Hash", b"add")],
                [Button.inline("📜 View Hashes", b"list")]
            ],
            parse_mode="Markdown"
        )

# -------------------------------
# ➕ /addhash COMMAND
# -------------------------------
@client.on(events.NewMessage(pattern=r"/addhash (.+)"))
async def addhash_cmd(event):
    if event.is_private:
        user_input = event.pattern_match.group(1).strip()

        if not user_input.startswith("#"):
            await event.reply("⚠️ Please provide hash like: /addhash #abc123")
            return

        if add_hash(user_input):
            await event.reply(f"✅ Hash added: {user_input}", parse_mode="Markdown")
        else:
            await event.reply("⚠️ Hash already exists")

# -------------------------------
# 📜 /listhash COMMAND
# -------------------------------
@client.on(events.NewMessage(pattern=r"/listhash"))
async def list_hash(event):
    if event.is_private:
        hashes = list(collection.find().limit(20))

        if not hashes:
            await event.reply("📭 No hashes found")
            return

        text = "📜 Stored Hashes:\n\n"
        for h in hashes:
            text += f"{h['hash']}\n"

        await event.reply(text , parse_mode="Markdown")

# -------------------------------
# ❓ /help COMMAND
# -------------------------------
@client.on(events.NewMessage(pattern=r"/help"))
async def help_cmd(event):
    if event.is_private:
        await event.reply(
            "🛠 Commands:\n\n"
            "/addhash #hash → Add hash\n"
            "/listhash → Show hashes\n"
            "/help → Help menu",
            parse_mode="Markdown"
        )

# -------------------------------
# 🎯 BUTTON HANDLER
# -------------------------------
@client.on(events.CallbackQuery)
async def buttons(event):
    data = event.data.decode()

    if data == "add":
        await event.respond("➕ Send: /addhash #yourhash")

    elif data == "list":
        hashes = list(collection.find().limit(10))
        text = "📜 Hashes:\n\n"
        for h in hashes:
            text += f"{h['hash']}\n"
        await event.respond(text)


# -------------------------------
# 📡 CHANNEL LISTENER
# -------------------------------

@client.on(events.NewMessage(chats=channel))
async def handler(event):
    try:
        message = event.message.message

        print("\n📩 New Message:")
        print(message)

        found_hashes = re.findall(r"#\w+", message)

        for h in found_hashes:
            if hash_exists(h):
                time = datetime.now().strftime("%H:%M:%S")
                print("🚨 MATCH FOUND:", h)

                alert = (
                    f"🚨 *ALPHA DETECTED*\n\n"
                    f"🔑 Hash: `{h}`\n"
                    f"📡 Channel: {channel}\n"
                    f"⏰ Time: {time}\n\n"
                    f"{message}"
                )
                print("🚨 MATCH FOUND:", h)
                send_telegram_alert(alert)


    except Exception as e:
        print("❌ Error:", e)


# ▶ Start bot
print("🚀 Bot is running...")
send_telegram_alert("🚀 Bot is running...")
client.start()
client.run_until_disconnected()



# @client.on(events.NewMessage)
# async def handler(event):
#     try:
#         # Only process messages from target channel
#         if event.chat.username != channel:
#             return

#         message = event.message.message
#         print("\n📩 New Message:")
#         print(message)

#         # 🔍 Extract hashes
#         found_hashes = re.findall(r"#\w+", message)

#         for h in found_hashes:
#             if hash_exists(h):
#                 print("🚨 MATCH FOUND:", h)

#                 await client.send_message(
#                     "me",
#                     f"🚨 MATCH FOUND: {h}\n\n{message}"
#                 )

#     except Exception as e:
#         print("❌ Error:", e)

# @client.on(events.NewMessage(chats=channel))
# async def handler(event):
#     try:
#         await client.send_message( "me", "Bot running...")
#         message = event.message.message


#         print("\n📩 New Message:")
#         print(message)

#         found_hashes = re.findall(r"#\w+", message)

#         for h in found_hashes:
#             if hash_exists(h):
#                 print("🚨 MATCH FOUND:", h)

#                 await client.send_message(
#                     "me",
#                     f"🚨 MATCH FOUND: {h}\n\n{message}"
#                 )

#     except Exception as e:
#         print("❌ Error:", e)
