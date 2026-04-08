import asyncio
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os
from dotenv import load_dotenv

# Load credentials from .env
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

print("Logging in to Telegram...")

# Start telethon. This will prompt you for your phone number and OTP in the console
with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()
    print("\n" + "="*50)
    print("✅ SUCCESS! Here is your SESSION_STRING:")
    print("="*50 + "\n")
    print(session_string)
    print("\n" + "="*50)
    print("⚠️  KEEP THIS SECRET! Anyone with this string can access your account.")
    print("👉 Add it as an Environment Variable named SESSION_STRING on Render.")
