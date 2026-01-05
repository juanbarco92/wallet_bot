
import pandas as pd
import sys
import os
from datetime import datetime
from src.config import CATEGORIES_CONFIG
from src.loader import SheetsLoader
import unicodedata

# Setup
FILE_PATH = r"c:\Users\Administrador\Documents\Proyectos\autotrx\resources\wallet_records (1).xlsx"
DRY_RUN = False  # Set to False to really write

def normalize_text(text):
    """Normalize text for fuzzy matching (lowercase, no accents)."""
    if not isinstance(text, str):
        return str(text).lower()
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn').lower()

def find_category_match(account_name):
    """
    Finds the (Main Category, Subcategory) pair in CATEGORIES_CONFIG 
    that best matches the account_name.
    """
    # 1. Build flattened map of normalized subcats -> (Main, OriginalSub)
    # Priority: Exact match -> Contains match
    
    clean_account = normalize_text(account_name)
    
    # We only look in "Familiar" as per user instruction, but could look in both.
    scope = "Familiar" 
    categories = CATEGORIES_CONFIG.get(scope, {})
    
    # Direct check
    for main_cat, subcats in categories.items():
        for sub in subcats:
            clean_sub = normalize_text(sub)
            # Check if account name is inside the config subcategory or vice versa
            # Example: Account="Matricula Jardín", Config="[Bolsillo] Matricula Jardin"
            # Logic: If vital keywords match.
            if clean_account in clean_sub or clean_sub in clean_account:
                return main_cat, sub
                
    # If no match found, default to "Otros" (or creating a new subcat using account name)
    return "❔ Otros", account_name

def process_history():
    print(f"--- STARTING IMPORT (DRY_RUN={DRY_RUN}) ---")
    
    # 1. Load Excel
    try:
        df = pd.read_excel(FILE_PATH)
    except Exception as e:
        print(f"Error loading Excel: {e}")
        return

    # 2. Initialize Loader
    loader = None
    if not DRY_RUN:
        try:
            # Use GmailClient to handle OAuth flow and get credentials
            from src.ingestion import GmailClient
            gmail = GmailClient(interactive=False)
            loader = SheetsLoader(credentials=gmail.creds)
            print("Successfully authenticated via GmailClient credentials.")
        except Exception as e:
            print(f"Auth failed: {e}")
            return

    # 3. Iterate
    success_count = 0
    
    for index, row in df.iterrows():
        # -- Parse Date --
        # ISO format in Excel: 2025-12-01T21:36:25.441Z
        # We need to strip Z and parse
        try:
            raw_date = str(row['date']).replace('Z', '')
            dt_obj = datetime.fromisoformat(raw_date)
            formatted_date = dt_obj.strftime("%d/%m/%Y %H:%M:%S")
        except Exception as e:
            print(f"Skipping row {index}: Invalid date {row['date']} ({e})")
            continue

        # -- Map Fields --
        amount = float(row['amount'])
        tx_type_raw = row['type'] # Income / Expense
        tx_type = "Gasto"
        if str(tx_type_raw).lower() == "income":
            tx_type = "Ingreso" # Or Ahorro? User said keep consistency. 
            # If it is a pocket transfer, maybe "Ahorro"? 
            # User said "column type effectively belongs to Gasto or Ingreso".
            # But in bot we use "Ahorro" vs "Gasto".
            # Let's stick to "Ingreso" if user explicitly said so, but bot flow uses "Ahorro".
            # Re-reading user request: "la columna type efectivamente pertenece a Gasto (Expense) o Ingreso (Income)."
            # I will use "Ingreso".

        description = row['note'] if pd.notna(row['note']) else ""
        if pd.isna(description) or description == "":
            # Try others
            if pd.notna(row.get('payee')): description = row['payee']
            elif pd.notna(row.get('labels')): description = row['labels']
            else: description = "Importación Histórica"

        account = row['account']
        
        # -- Map Category --
        main_cat, sub_cat = find_category_match(account)
        full_category_arg = f"{main_cat} - {sub_cat}"

        # -- Construct Transaction Dict --
        transaction_data = {
            "date": formatted_date,
            "timestamp": formatted_date, # Same value as requested
            "amount": amount,
            "merchant": description
        }

        print(f"Row {index}: {formatted_date} | ${amount} | {tx_type} | {full_category_arg} | Scope: Familiar")

        if not DRY_RUN:
            loader.append_transaction(
                transaction=transaction_data,
                category=full_category_arg,
                scope="Familiar",
                user_who_paid="Historical",
                transaction_type=tx_type
            )
            success_count += 1

    print(f"--- FINISHED. Processed {len(df)} rows. Success: {success_count} ---")

if __name__ == "__main__":
    process_history()
