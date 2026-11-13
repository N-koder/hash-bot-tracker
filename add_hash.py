#!/usr/bin/env python3
"""
CLI helper to add hashes directly to the database.
Reads connection details from .env.
"""

import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    print("❌ Error: MONGO_URI is not set in .env")
    exit(1)

client = MongoClient(MONGO_URI)
db = client["telegram_bot"]
collection = db["hashes"]

def main():
    new_hash = input("Enter hash (e.g. #BTC): ").strip()
    if not new_hash:
        print("⚠️ Hash cannot be empty")
        return

    if not new_hash.startswith("#"):
        new_hash = "#" + new_hash

    nickname = input("Enter nickname (optional): ").strip()
    user_id_input = input("Enter Telegram User ID (press enter for system default 0): ").strip()
    user_id = int(user_id_input) if user_id_input.isdigit() else 0

    exists = collection.find_one({"hash": new_hash, "added_by": user_id})
    if exists:
        print("⚠️ Already exists for this user")
    else:
        collection.insert_one({
            "hash": new_hash,
            "added_by": user_id,
            "username": "CLI_Admin",
            "first_name": "Admin",
            "nickname": nickname
        })
        print(f"✅ Hash {new_hash} added successfully!")

if __name__ == "__main__":
    main()
