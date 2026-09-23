import pytest
from unittest.mock import AsyncMock, MagicMock
from src.parser import TransactionParser
from src.bot import TransactionsBot, escape_md

def test_parser_with_asterisks_and_domains():
    parser = TransactionParser()

    # Case 1: Subscription with asterisk and .com ending in ', el'
    t1 = "Compraste COP64.700,00 en\r\nDLO*Netflix.com, el 04:06 a las 20/11/2025. T.Cred *8774."
    p1 = parser.parse(t1)
    assert p1['amount'] == 64700.0
    assert p1['merchant'] == "DLO*NETFLIX.COM"

    # Case 2: Wrapping asterisks around merchant
    t2 = "Compraste $35.000,00 en *EXITO CALLE 80* con tu tarjeta"
    p2 = parser.parse(t2)
    assert p2['amount'] == 35000.0
    assert p2['merchant'] == "EXITO CALLE 80"

    # Case 3: Merchant with asterisk in the middle
    t3 = "Compraste $12.500,00 en D1 * MEDELLIN con tu tarjeta"
    p3 = parser.parse(t3)
    assert p3['amount'] == 12500.0
    assert p3['merchant'] == "D1 * MEDELLIN"

    # Case 4: Merchant with multiple dots (S.A.S.)
    t4 = "Compraste $89.000,00 en RAPPI S.A.S. con tu cuenta"
    p4 = parser.parse(t4)
    assert p4['amount'] == 89000.0
    assert p4['merchant'] == "RAPPI S.A.S."

def test_header_sanitization_with_asterisks():
    bot = TransactionsBot()
    message_id = 12345
    bot.flow_data[message_id] = {
        "merchant": "DLO*Netflix.com",
        "total_amount": 64700.0,
        "date": "20/11/2025",
        "user_name": "Juanma"
    }

    header = bot._get_flow_context_header(message_id)
    # The header should NOT contain nested asterisks like *...*...* that break Telegram Markdown
    # Clean merchant replaces '*' with ' ' for the Markdown bold container
    assert "*DLO*Netflix" not in header
    assert "DLO Netflix.com" in header

@pytest.mark.asyncio
async def test_direct_save_transitions_to_success():
    mock_loader = MagicMock()
    mock_loader.append_transaction.return_value = True
    mock_loader.get_accumulated_total.return_value = 150000.0

    mock_storage = MagicMock()
    bot = TransactionsBot(loader=mock_loader)
    bot.storage = mock_storage
    bot.application = MagicMock()
    bot.application.bot = MagicMock()
    bot.application.bot.send_message = AsyncMock()

    message_id = 999
    # Simulate orphan state (bot restarted, not in pending_futures)
    bot.flow_data[message_id] = {
        "splits": [("Alimentación", "Personal", 50000.0, "Juanma", "Gasto")],
        "merchant": "D1 * MEDELLIN",
        "date": "2026-09-22",
        "user_name": "Juanma",
        "total_amount": 50000.0
    }

    update = MagicMock()
    query = MagicMock()
    query.data = "CONFIRM|SAVE"
    query.message.message_id = message_id
    query.message.chat_id = 123456
    query.from_user.id = 123456
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update.callback_query = query

    context = MagicMock()

    await bot.button(update, context)

    # 1. Loader should have been called
    assert mock_loader.append_transaction.called
    # 2. SQLite should have marked as synced
    assert mock_storage.mark_as_synced.called
    # 3. Message should be edited to "Guardado Exitoso" and retain transaction description
    edit_calls = query.edit_message_text.call_args_list
    assert len(edit_calls) >= 2
    # The final edit should be Guardado Exitoso with merchant and amount preserved
    final_call_kwargs = edit_calls[-1].kwargs
    final_text = final_call_kwargs.get("text", "")
    assert "Guardado Exitoso" in final_text
    assert "D1 MEDELLIN" in final_text
    assert "50,000.00" in final_text
    # 4. Standalone push notification "guardado" should NOT be sent
    assert not any("guardado" in str(call) for call in bot.application.bot.send_message.call_args_list)
