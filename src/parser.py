import re
from typing import Dict, Optional, Tuple
from datetime import datetime

class TransactionParser:
    def __init__(self):
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
            r"\ben\s+(.*?)\s+(?:con|si tienes dudas)",
            r"\ba\s+(.*?)\s+el\s+\d{2}/\d{2}",
            r"a la cuenta\s+(\*?\d+)",
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
            # Clean string: "1.623.500,00" -> 1623500.00
            # Strategy: Remove non-numeric chars except the LAST separator if meaningful
            raw_amount = amount_match.group(1).strip()
            
            # Remove symbols if captured inadvertently
            raw_amount = re.sub(r'[^\d,\.]', '', raw_amount)
            
            # Determine separator (comma or dot)
            # If both exist, the one that appears last is likely decimal
            # If only one exists:
            #   - if it appears multiple times (1.000.000), it's thousands -> remove
            #   - if appears once, check context (3 digits after?). Ambiguous. 
            #   Col/EU standard: dot=thousands, comma=decimals (1.234,56)
            #   US standard: comma=thousands, dot=decimals (1,234.56)
            
            # Simple heuristic for this user's context (Bancolombia)
            # Usually uses 1.234,56 or 1,234 for pure ints?
            # User example: 1,623,500 (no decimal?) or 1.623.500? User wrote "1,623,500"
            pass_1 = raw_amount.replace('.', '').replace(',', '.') # Assume dot=thousand, comma=decimal
            try:
                amount = float(pass_1)
            except:
                # Retry assuming comma=thousand, dot=decimal
                pass_2 = raw_amount.replace(',', '')
                try:
                    amount = float(pass_2)
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
