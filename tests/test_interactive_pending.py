import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from src.bot import TransactionsBot
from src.storage import TransactionStorage

@pytest.mark.asyncio
async def test_show_pending_zero():
    bot = TransactionsBot(loader=MagicMock(), storage=TransactionStorage(db_path=":memory:"))
    update = MagicMock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()

    await bot.show_pending(update, MagicMock())
    update.message.reply_text.assert_called_once()
    assert "No tienes transacciones pendientes" in update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_show_pending_single_interactive():
    storage = TransactionStorage(db_path=":memory:")
    mock_loader = MagicMock()
    bot = TransactionsBot(loader=mock_loader, storage=storage)

    tx_id = storage.insert_incoming_transaction("gmail", "BURGER KING", 38000.0, "2026-09-23", "Juanma")

    update = MagicMock()
    update.effective_user.id = 12345
    sent_msg = MagicMock()
    sent_msg.message_id = 777
    update.message.reply_text = AsyncMock(return_value=sent_msg)

    # 1. User executes /pendientes
    await bot.show_pending(update, MagicMock())

    # Message sent with inline buttons
    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args[0][0]
    call_kwargs = update.message.reply_text.call_args[1]
    assert "BURGER KING" in call_text
    assert "Transacciones Pendientes" in call_text
    assert call_kwargs.get("reply_markup") is not None

    # Check flow_data initialized
    assert 777 in bot.flow_data
    assert bot.flow_data[777]["total_amount"] == 38000.0
    assert bot.flow_data[777]["merchant"] == "BURGER KING"

    # Check SQLite bound
    rec = storage.get_by_message_id(777)
    assert rec is not None
    assert rec["id"] == tx_id

    # 2. User clicks ✅ Registrar (VALID|Yes)
    query = MagicMock()
    query.data = "VALID|Yes"
    query.message.message_id = 777
    query.message.chat_id = 12345
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    cb_update = MagicMock()
    cb_update.callback_query = query

    await bot.button(cb_update, MagicMock())
    assert bot.flow_data[777]["status"] == "WAITING_MULTIPLE"

@pytest.mark.asyncio
async def test_show_pending_multiple_and_select():
    storage = TransactionStorage(db_path=":memory:")
    mock_loader = MagicMock()
    mock_loader.append_transaction.return_value = True
    bot = TransactionsBot(loader=mock_loader, storage=storage)

    # Insert 2 transactions
    tx1_id = storage.insert_incoming_transaction("gmail", "STARBUCKS", 18000.0, "2026-09-23", "Juanma")
    tx2_id = storage.insert_incoming_transaction("gmail", "SUPERMERCADO", 150000.0, "2026-09-23", "Juanma")

    update = MagicMock()
    update.effective_user.id = 12345
    sent_msg = MagicMock()
    sent_msg.message_id = 888
    update.message.reply_text = AsyncMock(return_value=sent_msg)

    # 1. Call /pendientes
    await bot.show_pending(update, MagicMock())
    call_text = update.message.reply_text.call_args[0][0]
    call_kwargs = update.message.reply_text.call_args[1]
    assert "STARBUCKS" in call_text
    assert "SUPERMERCADO" in call_text
    markup = call_kwargs["reply_markup"]
    assert len(markup.inline_keyboard) == 2

    # 2. User clicks button for STARBUCKS (PEND|SELECT_<tx1_id>)
    query = MagicMock()
    query.data = f"PEND|SELECT_{tx1_id}"
    query.message.message_id = 888
    query.message.chat_id = 12345
    query.from_user.id = 12345
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    cb_update = MagicMock()
    cb_update.callback_query = query

    await bot.button(cb_update, MagicMock())

    # Should edit message to ask for categorization
    assert query.edit_message_text.called
    edit_text = query.edit_message_text.call_args[1]["text"]
    assert "STARBUCKS" in edit_text
    assert "Transacción por Categorizar" in edit_text

    # Flow data is now set up on message 888
    assert 888 in bot.flow_data
    assert bot.flow_data[888]["total_amount"] == 18000.0

    # 3. User discards it (VALID|No)
    query.data = "VALID|No"
    query.edit_message_text.reset_mock()
    await bot.button(cb_update, MagicMock())

    # STARBUCKS discarded in SQLite
    rec1 = storage.get_by_id(tx1_id)
    assert rec1["estado"] == "DESCARTADA"

    # Message offers next pending (SUPERMERCADO)
    assert query.edit_message_text.called
    discard_text = query.edit_message_text.call_args[1]["text"]
    assert "Descartada" in discard_text
    assert "Te quedan *1* transacciones pendientes" in discard_text
    discard_markup = query.edit_message_text.call_args[1]["reply_markup"]
    assert discard_markup is not None
