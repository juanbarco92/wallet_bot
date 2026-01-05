
import pandas as pd
import sys

# clean output
sys.stdout.reconfigure(encoding='utf-8')

file_path = r"c:\Users\Administrador\Documents\Proyectos\autotrx\resources\wallet_records.xlsx"

try:
    df = pd.read_excel(file_path)
    print("---COLS---")
    for c in df.columns:
        print(c)
    print("---END COLS---")
    
    print("---SAMPLE---")
    # Print first row as dict
    print(df.iloc[0].to_dict())
    print("---END SAMPLE---")

    if 'category' in df.columns:
        print("---CATS---")
        print(df['category'].unique())
        print("---END CATS---")

    if 'payment_type' in df.columns:
        print("---PAYTYPES---")
        print(df['payment_type'].unique())

except Exception as e:
    print(f"Error: {e}")
