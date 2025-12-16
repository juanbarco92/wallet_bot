# AutoTrx: Personal Finance ETL

A "Human-in-the-Loop" ETL pipeline that reads bank notification emails, parses them, automatically categorizes clear transactions, and asks the user via a Telegram Bot to manually categorize ambiguous ones. Finally, it loads the clean data into Google Sheets.

## Architecture

1.  **Ingestion**: Connects to Gmail API to fetch unread bank notifications.
2.  **Transformation**: Parses email content using Regex and heuristics.
3.  **Human-in-the-Loop**: Uses a Telegram Bot to ask the user for categorization of ambiguous transactions.
4.  **Load**: Appends processed data to a Google Sheet.

## Setup

1.  **Prerequisites**:
    -   Python 3.10+
    -   Poetry
    -   A Google Cloud Project with Gmail API and Google Sheets API enabled.
    -   A Telegram Bot Token (from @BotFather).

2.  **Installation**:
    ```bash
    poetry install
    ```

3.  **Configuration**:
    -   Copy `.env.example` to `.env` and fill in your values.
    -   Place your Google Cloud `credentials.json` in the project root.

4.  **Usage**:
    ```bash
    poetry run python main.py
    ```

## Project Structure

-   `src/`: Source code modules.
-   `main.py`: Entry point.
