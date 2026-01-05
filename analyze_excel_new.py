
import pandas as pd
import sys

# clean output
sys.stdout.reconfigure(encoding='utf-8')

file_path = r"c:\Users\Administrador\Documents\Proyectos\autotrx\resources\wallet_records (3).xlsx"

try:
    df = pd.read_excel(file_path)
    
    print("--- UNIQUE ACCOUNTS ---")
    print(df['account'].unique())
    
    print("\n--- UNIQUE CATEGORIES ---")
    print(df['category'].unique())

    print("\n--- SAMPLE ROWS (First 5) ---")
    print(df[['date', 'amount', 'type', 'account', 'category', 'note']].head().to_string())

except Exception as e:
    print(f"Error: {e}")
