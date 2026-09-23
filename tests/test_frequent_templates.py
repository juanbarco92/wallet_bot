import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.storage import TransactionStorage
from src.bot import TransactionsBot

class TestFrequentTemplates:
    def test_storage_template_crud(self):
        storage = TransactionStorage(db_path=":memory:")
        
        # 1. Save templates for Juanma
        storage.save_recurring_template(
            name="Arriendo",
            amount=1800000.0,
            category="🏠 Vivienda - Arriendo",
            scope="Familiar",
            usuario="Juanma",
            tx_type="Gasto",
            is_monthly=1
        )
        storage.save_recurring_template(
            name="Mercado Plaza",
            amount=150000.0,
            category="🛒 Mercado - Supermercado",
            scope="Familiar",
            usuario="Juanma",
            tx_type="Gasto",
            is_monthly=0 # On demand only
        )

        # 2. Save template for Leydi (User isolation check)
        storage.save_recurring_template(
            name="Gimnasio",
            amount=120000.0,
            category="💪 Deporte - Gimnasio",
            scope="Personal",
            usuario="Leydi",
            tx_type="Gasto",
            is_monthly=1
        )

        # 3. Retrieve for Juanma
        juanma_all = storage.get_recurring_templates(usuario="Juanma")
        assert len(juanma_all) == 2
        names = [t["name"] for t in juanma_all]
        assert "Arriendo" in names
        assert "Mercado Plaza" in names
        assert "Gimnasio" not in names # Strict user privacy

        # 4. Monthly review filter (/fijos)
        juanma_monthly = storage.get_recurring_templates(usuario="Juanma", only_monthly=True)
        assert len(juanma_monthly) == 1
        assert juanma_monthly[0]["name"] == "Arriendo"

        # 5. Get by name
        arriendo = storage.get_recurring_template("Arriendo", "Juanma")
        assert arriendo is not None
        assert arriendo["amount"] == 1800000.0
        assert arriendo["category"] == "🏠 Vivienda - Arriendo"

        # 6. Update template via UPSERT
        storage.save_recurring_template(
            name="Arriendo",
            amount=1900000.0,
            category="🏠 Vivienda - Arriendo",
            scope="Familiar",
            usuario="Juanma",
            tx_type="Gasto",
            is_monthly=1
        )
        arriendo_updated = storage.get_recurring_template("Arriendo", "Juanma")
        assert arriendo_updated["amount"] == 1900000.0

        # 7. Delete template
        assert storage.delete_recurring_template("Mercado Plaza", "Juanma") is True
        assert storage.get_recurring_template("Mercado Plaza", "Juanma") is None
        assert len(storage.get_recurring_templates(usuario="Juanma")) == 1

@pytest.mark.asyncio
async def test_frecuentes_command_renders_buttons():
    storage = TransactionStorage(db_path=":memory:")
    storage.save_recurring_template(
        name="Arriendo",
        amount=1800000.0,
        category="🏠 Vivienda - Arriendo",
        scope="Familiar",
        usuario="Juanma",
        is_monthly=1
    )

    bot = TransactionsBot(token="DUMMY", storage=storage)
    bot.application = MagicMock()
    bot.application.bot = AsyncMock()

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []

    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot.start_frecuentes_flow(update, context)

    assert update.message.reply_text.called
    args, kwargs = update.message.reply_text.call_args
    assert "Transacciones Frecuentes" in args[0]
    keyboard = kwargs.get("reply_markup").inline_keyboard
    button_callbacks = [btn.callback_data for row in keyboard for btn in row]
    assert "FAV|SEL_Arriendo" in button_callbacks
    assert "FAV|NEW" in button_callbacks
    assert "FAV|MANAGE" in button_callbacks

