import os

MODO_HOMOLOGACAO = os.getenv("MODO_HOMOLOGACAO", "true").lower() == "true"
MODULO_USUARIOS = False
MODULO_FINANCEIRO = True
MODULO_DRE = True
MODULO_INTELIGENCIA = True
MODULO_NFE = False
MODULO_WHATSAPP = False

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cafeteria.db")
APP_NAME = "Café Aroma do Sul"
