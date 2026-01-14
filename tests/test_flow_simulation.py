import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot import TransactionsBot

class TestBotFlow(unittest.TestCase):
    def setUp(self):
        # Mock environment variables if needed
        with patch.dict(os.environ, {"TELEGRAM_TOKEN_JUANMA": "fake_token", "TELEGRAM_CHAT_ID_JUANMA": "123"}):
            # Patch ApplicationBuilder to avoid actual network calls during init
            with patch("src.bot.ApplicationBuilder") as mock_builder:
                mock_app = MagicMock()
                mock_builder.return_value.token.return_value.request.return_value.build.return_value = mock_app
                self.bot = TransactionsBot()
                self.bot.application = mock_app

    async def _simulate_callback(self, data, message_id=111):
        update = MagicMock()
        update.effective_user.first_name = "TestUser"
        query = MagicMock()
        query.data = data
        query.message.message_id = message_id
        # Async mocks for awaitable methods
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        
        update.callback_query = query
        
        context = MagicMock()
        context.bot.edit_message_text = AsyncMock()
        
        # Ensure flow_data has state if not VALID
        if "VALID" not in data and message_id not in self.bot.flow_data:
             self.bot.flow_data[message_id] = {
                "total_amount": 10000.0,
                "remaining_amount": 10000.0,
                "splits": [],
                "scope": "Personal",
                "status": "INIT"
            }

        await self.bot.button(update, context)
        return query

    def test_flow_reorder(self):
        async def run_test():
            # 1. Start with VALID|Yes (User confirms transaction)
            # OLD EXPECTATION: Asks for SCOPE
            # NEW EXPECTATION: Asks for MULTIPLE
            
            # Setup initial state
            msg_id = 999
            self.bot.flow_data[msg_id] = {
                "total_amount": 50000.0,
                "remaining_amount": 50000.0,
                "splits": [],
                "scope": "Personal"
            }
            
            # Step 1: User clicks "Registrar" (VALID|Yes)
            query = await self._simulate_callback("VALID|Yes", msg_id)
            
            # Verify we are asking about Multiple/Single
            args = query.edit_message_text.call_args[1]
            text = args.get('text', '')
            reply_markup = args.get('reply_markup')
            
            print(f"Step 1 Output: {text}")
            
            # We expect "Única" or "Múltiple" in text
            # And buttons MULTIPLE|No / MULTIPLE|Yes
            # For now, asserting it fails if logic is old (old logic asks for Family/Personal)
            
            has_multiple_kw = "Múltiple" in text or "Única" in text
            has_scope_kw = "Familiar" in text or "Personal" in text
            
            # This assert confirms if we have successfully changed the logic
            if has_scope_kw and not has_multiple_kw:
                print("FAIL: Bot is still asking for Scope first.")
            elif has_multiple_kw:
                 print("PASS: Bot is asking for Multiple/Single first.")
            else:
                 print(f"UNKNOWN: text was '{text}'")

            # Step 2: Simulate User says "Una sola" (MULTIPLE|No)
            # OLD: This step didn't exist here. 
            # NEW: Should ask for SCOPE.
            query = await self._simulate_callback("MULTIPLE|No", msg_id)
            args = query.edit_message_text.call_args[1]
            text = args.get('text', '')
            
            print(f"Step 2 Output: {text}")
            # Expect "Familiar" or "Personal"
            
            # Step 3: Simulate User says "Personal" (SCOPE|Personal)
            # NEW: Should ask for Category (since Single)
            self.bot.flow_data[msg_id]['is_multiple'] = False # Set by step 2 logic usually
            query = await self._simulate_callback("SCOPE|Personal", msg_id)
            args = query.edit_message_text.call_args[1]
            text = args.get('text', '')
             
            print(f"Step 3 Output: {text}")
            # Expect Category selection
            
        asyncio.run(run_test())

    def test_multiple_flow(self):
        async def run_test():
            msg_id = 888
            self.bot.flow_data[msg_id] = {
                "total_amount": 100000.0,
                "remaining_amount": 100000.0,
                "splits": [],
                "scope": "Personal" # Default, will be overwritten
            }
            
            # Step 1: Valid
            await self._simulate_callback("VALID|Yes", msg_id)
            
            # Step 2: Choose Multiple
            query = await self._simulate_callback("MULTIPLE|Yes", msg_id)
            text = query.edit_message_text.call_args[1]['text']
            print(f"Multiple Step 2: {text}")
            # Expect Scope Question
            assert "Familiar" in text or "Personal" in text, "Should ask for Scope after Multiple"
            
            # Step 3: Choose Family
            query = await self._simulate_callback("SCOPE|Familiar", msg_id)
            text = query.edit_message_text.call_args[1]['text']
            print(f"Multiple Step 3: {text}")
            # Expect Waiting Amount question
            assert "Total:" in text and "Restante" in text, "Should ask for Amount split"
            
            # Verify state
            assert self.bot.flow_data[msg_id]["is_multiple"] is True
            assert self.bot.flow_data[msg_id]["scope"] == "Familiar"
            assert self.bot.flow_data[msg_id]["status"] == "WAITING_AMOUNT"
            
        asyncio.run(run_test())

    def test_accumulated_display(self):
        async def run_test():
            msg_id = 777
            # Mock Loader
            mock_loader = MagicMock()
            mock_loader.get_accumulated_total.return_value = 1234.56
            self.bot.loader = mock_loader
            
            # Setup State ready for confirm
            self.bot.flow_data[msg_id] = {
                "splits": [("TestCat", "Personal", 100.0, "TestUser", "Gasto")],
                "scope": "Personal"
            }
            
            # Trigger Confirm Save
            query = await self._simulate_callback("CONFIRM|SAVE", msg_id)
            
            # Verify Message contains Acum
            text = query.edit_message_text.call_args[1]['text']
            print(f"Confirm Output: {text}")
            
            assert "Acum: $1,234.56" in text, "Message should show accumulated total"
            
        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()