@pytest.mark.asyncio
async def test_frecuentes_quicksave_execution():
    storage = TransactionStorage(db_path=":memory:")
    storage.save_recurring_template(
        name="Servicios EPM",
        amount=320000.0,
        category="💡 Servicios - Energía",
        scope="Familiar",
        usuario="Juanma",
        is_monthly=1
    )

    mock_loader = MagicMock()
    mock_loader.append_transaction.return_value = True
    mock_loader.get_accumulated_total.return_value = 320000.0

    bot = TransactionsBot(token="DUMMY", storage=storage, loader=mock_loader)
    bot.application = MagicMock()
    bot.application.bot = AsyncMock()

    query = MagicMock()
    query.message.message_id = 999
    query.message.chat_id = 12345
    query.from_user.id = 12345
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    context = MagicMock()

    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot._handle_fav_callback(update, context, query, "SAVE_Servicios EPM")

    # Verify append to sheets
    assert mock_loader.append_transaction.called
    t_data = mock_loader.append_transaction.call_args[0][0]
    assert t_data["amount"] == 320000.0
    assert t_data["merchant"] == "Servicios EPM"

    # Verify SQLite tracking
    recent = storage.get_recent_transactions(limit=1, usuario="Juanma")
    assert len(recent) == 1
    assert recent[0]["comercio"] == "Servicios EPM"
    assert recent[0]["estado"] == "DILIGENCIADA"

    # Verify Telegram message confirmation
    assert query.edit_message_text.called
    confirm_text = query.edit_message_text.call_args[1]["text"]
    assert "Guardado Exitoso" in confirm_text
    assert "Servicios EPM" in confirm_text
    assert "$320,000.00" in confirm_text

@pytest.mark.asyncio
async def test_frecuentes_custom_amount_flow():
    storage = TransactionStorage(db_path=":memory:")
    storage.save_recurring_template(
        name="Mercado Plaza",
        amount=150000.0,
        category="🛒 Mercado - Supermercado",
        scope="Familiar",
        usuario="Juanma",
        is_monthly=0
    )

    mock_loader = MagicMock()
    mock_loader.append_transaction.return_value = True
    mock_loader.get_accumulated_total.return_value = 185000.0

    bot = TransactionsBot(token="DUMMY", storage=storage, loader=mock_loader)
    bot.application = MagicMock()
    bot.application.bot = AsyncMock()

    # Step 1: User clicks EDIT (otro monto)
    query = MagicMock()
    query.message.message_id = 555
    query.message.chat_id = 12345
    query.from_user.id = 12345
    query.edit_message_text = AsyncMock()
    update_btn = MagicMock()
    context = MagicMock()

    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot._handle_fav_callback(update_btn, context, query, "EDIT_Mercado Plaza")

    assert 12345 in bot.fav_amount_sessions
    assert bot.fav_amount_sessions[12345]["name"] == "Mercado Plaza"

    # Step 2: User responds with new amount: "185k"
    msg_update = MagicMock()
    msg_update.effective_user.id = 12345
    msg_update.effective_chat.id = 12345
    msg_update.message.text = "185k"
    msg_update.message.reply_to_message = None

    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot.handle_message(msg_update, context)

    assert mock_loader.append_transaction.called
    saved_tx = mock_loader.append_transaction.call_args[0][0]
    assert saved_tx["amount"] == 185000.0

