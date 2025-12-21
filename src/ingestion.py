import os
import os.path
from typing import List, Dict, Optional, Tuple
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import base64
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

class TokenExpiredError(Exception):
    """Raised when the OAuth token is invalid/expired and cannot be refreshed automatically."""
    pass

class GmailClient:
    def __init__(self, credentials_path: str = 'credentials.json', token_path: str = 'token.json', interactive: bool = False):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.interactive = interactive
        self.creds = None
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Shows basic usage of the Gmail API.
        Lists the user's Gmail labels.
        """
        if os.path.exists(self.token_path):
            try:
                self.creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception as e:
                print(f"Error loading token.json: {e}")
                self.creds = None

        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            refreshed = False
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                    refreshed = True
                except Exception as e:
                    print(f"Error refreshing token: {e}. Needs re-authentication.")
            
            if not refreshed:
                if self.interactive:
                    if not os.path.exists(self.credentials_path):
                         raise FileNotFoundError(f"Credentials file not found at {self.credentials_path}. Please download it from Google Cloud Console.")
                    
                    print("Interactive mode: Launching browser for authentication...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path, SCOPES)
                    self.creds = flow.run_local_server(port=0)
                else:
                    # Non-interactive mode: Fail loudly so we can alert
                    raise TokenExpiredError("Token is expired or invalid, and interactive mode is off. Manual re-authentication required.")
            
            # Save the credentials for the next run (if we successfully got them)
            if self.creds and self.creds.valid:
                with open(self.token_path, 'w') as token:
                    token.write(self.creds.to_json())

        self.service = build('gmail', 'v1', credentials=self.creds)

    def fetch_unread_emails(self, sender: Optional[str] = None, max_results: int = 1, custom_query: str = None) -> List[Dict]:
        """Fetches unread emails. Defaults to just 1 (the latest)."""
        query = custom_query if custom_query else 'is:unread newer_than:1d'
        if sender:
            # Handle comma-separated senders robustly
            senders = [s.strip() for s in sender.split(',') if s.strip()]
            if len(senders) > 1:
                # from:(email1 OR email2)
                or_query = " OR ".join(senders)
                query += f' from:({or_query})'
            else:
                query += f' from:{senders[0]}'
        
        print(f"Fetching latest {max_results} emails with query: {query}")
        results = self.service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
        messages = results.get('messages', [])
        
        email_data = []

        if not messages:
            print('No new messages.')
            return []

        for message in messages:
            msg = self.service.users().messages().get(userId='me', id=message['id']).execute()
            
            # simplified parsing for now, focus on body and snippet
            payload = msg['payload']
            headers = payload.get("headers")
            snippet = msg.get("snippet")
            
            body = ""
            found_plain_text = False
            
            if 'parts' in payload:
                # First pass: Look for text/plain
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain':
                         data = part['body'].get('data')
                         if data:
                            body = base64.urlsafe_b64decode(data).decode()
                            found_plain_text = True
                            break # precise hit
                
                # Second pass: If no plain text, look for HTML (and maybe strip it later?)
                if not found_plain_text:
                    for part in payload['parts']:
                        if part['mimeType'] == 'text/html':
                             data = part['body'].get('data')
                             if data:
                                body = base64.urlsafe_b64decode(data).decode()
                                # TODO: Consider stripping HTML tags if regex fails often
                                break
                                
            elif 'body' in payload:
                 data = payload['body'].get('data')
                 if data:
                    body = base64.urlsafe_b64decode(data).decode()

            email_data.append({
                'id': message['id'],
                'snippet': snippet,
                'body': body,
                'payload': payload # Keep full payload for deeper inspection if needed
            })
            
        print(f"Fetched {len(email_data)} emails.")
        return email_data

    def mark_as_read(self, message_id: str):
        """Marks a message as read by removing the UNREAD label."""
        self.service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        print(f"Marked message {message_id} as read.")

def detect_original_source(email_data: Dict) -> Tuple[str, str, str]:
    """
    Analyzes the email to detect the original sender and the target user.
    Returns: (Original Sender, Target User, Target Chat ID Key)
    
    Target Chat ID Key is the env var name for the chat ID (e.g., 'TELEGRAM_CHAT_ID_LEY').
    """
    headers = email_data.get('payload', {}).get('headers', [])
    body = email_data.get('body', '')
    snippet = email_data.get('snippet', '')
    
    # helper to get header value
    def get_header(name):
        for h in headers:
            if h['name'].lower() == name.lower():
                return h['value']
        return ""

    from_header = get_header('From')
    
    # 1. Check if it comes from the Wife
    # We check if 'lejom_0721@hotmail.com' is in the sender
    if "lejom_0721@hotmail.com" in from_header.lower():
        # It's from her. Now determine the Bank.
        
        # Priority 1: Check Headers (X-Original-Sender, Reply-To) - simplified check
        # (Hotmail forwarding might not preserve these perfectly, but worth checking)
        
        # Priority 2: Body/Content Content
        # We look for keywords in the body or snippet
        text_to_search = (body + " " + snippet).lower()
        
        if "bancolombia" in text_to_search:
            return "Bancolombia", "Leydi", "TELEGRAM_CHAT_ID_LEY"
        elif "rappi" in text_to_search:
            return "RappiCard", "Leydi", "TELEGRAM_CHAT_ID_LEY"
        else:
            # Fallback: Treat as generic message from her
            return from_header, "Leydi", "TELEGRAM_CHAT_ID_LEY"

    # 2. Default: It's my own email
    return from_header, "Juanma", "TELEGRAM_CHAT_ID_JUANMA"


if __name__ == '__main__':
    # Test execution
    try:
        # manual run implies interactive
        client = GmailClient(interactive=True)
        emails = client.fetch_unread_emails()
        # Don't mark as read during test to avoid annoying the user
        # for email in emails:
        #    client.mark_as_read(email['id'])
    except Exception as e:
        print(f"Error: {e}")
