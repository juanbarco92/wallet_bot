import os
import os.path
from typing import List, Dict, Optional
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

class GmailClient:
    def __init__(self, credentials_path: str = 'credentials.json', token_path: str = 'token.json'):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.creds = None
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Shows basic usage of the Gmail API.
        Lists the user's Gmail labels.
        """
        if os.path.exists(self.token_path):
            self.creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                     raise FileNotFoundError(f"Credentials file not found at {self.credentials_path}. Please download it from Google Cloud Console.")
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(self.token_path, 'w') as token:
                token.write(self.creds.to_json())

        self.service = build('gmail', 'v1', credentials=self.creds)

    def fetch_unread_emails(self, sender: Optional[str] = None, max_results: int = 1) -> List[Dict]:
        """Fetches unread emails. Defaults to just 1 (the latest)."""
        query = 'is:unread'
        if sender:
            query += f' from:{sender}'
        
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

if __name__ == '__main__':
    # Test execution
    try:
        client = GmailClient()
        emails = client.fetch_unread_emails()
        # Don't mark as read during test to avoid annoying the user
        # for email in emails:
        #    client.mark_as_read(email['id'])
    except Exception as e:
        print(f"Error: {e}")
