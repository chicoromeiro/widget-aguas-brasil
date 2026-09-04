"""
Envio do e-mail de chamado para a equipe da ANA, via API HTTP do Mailgun.

Correcao de seguranca em relacao ao bot original: todos os campos do usuario
sao SANITIZADOS (escape de HTML) antes de compor o e-mail, evitando que
conteudo malicioso chegue renderizado ao cliente de e-mail da equipe.

Se o Mailgun nao estiver configurado, o chamado NAO deixa de existir: ele e
salvo e recebe protocolo; apenas o envio fica pendente (registrado em log).
Isso e comportamento real, nao mock - o envio depende de credenciais que
serao fornecidas na fase de producao.

Por que API HTTP e nao SMTP: varios provedores de hospedagem bloqueiam
trafego de saida nas portas SMTP no plano gratuito (ver app/config.py). A API
roda por HTTPS normal, sem esse problema.
"""
import logging

import httpx

from app import config
from app.validators import sanitizar

logger = logging.getLogger("widget.notifier")

_CAMPOS = [
    ("nome", "Nome"),
    ("cpf_cnpj", "CPF/CNPJ"),
    ("email", "E-mail"),
    ("telefone", "Telefone"),
    ("cnarh", "Numero CNARH"),
    ("descricao", "Descricao do problema"),
]


def _corpo(dados: dict, protocolo: str) -> tuple:
    """Monta o corpo do e-mail do chamado em HTML e em texto simples."""
    html = [f"<h2>Novo Chamado - Plataforma Aguas Brasil</h2>",
            f"<p><strong>Protocolo:</strong> {sanitizar(protocolo)}</p>"]
    texto = [f"Novo Chamado - Plataforma Aguas Brasil", f"Protocolo: {protocolo}"]
    for chave, rotulo in _CAMPOS:
        valor = sanitizar(str(dados.get(chave, "Nao informado")))
        html.append(f"<p><strong>{rotulo}:</strong> {valor}</p>")
        texto.append(f"{rotulo}: {dados.get(chave, 'Nao informado')}")
    html.append("<p><em>E-mail automatico do assistente virtual (COINT/ANA).</em></p>")
    texto.append("\nE-mail automatico do assistente virtual (COINT/ANA).")
    return "\n".join(texto), "\n".join(html)


def _enviar(assunto: str, texto: str, html: str, destino: str) -> bool:
    """Envia um e-mail via API HTTP do Mailgun. Retorna True se aceito para envio."""
    if not config.EMAIL_ENABLED:
        return False
    try:
        r = httpx.post(
            f"{config.MAILGUN_BASE_URL}/{config.MAILGUN_DOMAIN}/messages",
            auth=("api", config.MAILGUN_API_KEY),
            data={"from": config.CHAMADO_EMAIL_FROM, "to": [destino],
                  "subject": assunto, "text": texto, "html": html},
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Falha ao enviar e-mail para %s: %s", destino, e)
        return False


def enviar_codigo_email(email: str, codigo: str) -> bool:
    """Envia o codigo de confirmacao para o e-mail informado no chamado."""
    codigo_seguro = sanitizar(codigo)
    texto = f"Seu codigo de confirmacao para abrir o chamado e: {codigo_seguro}\n\nSe voce nao solicitou, ignore este e-mail."
    html = (f"<p>Seu codigo de confirmacao para abrir o chamado e:</p>"
            f"<h2>{codigo_seguro}</h2>"
            f"<p>Se voce nao solicitou, ignore este e-mail.</p>")
    return _enviar("Codigo de confirmacao - Plataforma Aguas Brasil", texto, html, email)


def enviar_email_chamado(dados: dict, protocolo: str) -> bool:
    """Envia o e-mail do chamado. Retorna True se enviado, False caso contrario."""
    if not config.EMAIL_ENABLED:
        logger.info("Mailgun nao configurado; chamado %s salvo sem envio de e-mail.", protocolo)
        return False
    texto, html = _corpo(dados, protocolo)
    ok = _enviar(f"Novo Chamado - Plataforma Aguas Brasil - {protocolo}",
                 texto, html, config.CHAMADO_EMAIL_TO)
    logger.info("Chamado %s %s.", protocolo, "enviado por e-mail" if ok else "com falha de envio")
    return ok
