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
   - In-place edits (`edit_message_text`) do not trigger push notifications/sounds on mobile devices.
   - For robust push notifications and Tasker/automation parsing, the bot sends an explicit new `"guardado"` message on successful write.
3. **MIME & Forwarding Email Robustness (`src/parser.py`):**
   - Email forwarding (e.g. from Outlook/Hotmail to Gmail) often inserts carriage returns (`\r\n`). All regex patterns (amounts, merchant, and dates) are case-insensitive and support whitespace matching (`\s+`, `\r?\n`) to handle these characters properly.
   - Date regex supports matching and normalizing `YYYY/MM/DD` date formats inside transfers.
   - Supports Glim transaction emails (sender `no-responder@getglim.com`) using a specific pattern to match the merchant before general fallback rules are processed: `r"tarjeta de beneficios Glim.*?en\s+(.*?)(?:\.|$)"`.
  - **Tasker Webhook Configuration:** To ensure both transaction amount and merchant are parsed correctly, the Tasker webhook HTTP POST body must concatenate `%evtprm2` (Title, containing the amount) and `%evtprm3` (Text, containing the merchant) like: `{"texto": "%evtprm2 %evtprm3"}`.
4. **Google Cloud Logging Integration (`main.py`):**
   - Integrates with `google-cloud-logging` to stream logs directly to GCP Cloud Logging. This consumes 0 bytes of the VM's local 30GB persistent disk.
   - In case of warning scenarios (e.g. `merchant == 'UNKNOWN'` or `amount == 0.0`), the system logs a `logger.warning` containing the Gmail message ID, sender, subject, and the entire MIME-decoded body, making troubleshooting via Log Explorer simple.