@pytest.mark.asyncio
async def test_template_creation_wizard():
    storage = TransactionStorage(db_path=":memory:")
    mock_loader = MagicMock()
    mock_loader.sync_recurring_template_to_sheet.return_value = True

    bot = TransactionsBot(token="DUMMY", storage=storage, loader=mock_loader)
    bot.application = MagicMock()
    bot.application.bot = AsyncMock()

    user_id = 12345
    context = MagicMock()

    # 1. Start wizard: /nuevo_frecuente
    start_update = MagicMock()
    start_update.effective_user.id = user_id
    start_update.effective_chat.id = user_id
    start_update.message.reply_text = AsyncMock()
    context.args = []

    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot.start_nuevo_template_flow(start_update, context)

    assert user_id in bot.template_sessions
    assert bot.template_sessions[user_id]["step"] == "WAITING_NAME"

    # 2. Enter name: "Lavada Carro"
    name_update = MagicMock()
    name_update.effective_user.id = user_id
    name_update.effective_chat.id = user_id
    name_update.message.text = "Lavada Carro"
    name_update.message.reply_text = AsyncMock()
    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot.handle_message(name_update, context)

    assert bot.template_sessions[user_id]["step"] == "WAITING_AMOUNT"
    assert bot.template_sessions[user_id]["data"]["name"] == "Lavada Carro"

    # 3. Enter amount: "35k"
    amt_update = MagicMock()
    amt_update.effective_user.id = user_id
    amt_update.effective_chat.id = user_id
    amt_update.message.text = "35k"
    amt_update.message.reply_text = AsyncMock()
    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot.handle_message(amt_update, context)

    assert bot.template_sessions[user_id]["step"] == "WAITING_SCOPE"
    assert bot.template_sessions[user_id]["data"]["amount"] == 35000.0

    # 4. Callback: Scope Personal
    query = MagicMock()
    query.from_user.id = user_id
    query.edit_message_text = AsyncMock()
    scope_update = MagicMock()
    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot._handle_templ_callback(scope_update, context, query, "SCOPE_Personal")

    assert bot.template_sessions[user_id]["step"] == "WAITING_CAT"
    assert bot.template_sessions[user_id]["data"]["scope"] == "Personal"

    # 5. Callback: Category
    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot._handle_templ_callback(scope_update, context, query, "CAT_🚗 Transporte")

    assert bot.template_sessions[user_id]["step"] == "WAITING_SUBCAT"

    # 6. Callback: Subcategory
    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot._handle_templ_callback(scope_update, context, query, "SUBCAT_Lavado")

    assert bot.template_sessions[user_id]["step"] == "WAITING_MONTHLY"

    # 7. Callback: Monthly (0 = On-demand)
    with patch.object(bot, '_get_user_label', return_value="Juanma"):
        await bot._handle_templ_callback(scope_update, context, query, "MONTHLY_0")

    assert user_id not in bot.template_sessions

    # Verify template is saved in storage
    saved = storage.get_recurring_template("Lavada Carro", "Juanma")
    assert saved is not None
    assert saved["amount"] == 35000.0
    assert saved["is_monthly"] == 0
    assert "🚗 Transporte" in saved["category"]

@pytest.mark.asyncio
async def test_recurring_monthly_review_flow():
    storage = TransactionStorage(db_path=":memory:")
    storage.save_recurring_template(
        name="Seguro Médico",
        amount=250000.0,
        category="🏥 Salud - Medicina Prepagada",
        scope="Personal",
        usuario="Leydi",
        is_monthly=1
    )

    mock_loader = MagicMock()
    mock_loader.append_transaction.return_value = True

    bot = TransactionsBot(token="DUMMY", storage=storage, loader=mock_loader)
    bot.application = MagicMock()
    bot.application.bot = AsyncMock()

    user_id = 99999
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.callback_query = None
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    # 1. Start monthly review: /fijos
    with patch.object(bot, '_get_user_label', return_value="Leydi"):
        await bot.start_recurring_flow(update, context)

    assert user_id in bot.recurring_sessions
    assert bot.recurring_sessions[user_id]["status"] == "RECURRING_REVIEW"

    # 2. Confirm registration (REC|YES)
    query = MagicMock()
    query.from_user.id = user_id
    query.edit_message_text = AsyncMock()
    context.bot.send_message = AsyncMock()

    with patch.object(bot, '_get_user_label', return_value="Leydi"):
        await bot._process_recurring_item_save(update, context, user_id)

    # Loader appended row
    assert mock_loader.append_transaction.called
    saved_tx = mock_loader.append_transaction.call_args[0][0]
    assert saved_tx["amount"] == 250000.0
    assert saved_tx["merchant"] == "Seguro Médico"

    # SQLite recorded as DILIGENCIADA
    recent = storage.get_recent_transactions(limit=1, usuario="Leydi")
    assert len(recent) == 1
    assert recent[0]["comercio"] == "Seguro Médico"
    assert recent[0]["estado"] == "DILIGENCIADA"
