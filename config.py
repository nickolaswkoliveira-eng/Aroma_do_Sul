import os

MODO_HOMOLOGACAO = os.getenv("MODO_HOMOLOGACAO", "true").lower() == "true"
MODO_DEMONSTRACAO = os.getenv("MODO_DEMONSTRACAO", "false").lower() == "true"
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Sao_Paulo")
MODULO_USUARIOS = False
MODULO_FINANCEIRO = True
MODULO_DRE = True
MODULO_INTELIGENCIA = True
MODULO_NFE = False
MODULO_WHATSAPP = False

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cafeteria.db")
DEMO_DATABASE_URL = os.getenv("DEMO_DATABASE_URL", "sqlite:///./cafeteria_demo.db")
APP_NAME = "Café Aroma do Sul"
