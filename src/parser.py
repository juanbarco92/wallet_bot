import re
from typing import Dict, Optional, Tuple
from datetime import datetime
import os
import json
import google.generativeai as genai
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

class TransactionParser:
    def __init__(self, api_key: Optional[str] = None):
        # Configure Gemini
        key = api_key or os.getenv("GEMINI_API_KEY")
        if key:
            genai.configure(api_key=key)
            self.model = genai.GenerativeModel("gemini-flash-latest")
        else:
            self.model = None

        # Regex patterns
        # 1. Amount: "$ 17.600,00" or "$17.600,00"
        # 1. Amount: "$ 17.600,00", "$17.600,00", "COP17.900,00"
        # 1. Amount: "$ 17.600,00", "COP17.900,00", "$1,623,500", "$ 5000"
        # Flexible match for numbers with dots/commas
        self.amount_pattern = r"(?:\$|COP)\s?([\d\.,]+)"
        
        # 2. Merchant Patterns
        # Format A: "en MERCHANT con" (Purchases)
        # Format B: "a MERCHANT el" (Transfers)
        self.merchant_patterns = [
            r"Comercio\n\s*(.*?)\n", # RappiCard
            r"\ben\s+(.*?)\s+(?:con|si tienes dudas)",
            r"\ba\s+(.*?)\s+el\s+\d{2}/\d{2}",
            r"a la llave\s+(@?[\w\d]+)", # Covers QR and Transfers to Key
            r"Retiraste\s+[\d\.,\s\$]+en\s+(.*?)\s+de tu", # Withdrawals
            r"\ben\s+(.*?)(?:,|\s+el)\s+\d{2}/\d{2}", # Generic 'en X, el'
        ]
        
        # 3. Date Patterns
        # Format A: "11/12/2025 a las 15:51"
        # Format B: "12/12/2025 10:00"
        # Format C: "2025-12-17 15:22:22" (Rappi)
        self.date_pattern = r"(?:(\d{2}/\d{2}/\d{4})(?:\s+a\s+las\s+|\s+)(\d{2}:\d{2}))|(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"

    def parse(self, text: str) -> Dict:
        """Parses the email body/snippet to extract transaction details."""
        # 0. Clean HTML if present
        if text and ("<html" in text.lower() or "<div" in text.lower() or "body {" in text.lower()):
            try:
                soup = BeautifulSoup(text, "html.parser")
                text = soup.get_text(separator="\n")
            except Exception as e:
                print(f"HTML cleaning failed: {e}")

        # 1. Try Regex First (Fast & Free)
        regex_result = self._parse_regex(text)
        
        # Validation: If regex got a valid amount and merchant, return it
        if regex_result['amount'] > 0 and regex_result['merchant'] != "UNKNOWN":
            return regex_result
            
        if self.model:
            print("Regex failed to fully parse. Attempting fallback to Gemini...")
            try:
                llm_result = self._parse_with_llm(text)
                if llm_result:
                    print(f"LLM Success: {llm_result}")
                    # Merge: use LLM values but keep original text
                    llm_result['original_text'] = text
                    return llm_result
            except Exception as e:
                print(f"LLM Fallback failed with exception: {e}")
        
        return regex_result

    def _parse_regex(self, text: str) -> Dict:
        """Original Regex Logic"""
        
        # 1. Extract Amount
        amount_match = re.search(self.amount_pattern, text)
        amount = 0.0
        if amount_match:
            # Normalize amount string
            raw = amount_match.group(1).strip()
            # Remove currency symbols or stray chars if any remain (regex handles most)
            raw = re.sub(r'[^\d,\.]', '', raw)

            # Heuristic: Detect separator
            # Case 1: Both . and , exist (e.g. "18,400.00" or "1.200,50")
            if '.' in raw and ',' in raw:
                last_dot = raw.rfind('.')
                last_comma = raw.rfind(',')
                if last_dot > last_comma:
                    # US Format: 18,400.00 -> Remove commas
                    clean = raw.replace(',', '')
                else:
                    # EU/Col Format: 1.200,50 -> Remove dots, swap comma
                    clean = raw.replace('.', '').replace(',', '.')
            
            # Case 2: Only one separator exists (e.g. "17.900" or "17,900" or "5000")
            elif '.' in raw:
                # Ambiguous: 17.900 (17k) vs 17.90 (17.9). 
                # Bancolombia usually sends 2 decimals for cents if it is a decimal.
                # If 3 digits follow, it's likely thousands. 
                # If 2 digits, it works as decimal or thousands (usually decimal in US, thousands in Col).
                # Assumption: If string ends with .XX, treat as decimal? 
                # Actually, "17.900" is almost always 17k in this context. 
                # But "18.400.00" (handled above).
                # Let's clean . if it looks like thousands
                if len(raw.split('.')[-1]) == 3:
                     clean = raw.replace('.', '')
                else:
                     clean = raw # preserve decimal? Risk.
                     # 17.900 -> 17900. 17.00 -> 17.00
            elif ',' in raw:
                # "17,900" -> 17900 or 17.9?
                if len(raw.split(',')[-1]) == 3:
                    clean = raw.replace(',', '')
                else:
                    clean = raw.replace(',', '.')
            else:
                clean = raw

            try:
                amount = float(clean)
            except:
                pass

        # 2. Extract Merchant (Try patterns)
        merchant = "UNKNOWN"
        for pattern in self.merchant_patterns:
            match = re.search(pattern, text)
            if match:
                merchant = match.group(1).strip().upper()
                break # Stop after first match

        # 3. Extract Date
        date_match = re.search(self.date_pattern, text)
        date_str = ""
        if date_match:

            if date_match.group(1):
                # Format A (DD/MM/YYYY HH:MM)
                date_part = date_match.group(1)
                time_part = date_match.group(2)
                date_str = f"{date_part} {time_part}"
            elif date_match.group(3):
                # Format C (YYYY-MM-DD HH:MM:SS) - Rappi
                # normalize to DD/MM/YYYY HH:MM
                dt_obj = datetime.strptime(date_match.group(3), "%Y-%m-%d %H:%M:%S")
                date_str = dt_obj.strftime("%d/%m/%Y %H:%M")
        else:
            # Fallback to now if not found
            date_str = datetime.now().strftime("%d/%m/%Y %H:%M")

        return {
            "date": date_str,
            "amount": amount,
            "merchant": merchant,
            "description": merchant,
            "original_text": text
        }

    def _parse_with_llm(self, text: str) -> Optional[Dict]:
        """Uses Gemini to extract structured data."""
        prompt = f"""
        Extract transaction details from this email text into JSON format.
        Fields: 
        - amount (number, no strings)
        - merchant (string, NAME ONLY, no "Compra en")
        - date (string, format DD/MM/YYYY HH:MM)
        
        Text: '{text}'
        
        Return ONLY valid JSON.
        """
        try:
            # print("Calling Gemini generate_content...")
            response = self.model.generate_content(prompt)
            
            # Clean response (remove markdown ```json ... ```)
            raw_json = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw_json)
            
            return {
                "date": data.get("date", datetime.now().strftime("%d/%m/%Y %H:%M")),
                "amount": float(data.get("amount", 0.0)),
                "merchant": str(data.get("merchant", "UNKNOWN")).upper(),
                "description": str(data.get("merchant", "UNKNOWN")).upper(),
            }
        except Exception as e:
            print(f"Error inside _parse_with_llm: {e}")
            return None

