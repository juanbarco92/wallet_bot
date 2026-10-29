import pytest
from unittest.mock import MagicMock, AsyncMock
from src.bot import TransactionsBot
from src.loader import SheetsLoader
from src.storage import TransactionStorage

@pytest.mark.asyncio
async def test_bot_default_user_and_resolution():
    storage = TransactionStorage(":memory:")
    bot_j = TransactionsBot(storage=storage, default_user="Juanma")
    assert bot_j._get_user_label() == "Juanma"

    bot_l = TransactionsBot(storage=storage, default_user="Leydi")
    assert bot_l._get_user_label() == "Leydi"

@pytest.mark.asyncio
async def test_finalize_classification_step_preserves_user_name():
    storage = TransactionStorage(":memory:")
    bot = TransactionsBot(storage=storage, default_user="Juanma")
    message_id = 888
    bot.flow_data[message_id] = {
        "status": "WAITING_CATEGORY",
        "scope": "Personal",
        "is_multiple": False,
        "total_amount": 35000.0,
        "user_name": "Leydi",
        "splits": []
    }

    update = MagicMock()
    update.effective_user.first_name = "RandomTelegramName"
    update.effective_user.id = 999999
    update.callback_query = MagicMock()
    update.callback_query.edit_message_text = AsyncMock()

    context = MagicMock()

    await bot._finalize_classification_step(update, context, message_id, "Restaurante")

    splits = bot.flow_data[message_id]["splits"]
    assert len(splits) == 1
    cat, scope, amount, user, tx_type = splits[0]
    # Should prioritize state["user_name"] over random Telegram first_name
    assert user == "Leydi"
    assert bot.flow_data[message_id]["user_name"] == "Leydi"

@pytest.mark.asyncio
async def test_manual_flow_resolves_correct_user():
    storage = TransactionStorage(":memory:")
    bot = TransactionsBot(storage=storage, default_user="Juanma")
    bot.process_manual_transaction = AsyncMock()

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["45000", "Almuerzo", "corrientazo"]

    await bot.start_manual_flow(update, context)

    # Verify transaction in SQLite has usuario == 'Juanma', not 'User'
    txs = storage.get_pending_transactions()
    # It might be in INGRESADA state
    with storage._connection() as conn:
        row = conn.execute("SELECT usuario, monto_total, comercio FROM transacciones_log ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        assert row["usuario"] == "Juanma"
        assert row["monto_total"] == 45000.0

    assert bot.process_manual_transaction.called
    call_args, call_kwargs = bot.process_manual_transaction.call_args
    assert call_kwargs.get("user_name") == "Juanma"

def test_loader_append_transaction_prevents_user_literal():
    loader = SheetsLoader()
    loader.client = MagicMock()
    loader.sheet = MagicMock()
    loader.sheet.col_values.return_value = ["Fecha"]
    loader.sheet.row_count = 100
    loader.sheet.update = MagicMock()

    # When user_who_paid is "User", it should fallback to transaction's user_name or "Juanma"
    tx = {"date": "2026-10-28", "merchant": "TEST", "amount": 25000.0, "user_name": "Leydi"}
    success = loader.append_transaction(tx, "Restaurante", scope="Personal", user_who_paid="User")
    assert success is True

    written_row = loader.sheet.update.call_args[1]["values"][0]
    # Row schema: [tx_date, current_timestamp, user_who_paid, scope, ...]
    assert written_row[2] == "Leydi"
    assert written_row[2] != "User"
