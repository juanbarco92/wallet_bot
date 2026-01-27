FAMILIAR_CATEGORIES = {
    "🏠 Casa": [
        "Arriendo",
        "Servicios",
        "Aseo Casa",
        "Mercado",
        "Compras Casa",
        "Suscripciones",
        "[Bolsillo] Seguro Gatos",
        "Gorditos"
    ],
    "🚗 Transporte": [
        "Cuota BLU",
        "Gasolina",
        "[Bolsillo] SOAT + Técnico",
        "[Bolsillo] Seguro",
        "Taxis",
        "Parqueaderos",
        "[Bolsillo] Impuestos",
        "[Bolsillo] Taller General"
    ],
    "👧 Emma": [
        "Basics Emma",
        "Desarrollo Emma",
        "Ropa Emma",
        "Salud Emma",
        "Mildred",
        "[Bolsillo] Prima Mildred",
        "Otras Compras Emma",
        "Pensión Jardin",
        "[Bolsillo] Matricula Jardin"
    ],
    "👶 Benja": [
        "Basics Benja",
        "Desarrollo Benja",
        "Ropa Benja",
        "Salud Benja",
        "STEM",
        "Otras Compras Benja"
    ],
    "🎬 Entretenimiento": [
        "[Bolsillo] Viajes",
        "Salidas Generales",
        "Almuerzos Cumple",
        "Almuerzos entre semana",
        "[Bolsillo] Matrimonio"
    ],
    "🏥 Salud": [
        "Citas medicas",
        "Medicamentos"
    ]
}

PERSONAL_CATEGORIES = {
    "💸 Deudas": [],
    "🧖 Cuidado Personal": [],
    "💰 Ahorro/Inversion": [
        "CREA Emma",
        "CREA Benja",
        "AFP"
    ],
    "👨‍👩‍👧‍👦 Familia": [
        "Mama",
        "Papa"
    ],
    "🛍️ Compras": [
        "Ropa",
        "Suscripciones",
        "Cositas Varias",
        "Regalos",
        "Alcohol"
    ],
    "❔ Otros": []
}

# Wrapper for access
CATEGORIES_CONFIG = {
    "Familiar": FAMILIAR_CATEGORIES,
    "Personal": PERSONAL_CATEGORIES
}

import os
from dotenv import load_dotenv

load_dotenv()

# Recurring Expenses Configuration
# Keys are Telegram Chat IDs (int)
RECURRING_EXPENSES = {
    # Juanma
    int(os.getenv("TELEGRAM_CHAT_ID_JUANMA", 0)): [
        {"name": "Crea Benja", "amount": 1000000, "category": "💰 Ahorro/Inversion - CREA Benja", "scope": "Personal", "owner": "Juanma"},
        {"name": "Crea Emma", "amount": 1000000, "category": "💰 Ahorro/Inversion - CREA Emma", "scope": "Personal", "owner": "Juanma"},
        {"name": "AFP", "amount": 200000, "category": "💰 Ahorro/Inversion - AFP", "scope": "Personal", "owner": "Juanma"},
        {"name": "Deudas", "amount": 497012, "category": "💸 Deudas", "scope": "Personal", "owner": "Juanma"}, # Main category only
        {"name": "[Bolsillo] Matrimonio", "amount": 500100, "category": "🎬 Entretenimiento - [Bolsillo] Matrimonio", "scope": "Personal", "owner": "Juanma"},
        {"name": "[Bolsillo] Viajes", "amount": 728000, "category": "🎬 Entretenimiento - [Bolsillo] Viajes", "scope": "Personal", "owner": "Juanma"},
        {"name": "[Bolsillo] Prima Mildred", "amount": 354000, "category": "👧 Emma - [Bolsillo] Prima Mildred", "scope": "Familiar", "owner": "Juanma"},
        {"name": "[Bolsillo] Matricula Jardin", "amount": 337500, "category": "👧 Emma - [Bolsillo] Matricula Jardin", "scope": "Familiar", "owner": "Juanma"},
        {"name": "[Bolsillo] Seguro Gatos", "amount": 91200, "category": "🏠 Casa - [Bolsillo] Seguro Gatos", "scope": "Familiar", "owner": "Juanma"},
    ],
    # Leydi
    int(os.getenv("TELEGRAM_CHAT_ID_LEY", 0)): [
        {"name": "[Bolsillo] SOAT + Técnico", "amount": 75950, "category": "🚗 Transporte - [Bolsillo] SOAT + Técnico", "scope": "Familiar", "owner": "Leydi"},
        {"name": "[Bolsillo] Seguro", "amount": 288700, "category": "🚗 Transporte - [Bolsillo] Seguro", "scope": "Familiar", "owner": "Leydi"},
        {"name": "[Bolsillo] Impuestos", "amount": 129000, "category": "🚗 Transporte - [Bolsillo] Impuestos", "scope": "Familiar", "owner": "Leydi"},
        {"name": "[Bolsillo] Taller General", "amount": 84300, "category": "🚗 Transporte - [Bolsillo] Taller General", "scope": "Familiar", "owner": "Leydi"},
    ]
}
