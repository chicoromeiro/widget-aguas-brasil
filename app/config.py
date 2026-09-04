"""Configuracoes centralizadas, lidas de variaveis de ambiente (.env)."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CONTENT_DIR = Path(__file__).resolve().parent / "content"
WEB_DIR = BASE_DIR / "web"

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./widget.db")

# CORS: lista de origens permitidas para embutir o widget.
_origins = os.getenv("ALLOWED_ORIGINS", "*").strip()
ALLOWED_ORIGINS = ["*"] if _origins == "*" else [o.strip() for o in _origins.split(",") if o.strip()]

CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))
# Reservado para a rotina de expurgo de sessoes antigas (Sprint 4). Ainda nao
# consumido: as sessoes permanecem no banco ate a limpeza ser implementada.
SESSION_TIMEOUT_MINUTES: int = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))

# E-mail do chamado, via API HTTP do Mailgun (Sprint 2 - opcional nesta fase).
# Nao usa SMTP: varios provedores de hospedagem (Render incluso, no plano
# gratuito) bloqueiam trafego de saida nas portas SMTP (25/465/587) para
# reduzir abuso - a chamada trava ate estourar o timeout, sem erro de
# credencial. A API HTTP roda por HTTPS normal (porta 443), que nao e
# bloqueada. E o mesmo padrao que o bot de WhatsApp original ja usava.
MAILGUN_API_KEY: str = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN: str = os.getenv("MAILGUN_DOMAIN", "")
# Troque para "https://api.eu.mailgun.net/v3" se o dominio foi criado na
# regiao EU do Mailgun (a API US e EU nao sao intercambiaveis).
MAILGUN_BASE_URL: str = os.getenv("MAILGUN_BASE_URL", "https://api.mailgun.net/v3")

CHAMADO_EMAIL_TO: str = os.getenv("CHAMADO_EMAIL_TO", "cnarh@ana.gov.br")
CHAMADO_EMAIL_FROM: str = os.getenv("CHAMADO_EMAIL_FROM", "nao-responder@exemplo.gov.br")

EMAIL_ENABLED: bool = bool(MAILGUN_API_KEY and MAILGUN_DOMAIN)

# ----------------------------------------------------------------------------
# Seguranca / anti-abuso (Sprint 2)
# ----------------------------------------------------------------------------
# Limite de mensagens por IP por minuto no /chat.
RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_PER_MIN: int = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))

# Teto de chamados abertos por IP por dia (0 = sem limite).
TICKET_CAP_PER_DAY: int = int(os.getenv("TICKET_CAP_PER_DAY", "5"))

# Sal para hashear o IP antes de armazenar/registrar (privacidade).
IP_HASH_SALT: str = os.getenv("IP_HASH_SALT", "trocar-este-sal-em-producao")

# Token para consultar o log de perguntas nao/mal-respondidas (GET /admin/duvidas
# com header X-Admin-Token). Vazio (padrao) = endpoint desligado (404).
ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")

# Tentativas permitidas no desafio anti-robo e no codigo de e-mail.
MAX_TENTATIVAS: int = int(os.getenv("MAX_TENTATIVAS", "3"))

# ----------------------------------------------------------------------------
# IA ancorada no FAQ (Sprint 3) - Google Gemini
# ----------------------------------------------------------------------------
# Provedor de IA: "gemini" (ativo/testado) ou "openai" (Azure OpenAI ou OpenAI
# direto - pronto por config, ativado em producao). A camada e agnostica: a
# mesma logica de selecao e de fallback vale para os dois.
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").lower()

# Chave do Google AI Studio. Sem ela (no provedor gemini), a IA fica desligada e
# o bot opera so com as camadas deterministicas (menu, classificador, topicos).
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

# Modelo. Observacao: o id 'gemini-2.5-flash-lite' e bloqueado pela API para
# chaves/projetos novos (404 'no longer available to new users'); use um id que
# sua chave aceite. 'gemini-3.1-flash-lite' foi verificado como funcional.
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

# Modelo PAGO de fallback: usado apenas quando o gratuito retorna 429 (limite/
# quota atingido). Vazio = desligado. Requer faturamento habilitado no projeto
# Google e um id que a chave aceite (os antigos gemini-2.5-flash* dao 404 para
# chaves novas). Aceita tambem AI_CLASSIFIER_MODEL_PAID (nome herdado do .env).
GEMINI_MODEL_PAID: str = os.getenv("GEMINI_MODEL_PAID", "") or os.getenv("AI_CLASSIFIER_MODEL_PAID", "")

GEMINI_ENDPOINT: str = os.getenv(
    "GEMINI_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta"
)

# --- OpenAI (Azure OpenAI ou OpenAI direto) - pronto, ativado por config ---
# Tokens custeados pela ANA em producao. O endpoint (Azure in-tenant vs direto)
# e definido em OPENAI_BASE_URL na hora de provisionar.
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
# Modelo de fallback quando o primario retorna 429 (limite/quota). Vazio = off.
OPENAI_MODEL_FALLBACK: str = os.getenv("OPENAI_MODEL_FALLBACK", "")
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# Timeout POR TENTATIVA (ha uma retentativa em falha transitoria).
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "8"))

# Habilitada conforme o provedor ativo ter chave configurada.
LLM_ENABLED: bool = bool(OPENAI_API_KEY) if LLM_PROVIDER == "openai" else bool(GOOGLE_API_KEY)
