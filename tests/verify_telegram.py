import asyncio
import os
import sys
from telegram import Bot
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def verify_telegram():
    load_dotenv()
    token = os.getenv("TELEGRAM_TOKEN_JUANMA")
    chat_id = os.getenv("TELEGRAM_CHAT_ID_JUANMA")

    print("--- Verifying Telegram Bot ---")

    if not token:
        print("❌ Error: TELEGRAM_TOKEN_JUANMA missing in .env")
        return

    try:
        bot = Bot(token=token)
        bot_info = await bot.get_me()
        print(f"✅ Bot Authentication Successful! Bot Name: @{bot_info.username}")
        
        if not chat_id:
            print("⚠️ Warning: TELEGRAM_CHAT_ID_JUANMA missing in .env")
            print("   To get your Chat ID:")
            print(f"   1. Send /start to @{bot_info.username} on Telegram.")
            print("   2. Run the main bot script (`poetry run python main.py`).")
            print("   3. Check the logs/console output for your Chat ID.")
            print("   4. Add it to .env: TELEGRAM_CHAT_ID_JUANMA=your_id")
        else:
            print(f"   Attempting to send test message to Chat ID: {chat_id}")
            try:
                await bot.send_message(chat_id=chat_id, text="✅ AutoTrx: Test Message. Telegram connection is working!")
                print("✅ Test message sent successfully! Check your Telegram.")
            except Exception as e:
                print(f"❌ Failed to send message: {e}")
                print("   - Verify that you have started a conversation with the bot.")
                print("   - Verify the Chat ID is correct.")

    except Exception as e:
        print(f"❌ General Telegram Error: {e}")

if __name__ == "__main__":
    asyncio.run(verify_telegram())
