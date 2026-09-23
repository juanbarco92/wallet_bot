# AutoTrx Project Context

## Project Architecture
- **Environment:** Runs in a Google Cloud Platform (GCP) Compute Engine instance.
- **Repository:** The code in the repository matches the running code on GCP exactly.
- **Core Functionality:** Processes bank transaction notifications from Gmail (including RappiCard and Glim) and manual inputs from Telegram, prompting the user for categorization, and then logs them into a Google Sheet.

## Key Behaviors & Known Quirks
1. **Google Sheets Persistence (`src/loader.py`):**
   - The spreadsheet worksheet name is `"Base_Transacciones"`.
   - **Filter + Grid Limits Bug:** When a basic filter is active and the sheet reaches its grid limits (e.g. 1000 rows), calling `append_row` can result in Google's API silently discarding the row (returning success HTTP 200, but writing nothing to the sheet, resulting in lost data).
   - **Programmatic Fix:** The code uses `sheet.col_values(1)` to count the actual rows, checks the grid boundary `sheet.row_count`, explicitly calls `sheet.add_rows(100)` to expand the sheet if the limit is exceeded (bypassing Google's auto-expansion under active filters), and uses `sheet.update(range_name=...)` to write to the exact target cells.
   - If the worksheet `"Base_Transacciones"` is not found, the loader automatically creates a new tab with that name instead of failing.
2. **Telegram Notifications & Feedback:**
   - When a transaction is confirmed and saved, `edit_message_text` overwrites the interactive prompt with a comprehensive confirmation containing the full original transaction details (User, Merchant, Amount, Date) along with the assigned Category, Scope, and accumulated total.
   - The standalone redundant push message `"guardado"` was removed at the user's request.
3. **MIME & Forwarding Email Robustness (`src/parser.py`):**
   - Email forwarding (e.g. from Outlook/Hotmail to Gmail) often inserts carriage returns (`\r\n`). All regex patterns (amounts, merchant, and dates) are case-insensitive and support whitespace matching (`\s+`, `\r?\n`) to handle these characters properly.
   - Date regex supports matching and normalizing `YYYY/MM/DD` date formats inside transfers.
   - Supports Glim transaction emails (sender `no-responder@getglim.com`) using a specific pattern to match the merchant before general fallback rules are processed: `r"tarjeta de beneficios Glim.*?en\s+(.*?)(?:\.|$)"`.
  - **Tasker Webhook Configuration:** To ensure both transaction amount and merchant are parsed correctly, the Tasker webhook HTTP POST body must concatenate `%evtprm2` (Title, containing the amount) and `%evtprm3` (Text, containing the merchant) like: `{"texto": "%evtprm2 %evtprm3"}`.
4. **Google Cloud Logging Integration (`main.py`):**
   - Integrates with `google-cloud-logging` to stream logs directly to GCP Cloud Logging. This consumes 0 bytes of the VM's local 30GB persistent disk.
   - In case of warning scenarios (e.g. `merchant == 'UNKNOWN'` or `amount == 0.0`), the system logs a `logger.warning` containing the Gmail message ID, sender, subject, and the entire MIME-decoded body, making troubleshooting via Log Explorer simple.
5. **Local SQLite Persistence Buffer (`src/storage.py`):**
   - AutoTrx uses a lightweight local SQLite database (`autotrx.db`) running in WAL mode to persist and buffer all incoming transactions (emails and webhooks) upon arrival.
   - Fixes the bug where transactions turned into $0.00 / Desconocido if left unanswered or if the bot restarted. State is restored directly from SQLite on user interaction.
   - Provides commands `/pendientes` (or `/p`) and `/ultimas` (or `/u`) to audit unclassified and recently synced/discarded transactions.
6. **Merchant Parsing & Telegram Markdown Asterisk Robustness (`src/parser.py`, `src/bot.py`, `main.py`):**
   - **Domains & Subscriptions:** Parser regex supports online subscriptions ending in `, el` (e.g. `en DLO*Netflix.com, el...`) and names with dots (`.com`, `S.A.S.`).
   - **Wrapping Asterisks:** Cleans prefix/suffix asterisks from extracted merchant names (`.strip("* \t\r\n")`).
   - **No More "Guardando..." Freezing:** When saving orphan/recovered transactions or manual transactions, the UI reliably transitions from `⏳ Guardando...` to `💾 Guardado Exitoso`. All `edit_message_text` calls feature plain-text fallback if Markdown V1 entities fail, and send the `"guardado"` push notification for Tasker.
7. **Smart Quick-Save en 1 Clic (`merchant_memory` en `src/storage.py` y `src/bot.py`):**
   - **Tabla `merchant_memory`:** Almacena frecuencias históricas particionadas por `(merchant_pattern, category_full, scope, tx_type, usuario)`.
   - **Normalización de Comercios:** Limpia prefijos agregadores (`BOLD*`, `DLO*`, `CAC*`, `PAYU*`, etc.) y extrae destinatarios de transferencias Bancolombia (`LA LLAVE ... A <DESTINATARIO>`).
   - **Umbral de Confianza:** Si $\text{confianza} \ge 80\%$ y ocurrencias $\ge 2$, presenta botón interactivo `[⚡ Guardar: <Categoría>]` para registrar en 1 solo toque.
   - **Protección contra Ambigüedades:** Si el comercio tiene registros divididos o dispersos (ej. Farmatodo, Falabella), el bot no asume a ciegas y ofrece `[✏️ Cambiar / Dividir]`.
   - **Aprendizaje Continuo:** Cada confirmación (vía 1 clic, flujo manual o `/pendientes`) actualiza y refuerza la memoria atómicamente en SQLite (`record_merchant_learning`).
   - **Siembra:** Script `scripts/seed_merchant_memory.py` permite sembrar o resincronizar las reglas directamente desde `Base_Transacciones` en Google Sheets.

