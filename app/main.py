"""
Aplicacao FastAPI do assistente virtual (Widget Aguas Brasil).

Expoe:
- GET  /health            estado da aplicacao
- POST /chat              conversa (session_id + message -> reply)
- GET  /                  pagina de demonstracao standalone
- GET  /web/*             arquivos do widget (js/css)
"""
import logging
from uuid import uuid4

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import __version__, config
from app.content import loader
from app.sessions import init_db, Repository
from app.engine import ChatEngine
from app.ratelimit import RateLimiter, get_client_ip, hash_ip

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# Silencia o log de acesso do httpx: ele registra a URL completa das chamadas,
# que poderia conter segredos em query string. Alem disso, agora a chave da IA
# vai no header (nao na URL). Defesa em profundidade.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("widget")

app = FastAPI(title="Assistente Virtual - Plataforma Aguas Brasil", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

repo = Repository()
engine = ChatEngine(repo)
limiter = RateLimiter(max_events=config.RATE_LIMIT_PER_MIN, window_seconds=60)

MAX_MSG = 4000


class ChatIn(BaseModel):
    message: str = Field(default="", max_length=MAX_MSG)
    session_id: str | None = None


class ChatOut(BaseModel):
    session_id: str
    reply: str
    options: list = []


@app.on_event("startup")
def _startup():
    init_db()
    erros = loader.validate_content()
    if erros:
        for e in erros:
            logger.error("Conteudo invalido: %s", e)
    else:
        logger.info("Conteudo validado com sucesso.")
    if not config.EMAIL_ENABLED:
        logger.warning("SMTP nao configurado: chamados serao salvos sem envio de e-mail.")


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "email_enabled": config.EMAIL_ENABLED}


@app.post("/chat", response_model=ChatOut)
def chat(payload: ChatIn, request: Request):
    ip_hash = hash_ip(get_client_ip(request))

    if config.RATE_LIMIT_ENABLED and not limiter.allow(ip_hash):
        raise HTTPException(
            status_code=429,
            detail="Voce enviou muitas mensagens em pouco tempo. Aguarde alguns instantes.",
        )

    session_id = payload.session_id or uuid4().hex
    state = repo.get_or_create(session_id)
    reply = engine.handle(state, payload.message or "", ctx={"ip_hash": ip_hash})
    options = engine.quick_replies(state)
    repo.save(state)
    return ChatOut(session_id=session_id, reply=reply, options=options)


@app.get("/admin/duvidas")
def listar_duvidas(x_admin_token: str = Header(default="")):
    """
    Log de perguntas nao/mal-respondidas (para revisao humana de gaps de
    conteudo). Desligado por padrao: sem ADMIN_TOKEN configurado, o endpoint
    nem revela que existe (404), nao apenas nega acesso.
    """
    if not config.ADMIN_TOKEN or x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=404)
    return {"duvidas": repo.listar_duvidas()}


@app.get("/")
def demo():
    return FileResponse(config.WEB_DIR / "demo.html")


# Arquivos do widget (js/css)
app.mount("/web", StaticFiles(directory=str(config.WEB_DIR)), name="web")
