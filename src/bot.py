import asyncio
import os
import re
from datetime import datetime
from typing import Dict, Optional, List, Tuple, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from telegram.error import NetworkError, TimedOut, Conflict
import logging
from src.config import CATEGORIES_CONFIG, RECURRING_EXPENSES
from src.storage import TransactionStorage
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN_JUANMA")

def escape_md(text):
    """Escapes special characters for Markdown V1."""
    if not text:
        return ""
    # In Markdown V1, we mainly need to escape *, _, `, [
    return str(text).replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')

from telegram.request import HTTPXRequest

class TransactionsBot:
    def __init__(self, loader=None, token=None, notifier=None, storage=None):
        self.token = token or TOKEN
        self.notifier = notifier # Callback for notifications (e.g., email)
        self.loader = loader
        self.storage = storage if storage is not None else TransactionStorage()
        
        self.pending_futures: Dict[str, asyncio.Future] = {}
        self.flow_data: Dict[str, Dict] = {} 
        self.manual_sessions: Dict[int, Dict] = {} 
        self.recurring_sessions: Dict[int, Dict] = {} # {chat_id: {queue: [], index: 0}}
        self.fav_amount_sessions: Dict[int, Dict] = {} # {user_id: {"name": ..., "user_name": ...}}
        self.template_sessions: Dict[int, Dict] = {} # {user_id: {"step": ..., "data": ...}}
        self.chat_id: Optional[int] = None
        
        # Build immediately
        self._build_application()

    def _build_application(self):
        """Builds (or rebuilds) the Telegram Application and registers handlers."""
        # Configure request with longer timeouts for VM stability
        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0
        )
        
        self.application = ApplicationBuilder().token(self.token).request(request).build()
        
        # Handlers
        start_handler = CommandHandler('start', self.start)
        manual_handler = CommandHandler('manual', self.start_manual_flow)
        callback_handler = CallbackQueryHandler(self.button)
        message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_message)
        
        self.application.add_handler(start_handler)
        self.application.add_handler(manual_handler)
        self.application.add_handler(CommandHandler('m', self.start_manual_flow)) # Shortcut
        self.application.add_handler(CommandHandler('fijos', self.start_recurring_flow)) # Recurring
        self.application.add_handler(CommandHandler('frecuentes', self.start_frecuentes_flow))
        self.application.add_handler(CommandHandler('f', self.start_frecuentes_flow))
        self.application.add_handler(CommandHandler('fav', self.start_frecuentes_flow))
        self.application.add_handler(CommandHandler('nuevo_frecuente', self.start_nuevo_template_flow))
        self.application.add_handler(CommandHandler('nuevo_fijo', self.start_nuevo_template_flow))
        self.application.add_handler(CommandHandler('nf', self.start_nuevo_template_flow))
        self.application.add_handler(CommandHandler('borrar_frecuente', self.start_borrar_template_flow))
        self.application.add_handler(CommandHandler('bf', self.start_borrar_template_flow))
        self.application.add_handler(CommandHandler('pendientes', self.show_pending))
        self.application.add_handler(CommandHandler('p', self.show_pending))
        self.application.add_handler(CommandHandler('ultimas', self.show_recent))
        self.application.add_handler(CommandHandler('u', self.show_recent))
        self.application.add_handler(callback_handler)
        self.application.add_handler(message_handler)
        self.application.add_error_handler(self.global_error_handler)

    async def global_error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global error handler that auto-heals webhook conflicts."""
        err = context.error
        logger.error(f"Telegram error in bot update loop: {err}")
        if isinstance(err, Conflict) or "deleteWebhook" in str(err) or "Conflict" in str(err):
            logger.warning("⚠️ Conflicto de Webhook detectado en Telegram. Eliminando webhook automáticamente...")
            try:
                await self.application.bot.delete_webhook(drop_pending_updates=False)
                logger.info("✅ Webhook conflictivo eliminado exitosamente.")
            except Exception as we:
                logger.error(f"Fallo al intentar auto-eliminar webhook: {we}")

    async def _retry_request(self, func, *args, **kwargs):
        """Retries a Telegram API request on network failure."""
        max_retries = 3
        delay = 2
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except (TimedOut, NetworkError) as e:
                logger.warning(f"⚠️ Telegram Request failed (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(delay)
                delay *= 2

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.chat_id = update.effective_chat.id
        print(f"\n✅ BY JUPITER! I HAVE FOUND YOUR CHAT ID: {self.chat_id}\n")
        logger.info(f"Chat ID received: {self.chat_id}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=f"Bot initialized! Your Chat ID is: {self.chat_id}. I will send you transactions here."
        )

    async def start_manual_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Starts the manual transaction registration."""
        user_id = update.effective_user.id
        self.chat_id = update.effective_chat.id
        
        if context.args:
            try:
                amount_str = context.args[0].replace(',', '').replace('$', '')
                if amount_str.lower().endswith('k'):
                    amount = float(amount_str.lower().replace('k', '')) * 1000
                else:
                    amount = float(amount_str)
                
                if len(context.args) >= 2:
                    desc = " ".join(context.args[1:]).strip()
                    
                    from datetime import datetime
                    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
                    transaction_data = {
                        "amount": amount,
                        "merchant": desc,
                        "date": now_str,
                        "source": "manual"
                    }
                    if self.storage:
                        tx_id = self.storage.insert_incoming_transaction(
                            origen="manual",
                            comercio=desc,
                            monto=amount,
                            fecha=now_str,
                            usuario=self._get_user_label(),
                            raw_text=f"/manual {amount} {desc}"
                        )
                        transaction_data["db_id"] = tx_id
                    
                    await self._retry_request(update.message.reply_text, f"💰 Monto: ${amount:,.2f}\n✅ Descripción: {desc}. Clasificando...", parse_mode='Markdown')
                    asyncio.create_task(self.process_manual_transaction(transaction_data))
                    return
                else:
                    self.manual_sessions[user_id] = {
                        "status": "MANUAL_WAITING_DESC",
                        "data": {"amount": amount}
                    }
                    await self._retry_request(update.message.reply_text, f"💰 Monto: ${amount:,.2f}\n\nAhora ingresa una *Descripción* (tienda, concepto, etc):", parse_mode='Markdown')
                    return
            except ValueError:
                pass
        
        self.manual_sessions[user_id] = {
            "status": "MANUAL_WAITING_AMOUNT",
            "data": {}
        }
        
        await update.message.reply_text("📝 *Nueva Transacción Manual*\n\nPor favor ingresa el *Monto* de la transacción:\n(Ej: 50000)", parse_mode='Markdown')
    async def start_recurring_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Starts the flow to confirm recurring expenses (monthly review)."""
        user_id = update.effective_user.id if update.effective_user else None
        self.chat_id = update.effective_chat.id if update.effective_chat else self.chat_id
        user_name = self._get_user_label(user_id)
        
        queue = []
        if self.storage:
            templates = self.storage.get_recurring_templates(usuario=user_name, only_monthly=True)
            if templates:
                queue = [
                    {
                        "name": t["name"],
                        "amount": t["amount"],
                        "category": t["category"],
                        "scope": t["scope"],
                        "owner": t["usuario"],
                        "tx_type": t.get("tx_type", "Gasto")
                    }
                    for t in templates
                ]

        if not queue and self.loader:
            sheet_items = self.loader.get_recurring_expenses_for_user(usuario=user_name, chat_id=self.chat_id)
            if sheet_items:
                queue = sheet_items
                if self.storage:
                    for it in sheet_items:
                        self.storage.save_recurring_template(
                            name=it["name"],
                            amount=it["amount"],
                            category=it["category"],
                            scope=it["scope"],
                            usuario=user_name,
                            tx_type=it.get("tx_type", "Gasto"),
                            is_monthly=1
                        )

        if not queue:
            await self._retry_request(
                update.message.reply_text,
                f"⚠️ No tienes gastos fijos mensuales configurados para {escape_md(user_name)}.\n\n"
                f"Usa `/nuevo_fijo` o `/nuevo_frecuente` para crear uno.",
                parse_mode='Markdown'
            )
            return

        self.recurring_sessions[user_id] = {
            "queue": [item.copy() for item in queue],
            "index": 0,
            "status": "RECURRING_REVIEW",
            "saved_count": 0
        }
        
        await self._show_next_recurring_item(update, context, user_id)

    async def _show_next_recurring_item(self, update, context, user_id):
        session = self.recurring_sessions[user_id]
        idx = session["index"]
        queue = session["queue"]
        
        if idx >= len(queue):
            saved = session.get("saved_count", 0)
            del self.recurring_sessions[user_id]
            await self._retry_request(
                context.bot.send_message if update.callback_query else update.message.reply_text,
                chat_id=self.chat_id,
                text=f"✅ *Proceso Finalizado*\nSe registraron {saved} gastos fijos mensuales.",
                parse_mode='Markdown'
            )
            return

        item = queue[idx]
        msg = (
            f"📅 *Gasto Fijo {idx + 1}/{len(queue)}*\n"
            f"🏷️ {escape_md(item['name'])}\n"
            f"💵 ${item['amount']:,.2f}\n"
            f"📁 {escape_md(item['category'])} ({escape_md(item['scope'])})\n\n"
            f"¿Registrar?"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Sí, Registrar", callback_data="REC|YES"),
                InlineKeyboardButton("✏️ Editar Valor", callback_data="REC|EDIT"),
            ],
            [
                InlineKeyboardButton("⏭️ Saltar", callback_data="REC|SKIP"),
                InlineKeyboardButton("❌ Cancelar Todo", callback_data="REC|CANCEL"),
            ]
        ]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await self._retry_request(update.message.reply_text, text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def _process_recurring_item_save(self, update, context, user_id):
        session = self.recurring_sessions[user_id]
        idx = session["index"]
        item = session["queue"][idx]
        user_name = item.get("owner") or self._get_user_label(user_id)
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        saved = False
        if self.loader:
            t_data = {
                "date": now_str,
                "amount": item["amount"],
                "merchant": item["name"]
            }
            saved = self.loader.append_transaction(
                t_data, 
                category=item["category"], 
                scope=item["scope"], 
                user_who_paid=user_name, 
                transaction_type=item.get("tx_type", "Gasto")
            )
        else:
            saved = True

        if saved:
            session["saved_count"] += 1
            if self.storage:
                tx_id = self.storage.insert_incoming_transaction(
                    origen="fijos_mensual",
                    comercio=item["name"],
                    monto=item["amount"],
                    fecha=now_str,
                    usuario=user_name,
                    raw_text=f"Gasto Fijo: {item['name']}"
                )
                self.storage.mark_as_synced(0, tx_id=tx_id)
                self.storage.record_merchant_learning(
                    merchant=item["name"],
                    category_full=item["category"],
                    scope=item["scope"],
                    tx_type=item.get("tx_type", "Gasto"),
                    usuario=user_name
                )
        else:
            await self._retry_request(context.bot.send_message, chat_id=self.chat_id, text=f"⚠️ Error guardando {item['name']}")
        
        session["index"] += 1
        self.recurring_sessions[user_id] = session
        await self._show_next_recurring_item(update, context, user_id)

    # --- Frequent Templates (/frecuentes, /fav, /f) ---
    async def start_frecuentes_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays frequent/favorite transaction templates as interactive buttons."""
        user_id = update.effective_user.id if update.effective_user else None
        user_name = self._get_user_label(user_id)
        chat_id = update.effective_chat.id if update.effective_chat else self.chat_id
        self.chat_id = chat_id

        # Direct argument matching (e.g. /frecuentes Arriendo)
        if context.args:
            query_name = " ".join(context.args).strip()
            template = self.storage.get_recurring_template(query_name, user_name) if self.storage else None
            if template:
                await self._render_template_confirmation(update, context, template, user_name)
                return

        templates = self.storage.get_recurring_templates(usuario=user_name) if self.storage else []
        
        # If storage empty, seed from Sheets if available
        if not templates and self.loader:
            sheet_items = self.loader.get_recurring_expenses_for_user(usuario=user_name, chat_id=chat_id)
            if sheet_items:
                if self.storage:
                    for it in sheet_items:
                        self.storage.save_recurring_template(
                            name=it["name"],
                            amount=it["amount"],
                            category=it["category"],
                            scope=it["scope"],
                            usuario=user_name,
                            tx_type=it.get("tx_type", "Gasto"),
                            is_monthly=1
                        )
                    templates = self.storage.get_recurring_templates(usuario=user_name)

        if not templates:
            keyboard = [
                [InlineKeyboardButton("➕ Crear Nueva Plantilla", callback_data="FAV|NEW")]
            ]
            msg = (
                f"⭐ *Transacciones Frecuentes* ({escape_md(user_name)})\n\n"
                f"No tienes plantillas guardadas aún.\n"
                f"Crea una para registrar pagos repetitivos (ej: Arriendo, Servicios, Mercado Plaza) en 1 toque."
            )
            await self._retry_request(
                update.message.reply_text,
                msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return

        keyboard = []
        for t in templates:
            name = t["name"]
            amt = t.get("amount", 0.0)
            amt_str = f" (${amt:,.0f})" if amt > 0 else ""
            short_name = (name[:16] + "…") if len(name) > 16 else name
            keyboard.append([InlineKeyboardButton(f"📌 {short_name}{amt_str}", callback_data=f"FAV|SEL_{name}")])

        keyboard.append([
            InlineKeyboardButton("➕ Nueva", callback_data="FAV|NEW"),
            InlineKeyboardButton("🗑️ Eliminar", callback_data="FAV|MANAGE")
        ])

        msg = (
            f"⭐ *Transacciones Frecuentes* ({escape_md(user_name)})\n"
            f"Selecciona una para registrarla rápidamente:"
        )
        await self._retry_request(
            update.message.reply_text,
            msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def _render_template_confirmation(self, update, context, template: Dict[str, Any], user_name: str, query=None):
        """Displays options for a specific template."""
        name = template["name"]
        amt = template.get("amount", 0.0)
        cat = template.get("category", "")
        scope = template.get("scope", "Personal")
        tx_type = template.get("tx_type", "Gasto")

        keyboard = []
        if amt > 0:
            keyboard.append([InlineKeyboardButton(f"⚡ Guardar: ${amt:,.0f}", callback_data=f"FAV|SAVE_{name}")])
        keyboard.append([InlineKeyboardButton("✏️ Otro Monto", callback_data=f"FAV|EDIT_{name}")])
        keyboard.append([
            InlineKeyboardButton("🔙 Volver", callback_data="FAV|LIST"),
            InlineKeyboardButton("❌ Cancelar", callback_data="FAV|CANCEL")
        ])

        text = (
            f"⭐ *Plantilla:* *{escape_md(name)}*\n"
            f"👤 *Usuario:* {escape_md(user_name)}\n"
            f"📁 *Categoría:* {escape_md(cat)} ({escape_md(scope)}) [{escape_md(tx_type)}]\n"
            f"💵 *Monto Sugerido:* ${amt:,.2f}\n\n"
            f"¿Deseas registrarla con este valor o ingresar otro monto?"
        )

        if query:
            await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await self._retry_request(update.message.reply_text, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def start_nuevo_template_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Starts the wizard to create a new frequent/recurring template."""
        user_id = update.effective_user.id if update.effective_user else None
        user_name = self._get_user_label(user_id)
        chat_id = update.effective_chat.id if update.effective_chat else self.chat_id
        self.chat_id = chat_id

        self.template_sessions[user_id] = {
            "step": "WAITING_NAME",
            "data": {"usuario": user_name},
            "chat_id": chat_id
        }

        if context.args:
            args = list(context.args)
            last_arg = args[-1]
            amount = None
            try:
                amt_str = last_arg.replace(',', '').replace('$', '').strip()
                if amt_str.lower().endswith('k'):
                    amount = float(amt_str.lower().replace('k', '')) * 1000
                else:
                    amount = float(amt_str)
                name = " ".join(args[:-1]).strip()
            except ValueError:
                name = " ".join(args).strip()
                amount = 0.0

            if name:
                self.template_sessions[user_id]["data"]["name"] = name
                self.template_sessions[user_id]["data"]["amount"] = amount
                self.template_sessions[user_id]["step"] = "WAITING_SCOPE"
                keyboard = [
                    [
                        InlineKeyboardButton("🏠 Familiar", callback_data="TEMPL|SCOPE_Familiar"),
                        InlineKeyboardButton("👤 Personal", callback_data="TEMPL|SCOPE_Personal"),
                    ],
                    [
                        InlineKeyboardButton("❌ Cancelar", callback_data="TEMPL|CANCEL")
                    ]
                ]
                await self._retry_request(
                    update.message.reply_text,
                    f"📝 *Nueva Plantilla:* *{escape_md(name)}*\n"
                    f"💵 Monto: ${amount:,.2f}\n\n"
                    f"¿Es un gasto 🏠 Familiar o 👤 Personal?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                return

        await self._retry_request(
            update.message.reply_text,
            "📝 *Nueva Plantilla Frecuente / Fija*\n\n"
            "Por favor ingresa el *Nombre* de la plantilla (ej: Arriendo, Servicios EPM, Netflix, Mercado Plaza):",
            parse_mode='Markdown'
        )

    async def start_borrar_template_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays options to delete a frequent template."""
        user_id = update.effective_user.id if update.effective_user else None
        user_name = self._get_user_label(user_id)
        templates = self.storage.get_recurring_templates(usuario=user_name) if self.storage else []
        if not templates:
            await self._retry_request(update.message.reply_text, "ℹ️ No tienes plantillas para eliminar.")
            return

        keyboard = []
        for t in templates:
            keyboard.append([InlineKeyboardButton(f"🗑️ {t['name']}", callback_data=f"FAV|DEL_{t['name']}")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="FAV|CANCEL")])

        await self._retry_request(
            update.message.reply_text,
            "🗑️ *Eliminar Plantilla*\nSelecciona la plantilla que deseas borrar:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def _handle_fav_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query, value: str):
        """Handles callbacks for frequent templates (/frecuentes)."""
        user_id = query.from_user.id if query.from_user else None
        user_name = self._get_user_label(user_id)

        if value == "LIST" or value == "SHOW":
            templates = self.storage.get_recurring_templates(usuario=user_name) if self.storage else []
            if not templates:
                await query.edit_message_text(
                    "ℹ️ No tienes plantillas guardadas. Usa /nuevo_frecuente para agregar una."
                )
                return
            keyboard = []
            for t in templates:
                name = t["name"]
                amt = t.get("amount", 0.0)
                amt_str = f" (${amt:,.0f})" if amt > 0 else ""
                short_name = (name[:16] + "…") if len(name) > 16 else name
                keyboard.append([InlineKeyboardButton(f"📌 {short_name}{amt_str}", callback_data=f"FAV|SEL_{name}")])
            keyboard.append([
                InlineKeyboardButton("➕ Nueva", callback_data="FAV|NEW"),
                InlineKeyboardButton("🗑️ Eliminar", callback_data="FAV|MANAGE")
            ])
            msg = (
                f"⭐ *Transacciones Frecuentes* ({escape_md(user_name)})\n"
                f"Selecciona una para registrarla rápidamente:"
            )
            await query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return

        elif value.startswith("SEL_"):
            name = value.replace("SEL_", "", 1).strip()
            template = self.storage.get_recurring_template(name, user_name) if self.storage else None
            if not template:
                await query.answer("Plantilla no encontrada.")
                return
            await self._render_template_confirmation(update, context, template, user_name, query=query)

        elif value.startswith("SAVE_"):
            name = value.replace("SAVE_", "", 1).strip()
            template = self.storage.get_recurring_template(name, user_name) if self.storage else None
            if not template:
                await query.answer("Plantilla no encontrada.")
                return
            await self._save_template_transaction(
                query=query,
                template=template,
                amount=template["amount"],
                user_name=user_name
            )

        elif value.startswith("EDIT_"):
            name = value.replace("EDIT_", "", 1).strip()
            self.fav_amount_sessions[user_id] = {
                "name": name,
                "user_name": user_name,
                "message_id": query.message.message_id
            }
            await query.edit_message_text(
                text=f"✏️ Ingresa el nuevo monto para *{escape_md(name)}*:\n(Ej: 45000 o 45k)",
                parse_mode='Markdown'
            )

        elif value == "NEW":
            self.template_sessions[user_id] = {
                "step": "WAITING_NAME",
                "data": {"usuario": user_name},
                "chat_id": query.message.chat_id
            }
            await query.edit_message_text(
                text="📝 *Nueva Plantilla Frecuente*\n\nIngresa el *Nombre* de la plantilla (ej: Arriendo, Netflix, Servicios EPM):",
                parse_mode='Markdown'
            )

        elif value == "MANAGE":
            templates = self.storage.get_recurring_templates(usuario=user_name) if self.storage else []
            keyboard = []
            for t in templates:
                keyboard.append([InlineKeyboardButton(f"🗑️ {t['name']}", callback_data=f"FAV|DEL_{t['name']}")])
            keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="FAV|LIST")])
            await query.edit_message_text(
                text="🗑️ *Eliminar Plantilla*\nSelecciona la plantilla que deseas borrar:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        elif value.startswith("DEL_"):
            name = value.replace("DEL_", "", 1).strip()
            if self.storage:
                self.storage.delete_recurring_template(name, user_name)
            if self.loader:
                self.loader.delete_recurring_template_from_sheet(name, user_name)
            keyboard = [[InlineKeyboardButton("📋 Volver a la lista", callback_data="FAV|LIST")]]
            await query.edit_message_text(
                text=f"🗑️ Plantilla *{escape_md(name)}* eliminada exitosamente.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        elif value == "CANCEL":
            if user_id in self.fav_amount_sessions:
                del self.fav_amount_sessions[user_id]
            await query.edit_message_text(text="❌ Operación cancelada.")

    async def _handle_templ_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query, value: str):
        """Handles callbacks for template wizard creation (/nuevo_frecuente)."""
        user_id = query.from_user.id if query.from_user else None
        user_name = self._get_user_label(user_id)

        if user_id not in self.template_sessions:
            await query.edit_message_text("⚠️ Sesión de plantilla expirada. Usa /nuevo_frecuente de nuevo.")
            return

        session = self.template_sessions[user_id]

        if value == "CANCEL":
            del self.template_sessions[user_id]
            await query.edit_message_text("❌ Creación de plantilla cancelada.")
            return

        if value.startswith("SCOPE_"):
            scope = value.replace("SCOPE_", "", 1)
            session["data"]["scope"] = scope
            session["step"] = "WAITING_CAT"

            categories = CATEGORIES_CONFIG.get(scope, {})
            keyboard = []
            row = []
            for cat in categories.keys():
                row.append(InlineKeyboardButton(cat, callback_data=f"TEMPL|CAT_{cat}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="TEMPL|CANCEL")])

            await query.edit_message_text(
                text=f"Ámbito: *{escape_md(scope)}*\n\n📁 Selecciona la Categoría:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return

        elif value.startswith("CAT_"):
            cat = value.replace("CAT_", "", 1)
            session["data"]["category_main"] = cat
            session["step"] = "WAITING_SUBCAT"
            scope = session["data"].get("scope", "Personal")

            subcats = CATEGORIES_CONFIG.get(scope, {}).get(cat, [])
            keyboard = []
            row = []
            for sub in subcats:
                row.append(InlineKeyboardButton(sub, callback_data=f"TEMPL|SUBCAT_{sub}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="TEMPL|CANCEL")])

            await query.edit_message_text(
                text=f"Categoría: *{escape_md(cat)}*\n\n📂 Selecciona la Subcategoría:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return

        elif value.startswith("SUBCAT_"):
            sub = value.replace("SUBCAT_", "", 1)
            cat_main = session["data"].get("category_main", "")
            cat_full = f"{cat_main} - {sub}" if cat_main and sub != cat_main else (sub or cat_main)
            session["data"]["category"] = cat_full
            session["step"] = "WAITING_MONTHLY"

            keyboard = [
                [
                    InlineKeyboardButton("📅 Sí, mensual (/fijos)", callback_data="TEMPL|MONTHLY_1"),
                    InlineKeyboardButton("⚡ Solo frecuente (/frecuentes)", callback_data="TEMPL|MONTHLY_0"),
                ],
                [
                    InlineKeyboardButton("❌ Cancelar", callback_data="TEMPL|CANCEL")
                ]
            ]
            await query.edit_message_text(
                text=(
                    f"📁 Categoría: *{escape_md(cat_full)}*\n\n"
                    f"📅 ¿Deseas incluirlo en la revisión de gastos fijos mensuales (`/fijos`)?"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return

        elif value.startswith("MONTHLY_"):
            is_monthly = int(value.replace("MONTHLY_", "", 1))
            session["data"]["is_monthly"] = is_monthly
            
            data = session["data"]
            name = data["name"]
            amount = float(data.get("amount", 0.0))
            category = data["category"]
            scope = data.get("scope", "Personal")
            tx_type = data.get("tx_type", "Gasto")

            # Save in SQLite
            if self.storage:
                self.storage.save_recurring_template(
                    name=name,
                    amount=amount,
                    category=category,
                    scope=scope,
                    usuario=user_name,
                    tx_type=tx_type,
                    is_monthly=is_monthly
                )

            # Sync in Google Sheets
            if self.loader:
                try:
                    self.loader.sync_recurring_template_to_sheet(
                        {
                            "name": name,
                            "amount": amount,
                            "category": category,
                            "scope": scope,
                            "usuario": user_name,
                            "tx_type": tx_type,
                            "is_monthly": is_monthly
                        },
                        chat_id=session.get("chat_id")
                    )
                except Exception as e:
                    logger.error(f"Error syncing template to sheet: {e}")

            del self.template_sessions[user_id]

            tipo_desc = "📅 Gasto Fijo Mensual (/fijos y /frecuentes)" if is_monthly else "⚡ Acceso Rápido (/frecuentes)"
            text = (
                f"✅ *Plantilla Creada Exitosamente*\n\n"
                f"🏷️ *Nombre:* {escape_md(name)}\n"
                f"💵 *Monto Sugerido:* ${amount:,.2f}\n"
                f"📁 *Categoría:* {escape_md(category)} ({escape_md(scope)})\n"
                f"📌 *Modo:* {tipo_desc}\n\n"
                f"¡Ya puedes usarla con `/frecuentes`!"
            )
            keyboard = [[InlineKeyboardButton("⭐ Ver Frecuentes", callback_data="FAV|LIST")]]
            await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def _save_template_transaction(
        self,
        query,
        template: Dict[str, Any],
        amount: float,
        user_name: str,
        target_message_id: Optional[int] = None,
        chat_id: Optional[int] = None
    ):
        """Saves a frequent transaction from template to Sheets & SQLite with feedback."""
        t_name = template["name"]
        cat_full = template["category"]
        scope = template.get("scope", "Personal")
        tx_type = template.get("tx_type", "Gasto")
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        eff_chat_id = chat_id or (query.message.chat_id if query else self.chat_id)

        # 1. Google Sheets
        success = False
        if self.loader:
            t_data = {
                "date": now_str,
                "amount": amount,
                "merchant": t_name
            }
            success = self.loader.append_transaction(
                t_data,
                category=cat_full,
                scope=scope,
                user_who_paid=user_name,
                transaction_type=tx_type
            )
        else:
            success = True

        if not success:
            err_msg = f"⚠️ Error al guardar la transacción de '{t_name}' en Google Sheets."
            if query:
                await query.edit_message_text(text=err_msg)
            else:
                await self._retry_request(self.application.bot.send_message, chat_id=eff_chat_id, text=err_msg)
            return

        # 2. SQLite Tracking & Learning
        if self.storage:
            tx_id = self.storage.insert_incoming_transaction(
                origen="frecuente_manual",
                comercio=t_name,
                monto=amount,
                fecha=now_str,
                usuario=user_name,
                raw_text=f"Plantilla Frecuente: {t_name}"
            )
            self.storage.mark_as_synced(0, tx_id=tx_id)
            self.storage.record_merchant_learning(
                merchant=t_name,
                category_full=cat_full,
                scope=scope,
                tx_type=tx_type,
                usuario=user_name
            )

        # 3. Calculate accumulation
        accumulated = 0.0
        if self.loader:
            try:
                res = self.loader.get_accumulated_total(cat_full, scope, tx_type, user=user_name)
                accumulated = float(res) if isinstance(res, (int, float)) else 0.0
            except Exception:
                accumulated = 0.0

        clean_m = re.sub(r'\s+', ' ', str(t_name).replace('*', ' ')).strip()
        msg_text = (
            f"✅ *Guardado Exitoso* en Google Sheets\n\n"
            f"👤 *Usuario:* {escape_md(user_name)}\n"
            f"🛒 *Comercio:* {escape_md(clean_m)}\n"
            f"💵 *Monto:* ${amount:,.2f}\n"
            f"📅 *Fecha:* {escape_md(now_str)}\n\n"
            f"📁 *Clasificación:*\n"
            f"• *{escape_md(cat_full)}* ({escape_md(scope)}): ${amount:,.2f}\n"
        )
        if accumulated > 0:
            msg_text += f"   📊 Acumulado: ${accumulated:,.2f}\n"

        if query:
            try:
                await query.edit_message_text(text=msg_text, parse_mode='Markdown')
            except Exception:
                await query.edit_message_text(text=msg_text.replace('*', ''))
        elif target_message_id:
            try:
                await self.application.bot.edit_message_text(
                    chat_id=eff_chat_id,
                    message_id=target_message_id,
                    text=msg_text,
                    parse_mode='Markdown'
                )
            except Exception:
                await self._retry_request(self.application.bot.send_message, chat_id=eff_chat_id, text=msg_text, parse_mode='Markdown')
        else:
            await self._retry_request(self.application.bot.send_message, chat_id=eff_chat_id, text=msg_text, parse_mode='Markdown')

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages (for manual flow, recurring flow, frequent templates, or split flow)."""
        if not update.message:
            return

        user_id = update.effective_user.id
        user_name = self._get_user_label(user_id)

        # --- 1. Check for Recurring Session Waiting Amount ---
        if user_id in self.recurring_sessions:
            r_session = self.recurring_sessions[user_id]
            if r_session.get("status") == "RECURRING_WAITING_AMOUNT":
                try:
                    text = update.message.text.replace(',', '').replace('$', '').strip()
                    if text.lower().endswith('k'):
                        amount = float(text.lower().replace('k', '')) * 1000
                    else:
                        amount = float(text)
                    current_idx = r_session["index"]
                    r_session["queue"][current_idx]["amount"] = amount
                    r_session["status"] = "RECURRING_REVIEW"
                    await self._process_recurring_item_save(update, context, user_id)
                except ValueError:
                    await self._retry_request(update.message.reply_text, "❌ Número inválido. Intenta de nuevo (ej: 50000 o 50k).")
                return

        # --- 2. Check for Frequent Template Custom Amount ---
        if user_id in self.fav_amount_sessions:
            f_session = self.fav_amount_sessions[user_id]
            try:
                text = update.message.text.replace(',', '').replace('$', '').strip()
                if text.lower().endswith('k'):
                    amount = float(text.lower().replace('k', '')) * 1000
                else:
                    amount = float(text)
                
                t_name = f_session["name"]
                del self.fav_amount_sessions[user_id]

                template = self.storage.get_recurring_template(t_name, user_name) if self.storage else None
                if template:
                    await self._save_template_transaction(
                        query=None,
                        template=template,
                        amount=amount,
                        user_name=user_name,
                        target_message_id=f_session.get("message_id"),
                        chat_id=update.effective_chat.id
                    )
                else:
                    await self._retry_request(update.message.reply_text, f"⚠️ No se encontró la plantilla '{t_name}'.")
            except ValueError:
                await self._retry_request(update.message.reply_text, "❌ Por favor ingresa un número válido (ej: 45000 o 45k).")
            return

        # --- 3. Check for Template Creation Wizard ---
        if user_id in self.template_sessions:
            t_session = self.template_sessions[user_id]
            step = t_session.get("step")

            if step == "WAITING_NAME":
                name = update.message.text.strip()
                if not name:
                    await self._retry_request(update.message.reply_text, "❌ El nombre no puede estar vacío.")
                    return
                t_session["data"]["name"] = name
                t_session["step"] = "WAITING_AMOUNT"
                await self._retry_request(
                    update.message.reply_text,
                    f"🏷️ Nombre: *{escape_md(name)}*\n\n💵 Ingresa el *Monto por defecto* (o 0 si varía cada mes):\n(Ej: 1800000 o 1800k o 0)",
                    parse_mode='Markdown'
                )
                return

            elif step == "WAITING_AMOUNT":
                try:
                    text = update.message.text.replace(',', '').replace('$', '').strip()
                    if text.lower().endswith('k'):
                        amount = float(text.lower().replace('k', '')) * 1000
                    else:
                        amount = float(text)
                    t_session["data"]["amount"] = amount
                    t_session["step"] = "WAITING_SCOPE"

                    keyboard = [
                        [
                            InlineKeyboardButton("🏠 Familiar", callback_data="TEMPL|SCOPE_Familiar"),
                            InlineKeyboardButton("👤 Personal", callback_data="TEMPL|SCOPE_Personal"),
                        ],
                        [
                            InlineKeyboardButton("❌ Cancelar", callback_data="TEMPL|CANCEL")
                        ]
                    ]
                    await self._retry_request(
                        update.message.reply_text,
                        f"💵 Monto: ${amount:,.2f}\n\n¿Es un gasto 🏠 Familiar o 👤 Personal?",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                except ValueError:
                    await self._retry_request(update.message.reply_text, "❌ Número inválido. Ingresa un número (ej: 50000, 50k o 0).")
                return

        # --- 4. Check for Manual Session ---
        if user_id in self.manual_sessions:
            session = self.manual_sessions[user_id]
            status = session.get("status")

            if status == "MANUAL_WAITING_AMOUNT":
                try:
                    text = update.message.text.replace(',', '').replace('$', '').strip()
                    if text.lower().endswith('k'):
                        amount = float(text.lower().replace('k', '')) * 1000
                    else:
                        amount = float(text)

                    session["data"]["amount"] = amount
                    session["status"] = "MANUAL_WAITING_DESC"
                    self.manual_sessions[user_id] = session

                    await self._retry_request(update.message.reply_text, f"💰 Monto: ${amount:,.2f}\n\nAhora ingresa una *Descripción* (tienda, concepto, etc):", parse_mode='Markdown')
                except ValueError:
                    await self._retry_request(update.message.reply_text, "❌ Número inválido. Intenta de nuevo (ej: 15000 o 15k).")
                return

            elif status == "MANUAL_WAITING_DESC":
                desc = update.message.text.strip()
                session["data"]["merchant"] = desc
                now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
                session["data"]["date"] = now_str
                session["data"]["source"] = "manual"

                # Insert into storage
                if self.storage:
                    tx_id = self.storage.insert_incoming_transaction(
                        origen="manual",
                        comercio=desc,
                        monto=session["data"]["amount"],
                        fecha=now_str,
                        usuario=self._get_user_label(),
                        raw_text=f"/manual {session['data']['amount']} {desc}"
                    )
                    session["data"]["db_id"] = tx_id

                transaction_data = session["data"]
                del self.manual_sessions[user_id]

                await self._retry_request(update.message.reply_text, f"✅ Descripción: {desc}. Clasificando...")
                asyncio.create_task(self.process_manual_transaction(transaction_data))
                return

        # --- 2. Existing Split Flow (Waiting for Split Input) ---
        target_message_id = None
        
        # explicit reply
        if update.message.reply_to_message:
            target_message_id = update.message.reply_to_message.message_id
        
        # implicit context
        if not target_message_id:
             waiting_flows = [mid for mid, data in self.flow_data.items() if data.get("status") == "WAITING_AMOUNT"]
             if len(waiting_flows) == 1:
                 target_message_id = waiting_flows[0]
             elif len(waiting_flows) > 1:
                 # Only warn if not in a manual flow (already checked above)
                 await self._retry_request(update.message.reply_text, "⚠️ Múltiples transacciones pendientes. Responde (Reply) al mensaje específico.")
                 return
             else:
                 return

        if target_message_id not in self.flow_data:
            rec = self.storage.get_by_message_id(target_message_id) if self.storage else None
            if rec and rec.get("flow_state"):
                self.flow_data[target_message_id] = rec["flow_state"]
            else:
                return

        state = self.flow_data[target_message_id]
        if state.get("status") != "WAITING_AMOUNT":
            return

        try:
            self._save_history(target_message_id)
            # Parse amount
            text = update.message.text.replace(',', '').replace('$', '').strip()
            if text.lower().endswith('k'):
                amount_input = float(text.lower().replace('k', '')) * 1000
            else:
                amount_input = float(text)
            
            # Reset status handling
            state["status"] = "WAITING_SPLIT_SCOPE"
            state["current_split_amount"] = amount_input
            
            # Save back
            self.flow_data[target_message_id] = state
            if self.storage:
                self.storage.update_flow_state(target_message_id, state, estado="EN_PROCESO")
            
            keyboard = [
                [
                    InlineKeyboardButton("🏠 Familiar", callback_data="SCOPE|Familiar"),
                    InlineKeyboardButton("👤 Personal", callback_data="SCOPE|Personal"),
                ],
                [
                    InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                    InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART")
                ]
            ]
            
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=target_message_id,
                    text=self._get_flow_context_header(target_message_id) + f"Gasto por ${amount_input:,.2f}. ¿Es 🏠 Familiar o 👤 Personal?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )

            except Exception as e:
                logger.error(f"Failed to edit message {target_message_id}: {e}")
                await self._retry_request(
                    update.message.reply_text, 
                    self._get_flow_context_header(target_message_id) + f"Gasto por ${amount_input:,.2f}. ¿Es 🏠 Familiar o 👤 Personal?", 
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            
            # Delete user's message
            try:
                await update.message.delete()
            except:
                pass

        except ValueError:
            await self._retry_request(update.message.reply_text, "❌ Por favor ingresa un número válido (ej: 50000 o 50k).")

    async def process_manual_transaction(self, transaction: Dict):
        """Orchestrates the classification and saving for manual transactions."""
        logger.info(f"Processing manual transaction: {transaction}")
        
        # 1. Ask User (Reusing existing flow)
        splits, message_id = await self.ask_user_for_category(transaction)
        
        if not splits:
            if self.storage and message_id:
                self.storage.mark_as_discarded(message_id)
            if self.chat_id:
                try:
                    if message_id:
                        await self.application.bot.edit_message_text(chat_id=self.chat_id, message_id=message_id, text="❌ Transacción manual cancelada.")
                    else:
                        await self._retry_request(self.application.bot.send_message, chat_id=self.chat_id, text="❌ Transacción manual cancelada.")
                except:
                    pass
            return

        # 2. Save
        if self.loader:
            all_saved = True
            saved_cats = []
            for category, scope, amount, user_who_paid, tx_type in splits:
                t_copy = transaction.copy()
                t_copy['amount'] = amount
                success = self.loader.append_transaction(t_copy, category, scope=scope, user_who_paid=user_who_paid, transaction_type=tx_type)
                if success:
                    saved_cats.append(category)
                    if self.storage:
                        self.storage.record_merchant_learning(
                            merchant=transaction.get("merchant", "Manual"),
                            category_full=category,
                            scope=scope,
                            tx_type=tx_type or "Gasto",
                            usuario=user_who_paid
                        )
                else:
                    all_saved = False
            
            # Update SQLite status
            if all_saved:
                if self.storage and message_id:
                    self.storage.mark_as_synced(message_id)
            else:
                if self.storage and message_id:
                    self.storage.mark_as_error(message_id, "Error al guardar una o más filas en Google Sheets")

            # Confirm
            if all_saved:
                clean_m = re.sub(r'\s+', ' ', str(transaction.get('merchant') or 'Manual').replace('*', ' ')).strip()
                m_total = float(transaction.get('amount', 0.0))
                m_date = str(transaction.get('date') or '?')
                m_user = str(splits[0][3] if splits else 'User')

                msg_text = (
                    f"✅ *Guardado Exitoso* en Google Sheets\n\n"
                    f"👤 *Usuario:* {escape_md(m_user)}\n"
                    f"🛒 *Comercio:* {escape_md(clean_m)}\n"
                    f"💵 *Monto:* ${m_total:,.2f}\n"
                    f"📅 *Fecha:* {escape_md(m_date)}\n\n"
                    f"📁 *Clasificación:*\n"
                )
                
                for category, scope, amount, user_who_paid, tx_type in splits:
                    accumulated = 0.0
                    if self.loader:
                        try:
                            accumulated = self.loader.get_accumulated_total(category, scope, tx_type, user=user_who_paid)
                        except Exception:
                            pass
                    msg_text += f"• *{escape_md(category)}* ({escape_md(scope)}): ${amount:,.2f}\n"
                    if accumulated > 0:
                        msg_text += f"   📊 Acumulado: ${accumulated:,.2f}\n"

                target_chat_id = self.chat_id
                if not target_chat_id:
                    if self.storage and message_id:
                        rec = self.storage.get_by_message_id(message_id)
                        if rec and rec.get("telegram_chat_id"):
                            target_chat_id = rec["telegram_chat_id"]
                    if not target_chat_id:
                        env_chat_id = os.getenv("TELEGRAM_CHAT_ID_JUANMA")
                        if env_chat_id:
                            target_chat_id = int(env_chat_id)

                try:
                    if message_id:
                        await self.application.bot.edit_message_text(chat_id=target_chat_id, message_id=message_id, text=msg_text, parse_mode='Markdown')
                    else:
                        await self._retry_request(self.application.bot.send_message, chat_id=target_chat_id, text=msg_text, parse_mode='Markdown')
                except Exception as e:
                     logger.warning(f"Failed to edit confirmation message with Markdown ({e}), retrying plain text...")
                     clean_text = msg_text.replace('*', '')
                     if message_id:
                         try:
                             await self.application.bot.edit_message_text(chat_id=target_chat_id, message_id=message_id, text=clean_text)
                         except Exception as e2:
                             logger.error(f"Fallback plain text edit failed: {e2}")
                             await self._retry_request(self.application.bot.send_message, chat_id=target_chat_id, text=clean_text)
                     else:
                         await self._retry_request(self.application.bot.send_message, chat_id=target_chat_id, text=clean_text)
            else:
                 msg_err = "⚠️ Error al guardar en Google Sheets."
                 target_chat_id = self.chat_id or (int(os.getenv("TELEGRAM_CHAT_ID_JUANMA")) if os.getenv("TELEGRAM_CHAT_ID_JUANMA") else None)
                 try:
                     if message_id:
                         await self.application.bot.edit_message_text(chat_id=target_chat_id, message_id=message_id, text=msg_err)
                     else:
                         await self._retry_request(self.application.bot.send_message, chat_id=target_chat_id, text=msg_err)
                 except:
                      pass
        else:
             msg_err = "⚠️ Error: No hay conexión con Google Sheets."
             target_chat_id = self.chat_id or (int(os.getenv("TELEGRAM_CHAT_ID_JUANMA")) if os.getenv("TELEGRAM_CHAT_ID_JUANMA") else None)
             try:
                 if message_id:
                     await self.application.bot.edit_message_text(chat_id=target_chat_id, message_id=message_id, text=msg_err)
                 else:
                     await self._retry_request(self.application.bot.send_message, chat_id=target_chat_id, text=msg_err)
             except:
                  pass

    def _get_category_keyboard(self, scope="Personal", show_back=False):
        """Generates keyboard from config based on scope."""
        categories = CATEGORIES_CONFIG.get(scope, {})
        keyboard = []
        row = []
        for cat in categories.keys():
            row.append(InlineKeyboardButton(cat, callback_data=f"CAT|{cat}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        # Add Restart/Cancel options
        last_row = []
        if show_back:
            last_row.append(InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"))
        last_row.append(InlineKeyboardButton("🔄 Reiniciar", callback_data="CAT|RESTART"))
        keyboard.append(last_row)
        return keyboard

    def _get_subcategory_keyboard(self, category, scope="Personal", show_back=False):
        """Generates subcategory keyboard for a given category and scope."""
        categories = CATEGORIES_CONFIG.get(scope, {})
        subcats = categories.get(category, [])
        keyboard = []
        row = []
        for sub in subcats:
            row.append(InlineKeyboardButton(sub, callback_data=f"SUBCAT|{sub}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
        # Add Restart/Cancel options
        last_row = []
        if show_back:
            last_row.append(InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"))
        last_row.append(InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART"))
        keyboard.append(last_row)
        return keyboard

    async def button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        data = query.data
        message_id = query.message.message_id
        
        if "|" not in data:
            await query.edit_message_text(text=f"Error: Invalid data {data}")
            return

        step, value = data.split("|", 1)
        print(f"DEBUG FLOW: Recv Data={data} -> Step={step}, Value={value}")

        # PEND step handler (Resume/categorize from pending list)
        if step == "PEND":
            await self._handle_pending_callback(update, context, query, value)
            return

        # QUICK step handler (1-Click Smart Quick-Save)
        if step == "QUICK":
            await self._handle_quick_save(update, context, query, value)
            return

        # FAV step handler (Frequent transactions panel)
        if step == "FAV":
            await self._handle_fav_callback(update, context, query, value)
            return

        # TEMPL step handler (Template creation wizard)
        if step == "TEMPL":
            await self._handle_templ_callback(update, context, query, value)
            return

        # FLOW|BACK handler
        if step == "FLOW" and value == "BACK":
            if message_id in self.flow_data:
                state = self.flow_data[message_id]
                history = state.get("history", [])
                if history:
                    prev_state = history.pop()
                    for k, v in prev_state.items():
                        state[k] = v
                    state["history"] = history
                    if self.storage:
                        self.storage.update_flow_state(message_id, state, estado="EN_PROCESO")
                    await self._render_state(update, context, message_id, query)
                else:
                    try:
                        await query.answer("No hay más pasos atrás.")
                    except:
                        pass
            return

        # Save history if we are moving forward
        if step not in ("FLOW", "CONFIRM") and value != "RESTART":
             self._save_history(message_id)

        # Recovery/Check from Storage or Message Text
        if message_id not in self.flow_data:
            rec = self.storage.get_by_message_id(message_id) if self.storage else None
            if rec:
                estado = rec.get("estado")
                ext_id = rec.get("external_id")
                if estado in ("DILIGENCIADA", "DESCARTADA"):
                    await query.edit_message_text(text="✅ Esta transacción ya fue procesada anteriormente.")
                    return
                if ext_id:
                    ext_tx = self.storage.get_by_external_id(ext_id)
                    if ext_tx and ext_tx.get("estado") in ("DILIGENCIADA", "DESCARTADA"):
                        await query.edit_message_text(text="✅ Esta transacción ya fue procesada anteriormente.")
                        return

                flow_state = rec.get("flow_state") or {}
                self.flow_data[message_id] = {
                    "total_amount": flow_state.get("total_amount", rec["monto_total"]),
                    "remaining_amount": flow_state.get("remaining_amount", rec["monto_total"]),
                    "splits": flow_state.get("splits", []),
                    "scope": flow_state.get("scope", "Personal"),
                    "status": flow_state.get("status", "INIT"),
                    "merchant": rec["comercio"],
                    "date": rec["fecha_transaccion"],
                    "user_name": rec["usuario"],
                    "history": flow_state.get("history", []),
                    "is_multiple": flow_state.get("is_multiple", False),
                    "pending_category": flow_state.get("pending_category", ""),
                    "current_split_amount": flow_state.get("current_split_amount"),
                    "current_split_scope": flow_state.get("current_split_scope"),
                    "current_rel_category": flow_state.get("current_rel_category"),
                    "current_tx_type": flow_state.get("current_tx_type") or "Gasto"
                }
                logger.info(f"🔄 Transacción msg #{message_id} ({rec['comercio']}) restaurada desde SQLite.")
            else:
                parsed_ctx = self._parse_context_from_message_text(query.message.text or "")
                if parsed_ctx and parsed_ctx.get("amount", 0) > 0:
                    self.flow_data[message_id] = {
                        "total_amount": parsed_ctx["amount"],
                        "remaining_amount": parsed_ctx["amount"],
                        "splits": [],
                        "scope": "Personal",
                        "status": "INIT",
                        "merchant": parsed_ctx.get("merchant", "Desconocido"),
                        "date": parsed_ctx.get("date", "?"),
                        "user_name": parsed_ctx.get("user", "User"),
                        "history": []
                    }
                    if self.storage:
                        tx_id = self.storage.insert_incoming_transaction(
                            origen="recovered_telegram",
                            comercio=parsed_ctx.get("merchant", "Desconocido"),
                            monto=parsed_ctx["amount"],
                            fecha=parsed_ctx.get("date", "?"),
                            usuario=parsed_ctx.get("user", "User")
                        )
                        self.storage.bind_telegram_message(tx_id, message_id, query.message.chat_id, self.flow_data[message_id])
                    logger.info(f"🔄 Transacción msg #{message_id} recuperada desde el texto de Telegram.")
                elif step != "VALID":
                    from telegram.error import BadRequest
                    try:
                        await query.edit_message_text(text="⚠️ Sesión expirada. Intenta de nuevo.")
                    except BadRequest:
                        pass
                    return

        if step == "VALID" or value == "RESTART": 
             pass

        # Global Redirect for RESTART from any step
        if value == "RESTART":
            print("DEBUG FLOW: Redirecting RESTART to VALID step")
            step = "VALID"

        if step == "VALID":
            if value == "No":
                  # Cancel logic
                  state = self.flow_data.get(message_id, {})
                  merchant = state.get('merchant', 'Desconocido')
                  amount = state.get("total_amount", 0.0)
                  date = state.get("date", "?")
                  user = state.get("user_name", "User")
                  storage_id = state.get("storage_id")

                  if self.storage:
                      self.storage.mark_as_discarded(message_id, tx_id=storage_id)
                  
                  clean_m = str(merchant).strip("* ").replace("*", " ")
                  text = (
                      f"❌ *Transacción Descartada* ({escape_md(user)})\n"
                      f"🛒 {escape_md(clean_m)}\n"
                      f"💵 ${amount:,.2f}\n"
                      f"📅 {escape_md(date)}"
                  ) if state else "❌ Transacción descartada."

                  if message_id in self.pending_futures:
                      future = self.pending_futures[message_id]
                      if not future.done():
                          future.set_result([]) 
                          del self.pending_futures[message_id]
                  if message_id in self.flow_data:
                      del self.flow_data[message_id]

                  user_filter = user if user != "User" else None
                  remaining = self.storage.get_pending_transactions(usuario=user_filter) if self.storage else []
                  discard_keyboard = None
                  if isinstance(remaining, list) and len(remaining) > 0:
                      next_tx = remaining[0]
                      if isinstance(next_tx, dict):
                          text += f"\n\n📌 Te quedan *{len(remaining)}* transacciones pendientes:"
                          clean_nm = str(next_tx.get("comercio", "Desconocido")).strip("* ").replace("*", " ")
                          short_m = (clean_nm[:14] + "…") if len(clean_nm) > 14 else clean_nm
                          m_val = float(next_tx.get("monto_total", 0.0))
                          buttons = [
                              [InlineKeyboardButton(f"📝 Siguiente: {short_m} (${m_val:,.0f})", callback_data=f"PEND|SELECT_{next_tx.get('id', 0)}")],
                          ]
                          if len(remaining) > 1:
                              buttons.append([InlineKeyboardButton("📋 Ver lista de pendientes", callback_data="PEND|LIST")])
                          discard_keyboard = InlineKeyboardMarkup(buttons)

                  try:
                      await query.edit_message_text(text=text, reply_markup=discard_keyboard, parse_mode='Markdown')
                  except Exception as e:
                      clean_text = text.replace('*', '')
                      await query.edit_message_text(text=clean_text, reply_markup=discard_keyboard)
            
            elif value == "RESTART":
                  # Restart Logic
                  rec = self.storage.get_by_message_id(message_id) if self.storage else None
                  orig_amount = rec["monto_total"] if rec else self.flow_data.get(message_id, {}).get("total_amount", 0.0)
                  orig_merchant = rec["comercio"] if rec else self.flow_data.get(message_id, {}).get("merchant", "Desconocido")
                  orig_date = rec["fecha_transaccion"] if rec else self.flow_data.get(message_id, {}).get("date", "?")
                  orig_user = rec["usuario"] if rec else self.flow_data.get(message_id, {}).get("user_name", "User")

                  # Reset Internal State completely with original total
                  self.flow_data[message_id] = {
                      "total_amount": orig_amount,
                      "remaining_amount": orig_amount,
                      "splits": [],
                      "scope": "Personal",
                      "status": "INIT",
                      "merchant": orig_merchant,
                      "date": orig_date,
                      "user_name": orig_user,
                      "history": []
                  }
                  if self.storage:
                      self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="PENDIENTE_USUARIO")
                  
                  # Go back to Step 1 (Initial Alert)
                  keyboard = [
                     [
                         InlineKeyboardButton("✅ Registrar", callback_data="VALID|Yes"),
                         InlineKeyboardButton("❌ No Registrar", callback_data="VALID|No"),
                     ]
                  ]
                  
                  text = (
                     f"💰 *Nueva Transacción* (Reiniciada 🔄)\n"
                     f"👤 {escape_md(orig_user)}\n"
                     f"🛒 {escape_md(orig_merchant)}\n"
                     f"💵 ${orig_amount:,.2f}\n"
                     f"📅 {escape_md(orig_date)}\n\n"
                     f"¿Deseas registrarla?"
                  )
                  
                  await query.edit_message_text(
                      text=text,
                      reply_markup=InlineKeyboardMarkup(keyboard),
                      parse_mode='Markdown'
                  )

            else:
                  # Step 2: Multiple vs Single (VALID|Yes case)
                  if message_id not in self.flow_data:
                      self.flow_data[message_id] = {
                          "total_amount": 0.0,
                          "remaining_amount": 0.0,
                          "splits": [],
                          "scope": "Personal",
                          "status": "PROCESSING",
                          "merchant": "Desconocido",
                          "date": "?",
                          "user_name": "User"
                      }

                  self.flow_data[message_id]["status"] = "WAITING_MULTIPLE"
                  if self.storage:
                      self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="EN_PROCESO")
                  keyboard = [
                     [
                         InlineKeyboardButton("1️⃣ Una sola", callback_data="MULTIPLE|No"),
                         InlineKeyboardButton("🔢 Múltiples", callback_data="MULTIPLE|Yes"),
                     ],
                     [
                         InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK")
                     ]
                  ]
                  await query.edit_message_text(
                      text=self._get_flow_context_header(message_id) + "¿Es una transacción Única o Múltiple?",
                      reply_markup=InlineKeyboardMarkup(keyboard),
                      parse_mode='Markdown'
                  )

        elif step == "MULTIPLE":
            is_multiple = (value == "Yes")
            self.flow_data[message_id]["is_multiple"] = is_multiple
            
            if is_multiple:
                # SKIP Global Scope. Go straight to splitting.
                # Initialize logic for first split
                total = self.flow_data[message_id]["total_amount"]
                self.flow_data[message_id]["remaining_amount"] = total
                self.flow_data[message_id]["splits"] = [] # Clear splits if any
                
                self.flow_data[message_id]["status"] = "WAITING_AMOUNT"
                if self.storage:
                    self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="EN_PROCESO")
                
                keyboard = [
                    [
                        InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                        InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART")
                    ]
                ]
                await query.edit_message_text(
                    text=self._get_flow_context_header(message_id) + f"Total: ${total:,.2f}\n\n🔢 *RESPONDE* a este mensaje con el valor para el primer gasto.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            else:
                # Step 3: Scope (Global for Single)
                self.flow_data[message_id]["status"] = "WAITING_SCOPE"
                if self.storage:
                    self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="EN_PROCESO")
                keyboard = [
                    [
                        InlineKeyboardButton("🏠 Familiar", callback_data="SCOPE|Familiar"),
                        InlineKeyboardButton("👤 Personal", callback_data="SCOPE|Personal"),
                    ],
                    [
                        InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK")
                    ]
                ]
                await query.edit_message_text(
                    text=self._get_flow_context_header(message_id) + "¿Es un gasto 🏠 Familiar o 👤 Personal?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )

        elif step == "SCOPE":
            is_multiple = self.flow_data[message_id].get("is_multiple", False)
            
            if is_multiple:
                # Per-Split Scope
                self.flow_data[message_id]["current_split_scope"] = value
                selected_scope = value
                self.flow_data[message_id]["status"] = "WAITING_CATEGORY"
                if self.storage:
                    self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="EN_PROCESO")
                
                # Now ask for Category
                keyboard = self._get_category_keyboard(selected_scope, show_back=True)
                await query.edit_message_text(
                    text=self._get_flow_context_header(message_id) + f"Scope: {selected_scope}. Selecciona la categoría:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            else:
                # Global Scope (Single)
                self.flow_data[message_id]["scope"] = value
                selected_scope = value
                self.flow_data[message_id]["status"] = "WAITING_CATEGORY"
                if self.storage:
                    self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="EN_PROCESO")
                
                # Now ask for Category
                keyboard = self._get_category_keyboard(selected_scope, show_back=True)
                await query.edit_message_text(
                    text=self._get_flow_context_header(message_id) + "Selecciona la categoría:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                ) 
                
        elif step == "CAT":
            category = value
            # Store selected category
            self.flow_data[message_id]["pending_category"] = category
            
            is_multiple = self.flow_data[message_id].get("is_multiple", False)
            if is_multiple:
                 scope = self.flow_data[message_id].get("current_split_scope", "Personal")
            else:
                 scope = self.flow_data[message_id]["scope"]
            
            # Check for Subcategories
            categories_dict = CATEGORIES_CONFIG.get(scope, {})
            subcats = categories_dict.get(category, [])
            
            if subcats:
                # Ask for Subcategory
                self.flow_data[message_id]["status"] = "WAITING_SUBCAT"
                if self.storage:
                    self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="EN_PROCESO")
                keyboard = self._get_subcategory_keyboard(category, scope, show_back=True)
                await query.edit_message_text(
                    text=self._get_flow_context_header(message_id) + f"Categoría: {category}. Selecciona la subcategoría:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            else:
                # No subcategories, finish with main category
                await self._finalize_classification_step(update, context, message_id, category)

        elif step == "SUBCAT":
             subcategory = value
             parent_category = self.flow_data[message_id].get("pending_category", "")
             
             # Format: "Category - Subcategory"
             final_name = f"{parent_category} - {subcategory}"  if parent_category else subcategory
             
             # Check for [Bolsillo] Logic
             if subcategory.startswith("[Bolsillo]"):
                # Transition to ACTION step
                state = self.flow_data[message_id]
                state["current_rel_category"] = final_name 
                state["status"] = "WAITING_ACTION"
                self.flow_data[message_id] = state
                if self.storage:
                    self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="EN_PROCESO")
                
                keyboard = [
                    [
                        InlineKeyboardButton("🟢 Ahorrar/Ingresar", callback_data="ACTION|AHORRO"),
                        InlineKeyboardButton("🔴 Gastar/Pagar", callback_data="ACTION|GASTO"),
                    ],
                    [
                        InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK")
                    ]
                ]
                await query.edit_message_text(
                    text=self._get_flow_context_header(message_id) + f"📂 *{escape_md(subcategory)}*\n¿Es un Gasto o un Ingreso?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
             else:
                # Normal Category -> Default to "Gasto"
                self.flow_data[message_id]["current_tx_type"] = "Gasto"
                await self._finalize_classification_step(update, context, message_id, final_name)

        elif step == "ACTION":
            # User selected Action (Ahorro vs Gasto)
            action = value # AHORRO or GASTO
            
            # Update state
            state = self.flow_data[message_id]
            state["current_tx_type"] = "Gasto" if action == "GASTO" else "Ahorro"
            final_name = state.get("current_rel_category")
            
            self.flow_data[message_id] = state
            if self.storage:
                self.storage.update_flow_state(message_id, self.flow_data[message_id], estado="EN_PROCESO")
            
            # Finalize
            await self._finalize_classification_step(update, context, message_id, final_name)

        elif step == "CONFIRM":
            action = value
            if action == "SAVE":
                splits = self.flow_data[message_id]["splits"]
                if self.storage:
                    self.storage.mark_as_confirmed(message_id, splits)

                if message_id in self.pending_futures:
                     # Feedback to User while main.py handles save and final message
                     try:
                         await query.edit_message_text(text="⏳ Guardando...", reply_markup=None)
                     except:
                         pass
                     future = self.pending_futures[message_id]
                     if not future.done():
                         future.set_result(splits)
                         del self.pending_futures[message_id]
                else:
                    await self._save_orphan_splits(query, message_id, splits, self.flow_data.get(message_id, {}))

                # Cleanup
                if message_id in self.flow_data:
                    del self.flow_data[message_id]
            
            elif action == "CANCEL":
                  if self.storage:
                      self.storage.mark_as_discarded(message_id)
                  state = self.flow_data.get(message_id, {})
                  merchant = state.get('merchant', 'Desconocido')
                  amount = state.get("total_amount", 0.0)
                  date = state.get("date", "?")
                  user = state.get("user_name", "User")
                  
                  text = (
                      f"❌ *Operación Cancelada* ({escape_md(user)})\n"
                      f"🛒 {escape_md(merchant)}\n"
                      f"💵 ${amount:,.2f}\n"
                      f"📅 {escape_md(date)}"
                  ) if state else "❌ Operación cancelada."

                  if message_id in self.pending_futures:
                      future = self.pending_futures[message_id]
                      if not future.done():
                          future.set_result(None) # Cancel
                          del self.pending_futures[message_id]
                  if message_id in self.flow_data:
                     del self.flow_data[message_id]
                  await query.edit_message_text(text=text, parse_mode='Markdown')

        # --- 6. Recurring Flow Callbacks ---
        elif step == "REC":
            user_id = query.from_user.id
            if user_id not in self.recurring_sessions:
                await query.edit_message_text(text="⚠️ Sesión recurrente expirada.")
                return

            session = self.recurring_sessions[user_id]
            action = value
            
            if action == "YES":
                # Save current and move next
                await self._process_recurring_item_save(update, context, user_id)
            
            elif action == "EDIT":
                # Ask for new amount
                session["status"] = "RECURRING_WAITING_AMOUNT"
                self.recurring_sessions[user_id] = session
                
                idx = session["index"]
                item = session["queue"][idx]
                
                await query.edit_message_text(
                    text=f"✏️ Ingresa el nuevo valor para *{escape_md(item['name'])}*:",
                    parse_mode='Markdown'
                )
            
            elif action == "SKIP":
                # Just inc index and show next
                session["index"] += 1
                self.recurring_sessions[user_id] = session
                await self._show_next_recurring_item(update, context, user_id)
            
            elif action == "CANCEL":
                del self.recurring_sessions[user_id]
                await query.edit_message_text(text="❌ Proceso de fijos cancelado.")

    async def _trigger_confirmation(self, update, context, message_id, query):
        """Shows summary and asks for confirmation."""
        state = self.flow_data[message_id]
        state["status"] = "CONFIRMATION"
        self._save_history(message_id)
        if self.storage:
            self.storage.update_flow_state(message_id, state, estado="EN_PROCESO")

        splits = state["splits"]
        print(f"DEBUG: splits content -> {splits}")
        msg = "📝 *Resumen de la Transacción*\n\n"
        for cat, scope, amt, user, tx_type in splits:
            msg += f"• {escape_md(cat)} ({escape_md(scope)}) [{escape_md(tx_type)}]: ${amt:,.2f}\n"
        
        msg += "\n¿Es correcto?"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Guardar", callback_data="CONFIRM|SAVE"),
            ],
            [
                InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                InlineKeyboardButton("🔄 Reiniciar", callback_data="CONFIRM|RESTART"),
            ]
        ]
        await query.edit_message_text(
            text=self._get_flow_context_header(message_id) + msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def start_polling(self):
        """Starts the bot with robust retry logic for network stability."""
        retry_delay = 5
        max_delay = 60
        was_failing = False

        while True:
            try:
                # Rebuild application to ensure fresh state on retry
                self._build_application()

                # These methods can fail if network is down
                await self.application.initialize()
                await self.application.start()
                try:
                    await self.application.bot.delete_webhook(drop_pending_updates=False)
                except Exception as dwe:
                    logger.warning(f"Preemptive delete_webhook check: {dwe}")
                await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

                logger.info("✅ Bot started polling successfully.")

                # RECOVERY NOTIFICATION
                if was_failing and self.notifier:
                     try:
                         self.notifier("✅ Servicio Restaurado", "El bot de Telegram ha conectado exitosamente tras la caída.")
                     except Exception as e:
                         logger.error(f"Failed to send recovery email: {e}")

                break # Success, exit loop

            except (NetworkError, TimedOut) as e:
                logger.warning(f"⚠️ Connection failed during startup: {e}.")

                # OUTAGE NOTIFICATION (First time only)
                if not was_failing and self.notifier:
                    try:
                        self.notifier("⚠️ Servicio Caído (Telegram)", f"El bot no puede conectar con Telegram.\nError: {e}\n\nReintentando automáticamente...")
                    except Exception as ex:
                        logger.error(f"Failed to send outage email: {ex}")

                was_failing = True

                logger.warning(f"⏳ Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)

                # Exponential backoff
                retry_delay = min(retry_delay * 2, max_delay)

            except Exception as e:
                if "ConnectTimeout" in str(e) or "ConnectError" in str(e):
                     logger.warning(f"⚠️ Connection Timeout/Error: {e}.")
                     logger.warning(f"⏳ Retrying in {retry_delay} seconds...")
                     await asyncio.sleep(retry_delay)
                     retry_delay = min(retry_delay * 2, max_delay)
                else:
                    logger.error(f"🔥 Fatal error starting bot: {e}")
                    raise e

    async def stop(self):
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

    async def _finalize_classification_step(self, update, context, message_id, category_name):
        """Logic to split or finish classification."""
        # Use split-specific scope if multiple, else global
        state = self.flow_data[message_id]
        if state.get("is_multiple"):
             scope = state.get("current_split_scope", "Personal")
        else:
             scope = state.get("scope", "Personal")
             
        
        # Capture User Name
        user_name = "User"
        if update and getattr(update, "effective_user", None):
            fn = getattr(update.effective_user, "first_name", None)
            if isinstance(fn, str) and fn:
                user_name = fn
            else:
                uid = getattr(update.effective_user, "id", None)
                user_name = self._get_user_label(uid if isinstance(uid, int) else None)
        
        # Capture Type (default to Gasto if missing or None)
        tx_type = state.get("current_tx_type") or "Gasto"
        
        if state.get("is_multiple"):
            amount = state.get("current_split_amount", 0)
            
            # Add split with User and Type
            state["splits"].append((category_name, scope, amount, user_name, tx_type))
            
            # Recalculate remaining
            total = state["total_amount"]
            current_assigned = sum(s[2] for s in state["splits"])
            remaining = total - current_assigned
            state["remaining_amount"] = remaining
            
            query = update.callback_query
            
            if remaining > 1.0: # Tolerance
                    state["status"] = "WAITING_AMOUNT"
                    self.flow_data[message_id] = state
                    if self.storage:
                        self.storage.update_flow_state(message_id, state, estado="EN_PROCESO")
                    keyboard = [
                        [
                            InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                            InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART")
                        ]
                    ]
                    await query.edit_message_text(
                        text=self._get_flow_context_header(message_id) + f"✅ Asignado: ${amount:,.2f} a {escape_md(category_name)}\nRestante: ${remaining:,.2f}\n\n🔢 *RESPONDE* con el siguiente valor.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
            elif remaining < -1.0: 
                    # Remove last and retry
                    state["splits"].pop()
                    state["remaining_amount"] = total - sum(s[2] for s in state["splits"])
                    state["status"] = "WAITING_AMOUNT"
                    self.flow_data[message_id] = state
                    if self.storage:
                        self.storage.update_flow_state(message_id, state, estado="EN_PROCESO")
                    keyboard = [
                        [
                            InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                            InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART")
                        ]
                    ]
                    await query.edit_message_text(
                        text=self._get_flow_context_header(message_id) + f"⚠️ Error: Asignaste ${current_assigned:,.2f}, que supera el total.\nIntenta de nuevo el último monto.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
            else:
                # Done
                state["splits"][-1] = (category_name, scope, amount + remaining, user_name, tx_type)
                await self._trigger_confirmation(update, context, message_id, query)
        
        else:
            # Single
            total = state["total_amount"]
            state["splits"] = [(category_name, scope, total, user_name, tx_type)]
            await self._trigger_confirmation(update, context, message_id, update.callback_query)

    async def ask_user_for_category(self, transaction: Dict, user_name: str = "User", target_chat_id: int = None) -> Tuple[List[Tuple[str, str, float, str, str]], Optional[int]]:
        """
        Initiates the classification flow.
        Returns: Tuple(SplitsList, MessageID)
        """
        # Determine Chat ID
        chat_id_to_use = target_chat_id
        
        if not chat_id_to_use:
             # Fallback to self.chat_id (from /start) or env
             if self.chat_id:
                 chat_id_to_use = self.chat_id
             else:
                 env_chat_id = os.getenv("TELEGRAM_CHAT_ID_JUANMA")
                 if env_chat_id:
                     chat_id_to_use = int(env_chat_id)
                 else:
                     print("Warning: No Chat ID available.")
                     return [], None
        
        # Check merchant suggestion from storage
        suggestion = None
        if self.storage:
            try:
                suggestion = self.storage.get_merchant_suggestion(
                    merchant=transaction.get('merchant', ''),
                    usuario=user_name
                )
            except Exception as e:
                logger.warning(f"Error fetching merchant suggestion: {e}")

        is_quick = bool(suggestion and suggestion.get("is_high_confidence"))

        # Parse Amount from transaction
        try:
            total = float(transaction.get('amount', 0))
        except:
            total = 0.0

        if is_quick:
            cat_full = suggestion["category_full"]
            scope_sugg = suggestion["scope"]
            keyboard = [
                [
                    InlineKeyboardButton(f"⚡ Guardar: {cat_full}", callback_data="QUICK|SAVE"),
                ],
                [
                    InlineKeyboardButton("✏️ Cambiar / Dividir", callback_data="VALID|Yes"),
                    InlineKeyboardButton("❌ Descartar", callback_data="VALID|No"),
                ]
            ]
            text = (
                f"💰 *Nueva Transacción Detectada* ({escape_md(user_name)})\n"
                f"🛒 {escape_md(transaction.get('merchant'))}\n"
                f"💵 ${total:,.2f}\n"
                f"📅 {escape_md(transaction.get('date'))}\n\n"
                f"🎯 *Sugerencia:* {escape_md(cat_full)} ({escape_md(scope_sugg)})\n"
                f"¿Deseas registrarla?"
            )
        else:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Registrar", callback_data="VALID|Yes"),
                    InlineKeyboardButton("❌ No Registrar", callback_data="VALID|No"),
                ]
            ]
            text = (
                f"💰 *Nueva Transacción Detectada* ({escape_md(user_name)})\n"
                f"🛒 {escape_md(transaction.get('merchant'))}\n"
                f"💵 ${total:,.2f}\n"
                f"📅 {escape_md(transaction.get('date'))}\n\n"
                f"¿Deseas registrarla?"
            )

        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            message = await self._retry_request(
                self.application.bot.send_message,
                chat_id=chat_id_to_use, 
                text=text, 
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id_to_use}: {e}")
            return [], None

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        self.pending_futures[message.message_id] = future
        
        # Init shared state
        self.flow_data[message.message_id] = {
            "total_amount": total,
            "remaining_amount": total,
            "splits": [],
            "scope": suggestion["scope"] if is_quick else "Personal",
            "status": "INIT",
            # Store metadata for Restart context
            "merchant": transaction.get('merchant', 'Desconocido'),
            "date": transaction.get('date', '?'),
            "user_name": user_name,
            "history": [],
            "suggestion": suggestion
        }

        if self.storage:
            storage_id = transaction.get("storage_id") or transaction.get("db_id")
            if storage_id:
                self.storage.bind_telegram_message(storage_id, message.message_id, chat_id_to_use, self.flow_data[message.message_id])
            else:
                s_id = self.storage.insert_incoming_transaction(
                    origen=transaction.get("source", "notification"),
                    comercio=transaction.get("merchant", "Desconocido"),
                    monto=total,
                    fecha=transaction.get("date", "?"),
                    usuario=user_name,
                    raw_text=transaction.get("raw_text", "")
                )
                self.storage.bind_telegram_message(s_id, message.message_id, chat_id_to_use, self.flow_data[message.message_id])

        print(f"Waiting for input on message {message.message_id}...")
        try:
            result = await future
            return result, message.message_id
        except Exception as e:
            print(f"Error: {e}")
            return [], message.message_id

    def _save_history(self, message_id):
        state = self.flow_data.get(message_id)
        if not state:
            return
        if "history" not in state:
            state["history"] = []
        
        # Take a snapshot of the current state
        snapshot = {
            "total_amount": state.get("total_amount", 0.0),
            "remaining_amount": state.get("remaining_amount", 0.0),
            "splits": list(state.get("splits", [])),
            "scope": state.get("scope", "Personal"),
            "status": state.get("status", "INIT"),
            "merchant": state.get("merchant", "Desconocido"),
            "date": state.get("date", "?"),
            "user_name": state.get("user_name", "User"),
            "is_multiple": state.get("is_multiple", False),
            "pending_category": state.get("pending_category", ""),
            "current_split_amount": state.get("current_split_amount"),
            "current_split_scope": state.get("current_split_scope"),
            "current_rel_category": state.get("current_rel_category"),
            "current_tx_type": state.get("current_tx_type")
        }
        
        # To avoid duplicate history points of the same status/splits, check the last one
        if not state["history"] or state["history"][-1]["status"] != state["status"] or state["history"][-1]["splits"] != state["splits"]:
            state["history"].append(snapshot)

    def _get_flow_context_header(self, message_id):
        state = self.flow_data.get(message_id)
        if not state:
            return ""
        merchant = state.get("merchant", "Desconocido")
        amount = state.get("total_amount", 0.0)
        date = state.get("date", "?")
        user = state.get("user_name", "User")
        clean_merchant = str(merchant).strip("* ").replace("*", " ")
        return f"🛒 *{escape_md(clean_merchant)}* | 💵 ${amount:,.2f} | 📅 {escape_md(date)} ({escape_md(user)})\n\n"

    async def _render_state(self, update, context, message_id, query):
        state = self.flow_data[message_id]
        status = state.get("status")
        
        if status == "INIT":
            # Show initial question: "¿Deseas registrarla?"
            keyboard = [
                [
                    InlineKeyboardButton("✅ Registrar", callback_data="VALID|Yes"),
                    InlineKeyboardButton("❌ No Registrar", callback_data="VALID|No"),
                ]
            ]
            merchant = state.get('merchant', 'Desconocido')
            amount = state.get("total_amount", 0.0)
            date = state.get("date", "?")
            user = state.get("user_name", "User")
            
            text = (
                f"💰 *Nueva Transacción Detectada* ({escape_md(user)})\n"
                f"🛒 {escape_md(merchant)}\n"
                f"💵 ${amount:,.2f}\n"
                f"📅 {escape_md(date)}\n\n"
                f"¿Deseas registrarla?"
            )
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        elif status == "WAITING_MULTIPLE":
            keyboard = [
                [
                    InlineKeyboardButton("1️⃣ Una sola", callback_data="MULTIPLE|No"),
                    InlineKeyboardButton("🔢 Múltiples", callback_data="MULTIPLE|Yes"),
                ],
                [
                    InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK")
                ]
            ]
            await query.edit_message_text(
                text=self._get_flow_context_header(message_id) + "¿Es una transacción Única o Múltiple?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        elif status == "WAITING_SCOPE":
            keyboard = [
                [
                    InlineKeyboardButton("🏠 Familiar", callback_data="SCOPE|Familiar"),
                    InlineKeyboardButton("👤 Personal", callback_data="SCOPE|Personal"),
                ],
                [
                    InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                    InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART")
                ]
            ]
            await query.edit_message_text(
                text=self._get_flow_context_header(message_id) + "¿Es un gasto 🏠 Familiar o 👤 Personal?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        elif status == "WAITING_AMOUNT":
            keyboard = [
                [
                    InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                    InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART")
                ]
            ]
            total = state["total_amount"]
            remaining = state["remaining_amount"]
            await query.edit_message_text(
                text=self._get_flow_context_header(message_id) + f"Total: ${total:,.2f} | Restante: ${remaining:,.2f}\n\n🔢 *RESPONDE* a este mensaje con el valor para el próximo gasto.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        elif status == "WAITING_SPLIT_SCOPE":
            keyboard = [
                [
                    InlineKeyboardButton("🏠 Familiar", callback_data="SCOPE|Familiar"),
                    InlineKeyboardButton("👤 Personal", callback_data="SCOPE|Personal"),
                ],
                [
                    InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                    InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART")
                ]
            ]
            await query.edit_message_text(
                text=self._get_flow_context_header(message_id) + f"Gasto por ${state.get('current_split_amount', 0):,.2f}. ¿Es 🏠 Familiar o 👤 Personal?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        elif status == "WAITING_CATEGORY":
            scope = state.get("current_split_scope") if state.get("is_multiple") else state.get("scope", "Personal")
            keyboard = self._get_category_keyboard(scope, show_back=True)
            await query.edit_message_text(
                text=self._get_flow_context_header(message_id) + f"Scope: {scope}. Selecciona la categoría:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        elif status == "WAITING_SUBCAT":
            scope = state.get("current_split_scope") if state.get("is_multiple") else state.get("scope", "Personal")
            category = state.get("pending_category", "")
            keyboard = self._get_subcategory_keyboard(category, scope, show_back=True)
            await query.edit_message_text(
                text=self._get_flow_context_header(message_id) + f"Categoría: {category}. Selecciona la subcategoría:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        elif status == "WAITING_ACTION":
            subcategory = state.get("current_rel_category", "")
            keyboard = [
                [
                    InlineKeyboardButton("🟢 Ahorrar/Ingresar", callback_data="ACTION|AHORRO"),
                    InlineKeyboardButton("🔴 Gastar/Pagar", callback_data="ACTION|GASTO"),
                ],
                [
                    InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                    InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART")
                ]
            ]
            await query.edit_message_text(
                text=self._get_flow_context_header(message_id) + f"📂 *{escape_md(subcategory)}*\n¿Es un Gasto o un Ingreso?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        elif status == "CONFIRMATION":
            splits = state["splits"]
            msg = "📝 *Resumen de la Transacción*\n\n"
            for cat, scope, amt, user, tx_type in splits:
                msg += f"• {escape_md(cat)} ({escape_md(scope)}) [{escape_md(tx_type)}]: ${amt:,.2f}\n"
            
            msg += "\n¿Es correcto?"
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Guardar", callback_data="CONFIRM|SAVE"),
                ],
                [
                    InlineKeyboardButton("🔙 Atrás", callback_data="FLOW|BACK"),
                    InlineKeyboardButton("🔄 Reiniciar", callback_data="CONFIRM|RESTART"),
                ]
            ]
            await query.edit_message_text(
                text=self._get_flow_context_header(message_id) + msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

    def _get_user_label(self, user_id: Optional[int] = None) -> str:
        """Helper to resolve friendly user name from user_id or bot configuration."""
        juanma_id = os.getenv("TELEGRAM_CHAT_ID_JUANMA")
        leydi_id = os.getenv("TELEGRAM_CHAT_ID_LEY") or os.getenv("TELEGRAM_CHAT_ID_LEYDI")
        
        if user_id:
            if juanma_id and str(user_id) == str(juanma_id):
                return "Juanma"
            if leydi_id and str(user_id) == str(leydi_id):
                return "Leydi"
        if self.chat_id:
            if juanma_id and str(self.chat_id) == str(juanma_id):
                return "Juanma"
            if leydi_id and str(self.chat_id) == str(leydi_id):
                return "Leydi"
        return "User"

    def _parse_context_from_message_text(self, text: str) -> Dict[str, Any]:
        """
        Extracts merchant, amount, date, and user from Telegram message text as fallback.
        Handles both initial alerts and in-flow context headers.
        """
        import re
        result = {
            "merchant": "Desconocido",
            "amount": 0.0,
            "date": "?",
            "user": "User"
        }
        if not text:
            return result
        
        # 1. Merchant: after 🛒 (up to next emoji, pipe, or newline)
        m_match = re.search(r"🛒\s*\*?([^\n\|💵📅👤]+?)\*?(?:\s*\||\n|$)", text)
        if m_match:
            result["merchant"] = m_match.group(1).strip()
            
        # 2. Amount: after 💵 $...
        a_match = re.search(r"💵\s*\$?([\d\.,]+)", text)
        if a_match:
            raw_amt = a_match.group(1).replace(",", "")
            try:
                result["amount"] = float(raw_amt)
            except ValueError:
                pass
                
        # 3. Date: after 📅
        d_match = re.search(r"📅\s*([^\n\(\)]+)", text)
        if d_match:
            result["date"] = d_match.group(1).strip()
            
        # 4. User: 👤 Name or (Name)
        u_match = re.search(r"👤\s*([^\n\(\)]+)", text)
        if u_match:
            result["user"] = u_match.group(1).strip()
        else:
            p_match = re.search(r"\((Juanma|Leydi|User)\)", text, re.IGNORECASE)
            if p_match:
                result["user"] = p_match.group(1).capitalize()
                
        return result

    async def _handle_quick_save(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query, value: str):
        """Handles 1-Click Quick-Save using the merchant memory suggestion."""
        message_id = query.message.message_id

        if message_id not in self.flow_data:
            rec = self.storage.get_by_message_id(message_id) if self.storage else None
            if rec:
                estado = rec.get("estado")
                ext_id = rec.get("external_id")
                if estado in ("DILIGENCIADA", "DESCARTADA"):
                    await query.edit_message_text(text="✅ Esta transacción ya fue procesada anteriormente.")
                    return
                if ext_id:
                    ext_tx = self.storage.get_by_external_id(ext_id)
                    if ext_tx and ext_tx.get("estado") in ("DILIGENCIADA", "DESCARTADA"):
                        await query.edit_message_text(text="✅ Esta transacción ya fue procesada anteriormente.")
                        return

                flow_state = rec.get("flow_state") or {}
                self.flow_data[message_id] = {
                    "total_amount": flow_state.get("total_amount", rec["monto_total"]),
                    "remaining_amount": flow_state.get("remaining_amount", rec["monto_total"]),
                    "splits": flow_state.get("splits", []),
                    "scope": flow_state.get("scope", "Personal"),
                    "status": flow_state.get("status", "INIT"),
                    "merchant": rec["comercio"],
                    "date": rec["fecha_transaccion"],
                    "user_name": rec["usuario"],
                    "history": flow_state.get("history", []),
                    "storage_id": rec.get("id"),
                    "suggestion": flow_state.get("suggestion")
                }

        state = self.flow_data.get(message_id, {})
        merchant = state.get("merchant", "Desconocido")
        user_name = state.get("user_name") or self._get_user_label(query.from_user.id if query.from_user else None)
        total = state.get("total_amount", 0.0)

        suggestion = state.get("suggestion")
        if not suggestion and self.storage:
            suggestion = self.storage.get_merchant_suggestion(merchant, user_name)

        if not suggestion:
            try:
                await query.answer("No se encontró sugerencia para este comercio. Usa el flujo estándar.", show_alert=True)
            except:
                pass
            return

        cat_full = suggestion["category_full"]
        scope = suggestion["scope"]
        tx_type = suggestion.get("tx_type", "Gasto")
        pattern_to_record = suggestion.get("merchant_pattern") or merchant

        splits = [(cat_full, scope, total, user_name, tx_type)]
        state["splits"] = splits
        state["status"] = "CONFIRMED"

        if self.storage:
            self.storage.record_merchant_learning(
                merchant=pattern_to_record,
                category_full=cat_full,
                scope=scope,
                tx_type=tx_type,
                usuario=user_name
            )
            self.storage.mark_as_confirmed(message_id, splits, tx_id=state.get("storage_id"))

        if message_id in self.pending_futures:
            try:
                await query.edit_message_text(text="⏳ Guardando...", reply_markup=None)
            except:
                pass
            future = self.pending_futures[message_id]
            if not future.done():
                future.set_result(splits)
                del self.pending_futures[message_id]
            if message_id in self.flow_data:
                del self.flow_data[message_id]
        else:
            await self._save_orphan_splits(query, message_id, splits, state)

    async def _save_orphan_splits(self, query, message_id: int, splits: List[Tuple], state: Optional[Dict] = None):
        """Directly saves splits when bot was restarted or future is lost (orphan recovery or /pendientes)."""
        if not self.loader:
            return

        try:
            try:
                await query.edit_message_text(text="⏳ Guardando...", reply_markup=None)
            except:
                pass

            state = state or self.flow_data.get(message_id, {})
            rec = self.storage.get_by_message_id(message_id) if self.storage else None
            merchant = state.get("merchant") or (rec["comercio"] if rec else "Desconocido")
            date = state.get("date") or (rec["fecha_transaccion"] if rec else datetime.now().strftime("%Y-%m-%d"))
            user_name = state.get("user_name") or (rec["usuario"] if rec else self._get_user_label(query.from_user.id if query.from_user else None))
            orig_amount = state.get("total_amount") or (rec["monto_total"] if rec else (sum(s[2] for s in splits) if splits else 0.0))
            pattern_to_record = (state.get("suggestion") or {}).get("merchant_pattern") or merchant

            logger.info(f"Directly saving orphan/recovered transaction for message {message_id}: {splits}")
            for cat, scope, amt, user_who_paid, tx_type in splits:
                t_copy = {
                    'amount': amt,
                    'merchant': merchant,
                    'date': date
                }
                self.loader.append_transaction(t_copy, cat, scope=scope, user_who_paid=user_who_paid, transaction_type=tx_type or "Gasto")
                if self.storage:
                    self.storage.record_merchant_learning(
                        merchant=pattern_to_record,
                        category_full=cat,
                        scope=scope,
                        tx_type=tx_type or "Gasto",
                        usuario=user_who_paid
                    )
            storage_id = state.get("storage_id") or (rec["id"] if rec else None)
            if self.storage:
                self.storage.mark_as_synced(message_id, tx_id=storage_id)

            clean_m = re.sub(r'\s+', ' ', str(merchant).replace('*', ' ')).strip()
            msg_text = (
                f"✅ *Guardado Exitoso* en Google Sheets\n\n"
                f"👤 *Usuario:* {escape_md(user_name)}\n"
                f"🛒 *Comercio:* {escape_md(clean_m)}\n"
                f"💵 *Monto:* ${orig_amount:,.2f}\n"
                f"📅 *Fecha:* {escape_md(date)}\n\n"
                f"📁 *Clasificación:*\n"
            )
            for cat, scope, amt, user_who_paid, tx_type in splits:
                accumulated = 0.0
                if self.loader:
                    try:
                        res = self.loader.get_accumulated_total(cat, scope, tx_type or "Gasto", user=user_who_paid)
                        accumulated = float(res) if isinstance(res, (int, float)) else 0.0
                    except Exception:
                        accumulated = 0.0
                        pass
                msg_text += f"• *{escape_md(cat)}* ({escape_md(scope)}): ${amt:,.2f}\n"
                if accumulated > 0:
                    msg_text += f"   📊 Acumulado: ${accumulated:,.2f}\n"

            user_filter = user_name if user_name != "User" else None
            remaining_pending = self.storage.get_pending_transactions(usuario=user_filter) if self.storage else []
            next_keyboard = None
            if isinstance(remaining_pending, list) and len(remaining_pending) > 0:
                count = len(remaining_pending)
                next_tx = remaining_pending[0]
                if isinstance(next_tx, dict):
                    msg_text += f"\n📌 Te quedan *{count}* transacciones pendientes:"
                    clean_nm = str(next_tx.get("comercio", "Desconocido")).strip("* ").replace("*", " ")
                    short_m = (clean_nm[:14] + "…") if len(clean_nm) > 14 else clean_nm
                    m_val = float(next_tx.get("monto_total", 0.0))
                    buttons = [
                        [InlineKeyboardButton(f"📝 Categorizar: {short_m} (${m_val:,.0f})", callback_data=f"PEND|SELECT_{next_tx.get('id', 0)}")],
                    ]
                    if count > 1:
                        buttons.append([InlineKeyboardButton("📋 Ver todas las pendientes", callback_data="PEND|LIST")])
                    next_keyboard = InlineKeyboardMarkup(buttons)

            try:
                await query.edit_message_text(text=msg_text, reply_markup=next_keyboard, parse_mode='Markdown')
            except Exception as edit_err:
                logger.warning(f"Failed to edit orphan completion with Markdown ({edit_err}), retrying plain text...")
                clean_text = msg_text.replace('*', '')
                await query.edit_message_text(text=clean_text, reply_markup=next_keyboard)

        except Exception as e:
            logger.error(f"Failed direct save of recovered transaction {message_id}: {e}")
            if self.storage:
                self.storage.mark_as_error(message_id, str(e))
            try:
                await query.edit_message_text(text=f"⚠️ Error al guardar: {e}")
            except:
                pass
        finally:
            if message_id in self.flow_data:
                del self.flow_data[message_id]

    async def _render_single_pending(self, query, tx: Dict, message_id: int, user_name: str, show_back_to_list: bool = False):
        """Renders the initial categorization alert for a single pending transaction."""
        comercio = tx.get("comercio", "Desconocido")
        clean_merchant = str(comercio).strip("* ").replace("*", " ")
        monto = tx.get("monto_total", 0.0)
        fecha = tx.get("fecha_transaccion", "?")
        usuario = tx.get("usuario", user_name)

        suggestion = None
        if self.storage:
            try:
                suggestion = self.storage.get_merchant_suggestion(clean_merchant, usuario)
            except Exception as e:
                logger.warning(f"Error getting merchant suggestion in pending: {e}")

        is_quick = bool(suggestion and suggestion.get("is_high_confidence"))

        self.flow_data[message_id] = {
            "total_amount": monto,
            "remaining_amount": monto,
            "splits": [],
            "scope": suggestion["scope"] if is_quick else "Personal",
            "status": "INIT",
            "merchant": clean_merchant,
            "date": fecha,
            "user_name": usuario,
            "history": [],
            "storage_id": tx["id"],
            "suggestion": suggestion
        }

        if self.storage:
            chat_id = query.message.chat_id if query.message else self.chat_id
            self.storage.bind_telegram_message(
                tx["id"],
                message_id,
                chat_id,
                self.flow_data[message_id]
            )

        if is_quick:
            cat_full = suggestion["category_full"]
            scope_sugg = suggestion["scope"]
            keyboard = [
                [InlineKeyboardButton(f"⚡ Guardar: {cat_full}", callback_data="QUICK|SAVE")],
                [
                    InlineKeyboardButton("✏️ Cambiar / Dividir", callback_data="VALID|Yes"),
                    InlineKeyboardButton("❌ Descartar", callback_data="VALID|No"),
                ]
            ]
            if show_back_to_list:
                keyboard.append([InlineKeyboardButton("📋 Volver a la lista", callback_data="PEND|LIST")])

            text = (
                f"💰 *Transacción por Categorizar* ({escape_md(usuario)})\n"
                f"🛒 {escape_md(clean_merchant)}\n"
                f"💵 ${monto:,.2f}\n"
                f"📅 {escape_md(fecha)}\n\n"
                f"🎯 *Sugerencia:* {escape_md(cat_full)} ({escape_md(scope_sugg)})\n"
                f"¿Deseas registrarla?"
            )
        else:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Registrar", callback_data="VALID|Yes"),
                    InlineKeyboardButton("❌ Descartar", callback_data="VALID|No"),
                ]
            ]
            if show_back_to_list:
                keyboard.append([InlineKeyboardButton("📋 Volver a la lista", callback_data="PEND|LIST")])

            text = (
                f"💰 *Transacción por Categorizar* ({escape_md(usuario)})\n"
                f"🛒 {escape_md(clean_merchant)}\n"
                f"💵 ${monto:,.2f}\n"
                f"📅 {escape_md(fecha)}\n\n"
                f"¿Deseas registrarla?"
            )

        try:
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Markdown edit failed in _render_single_pending ({e}), retrying plain text...")
            clean_text = text.replace('*', '')
            await query.edit_message_text(
                text=clean_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def _handle_pending_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query, value: str):
        """Handles PEND step callbacks for resuming or selecting pending transactions."""
        message_id = query.message.message_id
        user_name = self._get_user_label(query.from_user.id if query.from_user else None)
        user_filter = user_name if user_name != "User" else None

        if value == "LIST":
            pending = self.storage.get_pending_transactions(usuario=user_filter) if self.storage else []
            if not pending:
                await query.edit_message_text("🎉 ¡No tienes transacciones pendientes por categorizar!")
                return
            
            if len(pending) == 1:
                tx = pending[0]
                await self._render_single_pending(query, tx, message_id, user_name, show_back_to_list=False)
                return

            msg = f"📋 *Transacciones Pendientes* ({len(pending)}):\n\n"
            keyboard = []
            for idx, tx in enumerate(pending[:8], start=1):
                comercio = tx.get("comercio", "Desconocido")
                clean_m = str(comercio).strip("* ").replace("*", " ")
                monto = tx.get("monto_total", 0.0)
                fecha = tx.get("fecha_transaccion", "?")
                msg += f"{idx}. 🛒 *{escape_md(clean_m)}* - ${monto:,.2f}\n"
                msg += f"   📅 {escape_md(fecha)}\n"

                short_comercio = (clean_m[:14] + "…") if len(clean_m) > 14 else clean_m
                btn_text = f"{idx}. {short_comercio} (${monto:,.0f})"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"PEND|SELECT_{tx['id']}")])

            msg += "\n👇 *Toca una para categorizarla ahora:*"
            if len(pending) > 8:
                msg += f"\n_...y {len(pending) - 8} más._"

            try:
                await query.edit_message_text(
                    text=msg,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"Markdown edit failed in PEND|LIST ({e}), retrying plain text...")
                clean_text = msg.replace('*', '')
                await query.edit_message_text(
                    text=clean_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return

        elif value.startswith("SELECT_"):
            tx_id_str = value.replace("SELECT_", "")
            try:
                tx_id = int(tx_id_str)
            except ValueError:
                await query.answer("ID de transacción inválido.")
                return

            tx = self.storage.get_by_id(tx_id) if self.storage else None
            if not tx or tx.get("estado") in ("DILIGENCIADA", "DESCARTADA"):
                await query.answer("Esta transacción ya fue procesada o descartada.")
                pending = self.storage.get_pending_transactions(usuario=user_filter) if self.storage else []
                if not pending:
                    await query.edit_message_text("🎉 ¡No tienes transacciones pendientes por categorizar!")
                else:
                    await self._handle_pending_callback(update, context, query, "LIST")
                return

            await self._render_single_pending(query, tx, message_id, user_name, show_back_to_list=True)

    async def show_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays pending transactions waiting for user categorization with inline actions."""
        if not self.storage:
            await update.message.reply_text("ℹ️ Almacenamiento no configurado.")
            return
            
        user_name = self._get_user_label(update.effective_user.id if update.effective_user else None)
        user_filter = user_name if user_name != "User" else None
        pending = self.storage.get_pending_transactions(usuario=user_filter)
            
        if not pending:
            await update.message.reply_text("🎉 ¡No tienes transacciones pendientes por categorizar!")
            return

        if len(pending) == 1:
            tx = pending[0]
            comercio = tx.get("comercio", "Desconocido")
            clean_merchant = str(comercio).strip("* ").replace("*", " ")
            monto = tx.get("monto_total", 0.0)
            fecha = tx.get("fecha_transaccion", "?")
            usuario = tx.get("usuario", user_name)

            keyboard = [
                [
                    InlineKeyboardButton("✅ Registrar", callback_data="VALID|Yes"),
                    InlineKeyboardButton("❌ Descartar", callback_data="VALID|No"),
                ]
            ]
            text = (
                f"📋 *Transacciones Pendientes* (1):\n\n"
                f"💰 *Transacción por Categorizar* ({escape_md(usuario)})\n"
                f"🛒 {escape_md(clean_merchant)}\n"
                f"💵 ${monto:,.2f}\n"
                f"📅 {escape_md(fecha)}\n\n"
                f"¿Deseas registrarla?"
            )
            try:
                sent_msg = await self._retry_request(
                    update.message.reply_text,
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"Markdown reply failed in show_pending ({e}), retrying plain text...")
                clean_text = text.replace('*', '')
                sent_msg = await self._retry_request(
                    update.message.reply_text,
                    clean_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            msg_id = getattr(sent_msg, 'message_id', None)
            if msg_id and isinstance(msg_id, int):
                self.flow_data[msg_id] = {
                    "total_amount": monto,
                    "remaining_amount": monto,
                    "splits": [],
                    "scope": "Personal",
                    "status": "INIT",
                    "merchant": clean_merchant,
                    "date": fecha,
                    "user_name": usuario,
                    "history": [],
                    "storage_id": tx["id"]
                }
                chat_id = update.effective_chat.id if update.effective_chat else self.chat_id
                self.storage.bind_telegram_message(
                    tx["id"],
                    msg_id,
                    chat_id,
                    self.flow_data[msg_id]
                )
            return

        # Multiple pending transactions
        msg = f"📋 *Transacciones Pendientes* ({len(pending)}):\n\n"
        keyboard = []
        for idx, tx in enumerate(pending[:8], start=1):
            comercio = tx.get("comercio", "Desconocido")
            clean_m = str(comercio).strip("* ").replace("*", " ")
            monto = tx.get("monto_total", 0.0)
            fecha = tx.get("fecha_transaccion", "?")
            msg += f"{idx}. 🛒 *{escape_md(clean_m)}* - ${monto:,.2f}\n"
            msg += f"   📅 {escape_md(fecha)}\n"

            short_comercio = (clean_m[:14] + "…") if len(clean_m) > 14 else clean_m
            btn_text = f"{idx}. {short_comercio} (${monto:,.0f})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"PEND|SELECT_{tx['id']}")])

        msg += "\n👇 *Toca una para categorizarla ahora:*"
        if len(pending) > 8:
            msg += f"\n_...y {len(pending) - 8} más._"

        try:
            await self._retry_request(
                update.message.reply_text,
                msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Markdown reply failed in show_pending multiple ({e}), retrying plain text...")
            clean_text = msg.replace('*', '')
            await self._retry_request(
                update.message.reply_text,
                clean_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def show_recent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays recent transactions and their synchronization status."""
        if not self.storage:
            await self._retry_request(update.message.reply_text, "ℹ️ Almacenamiento no configurado.")
            return
            
        user_name = self._get_user_label(update.effective_user.id if update.effective_user else None)
        user_filter = user_name if user_name != "User" else None
        recent = self.storage.get_recent_transactions(limit=5, usuario=user_filter)
            
        if not recent:
            await self._retry_request(update.message.reply_text, "ℹ️ No tienes transacciones registradas recientemente.")
            return
            
        status_icons = {
            "INGRESADA": "📥",
            "PENDIENTE_USUARIO": "⏳",
            "EN_PROCESO": "🔄",
            "CONFIRMADA": "📝",
            "DILIGENCIADA": "✅",
            "DESCARTADA": "❌",
            "ERROR_SHEETS": "⚠️"
        }
        
        msg = f"🕒 *Últimas Transacciones* ({escape_md(user_name)}):\n\n"
        for tx in recent:
            icon = status_icons.get(tx.get("estado"), "•")
            comercio = tx.get("comercio", "Desconocido")
            clean_m = re.sub(r'\s+', ' ', str(comercio).replace('*', ' ')).strip()
            monto = tx.get("monto_total", 0.0)
            fecha = tx.get("fecha_transaccion", "?")
            estado = tx.get("estado", "")
            msg += f"{icon} 🛒 *{escape_md(clean_m)}* - ${monto:,.2f}\n"
            msg += f"   📅 {escape_md(fecha)} | `{estado}`\n"
            
        try:
            await self._retry_request(update.message.reply_text, msg, parse_mode='Markdown')
        except Exception:
            clean_text = msg.replace('*', '').replace('`', '')
            await self._retry_request(update.message.reply_text, clean_text)

