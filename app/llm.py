"""
Camada de IA como SELETOR (Sprint 3) - agnostica de provedor.

Principio (mantido de todo o projeto): a IA NAO gera texto de resposta. Ela
apenas escolhe, entre respostas ja aprovadas, qual melhor atende a pergunta -
retornando um numero. O codigo devolve o texto aprovado. Assim, nem manipulacao
(prompt injection) faz o bot dizer algo fora do conjunto aprovado.

Provedores: "gemini" (ativo/testado) e "openai" (Azure OpenAI ou OpenAI direto,
pronto por config, ativado em producao). A logica de selecao, cache, retry em
falha transitoria e FALLBACK em limite (429) e a mesma para ambos.

Fallback em limite: cada provedor tem um modelo primario e, opcionalmente, um de
fallback. Se o primario retornar 429 (limite/quota), tenta o de fallback; so
entao desiste (o motor cai no deterministico). Em erro/timeout, NAO cacheia.
"""
import re
import logging
import threading

import httpx

from app import config

logger = logging.getLogger("widget.llm")

_cache = {}
_lock = threading.Lock()
_CACHE_MAX = 5000
# Resultados de select(): um indice int (casou), ou uma destas sentinelas:
NOMATCH = "__nomatch__"    # a IA respondeu 0/nenhuma (recusa limpa): cacheavel
ERROR = "__error__"        # falha transitoria / IA indisponivel: NAO cacheavel
_NOMATCH = NOMATCH          # alias interno (compat)

# Cliente persistente: reaproveita a conexao (keep-alive) entre chamadas.
_client = httpx.Client()

_PROMPT = (
    "Voce roteia perguntas de usuarios da Agencia Nacional de Aguas (ANA) sobre "
    "recursos hidricos: cadastro (CNARH), outorga, cobranca pelo uso da agua, "
    "declaracao de uso (DURH), boleto, fiscalizacao e acesso a Plataforma Aguas Brasil.\n"
    "Escolha o NUMERO do item cujo assunto melhor atende a PERGUNTA, mesmo que ela use "
    "outras palavras. Responda 0 SOMENTE se a pergunta claramente nao tiver relacao com "
    "esses temas (ex.: previsao do tempo, receitas, assuntos gerais). Caso contrario, "
    "escolha o item mais proximo.\n"
    "Responda apenas o numero, sem explicar.\n\n"
    "PERGUNTA: \"{pergunta}\"\n\n"
    "ITENS:\n{lista}\n\n"
    "Numero:"
)


def enabled() -> bool:
    return config.LLM_ENABLED


def select(pergunta_anon: str, titulos: list):
    """
    Retorna o indice (0-based) da resposta escolhida, ou None.

    Args:
        pergunta_anon: pergunta do usuario JA anonimizada.
        titulos: lista de titulos das respostas aprovadas (indice 0 -> item 1).
    """
    if not enabled() or not titulos or not (pergunta_anon or "").strip():
        return ERROR

    chave = pergunta_anon.strip().lower()
    with _lock:
        if chave in _cache:
            return _cache[chave]   # int (casou) ou NOMATCH

    res = _chamar(pergunta_anon, titulos)   # int | NOMATCH | None(erro)
    if res is None:
        # Erro transitorio (timeout, 503, vazio): NAO cacheia (nao "envenena")
        # e sinaliza ERROR para o motor cair no fallback deterministico.
        return ERROR

    _cache_put(chave, res)   # int ou NOMATCH
    return res


def _cache_put(chave, valor):
    with _lock:
        if chave not in _cache and len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))   # descarta o mais antigo (FIFO)
        _cache[chave] = valor


def _modelos() -> list:
    """Cadeia de modelos do provedor ativo: [primario, fallback (se houver)]."""
    if config.LLM_PROVIDER == "openai":
        chain = [config.OPENAI_MODEL]
        if config.OPENAI_MODEL_FALLBACK:
            chain.append(config.OPENAI_MODEL_FALLBACK)
    else:
        chain = [config.GEMINI_MODEL]
        if config.GEMINI_MODEL_PAID:
            chain.append(config.GEMINI_MODEL_PAID)
    return chain


