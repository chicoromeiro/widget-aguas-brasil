"""
Pseudonimizacao de dados pessoais antes de enviar texto a IA externa (LGPD).

Portado do DataAnonymizer do bot de e-mail. Substitui identificadores diretos
por tokens simbolicos, para que a IA (Gemini, externa) nunca receba PII em
claro. Mascaramento conservador: em duvida, mascara.

Limite conhecido: nomes proprios em texto livre so sao capturados apos pistas
(ex.: "meu nome e X", saudacoes). CPF/CNPJ/e-mail/telefone/CEP sao confiaveis.
"""
import re

# Ordem importa: padroes mais especificos/longos primeiro.
_PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("CNPJ", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|\b\d{14}\b")),
    ("CPF", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b")),
    ("CEP", re.compile(r"\b\d{5}-\d{3}\b")),
    ("TEL", re.compile(r"(?:\+55[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?)?9?\d{4}[\s.-]?\d{4}\b")),
]

# Nome apos pista explicita ("meu nome e Joao da Silva", "sou a Maria Souza").
_NAME_PATTERN = re.compile(
    r"(?P<cue>meu nome (?:e|eh)|me chamo|sou (?:o|a))\s+"
    r"(?P<name>[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõçà]+"
    r"(?:\s+(?:d[aeo]s?\s+)?[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõçà]+){0,3})",
    re.IGNORECASE,
)


def anonymize(texto: str) -> str:
    """Retorna o texto com os dados pessoais substituidos por tokens."""
    if not texto:
        return ""
    out = texto

    def _sub_nome(m):
        return m.group("cue") + " NOME"
    out = _NAME_PATTERN.sub(_sub_nome, out)

    for tipo, patt in _PATTERNS:
        out = patt.sub(tipo, out)
    return out
