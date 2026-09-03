# -*- coding: utf-8 -*-
"""Testes dos controles de seguranca do Sprint 2 (isolados)."""
import os, re, sys

os.environ["DATABASE_URL"] = "sqlite:///./_test_sec.db"
os.environ["RATE_LIMIT_ENABLED"] = "true"
os.environ["RATE_LIMIT_PER_MIN"] = "5"
os.environ["TICKET_CAP_PER_DAY"] = "2"
os.environ["GOOGLE_API_KEY"] = ""   # IA desligada nos testes de seguranca
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.sessions import init_db, Repository
from app.ratelimit import RateLimiter, hash_ip

init_db()
client = TestClient(app)


def _chat(msg, sid=None):
    r = client.post("/chat", json={"message": msg, "session_id": sid})
    return r


def test_rate_limiter_classe():
    rl = RateLimiter(max_events=3, window_seconds=60)
    assert rl.allow("k") and rl.allow("k") and rl.allow("k")
    assert rl.allow("k") is False           # 4a excede
    assert rl.allow("outro") is True        # chave diferente, isolada


def test_hash_ip_deterministico_e_distinto():
    assert hash_ip("1.2.3.4") == hash_ip("1.2.3.4")
    assert hash_ip("1.2.3.4") != hash_ip("4.3.2.1")
    assert "1.2.3.4" not in hash_ip("1.2.3.4")   # nao guarda IP em claro


def test_rate_limit_no_endpoint_retorna_429():
    # RATE_LIMIT_PER_MIN=5; a 6a requisicao do mesmo IP deve dar 429.
    codigos = [_chat("__start__").status_code for _ in range(7)]
    assert 429 in codigos
    assert codigos.count(200) <= 5


def test_protocolos_sequenciais_unicos():
    # Verifica unicidade sequencial. (A recuperacao sob concorrencia real - o
    # retry em IntegrityError - depende de condicao de corrida e nao e exercitada
    # aqui; a chave primaria garante a unicidade final.)
    repo = Repository()
    protocolos = {repo.criar_chamado({"nome": f"user{i}"}, ip_hash="x") for i in range(6)}
    assert len(protocolos) == 6


def test_teto_de_chamados_por_ip():
    # Conta direto no repo: com cap=2, o 3o chamado do mesmo ip deve ser barrado
    # pela regra do engine (aqui validamos a contagem que a regra usa).
    from datetime import datetime, timezone, timedelta
    repo = Repository()
    ip = hash_ip("9.9.9.9")
    repo.criar_chamado({"nome": "a"}, ip_hash=ip)
    repo.criar_chamado({"nome": "b"}, ip_hash=ip)
    desde = datetime.now(timezone.utc) - timedelta(days=1)
    assert repo.contar_chamados_por_ip(ip, desde) >= 2   # atingiu o teto (cap=2)


def test_engine_recusa_ao_atingir_teto():
    # Sem HTTP (nao mexe no rate limit): pre-carrega 2 chamados para um ip e
    # dirige o motor ate CONFIRMAR; com cap=2, deve recusar.
    from app.engine import ChatEngine
    from app.sessions import SessionState
    repo = Repository()
    eng = ChatEngine(repo)
    ip = hash_ip("7.7.7.7")
    repo.criar_chamado({"nome": "x"}, ip_hash=ip)
    repo.criar_chamado({"nome": "y"}, ip_hash=ip)
    state = SessionState("sess-teto", "ticket_revisao",
                         {"_chamado": {"nome": "Z", "cpf_cnpj": "52998224725",
                                       "email": "z@z.com", "telefone": "61999998888",
                                       "cnarh": "Nao informado", "descricao": "problema teste"}})
    resp = eng.handle(state, "confirmar", ctx={"ip_hash": ip})
    assert "limite" in resp.lower()
    assert state.step == "inicio"


def _chamado_base():
    return {"_chamado": {"nome": "Z", "cpf_cnpj": "52998224725",
                         "email": "z@z.com", "telefone": "61999998888",
                         "cnarh": "Nao informado", "descricao": "problema teste"}}


def _passar_desafio(eng, st, ip):
    r = eng.handle(st, "confirmar", ctx={"ip_hash": ip})
    m = re.search(r"(\d+)\s*\+\s*(\d+)", r)
    return eng.handle(st, str(int(m.group(1)) + int(m.group(2))), ctx={"ip_hash": ip})


def test_confirmacao_por_email_quando_smtp_ativo():
    # Exercita a branch EMAIL_ENABLED com transporte injetado (produto continua
    # real; so o envio e substituido para poder dirigir a branch).
    import app.config as cfg
    import app.engine as eng_mod
    from app.engine import ChatEngine
    from app.sessions import SessionState, Repository

    captura = {}
    orig = cfg.EMAIL_ENABLED
    cfg.EMAIL_ENABLED = True
    eng_mod.enviar_codigo_email = lambda email, codigo: captura.update(codigo=codigo) or True
    eng_mod.enviar_email_chamado = lambda dados, protocolo: True
    try:
        eng = ChatEngine(Repository())
        st = SessionState("s-email-ok", "ticket_revisao", _chamado_base())
        r = _passar_desafio(eng, st, hash_ip("2.2.2.2"))
        assert "código" in r.lower() and st.step == "ticket_email_code"
        assert "codigo" in captura
        r = eng.handle(st, captura["codigo"], ctx={"ip_hash": hash_ip("2.2.2.2")})
        assert "protocolo" in r.lower() and st.step == "inicio"
    finally:
        cfg.EMAIL_ENABLED = orig


def test_falha_no_envio_do_codigo_abre_chamado_fail_open():
    import app.config as cfg
    import app.engine as eng_mod
    from app.engine import ChatEngine
    from app.sessions import SessionState, Repository

    orig = cfg.EMAIL_ENABLED
    cfg.EMAIL_ENABLED = True
    eng_mod.enviar_codigo_email = lambda email, codigo: False   # simula falha de envio
    eng_mod.enviar_email_chamado = lambda dados, protocolo: False
    try:
        eng = ChatEngine(Repository())
        st = SessionState("s-email-fail", "ticket_revisao", _chamado_base())
        r = _passar_desafio(eng, st, hash_ip("3.3.3.3"))
        # fail open: abre o chamado mesmo com falha no envio do codigo
        assert "protocolo" in r.lower() and st.step == "inicio"
    finally:
        cfg.EMAIL_ENABLED = orig


def _cleanup():
    for f in ("./_test_sec.db",):
        try:
            os.remove(f)
        except OSError:
            pass


if __name__ == "__main__":
    test_rate_limiter_classe()
    test_hash_ip_deterministico_e_distinto()
    test_rate_limit_no_endpoint_retorna_429()
    test_protocolos_sequenciais_unicos()
    test_teto_de_chamados_por_ip()
    test_engine_recusa_ao_atingir_teto()
    test_confirmacao_por_email_quando_smtp_ativo()
    test_falha_no_envio_do_codigo_abre_chamado_fail_open()
    _cleanup()
    print("TESTES DE SEGURANCA OK")