def _chamar(pergunta: str, titulos: list):
    """Orquestra a cadeia de modelos. Retorna indice 0-based, _NOMATCH ou None."""
    lista = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titulos))
    prompt = _PROMPT.format(pergunta=pergunta, lista=lista)
    n = len(titulos)
    modelos = _modelos()
    for i, modelo in enumerate(modelos):
        kind, val = _provider_call(modelo, prompt, n)
        if kind == "ok":
            return val
        if kind == "nomatch":
            return _NOMATCH
        if kind == "quota" and i + 1 < len(modelos):
            logger.info("Limite (429) em %s; tentando modelo de fallback", modelo)
            continue
        return None  # error, ou quota sem fallback -> nao cacheia
    return None


def _provider_call(modelo: str, prompt: str, n: int):
    """Despacha para o provedor ativo. Retorna (kind, valor):
    kind in {'ok'(valor=idx), 'nomatch', 'quota', 'error'}."""
    if config.LLM_PROVIDER == "openai":
        return _openai_call(modelo, prompt, n)
    return _gemini_call(modelo, prompt, n)


def _parse_numero(texto: str, n: int):
    """Interpreta a resposta do modelo. Retorna (kind, valor)."""
    m = re.search(r"\d+", texto or "")
    if not m:
        return ("error", None)  # vazio -> transitorio (nao cacheia)
    v = int(m.group())
    if 1 <= v <= n:
        return ("ok", v - 1)
    return ("nomatch", None)    # 0 ou fora de faixa = recusa limpa


def _gemini_call(modelo: str, prompt: str, n: int):
    url = f"{config.GEMINI_ENDPOINT}/models/{modelo}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        # thinkingBudget=0: a tarefa e so escolher um numero -> rapido e barato.
        "generationConfig": {"temperature": 0, "maxOutputTokens": 64,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    # 1 retentativa em 503/timeout (intermitentes). Chave no HEADER, nao na URL.
    for tentativa in range(2):
        try:
            r = _client.post(url, headers={"x-goog-api-key": config.GOOGLE_API_KEY},
                             json=body, timeout=config.LLM_TIMEOUT)
        except httpx.TimeoutException:
            if tentativa == 0:
                continue
            logger.warning("Gemini timeout (%ss/tentativa)", config.LLM_TIMEOUT)
            return ("error", None)
        except Exception as e:  # noqa: BLE001
            logger.warning("Falha na chamada Gemini: %s", e)
            return ("error", None)
        if r.status_code == 503 and tentativa == 0:
            continue
        if r.status_code == 429:
            return ("quota", None)
        if r.status_code != 200:
            logger.warning("Gemini(%s) HTTP %s: %s", modelo, r.status_code, r.text[:120])
            return ("error", None)
        cand = (r.json().get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        return _parse_numero(parts[0].get("text") if parts else "", n)
    return ("error", None)


def _openai_call(modelo: str, prompt: str, n: int):
    """Chat Completions (OpenAI/Azure). NAO exercitado ainda (sem chave); ativa
    quando OPENAI_API_KEY/base_url forem definidos em producao."""
    url = config.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
    body = {"model": modelo, "temperature": 0, "max_tokens": 16,
            "messages": [{"role": "user", "content": prompt}]}
    for tentativa in range(2):
        try:
            r = _client.post(url, headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                             json=body, timeout=config.LLM_TIMEOUT)
        except httpx.TimeoutException:
            if tentativa == 0:
                continue
            logger.warning("OpenAI timeout (%ss/tentativa)", config.LLM_TIMEOUT)
            return ("error", None)
        except Exception as e:  # noqa: BLE001
            logger.warning("Falha na chamada OpenAI: %s", e)
            return ("error", None)
        if r.status_code in (500, 502, 503) and tentativa == 0:
            continue
        if r.status_code == 429:
            return ("quota", None)
        if r.status_code != 200:
            logger.warning("OpenAI(%s) HTTP %s: %s", modelo, r.status_code, r.text[:120])
            return ("error", None)
        try:
            texto = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ("error", None)
        return _parse_numero(texto, n)
    return ("error", None)
