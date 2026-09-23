import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import gc

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage import TransactionStorage
from src.bot import TransactionsBot

class TestPersistenceFlow(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_persistence.db")
        self.storage = TransactionStorage(db_path=self.db_path)
        
        self.mock_loader = MagicMock()
        self.mock_loader.append_transaction.return_value = True
        self.mock_loader.get_accumulated_total.return_value = 50000.0

        with patch("src.bot.ApplicationBuilder") as mock_builder:
            mock_app = MagicMock()
            mock_builder.return_value.token.return_value.request.return_value.build.return_value = mock_app
            self.bot = TransactionsBot(
                token="fake_token",
                loader=self.mock_loader,
                storage=self.storage
            )
            self.bot.application = mock_app

    def tearDown(self):
        gc.collect()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_restart_survival_and_recovery(self):
        async def run_test():
            # 1. Simulate an incoming transaction pre-inserted into SQLite
            tx_id = self.storage.insert_incoming_transaction(
                origen="email",
                comercio="EXITO WOW",
                monto=85000.0,
                fecha="2026-09-22",
                usuario="Juanma",
                raw_text="Compra en EXITO WOW por $85,000"
            )

            # 2. Simulate Telegram message sent with id 1234
            msg_id = 1234
            chat_id = 9999
            self.storage.bind_telegram_message(
                tx_id=tx_id,
                telegram_message_id=msg_id,
                telegram_chat_id=chat_id,
                initial_flow_state={
                    "total_amount": 85000.0,
                    "remaining_amount": 85000.0,
                    "splits": [],
                    "scope": "Personal",
                    "status": "INIT",
                    "merchant": "EXITO WOW",
                    "date": "2026-09-22",
                    "user_name": "Juanma",
                    "history": []
                }
            )

            # 3. Simulate BOT RESTART (Clear memory completely!)
            self.bot.flow_data.clear()
            self.bot.pending_futures.clear()
            self.assertEqual(len(self.bot.flow_data), 0)

            # 4. User clicks "VALID|Yes" after restart
            update = MagicMock()
            update.effective_user.first_name = "Juanma"
            update.effective_user.id = 1111
            query = MagicMock()
            query.data = "VALID|Yes"
            query.message.message_id = msg_id
            query.message.chat_id = chat_id
            query.answer = AsyncMock()
            query.edit_message_text = AsyncMock()
            update.callback_query = query
            context = MagicMock()

            await self.bot.button(update, context)

            # Assert state was restored from SQLite and total_amount is NOT 0
            self.assertIn(msg_id, self.bot.flow_data)
            restored = self.bot.flow_data[msg_id]
            self.assertEqual(restored["total_amount"], 85000.0)
            self.assertEqual(restored["merchant"], "EXITO WOW")
            self.assertEqual(restored["date"], "2026-09-22")
            self.assertEqual(restored["user_name"], "Juanma")

            # 5. User clicks MULTIPLE|No (Single)
            query.data = "MULTIPLE|No"
            await self.bot.button(update, context)
            self.assertEqual(self.bot.flow_data[msg_id]["status"], "WAITING_SCOPE")

            # 6. User clicks SCOPE|Personal
            query.data = "SCOPE|Personal"
            await self.bot.button(update, context)
            self.assertEqual(self.bot.flow_data[msg_id]["status"], "WAITING_CATEGORY")

            # 7. User clicks CAT|Mercado
            query.data = "CAT|Mercado"
            await self.bot.button(update, context)

            # Check confirmation state in SQLite
            db_rec = self.storage.get_by_message_id(msg_id)
            self.assertIsNotNone(db_rec)
            self.assertEqual(db_rec["estado"], "EN_PROCESO")

            # 8. User clicks CONFIRM|SAVE
            query.data = "CONFIRM|SAVE"
            await self.bot.button(update, context)

            # Verify saved via loader directly (since pending_futures was lost due to restart)
            self.mock_loader.append_transaction.assert_called()
            call_kwargs = self.mock_loader.append_transaction.call_args[1]
            self.assertEqual(call_kwargs["scope"], "Personal")
            self.assertEqual(call_kwargs["transaction_type"], "Gasto")

            # Verify SQLite record is marked as DILIGENCIADA / synced
            final_rec = self.storage.get_by_message_id(msg_id)
            self.assertEqual(final_rec["estado"], "DILIGENCIADA")
            self.assertIsNotNone(final_rec["sincronizado_el"])

        asyncio.run(run_test())

    def test_restart_reset_restores_original_data(self):
        async def run_test():
            msg_id = 5678
            tx_id = self.storage.insert_incoming_transaction(
                origen="email",
                comercio="SUPERMERCADO",
                monto=120000.0,
                fecha="2026-09-21",
                usuario="Leydi"
            )
            self.storage.bind_telegram_message(tx_id, msg_id, 8888, {
                "total_amount": 120000.0,
                "remaining_amount": 120000.0,
                "splits": [],
                "scope": "Personal",
                "status": "INIT",
                "merchant": "SUPERMERCADO",
                "date": "2026-09-21",
                "user_name": "Leydi",
                "history": []
            })

            # Simulate restart and user clicking Reiniciar
            self.bot.flow_data.clear()
            
            update = MagicMock()
            update.effective_user.first_name = "Leydi"
            query = MagicMock()
            query.data = "CONFIRM|RESTART"
            query.message.message_id = msg_id
            query.answer = AsyncMock()
            query.edit_message_text = AsyncMock()
            update.callback_query = query

            await self.bot.button(update, MagicMock())

            # Verify state was re-initialized with original amount, not 0.0
            state = self.bot.flow_data[msg_id]
            self.assertEqual(state["total_amount"], 120000.0)
            self.assertEqual(state["merchant"], "SUPERMERCADO")
            self.assertEqual(state["date"], "2026-09-21")
            self.assertEqual(state["splits"], [])
            self.assertEqual(state["history"], [])

        asyncio.run(run_test())

    def test_back_button_navigation(self):
        async def run_test():
            msg_id = 9012
            self.bot.flow_data[msg_id] = {
                "total_amount": 30000.0,
                "remaining_amount": 30000.0,
                "splits": [],
                "scope": "Personal",
                "status": "INIT",
                "merchant": "CAFE",
                "date": "2026-09-22",
                "user_name": "Juanma",
                "history": []
            }
            
            update = MagicMock()
            update.effective_user.first_name = "Juanma"
            query = MagicMock()
            query.message.message_id = msg_id
            query.answer = AsyncMock()
            query.edit_message_text = AsyncMock()
            update.callback_query = query

            # 1. Click Registrar -> Asks MULTIPLE
            query.data = "VALID|Yes"
            await self.bot.button(update, MagicMock())
            self.assertEqual(self.bot.flow_data[msg_id]["status"], "WAITING_MULTIPLE")
            self.assertEqual(len(self.bot.flow_data[msg_id]["history"]), 1)

            # 2. Click MULTIPLE|No -> Asks SCOPE
            query.data = "MULTIPLE|No"
            await self.bot.button(update, MagicMock())
            self.assertEqual(self.bot.flow_data[msg_id]["status"], "WAITING_SCOPE")
            self.assertEqual(len(self.bot.flow_data[msg_id]["history"]), 2)

            # 3. Click FLOW|BACK -> Should go back to WAITING_MULTIPLE
            query.data = "FLOW|BACK"
            await self.bot.button(update, MagicMock())
            self.assertEqual(self.bot.flow_data[msg_id]["status"], "WAITING_MULTIPLE")
            self.assertEqual(len(self.bot.flow_data[msg_id]["history"]), 1)

            # 4. Click FLOW|BACK again -> Should go back to INIT
            query.data = "FLOW|BACK"
            await self.bot.button(update, MagicMock())
            self.assertEqual(self.bot.flow_data[msg_id]["status"], "INIT")
            self.assertEqual(len(self.bot.flow_data[msg_id]["history"]), 0)

        asyncio.run(run_test())

    def test_show_pending_and_recent(self):
        async def run_test():
            self.storage.insert_incoming_transaction(
                origen="email",
                comercio="FARMACIA",
                monto=25000.0,
                fecha="2026-09-22",
                usuario="Juanma"
            )

            update = MagicMock()
            update.effective_user.id = 12345
            update.message.reply_text = AsyncMock()

            # Test show_pending
            await self.bot.show_pending(update, MagicMock())
            update.message.reply_text.assert_called()
            call_text = update.message.reply_text.call_args[0][0]
            self.assertIn("FARMACIA", call_text)
            self.assertIn("Transacciones Pendientes", call_text)

            # Test show_recent
            update.message.reply_text.reset_mock()
            await self.bot.show_recent(update, MagicMock())
            update.message.reply_text.assert_called()
            call_text = update.message.reply_text.call_args[0][0]
            self.assertIn("FARMACIA", call_text)
            self.assertIn("Últimas Transacciones", call_text)

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
