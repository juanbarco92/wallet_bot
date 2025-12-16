import sys
import os
import logging
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion import GmailClient
from src.parser import TransactionParser

from dotenv import load_dotenv

# Simple logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def debug_real_email():
    load_dotenv()
    print("--- DEBUGGING WITH REAL EMAIL ---")
    
    sender_filter = os.getenv("AUTHORIZED_SENDER_EMAIL")
    if not sender_filter:
        print("⚠️ AUTHORIZED_SENDER_EMAIL not set in .env. Fetching ANY unread email (might be spam).")
    else:
        print(f"🔍 Filtering for emails from: {sender_filter}")

    # 1. Fetch Real Email
    try:
        client = GmailClient()
        print("✅ Gmail Client Initialized.")
        
        # Fetch ONLY the latest email matching the filter
        emails = client.fetch_unread_emails(sender=sender_filter, max_results=1)
        
        if not emails:
            print("⚠️ No unread emails found. Send a test email to yourself and try again.")
            return

        email_data = emails[0]
        print(f"\n📧 Latest Email ID: {email_data['id']}")
        
        # Prefer body, fallback to snippet
        text_to_parse = email_data.get('body') or email_data.get('snippet', '')
        print("\n--- RAW TEXT START ---")
        print(text_to_parse)
        print("--- RAW TEXT END ---")

        # 2. Parse It
        parser = TransactionParser()
        parsed = parser.parse(text_to_parse)
        
        print("\n--- PARSED RESULT ---")
        print(parsed)
        
        if parsed['amount'] == 0:
            print("❌ WARNING: Amount is 0.0 (Regex failed?)")
        if parsed['merchant'] == "UNKNOWN":
            print("❌ WARNING: Merchant is UNKNOWN (Regex failed?)")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    debug_real_email()
