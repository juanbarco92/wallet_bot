
import asyncio
import os
from telegram import Bot
from dotenv import load_dotenv

async def get_chat_id():
    load_dotenv()
    token_key = "TELEGRAM_TOKEN_LEY"
    token = os.getenv(token_key)
    
    if not token:
        print(f"❌ Error: {token_key} not found in .env")
        return

    try:
        bot = Bot(token=token)
        bot_info = await bot.get_me()
        print(f"🤖 Bot identified: @{bot_info.username}")
        print(f"👉 Please send a message to @{bot_info.username} NOW.")
        print("⏳ Waiting for updates...")
        
        # Simple polling loop
        offset = None
        while True:
            try:
                updates = await bot.get_updates(offset=offset, timeout=10)
                if updates:
                    for u in updates:
                        offset = u.update_id + 1
                        if u.message:
                            chat = u.message.chat
                            user = u.message.from_user
                            print(f"\n✅ Message received!")
                            print(f"   From: {user.first_name} (ID: {user.id})")
                            print(f"   Chat ID: {chat.id}")
                            print(f"   Type: {chat.type}")
                            print(f"\n� If this is Leydi, copy the ID: {chat.id}")
                            print("   Waiting for more messages... (Ctrl+C to stop)\n")
            except Exception as e:
                print(f"Polling error: {e}")
                await asyncio.sleep(2)
            
            await asyncio.sleep(1)

    except Exception as e:
        print(f"❌ Error initializing bot: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(get_chat_id())
    except KeyboardInterrupt:
        print("Stopped.")
