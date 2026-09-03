"""
Classificador de intencao por palavras-chave e regex.

Mapeia texto livre em uma categoria de intencao (rota rapida deterministica). A
categoria e resolvida para uma resposta do FAQ aprovado pelo mapeamento CAT_FAQ
no engine. O classificador em si nao usa IA generativa.
"""
import re
from dataclasses import dataclass
from typing import List

# Categorias de intencao (resolvidas para o FAQ via CAT_FAQ no engine)
RESET_SENHA = "reset_senha"
PROCURACAO = "procuracao"
REPRESENTACAO = "representacao"
COBRANCA_DEBITOS = "cobranca_debitos"
DURH = "durh"
TROCA_TITULARIDADE = "troca_titularidade"
ACESSO_PLATAFORMA = "acesso_plataforma"
PROCEDIMENTOS = "procedimentos"
DESCONHECIDO = "desconhecido"


@dataclass
class Resultado:
    categoria: str
    confianca: float
    palavras: List[str]


class _Padrao:
    def __init__(self, categoria, keywords, prioridade=1, regex=None):
        self.categoria = categoria
        self.keywords = [k.lower() for k in keywords]
        self.prioridade = prioridade
        self.regex = [re.compile(p, re.IGNORECASE) for p in (regex or [])]

    def match(self, texto: str):
        t = texto.lower()
        achadas = [k for k in self.keywords if k in t]
        for p in self.regex:
            if p.search(t):
                achadas.append(f"regex:{p.pattern[:24]}")
        return achadas


_PADROES = [
    _Padrao(ACESSO_PLATAFORMA,
            ["plataforma nao", "erro 500", "erro 404", "nao funciona", "nao abre",
             "nao carrega", "pagina em branco", "aguasbrasil", "snirh", "fora do ar",
             "acessar com cnpj", "login com cnpj"],
            prioridade=11,
            regex=[r"plataforma\s+(?:nao|n[aã]o)\s+(?:funciona|abre|carrega|responde)",
                   r"(?:erro|problema)\s+(?:ao|na|no)\s+(?:acessar|entrar|abrir)",
                   r"p[aá]gina\s+(?:em\s+)?branco"]),
    _Padrao(RESET_SENHA,
            ["senha", "reset", "recuperar senha", "esqueci", "credencial",
             "autenticacao", "password", "bloqueado", "bloqueada", "acesso bloqueado",
             "entrar no sistema", "acessar o sistema", "acesso ao sistema",
             "nao consigo entrar", "nao consigo acessar", "nao consigo logar"],
            prioridade=10,
            regex=[r"(?:esqueci|perdi|reset|recuper)\w*\s+(?:minha\s+)?senha",
                   r"(?:nao|n[aã]o)\s+(?:\w+\s+){0,2}(?:consigo|consegu\w+)\s+(?:fazer\s+login|logar|entrar|acessar)",
                   r"senha\s+(?:expirada|vencida|invalida|bloqueada)"]),
    _Padrao(REPRESENTACAO,
            ["procurador", "representar", "representante", "quero ser representado",
             "acessar em nome", "empreendimento de outra", "em nome de terceiro",
             "trocar o procurador", "mudar o procurador"],
            prioridade=9,
            regex=[r"(?:trocar|mudar|alterar|indicar|novo)\s+(?:o\s+)?(?:procurador|representante)",
                   r"represent\w+\s+(?:o|outr|empreendimento)"]),
    _Padrao(PROCURACAO,
            ["procuracao", "poder legal", "modelo de procuracao"],
            prioridade=8,
            regex=[r"modelo\s+(?:de\s+)?procura[cç][aã]o",
                   r"como\s+(?:fa[cç]o|fazer)\s+(?:uma\s+)?procura[cç][aã]o"]),
    _Padrao(COBRANCA_DEBITOS,
            ["cobranca", "debito", "boleto", "pagamento", "atraso", "parcela",
             "financeiro", "fatura", "parcelamento"],
            prioridade=8,
            regex=[r"(?:boleto|fatura|d[eé]bito)\s+(?:em\s+)?atraso",
                   r"(?:como|onde)\s+(?:pagar|efetuar\s+pagamento)"]),
    _Padrao(DURH,
            ["durh", "declaracao de uso", "automonitoramento", "preenchimento",
             "declaracao", "uso de recursos"],
            prioridade=8,
            regex=[r"(?:d[uú]vida\w*)\s+(?:sobre\s+)?durh",
                   r"como\s+(?:preencher|fazer)\s+(?:a\s+)?durh"]),
    _Padrao(TROCA_TITULARIDADE,
            ["titularidade", "titular", "transferencia", "transferir", "troca de titular"],
            prioridade=7,
            regex=[r"(?:trocar|transferir|mudar)\s+(?:de\s+)?titularidade",
                   r"transfer[eê]ncia\s+(?:de\s+)?(?:outorga|concess[aã]o)"]),
    _Padrao(PROCEDIMENTOS,
            ["procedimento", "passo a passo", "orientacao", "guia", "tutorial",
             "solicitar outorga", "como solicitar", "como usar", "primeira vez"],
            prioridade=7,
            regex=[r"como\s+(?:solicitar|pedir|requerer)\s+(?:uma\s+)?outorga",
                   r"passo\s+a\s+passo"]),
]


def classify(texto: str) -> Resultado:
    """Classifica um texto livre em uma categoria conhecida."""
    if not texto or not texto.strip():
        return Resultado(DESCONHECIDO, 0.0, [])

    melhores = {}
    for padrao in _PADROES:
        achadas = padrao.match(texto)
        if achadas:
            conf = min(1.0, (padrao.prioridade / 10.0) * (1.0 + len(achadas) * 0.1))
            melhores[padrao.categoria] = (conf, achadas)

    if not melhores:
        return Resultado(DESCONHECIDO, 0.0, [])

    categoria, (conf, achadas) = max(melhores.items(), key=lambda x: x[1][0])
    return Resultado(categoria, round(conf, 3), achadas)
