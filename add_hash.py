from pymongo import MongoClient

MONGO_URI = "mongodb+srv://n8168397_db_user:tqY8IrAvUzJ2C6ik@hashtracker.zgfz5en.mongodb.net/?appName=hashtracker"

client = MongoClient(MONGO_URI)
collection = client["telegram_bot"]["hashes"]

new_hash = input("Enter hash: ")

if collection.find_one({"hash": new_hash}):
    print("⚠️ Already exists")
else:
    collection.insert_one({"hash": new_hash})
    print("✅ Hash added")