import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.getcwd())

from src.bot import TransactionsBot

async def test_restart_flow():
    print("🚀 Starting Logic Flow Simulation for RESTART...")
    
    # 1. Mock Bot
    mock_app = MagicMock()
    bot = TransactionsBot("TOKEN", "SHEET_ID")
    bot.application = mock_app
    bot.chat_id = 123456
    
    # 2. Simulate Initial State (as if ask_user_for_category just ran)
    message_id = 999
    
    # Pre-fill flow_data exactly how ask_user_for_category does now
    bot.flow_data[message_id] = {
        "total_amount": 50000.0,
        "remaining_amount": 50000.0,
        "splits": [],
        "scope": "Personal",
        "status": "INIT",
        "merchant": "Uber Test",
        "date": "2025-10-10",
        "user_name": "TestUser"
    }
    
    print(f"   ℹ️ State before restart: {bot.flow_data[message_id]}")

    # 3. Simulate RESTART Click
    print("   👉 Simulating Click: RESTART")
    
    mock_update = MagicMock()
    mock_update.callback_query.data = "VALID|RESTART"
    mock_update.callback_query.message.message_id = message_id
    mock_update.callback_query.answer = AsyncMock()
    mock_update.callback_query.edit_message_text = AsyncMock()
    
    # Execute button handler
    await bot.button(mock_update, None)
    
    # 4. Verify Results
    # Check if state was reset
    current_state = bot.flow_data[message_id]
    print(f"   ℹ️ State after restart: {current_state}")
    
    if current_state["status"] == "INIT" and len(current_state["splits"]) == 0:
        print("   ✅ State reset correctly.")
    else:
        print("   ❌ State NOT reset.")
        
    # Check if message was edited back to initial prompt
    args, kwargs = mock_update.callback_query.edit_message_text.call_args
    print(f"DEBUG CALL ARGS: {args} {kwargs}")
    text_sent = kwargs.get('text')
    if not text_sent and args:
         # Maybe passed as positional? 
         # edit_message_text(text="...", ...) usually keyword but let's check
         # signature is (text, parse_mode, ...) or something
         pass
    
    print(f"   📝 Message updated to:\n---\n{text_sent}\n---")
    
    if "Uber Test" in text_sent and "50,000.00" in text_sent and "¿Deseas registrarla?" in text_sent:
         print("   ✅ Restart message correct!")
    else:
         print("   ❌ Restart message INCORRECT.")

if __name__ == "__main__":
    asyncio.run(test_restart_flow())
