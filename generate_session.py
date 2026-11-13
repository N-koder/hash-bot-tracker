#!/usr/bin/env python3
"""
Session String Generator for Telethon
Use this script locally to generate a Telethon SESSION_STRING.
Copy the generated string into your .env or Render environment variables.
"""

import os
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

def main():
    print("=" * 60)
    print("  Telegram User Client - Session String Generator")
    print("=" * 60)
    
    env_api_id = os.getenv("API_ID")
    env_api_hash = os.getenv("API_HASH")
    
    api_id_input = input(f"Enter API_ID [{env_api_id or 'none'}]: ").strip() or env_api_id
    api_hash_input = input(f"Enter API_HASH [{env_api_hash or 'none'}]: ").strip() or env_api_hash

    if not api_id_input or not api_hash_input:
        print("\n❌ Error: Both API_ID and API_HASH are required!")
        return

    try:
        api_id = int(api_id_input)
    except ValueError:
        print("\n❌ Error: API_ID must be an integer!")
        return

    print("\nConnecting to Telegram... You will be prompted for your phone number and login code.")
    
    with TelegramClient(StringSession(), api_id, api_hash_input) as client:
        session_str = client.session.save()
        print("\n" + "=" * 60)
        print("✅ SUCCESS! Here is your SESSION_STRING:")
        print("=" * 60)
        print(session_str)
        print("=" * 60)
        print("\n👉 Next steps:")
        print("1. Copy the string above.")
        print("2. Set SESSION_STRING=<the_string> in your .env or Render Environment Variables.")
        print("3. Keep this string secret! Anyone with this string can access your Telegram account.")

if __name__ == "__main__":
    main()
