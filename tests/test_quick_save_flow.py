import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from src.bot import TransactionsBot
from src.storage import TransactionStorage

@pytest.mark.asyncio
async def test_quick_save_prompt_and_execution():
    """Tests that high confidence merchants display 1-Click button and execute directly."""
    storage = TransactionStorage(db_path=":memory:")
    
    # Pre-seed merchant memory for Juanma: D1 with high confidence
    storage.record_merchant_learning("D1", "🏠 Casa - Mercado", "Familiar", "Gasto", "Juanma")
    storage.record_merchant_learning("D1", "🏠 Casa - Mercado", "Familiar", "Gasto", "Juanma")
    
    mock_loader = MagicMock()
    mock_loader.append_transaction.return_value = True
    mock_loader.get_accumulated_total.return_value = 100000.0

    with patch("src.bot.ApplicationBuilder") as MockAppBuilder:
        mock_builder = MockAppBuilder.return_value
        mock_builder.token.return_value = mock_builder
        mock_builder.request.return_value = mock_builder
        mock_app = MagicMock()
        mock_builder.build.return_value = mock_app
        mock_bot = MagicMock()
        mock_app.bot = mock_bot
        
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=5001))
        mock_bot.edit_message_text = AsyncMock()

        bot = TransactionsBot(loader=mock_loader, token="FAKE:TOKEN", storage=storage)

        tx = {
            "date": "23/09/2026 10:00",
            "merchant": "D1 * MEDELLIN",
            "amount": 45000.0,
            "source": "notification"
        }

        # 1. Ask user
        task = asyncio.create_task(bot.ask_user_for_category(tx, user_name="Juanma", target_chat_id=12345))
        await asyncio.sleep(0.01)

        # Check send_message arguments
        assert mock_bot.send_message.called
        sent_args = mock_bot.send_message.call_args
        sent_text = sent_args.kwargs.get("text") or sent_args[1].get("text")
        sent_markup = sent_args.kwargs.get("reply_markup") or sent_args[1].get("reply_markup")

        assert "🎯 *Sugerencia:*" in sent_text
        assert "🏠 Casa - Mercado" in sent_text
        
        # Verify keyboard has QUICK|SAVE button
        inline_buttons = sent_markup.inline_keyboard
        assert any(btn.callback_data == "QUICK|SAVE" for row in inline_buttons for btn in row)
        assert any(btn.callback_data == "VALID|Yes" for row in inline_buttons for btn in row)

        # 2. Simulate user pressing QUICK|SAVE button
        update = MagicMock()
        query = MagicMock()
        query.data = "QUICK|SAVE"
        query.message.message_id = 5001
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user.id = 12345
        update.callback_query = query

        await bot.button(update, None)

        # 3. Verify future resolved
        splits, msg_id = await task
        assert msg_id == 5001
        assert len(splits) == 1
        cat, scope, amt, user, tx_type = splits[0]
        assert cat == "🏠 Casa - Mercado"
        assert scope == "Familiar"
        assert amt == 45000.0
        assert user == "Juanma"
        assert tx_type == "Gasto"

        # 4. Verify learning reinforcement (frequency incremented to 3)
        rules = storage.get_merchant_rules(usuario="Juanma")
        d1_rule = [r for r in rules if r["merchant_pattern"] == "D1"][0]
        assert d1_rule["frequency"] == 3

