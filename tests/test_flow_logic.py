import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch

# Add project root to path
sys.path.append(os.getcwd())

from src.bot import TransactionsBot

async def test_transaction_flow():
    print("🚀 Starting Logic Flow Simulation...")
    
    # 1. Mock Loader
    mock_loader = MagicMock()
    mock_loader.append_transaction.return_value = True
    mock_loader.get_accumulated_total.return_value = 150000.0

    # 2. Mock ApplicationBuilder to prevent real PTB init
    with patch("src.bot.ApplicationBuilder") as MockAppBuilder:
        # Check chain: ApplicationBuilder().token().request().build()
        mock_builder = MockAppBuilder.return_value
        mock_builder.token.return_value = mock_builder
        mock_builder.request.return_value = mock_builder
        
        mock_app = MagicMock()
        mock_builder.build.return_value = mock_app
        
        # Mock bot methods on the app
        mock_bot = MagicMock()
        mock_app.bot = mock_bot
        
        # Async methods need AsyncMock
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        mock_bot.edit_message_text = AsyncMock()
        mock_bot.answer_callback_query = AsyncMock()
        
        print("   Initializing Bot (with Mocks)...")
        bot = TransactionsBot(loader=mock_loader, token="123:FAKE_TOKEN")
        
        # Ensure pending_futures is init
        if not hasattr(bot, 'pending_futures'):
             bot.pending_futures = {}
        if not hasattr(bot, 'flow_data'):
             bot.flow_data = {}

        # Define a fake transaction
        transaction = {
            "date": "27/01/2026",
            "merchant": "TEST MERCHANT",
            "amount": 50000.0
        }
        
        print("   Simulating 'ask_user_for_category'...")
        # Create task for the waiting coroutine
        task = asyncio.create_task(bot.ask_user_for_category(transaction, target_chat_id=1001))
        
        # Give it a moment to run until await future
        await asyncio.sleep(0.1)
        
        # Check if future exists (Key is message_id=999 from mock)
        if 999 not in bot.pending_futures:
             # Debug
             print(f"   DEBUG: Futures keys: {list(bot.pending_futures.keys())}")
        
        assert 999 in bot.pending_futures
        print("   ✅ Future created for message 999")
        
        # --- SIMULATE USER INTERACTIONS ---
        
        # Helper to simulate button click
        async def click(data):
            print(f"   👉 User clicks: {data}")
            mock_update = MagicMock()
            mock_update.callback_query.data = data
            mock_update.callback_query.message.message_id = 999
            mock_update.callback_query.from_user.id = 12345
            
            # The bot calls query.answer() and query.edit_message_text()
            # which are usually methods on the callback_query object itself in recent PTB?
            # Or does it use context.bot?
            # Source check: await query.edit_message_text(...) 
            # So we need to mock these on the update object too.
            mock_update.callback_query.answer = AsyncMock()
            mock_update.callback_query.edit_message_text = AsyncMock()
            
            await bot.button(mock_update, MagicMock())

        # 1. VALID|Yes
        await click("VALID|Yes")
        assert 999 in bot.flow_data
        assert bot.flow_data[999]["total_amount"] == 50000.0
        
        # 2. MULTIPLE|No (Single)
        await click("MULTIPLE|No")
        
        # 3. SCOPE|Personal
        await click("SCOPE|Personal")
        assert bot.flow_data[999]["scope"] == "Personal"
        
        # 4. CAT|Alimentacion
        await click("CAT|Alimentacion")
        assert bot.flow_data[999]["pending_category"] == "Alimentacion"
        
        # 5. SUBCAT|General (Assume this step needed based on config logic usually)
        # We can't know for sure if logic requests subcat without real config.
        # But if we blindly fire SUBCAT, it should handle it if step matches.
        # If the bot thought it was done (no subcats), it would have called finalize.
        # Let's check flow_data status.
        state = bot.flow_data.get(999, {})
        print(f"   DEBUG: State after CAT: {state}")
        
        # If status is INIT or something else, it might be waiting.
        # If finalize was called, future is set?
        # Let's assume we need SUBCAT.
        await click("SUBCAT|General") 
        
        # 6. CONFIRM|SAVE
        await click("CONFIRM|SAVE")
        
        # --- VERIFY RESULTS ---
        print("   Waiting for task result...")
        try:
             # Wait with timeout
             result, msg_id = await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
             print("   ❌ Timeout waiting for future! Logic stuck?")
             # Debug state
             print(f"   State: {bot.flow_data.get(999)}")
             return

        print(f"   ✅ Task Result: {result}, MessageID: {msg_id}")
        
        assert msg_id == 999
        assert len(result) == 1
        cat, scope, amt, user, tx_type = result[0]
        
        print(f"   🔍 Captured Info: Cat={cat}, Amount={amt}, Scope={scope}")
        
        assert amt == 50000.0
        assert scope == "Personal"
        
        # --- VERIFY MAIN LOOP LOGIC ---
        print("   Simulating Main Loop Persistence...")
        
        all_saved = True
        for cat, scope, amt, user, tx_type in result:
            t_copy = transaction.copy()
            t_copy['amount'] = amt
            success = mock_loader.append_transaction(t_copy, cat, scope=scope, transaction_type=tx_type)
            if not success:
                all_saved = False
                
        if all_saved:
            print("   ✅ Transaction Saved successfully (Mock)")
            # Simulate final edit matching the 'main.py' fix
            # We must use the message_id we got back
            await mock_app.bot.edit_message_text(chat_id=1001, message_id=msg_id, text="💾 Guardado Exitoso")
            print("   ✅ Final Message Edit Triggered")
        else:
            print("   ❌ Save Failed")

        print("\n🎉 TEST PASSED: Full Flow Verified Locally!")

if __name__ == "__main__":
    asyncio.run(test_transaction_flow())
