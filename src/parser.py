import re
from typing import Dict, Optional, Tuple
from datetime import datetime

class TransactionParser:
    def __init__(self):
        # Regex patterns
        # 1. Amount: "$ 17.600,00" or "$17.600,00"
        # 1. Amount: "$ 17.600,00", "$17.600,00", "COP17.900,00"
        self.amount_pattern = r"(?:\$|COP)\s?([\d\.]+,\d{2})"
        
        # 2. Merchant Patterns
        # Format A: "en MERCHANT con" (Purchases)
        # Format B: "a MERCHANT el" (Transfers)
        self.merchant_patterns = [
            r"\ben\s+(.*?)\s+(?:con|si tienes dudas)",
            r"\ba\s+(.*?)\s+el\s+\d{2}/\d{2}"
        ]
        
        # 3. Date Patterns
        # Format A: "11/12/2025 a las 15:51"
        # Format B: "12/12/2025 10:00"
        self.date_pattern = r"(\d{2}/\d{2}/\d{4})(?:\s+a\s+las\s+|\s+)(\d{2}:\d{2})"

    def parse(self, text: str) -> Dict:
        """Parses the email body/snippet to extract transaction details."""
        
        # 1. Extract Amount
        amount_match = re.search(self.amount_pattern, text)
        amount = 0.0
        if amount_match:
            # Convert "17.600,00" -> 17600.00
            clean_amount = amount_match.group(1).replace('.', '').replace(',', '.')
            try:
                amount = float(clean_amount)
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
            date_part = date_match.group(1)
            time_part = date_match.group(2)
            date_str = f"{date_part} {time_part}"
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
