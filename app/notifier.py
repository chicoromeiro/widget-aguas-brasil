"""
Envio do e-mail de chamado para a equipe da ANA.

Correcao de seguranca em relacao ao bot original: todos os campos do usuario
sao SANITIZADOS (escape de HTML) antes de compor o e-mail, evitando que
conteudo malicioso chegue renderizado ao cliente de e-mail da equipe.

Se o SMTP nao estiver configurado, o chamado NAO deixa de existir: ele e salvo
e recebe protocolo; apenas o envio fica pendente (registrado em log). Isso e
comportamento real, nao mock - o envio depende de credenciais que serao
fornecidas na fase de producao.
"""
import smtplib
import logging
from email.mime.text import MIMEText

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


def _corpo_html(dados: dict, protocolo: str) -> str:
    linhas = [f"<h2>Novo Chamado - Plataforma Aguas Brasil</h2>",
              f"<p><strong>Protocolo:</strong> {sanitizar(protocolo)}</p>"]
    for chave, rotulo in _CAMPOS:
        valor = sanitizar(str(dados.get(chave, "Nao informado")))
        linhas.append(f"<p><strong>{rotulo}:</strong> {valor}</p>")
    linhas.append("<p><em>E-mail automatico do assistente virtual (COINT/ANA).</em></p>")
    return "\n".join(linhas)


def _enviar(assunto: str, corpo_html: str, destino: str) -> bool:
    """Envia um e-mail HTML. Retorna True se enviado."""
    if not config.EMAIL_ENABLED:
        return False
    try:
        msg = MIMEText(corpo_html, "html", "utf-8")
        msg["Subject"] = assunto
        msg["From"] = config.CHAMADO_EMAIL_FROM
        msg["To"] = destino
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.sendmail(config.CHAMADO_EMAIL_FROM, [destino], msg.as_string())
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Falha ao enviar e-mail para %s: %s", destino, e)
        return False


def enviar_codigo_email(email: str, codigo: str) -> bool:
    """Envia o codigo de confirmacao para o e-mail informado no chamado."""
    corpo = (f"<p>Seu codigo de confirmacao para abrir o chamado e:</p>"
             f"<h2>{sanitizar(codigo)}</h2>"
             f"<p>Se voce nao solicitou, ignore este e-mail.</p>")
    return _enviar("Codigo de confirmacao - Plataforma Aguas Brasil", corpo, email)


def enviar_email_chamado(dados: dict, protocolo: str) -> bool:
    """Envia o e-mail do chamado. Retorna True se enviado, False caso contrario."""
    if not config.EMAIL_ENABLED:
        logger.info("SMTP nao configurado; chamado %s salvo sem envio de e-mail.", protocolo)
        return False
    ok = _enviar(
        f"Novo Chamado - Plataforma Aguas Brasil - {protocolo}",
        _corpo_html(dados, protocolo),
        config.CHAMADO_EMAIL_TO,
    )
    logger.info("Chamado %s %s.", protocolo, "enviado por e-mail" if ok else "com falha de envio")
    return ok