class Classifier:
    def __init__(self):
        # Allow-list: Map keywords to categories
        self.categories: Dict[str, str] = {
            "JUMBO": "🛒 Mercado",
            "EXITO": "🛒 Mercado",
            "CARULLA": "🛒 Mercado",
            "D1": "🛒 Mercado",
            "ARA": "🛒 Mercado",
            "OXXO": "🍔 Comida",
            "UBER": "🚗 Transporte",
            "DIDIFOOD": "🍔 Comida",
            "RAPPI": "🍔 Comida",
            "CREPES": "🍔 Comida",
            "CORRAL": "🍔 Comida",
            "NETFLIX": "🎬 Entretenimiento",
            "SPOTIFY": "🎬 Entretenimiento",
            "CITY PARKING": "🚗 Parqueadero",
            "PARQUEADERO": "🚗 Parqueadero",
        }
        
        self.ambiguous_keywords = ["NEQUI", "TRANSFERENCIA", "TRANSF", "CAJERO"]

    def classify(self, transaction: Dict) -> Tuple[str, bool]:
        """
        Classifies a transaction.
        Returns (Category, Is_Ambiguous)
        """
        merchant = transaction.get("merchant", "").upper()
        
        # 1. Check for explicit ambiguity
        for kw in self.ambiguous_keywords:
            if kw in merchant:
                return "NEEDS_REVIEW", True
        
        # 2. Check allow-list
        for key, category in self.categories.items():
            if key in merchant:
                return category, False
        
        # 3. Default to manual review if unknown
        return "NEEDS_REVIEW", True

if __name__ == "__main__":
    # Test
    parser = TransactionParser()
    classifier = Classifier()
    
    test_text = "Bancolombia: Compraste $17.600,00 en CITY PARKING con tu T.Deb *4256, el 11/12/2025 a las 15:51."
    parsed = parser.parse(test_text)
    print(f"Parsed: {parsed}")
    
    cat, ambiguous = classifier.classify(parsed)
    print(f"Category: {cat}, Ambiguous: {ambiguous}")
