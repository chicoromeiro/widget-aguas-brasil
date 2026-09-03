# -*- coding: utf-8 -*-
"""
Testes da camada de IA (Sprint 3) com SELETOR injetado - sem rede.

O produto continua real; apenas a chamada externa e substituida para dirigir as
branches (seletor acerta -> resposta aprovada; seletor recusa -> fallback), e
para exercitar a logica de cache (que os testes de rede nao alcancariam).
"""
import os, sys

os.environ["DATABASE_URL"] = "sqlite:///./_test_llm.db"
os.environ["GOOGLE_API_KEY"] = "fake-key-para-ativar-a-camada"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import llm
from app.anonymizer import anonymize
from app.engine import ChatEngine
from app.sessions import SessionState, Repository, init_db

init_db()

# Originais, para salvar/restaurar (monkeypatch manual sem vazar entre testes).
_ORIG = {"enabled": llm.enabled, "select": llm.select, "_chamar": llm._chamar,
         "_provider_call": llm._provider_call}


def _restore():
    llm.enabled = _ORIG["enabled"]
    llm.select = _ORIG["select"]
    llm._chamar = _ORIG["_chamar"]
    llm._provider_call = _ORIG["_provider_call"]


def test_anonimiza_pii_antes_da_ia():
    t = anonymize("meu CPF e 529.982.247-25, email joao@x.com, tel (61) 98888-7777")
    assert "529.982.247-25" not in t and "joao@x.com" not in t and "98888-7777" not in t
    assert "CPF" in t and "EMAIL" in t and "TEL" in t


def test_ia_seleciona_resposta_aprovada():
    eng = ChatEngine(Repository())
    idx = next(i for i, (k, fid, _) in enumerate(eng.corpus) if fid == "senha")
    llm.enabled = lambda: True
    llm.select = lambda pergunta, titulos: idx
    try:
        st = SessionState("s-ia-1", "inicio", {})
        r = eng.handle(st, "tem algum problema estranho aqui, me ajuda")
        assert "gov.br" in r.lower()   # resposta aprovada do FAQ (senha)
    finally:
        _restore()


def test_ia_recusa_leva_a_rede_de_seguranca():
    # IA respondeu NOMATCH (nada se aplica) -> rede de seguranca (menu), NAO
    # tenta o classificador (a IA ja decidiu que nao ha resposta).
    eng = ChatEngine(Repository())
    llm.enabled = lambda: True
    llm.select = lambda pergunta, titulos: llm.NOMATCH
    try:
        st = SessionState("s-ia-2", "inicio", {})
        r = eng.handle(st, "qual a previsao do tempo para amanha")
        assert "não encontrei" in r.lower()
    finally:
        _restore()


def test_ia_tem_prioridade_sobre_classificador():
    # Com IA ligada, o texto livre vai PRIMEIRO para a IA - mesmo quando o
    # classificador casaria (aqui a IA escolhe outra P&R e ela prevalece).
    eng = ChatEngine(Repository())
    idx_out = next(i for i, (k, fid, _) in enumerate(eng.corpus) if fid == "outorga_nova")
    llm.enabled = lambda: True
    llm.select = lambda pergunta, titulos: idx_out
    try:
        st = SessionState("s-ia-4", "inicio", {})
        r = eng.handle(st, "esqueci minha senha")   # classificador diria RESET_SENHA
        assert "nova outorga" in r.lower()           # mas a IA venceu
    finally:
        _restore()


def test_erro_da_ia_cai_no_classificador():
    # IA retornou ERROR -> fallback deterministico (classificador) responde.
    eng = ChatEngine(Repository())
    llm.enabled = lambda: True
    llm.select = lambda pergunta, titulos: llm.ERROR
    try:
        st = SessionState("s-ia-5", "inicio", {})
        r = eng.handle(st, "esqueci minha senha")
        assert "gov.br" in r.lower()                 # classificador -> FAQ senha
    finally:
        _restore()


def test_ia_desligada_nao_e_chamada():
    eng = ChatEngine(Repository())
    contador = {"n": 0}
    llm.enabled = lambda: False
    llm.select = lambda *a: contador.__setitem__("n", contador["n"] + 1)
    try:
        st = SessionState("s-ia-3", "inicio", {})
        eng.handle(st, "pergunta qualquer sem correspondencia xyzzy")
        assert contador["n"] == 0
    finally:
        _restore()


def test_cache_nao_poisona_em_erro():
    # Bug corrigido: erro transitorio (None) NAO deve ser cacheado.
    llm._cache.clear()
    llm.enabled = lambda: True
    calls = {"n": 0}

    def fake(p, t):
        calls["n"] += 1
        return None if calls["n"] == 1 else 2   # 1a: erro; 2a: match idx 2
    llm._chamar = fake
    try:
        a = llm.select("mesma pergunta", ["x", "y", "z"])   # erro -> ERROR, sem cache
        b = llm.select("mesma pergunta", ["x", "y", "z"])   # re-tenta -> 2
        assert a == llm.ERROR and b == 2 and calls["n"] == 2
    finally:
        _restore()


def test_cache_guarda_recusa_limpa():
    # Recusa limpa (_NOMATCH) DEVE ser cacheada (nao re-chama).
    llm._cache.clear()
    llm.enabled = lambda: True
    calls = {"n": 0}

    def fake(p, t):
        calls["n"] += 1
        return llm.NOMATCH
    llm._chamar = fake
    try:
        a = llm.select("q2", ["x"])
        b = llm.select("q2", ["x"])
        assert a == llm.NOMATCH and b == llm.NOMATCH and calls["n"] == 1  # 2a do cache
    finally:
        _restore()


def test_fallback_em_limite_tenta_modelo_pago():
    # 429 no primario -> tenta o modelo de fallback (mecanismo gratis->pago).
    import app.config as cfg
    llm._cache.clear()
    o_paid = cfg.GEMINI_MODEL_PAID
    cfg.GEMINI_MODEL_PAID = "modelo-pago"
    llm.enabled = lambda: True

    def fake_prov(modelo, prompt, n):
        return ("quota", None) if modelo == cfg.GEMINI_MODEL else ("ok", 1)
    llm._provider_call = fake_prov
    try:
        assert llm.select("pergunta sob limite", ["a", "b", "c"]) == 1
    finally:
        cfg.GEMINI_MODEL_PAID = o_paid
        _restore()


def test_limite_sem_fallback_cai_no_deterministico():
    import app.config as cfg
    llm._cache.clear()
    o_paid = cfg.GEMINI_MODEL_PAID
    cfg.GEMINI_MODEL_PAID = ""            # sem fallback
    llm.enabled = lambda: True
    llm._provider_call = lambda m, p, n: ("quota", None)
    try:
        assert llm.select("outra pergunta", ["a"]) == llm.ERROR
    finally:
        cfg.GEMINI_MODEL_PAID = o_paid
        _restore()


def _cleanup():
    try:
        os.remove("./_test_llm.db")
    except OSError:
        pass


if __name__ == "__main__":
    test_anonimiza_pii_antes_da_ia()
    test_ia_seleciona_resposta_aprovada()
    test_ia_recusa_leva_a_rede_de_seguranca()
    test_ia_tem_prioridade_sobre_classificador()
    test_erro_da_ia_cai_no_classificador()
    test_ia_desligada_nao_e_chamada()
    test_cache_nao_poisona_em_erro()
    test_cache_guarda_recusa_limpa()
    test_fallback_em_limite_tenta_modelo_pago()
    test_limite_sem_fallback_cai_no_deterministico()
    _cleanup()
    print("TESTES DE IA OK")
