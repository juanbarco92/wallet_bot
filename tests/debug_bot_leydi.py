
import asyncio
import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot import TransactionsBot

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def debug_bot_leydi():
    load_dotenv()
    
    token = os.getenv("TELEGRAM_TOKEN_LEY")
    chat_id = os.getenv("TELEGRAM_CHAT_ID_LEY")
    
    print("--- DEBUGGING LEYDI BOT INTERACTION ---")
    if not token or not chat_id:
        print("❌ Error: TELEGRAM_TOKEN_LEY or TELEGRAM_CHAT_ID_LEY missing in .env")
        return

    # 1. Initialize Bot with Leydi's Token
    print(f"🤖 Initializing Bot for Leydi (Chat ID: {chat_id})...")
    bot = TransactionsBot(token=token)
    
    # 2. Set Chat ID Explicitly
    bot.chat_id = int(chat_id)
    
    # 3. Start Polling (Background)
    print("📡 Starting Polling...")
    await bot.start_polling()
    
    # 4. Create Mock Transaction
    mock_transaction = {
        'date': datetime.now().strftime("%d/%m/%Y %H:%M"),
        'amount': 50000,
        'merchant': 'TEST_LEYDI_STORE',
        'description': 'TEST_LEYDI_STORE',
        'original_text': 'Simulated email content for Leydi'
    }
    
    print(f"\n📨 Sending Mock Transaction to Bot: {mock_transaction['merchant']}")
    print("📱 LEYDI: CHECK YOUR TELEGRAM NOW! You should see buttons.")
    print("⏳ Waiting for response in script...")
    
    # 5. Wait for User Input
    splits = await bot.ask_user_for_category(mock_transaction)
    
    # 6. Output Result
    print(f"\n✅ RESULT RECEIVED!")
    print(f"📂 Splits: {splits}")
    for i, (cat, scope, amt, user, tx_type) in enumerate(splits, 1):
        print(f"   {i}. {cat} ({scope}) [{tx_type}] ({user}): ${amt}")
    
    print("\n🛑 Stopping Bot...")
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(debug_bot_leydi())
    except KeyboardInterrupt:
        print("Interrupted by user")
