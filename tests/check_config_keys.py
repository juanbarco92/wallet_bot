import sys
import os
sys.path.append(os.getcwd())
from src.config import CATEGORIES_CONFIG

def check():
    scope = "Personal"
    cat = "💰 Ahorro/Inversion"
    
    print(f"Checking Scope: {scope}")
    categories = CATEGORIES_CONFIG.get(scope, {})
    if not categories:
        print("❌ Scope not found!")
        return

    print(f"Keys available: {list(categories.keys())}")
    
    if cat in categories:
        print(f"✅ Found '{cat}'")
        subcats = categories[cat]
        print(f"   Subcategories: {subcats}")
    else:
        print(f"❌ '{cat}' NOT found in {scope}")
        for k in categories.keys():
            print(f"   '{k}' vs '{cat}' -> EQ? {k==cat}")

if __name__ == "__main__":
    check()