@pytest.mark.asyncio
async def test_quick_save_change_diverts_to_normal_flow():
    """Tests that pressing 'Cambiar / Dividir' (VALID|Yes) opens the normal category flow."""
    storage = TransactionStorage(db_path=":memory:")
    storage.record_merchant_learning("D1", "🏠 Casa - Mercado", "Familiar", "Gasto", "Juanma")
    storage.record_merchant_learning("D1", "🏠 Casa - Mercado", "Familiar", "Gasto", "Juanma")

    with patch("src.bot.ApplicationBuilder") as MockAppBuilder:
        mock_builder = MockAppBuilder.return_value
        mock_builder.token.return_value = mock_builder
        mock_builder.request.return_value = mock_builder
        mock_app = MagicMock()
        mock_builder.build.return_value = mock_app
        mock_bot = MagicMock()
        mock_app.bot = mock_bot
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=6001))
        mock_bot.edit_message_text = AsyncMock()

        bot = TransactionsBot(token="FAKE:TOKEN", storage=storage)

        tx = {
            "date": "23/09/2026 10:00",
            "merchant": "D1",
            "amount": 25000.0
        }

        task = asyncio.create_task(bot.ask_user_for_category(tx, user_name="Juanma", target_chat_id=12345))
        await asyncio.sleep(0.01)

        # User chooses to CHANGE / DIVIDE instead of quick-saving
        update = MagicMock()
        query = MagicMock()
        query.data = "VALID|Yes"
        query.message.message_id = 6001
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.from_user.id = 12345
        update.callback_query = query

        await bot.button(update, None)

        # Verify state transitioned to WAITING_MULTIPLE (single vs split prompt)
        state = bot.flow_data[6001]
        assert state["status"] == "WAITING_MULTIPLE"
        assert query.edit_message_text.called

        # Cancel cleanly so task finishes
        cancel_update = MagicMock()
        cancel_query = MagicMock()
        cancel_query.data = "CONFIRM|CANCEL"
        cancel_query.message.message_id = 6001
        cancel_query.answer = AsyncMock()
        cancel_query.edit_message_text = AsyncMock()
        cancel_update.callback_query = cancel_query
        await bot.button(cancel_update, None)
        splits, _ = await task
        assert not splits

@pytest.mark.asyncio
async def test_pending_render_quick_save():
    """Tests that _render_single_pending presents QUICK|SAVE for high confidence merchants."""
    storage = TransactionStorage(db_path=":memory:")
    storage.record_merchant_learning("CABIFY", "🚗 Transporte - Taxis", "Familiar", "Gasto", "Leydi")
    storage.record_merchant_learning("CABIFY", "🚗 Transporte - Taxis", "Familiar", "Gasto", "Leydi")

    tx_id = storage.insert_incoming_transaction(
        origen="gmail",
        comercio="CABIFY",
        monto=18000.0,
        fecha="23/09/2026 11:00",
        usuario="Leydi"
    )

    mock_loader = MagicMock()
    mock_loader.append_transaction.return_value = True
    mock_loader.get_accumulated_total.return_value = 0.0

    with patch("src.bot.ApplicationBuilder") as MockAppBuilder:
        mock_builder = MockAppBuilder.return_value
        mock_builder.token.return_value = mock_builder
        mock_builder.request.return_value = mock_builder
        mock_app = MagicMock()
        mock_builder.build.return_value = mock_app

        bot = TransactionsBot(loader=mock_loader, token="FAKE:TOKEN", storage=storage)

        query = MagicMock()
        query.message.message_id = 7001
        query.message.chat_id = 99999
        query.edit_message_text = AsyncMock()

        tx_data = storage.get_by_id(tx_id)
        await bot._render_single_pending(query, tx_data, message_id=7001, user_name="Leydi")

        # Verify edited text and buttons
        call_args = query.edit_message_text.call_args
        text = call_args.kwargs.get("text") or call_args[0][0]
        markup = call_args.kwargs.get("reply_markup") or call_args[0][1]

        assert "🎯 *Sugerencia:*" in text
        assert "🚗 Transporte - Taxis" in text
        assert any(b.callback_data == "QUICK|SAVE" for row in markup.inline_keyboard for b in row)

        # Now click QUICK|SAVE on this orphan pending item
        click_update = MagicMock()
        click_query = MagicMock()
        click_query.data = "QUICK|SAVE"
        click_query.message.message_id = 7001
        click_query.answer = AsyncMock()
        click_query.edit_message_text = AsyncMock()
        click_query.from_user.id = 99999
        click_update.callback_query = click_query

        await bot.button(click_update, None)

        # Verify loader was called directly (orphan direct save)
        assert mock_loader.append_transaction.called
        saved_rec = storage.get_by_id(tx_id)
        assert saved_rec["estado"] == "DILIGENCIADA"
