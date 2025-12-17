import sys
import os
sys.path.append(os.getcwd())
from src.loader import SheetsLoader
import sys

# Mock for verification
class MockSheet:
    def append_row(self, row):
        print(f"MOCK APPEND: {row}")

class MockClient:
    def __init__(self):
        self.sheet1 = MockSheet()
    def open_by_key(self, key):
        return self

def test_schema():
    print("Testing Loader Schema...")
    loader = SheetsLoader()
    # Inject mock client/sheet
    loader.client = MockClient()
    loader.sheet = loader.client.sheet1
    
    # Test Case 1: Category with Subcategory
    transaction = {
        "date": "16/12/2025",
        "merchant": "Uber Trip",
        "amount": 15000.0
    }
    category_full = "🚗 Transporte - Taxis"
    scope = "Personal"
    user = "UserJuan"
    
    print("\n--- Test 1: Category with Subcategory (Gasto Default) ---")
    loader.append_transaction(transaction, category_full, scope, user)
    
    # Test Case 2: Category WITHOUT Subcategory
    transaction2 = {
        "date": "17/12/2025",
        "merchant": "Netflix",
        "amount": 35000.0
    }
    category_simple = "🏠 Casa" 
    
    print("\n--- Test 2: Simple Category (Gasto Default) ---")
    loader.append_transaction(transaction2, category_simple, "Familiar", "UserMaria")

    # Test Case 3: Bolsillo (Ahorro)
    transaction3 = {
        "date": "18/12/2025",
        "merchant": "Transferencia Ahorro",
        "amount": 500000.0
    }
    category_bolsillo = "💰 Ahorro - [Bolsillo] Viaje"
    
    print("\n--- Test 3: Bolsillo (Ahorro) ---")
    loader.append_transaction(transaction3, category_bolsillo, "Personal", "UserJuan", transaction_type="Ahorro")

if __name__ == "__main__":
    test_schema()
