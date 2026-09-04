# -*- coding: utf-8 -*-
"""Teste ponta a ponta do fluxo via API (FastAPI TestClient), com DB temporario."""
import os, re, sys

os.environ["DATABASE_URL"] = "sqlite:///./_test_widget.db"
os.environ["RATE_LIMIT_ENABLED"] = "false"   # nao interferir no caminho feliz
os.environ["TICKET_CAP_PER_DAY"] = "0"        # teto testado em test_security.py
os.environ["GOOGLE_API_KEY"] = ""             # IA desligada: testa so o deterministico
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.sessions import init_db

init_db()  # TestClient nao dispara o evento de startup; criamos as tabelas aqui.
client = TestClient(app)


def _chat(msg, sid=None):
    r = client.post("/chat", json={"message": msg, "session_id": sid})
    assert r.status_code == 200
    return r.json()


def test_navegacao_menu_e_info():
    d = _chat("__start__")
    sid = d["session_id"]
    assert "Cadastro" in d["reply"]                        # menu principal
    d = _chat("2", sid)                                     # Outorga (info)
    assert "outorga" in d["reply"].lower()
    assert "outorga@ana.gov.br" in d["reply"]              # contato injetado
    d = _chat("0", sid)                                     # 0 volta ao menu
    assert "Cadastro" in d["reply"]


def test_funil_de_botoes():
    # Clicar num topico mantem a mensagem do setor E oferece sub-botoes (FAQ);
    # clicar num sub-botao (faq:<id>) devolve a resposta exata.
    d = _chat("__start__"); sid = d["session_id"]
    d = _chat("2", sid)                                     # topico Outorga
    assert "outorga@ana.gov.br" in d["reply"]              # setor (contato)
    subs = [o["value"] for o in d["options"] if o["value"].startswith("faq:")]
    assert "faq:outorga_nova" in subs and "faq:titularidade" in subs
    d = _chat("faq:titularidade", sid)                     # clica o sub-botao
    assert "titular" in d["reply"].lower() and "outorga@ana.gov.br" in d["reply"]
    # Lendo a resposta: o botao recem-clicado NAO e reoferecido; aparecem
    # "Voltar" (volta a lista do topico) E "Menu inicial" (vai ao inicio).
    vals2 = [o["value"] for o in d["options"]]
    labels2 = [o["label"] for o in d["options"]]
    assert "faq:titularidade" not in vals2
    assert "faq:outorga_nova" in vals2                      # as irmas continuam
    assert "acao:voltar" in vals2 and "Voltar" in labels2
    assert "Menu inicial" in labels2
    # "Voltar" retorna a lista do topico (tela anterior), NAO ao inicio.
    d = _chat("acao:voltar", sid)
    assert "outorga@ana.gov.br" in d["reply"]              # ainda no topico Outorga
    vals3 = [o["value"] for o in d["options"]]
    assert "faq:titularidade" in vals3                      # pergunta restaurada
    assert "acao:voltar" not in vals3                       # tela plana: so Menu inicial


def test_texto_livre_dentro_de_tela_info():
    # Na tela de info, escrever uma duvida deve classificar (nao "bouncar").
    d = _chat("__start__"); sid = d["session_id"]
    _chat("2", sid)                                         # entra em Outorga (info)
    d = _chat("como preencher a durh", sid)                 # pergunta livre na info
    assert "cocam" in d["reply"].lower()                    # respondeu DURH (FAQ)


def test_abrir_chamado_por_texto_livre():
    # Bug corrigido: "abrir chamado" como texto livre deve iniciar o fluxo.
    d = _chat("__start__"); sid = d["session_id"]
    d = _chat("quero abrir um chamado", sid)
    assert "nome" in d["reply"].lower()


def test_opcoes_clicaveis():
    d = _chat("__start__")
    vals = [o["value"] for o in d["options"]]
    assert vals[:7] == ["1", "2", "3", "4", "5", "6", "7"]   # 7 topicos
    assert "acao:chamado" in vals                            # + abrir chamado no menu
    assert d["options"][0]["icon"]
    sid = d["session_id"]
    d = _chat("2", sid)                                       # tela de info (outorga = COOUT)
    labels = [o["label"] for o in d["options"]]
    assert "Menu inicial" in labels
    assert "Abrir chamado" not in labels                      # COOUT nao e COINT/Aguas Brasil
    assert any(o["value"].startswith("faq:") for o in d["options"])   # sub-botoes
    # na revisao do chamado, aparecem Confirmar/Recomecar/Cancelar - abre pelo
    # menu inicial (la o chamado e permitido, sem coordenacao ainda definida)
    d = _chat("0", sid)
    d = _chat("acao:chamado", sid)                            # botao abre o chamado
    for campo in ["Joao", "529.982.247-25", "j@x.com", "61999998888", "nao tenho", "descricao valida do problema"]:
        d = _chat(campo, sid)
    # passo do anexo (opcional) - "pular" avanca para a revisao
    vals_anexo = [o["value"] for o in d["options"]]
    assert "acao:anexar" in vals_anexo and "pular" in vals_anexo
    d = _chat("pular", sid)
    vals = [o["value"] for o in d["options"]]
    assert "confirmar" in vals and "recomecar" in vals


def test_chamado_restrito_a_coint_e_aguas_brasil():
    # Abrir chamado (botao E texto livre) so deve funcionar nos topicos que a
    # COINT atende (CNARH) e na Plataforma Aguas Brasil - nas demais
    # coordenacoes (outorga, cobranca, DURH, boleto, fiscalizacao) o contato
    # certo ja esta na tela do topico; abrir chamado ali e bloqueado.
    permitido = {"1": True, "2": False, "3": False, "4": False,
                 "5": False, "6": False, "7": True}
    for topico, esperado in permitido.items():
        d = _chat("__start__"); sid = d["session_id"]
        d = _chat(topico, sid)
        labels = [o["label"] for o in d["options"]]
        vals = [o["value"] for o in d["options"]]
        assert ("Abrir chamado" in labels) == esperado, f"topico {topico}: botao"
        assert ("acao:chamado" in vals) == esperado, f"topico {topico}: valor"
        d2 = _chat("acao:chamado", sid)   # mesmo sem botao, tenta pelo valor direto
        if esperado:
            assert "informe seu nome" in d2["reply"].lower(), f"topico {topico}: deveria abrir"
        else:
            assert "atendem apenas assuntos" in d2["reply"].lower(), f"topico {topico}: deveria bloquear"
        # texto livre "abrir chamado" segue a mesma regra do botao
        d3 = _chat("__start__"); sid3 = d3["session_id"]
        _chat(topico, sid3)
        d4 = _chat("quero abrir um chamado", sid3)
        if esperado:
            assert "informe seu nome" in d4["reply"].lower(), f"topico {topico}: texto livre deveria abrir"
        else:
            assert "atendem apenas assuntos" in d4["reply"].lower(), f"topico {topico}: texto livre deveria bloquear"


def test_roteamento_por_topico():
    # Nomes de assuntos do menu, em texto livre, levam ao conteudo certo
    # (antes caiam no fallback).
    casos = {
        "Aguas Brasil": "aguasbrasil@ana.gov.br",
        "Plataforma Aguas Brasil": "aguasbrasil@ana.gov.br",
        "outorga": "outorga@ana.gov.br",
        "fiscalizacao": "cofiu@ana.gov.br",
        "fiscalização ambiental": "cofiu@ana.gov.br",  # com acento -> normaliza
    }
    for texto, esperado in casos.items():
        d = _chat("__start__"); sid = d["session_id"]
        d = _chat(texto, sid)
        assert esperado in d["reply"], f"{texto!r} -> {d['reply'][:80]!r}"


def test_texto_livre_classifica_e_responde():
    d = _chat("__start__")
    sid = d["session_id"]
    d = _chat("esqueci minha senha", sid)
    assert "gov.br" in d["reply"].lower()                   # template reset_senha


def test_fluxo_chamado_completo():
    d = _chat("__start__")
    sid = d["session_id"]
    d = _chat("acao:chamado", sid)                           # botao "Abrir chamado"
    assert "nome" in d["reply"].lower()
    _chat("Maria de Souza", sid)
    d = _chat("111.111.111-11", sid)                         # CPF invalido (dv)
    assert "inválido" in d["reply"].lower()
    _chat("529.982.247-25", sid)                             # CPF valido
    _chat("maria@exemplo.com", sid)
    _chat("61999998888", sid)
    _chat("nao tenho", sid)
    d = _chat("Nao consigo acessar minha conta ha dias", sid)
    assert "anexar" in d["reply"].lower()                   # passo opcional de anexo
    d = _chat("pular", sid)
    assert "revise" in d["reply"].lower()
    d = _chat("confirmar", sid)                             # -> desafio anti-robo
    assert "robô" in d["reply"].lower()
    m = re.search(r"(\d+)\s*\+\s*(\d+)", d["reply"])
    soma = int(m.group(1)) + int(m.group(2))
    d = _chat(str(soma), sid)                               # responde o desafio
    assert "protocolo" in d["reply"].lower()


def test_reset_global_cancela_chamado():
    d = _chat("__start__")
    sid = d["session_id"]
    _chat("acao:chamado", sid); _chat("Fulano", sid)
    d = _chat("0", sid)                                      # cancela
    assert "Cadastro" in d["reply"]


def test_log_pergunta_nao_respondida():
    # Texto livre sem correspondencia (IA desligada -> fallback deterministico
    # tambem nao acha nada) deve cair na rede de seguranca E ficar registrado
    # para revisao humana.
    from app.sessions import Repository
    d = _chat("__start__"); sid = d["session_id"]
    d = _chat("qual a previsao do tempo para amanha em marte", sid)
    assert "não encontrei" in d["reply"].lower()
    duvidas = Repository().listar_duvidas()
    assert any(x["session_id"] == sid and x["motivo"] == "sem_correspondencia"
               for x in duvidas)


def test_feedback_negativo_em_resposta_de_faq():
    # Depois de uma resposta de FAQ aparece o botao "Nao ajudou"; clicar
    # registra o feedback (para revisao) e o botao some da tela seguinte.
    from app.sessions import Repository
    d = _chat("__start__"); sid = d["session_id"]
    _chat("2", sid)                                          # topico Outorga
    d = _chat("faq:titularidade", sid)
    vals = [o["value"] for o in d["options"]]
    assert "acao:feedback_negativo" in vals
    d = _chat("acao:feedback_negativo", sid)
    assert "obrigado" in d["reply"].lower()
    vals2 = [o["value"] for o in d["options"]]
    assert "acao:feedback_negativo" not in vals2             # nao reaparece
    duvidas = Repository().listar_duvidas()
    assert any(x["session_id"] == sid and x["motivo"] == "feedback_negativo"
               and x["faq_id"] == "titularidade" for x in duvidas)


def test_anexo_no_fluxo_de_chamado():
    # Print de tela opcional no fluxo de chamado (endpoint /anexo, multipart).
    import base64
    d = _chat("__start__"); sid = d["session_id"]
    _chat("acao:chamado", sid)
    for campo in ["Ana Paula", "529.982.247-25", "ana@x.com", "61999998888", "nao tenho",
                  "descricao valida do problema para teste de anexo"]:
        d = _chat(campo, sid)
    vals = [o["value"] for o in d["options"]]
    assert "acao:anexar" in vals and "pular" in vals

    # tipo nao suportado -> rejeitado, sessao nao avanca (continua em ticket_anexo)
    r_invalido = client.post("/anexo", data={"session_id": sid},
                             files={"file": ("nota.txt", b"nao e imagem", "text/plain")})
    assert r_invalido.status_code == 400

    # PNG 1x1 valido -> aceito, avanca direto para a revisao com o nome do arquivo
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    r = client.post("/anexo", data={"session_id": sid},
                     files={"file": ("print.png", png, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert "print.png" in body["reply"]
    assert "confirmar" in [o["value"] for o in body["options"]]

    # fluxo segue normalmente ate o protocolo (anexo presente nao quebra nada)
    d = _chat("confirmar", sid)
    m = re.search(r"(\d+)\s*\+\s*(\d+)", d["reply"])
    soma = int(m.group(1)) + int(m.group(2))
    d = _chat(str(soma), sid)
    assert "protocolo" in d["reply"].lower()


def test_anexo_entra_no_corpo_do_email():
    # Unitario, sem rede: o nome do anexo aparece no corpo do e-mail montado.
    from app.notifier import _corpo
    dados = {"nome": "Ana", "cpf_cnpj": "1", "email": "a@a.com", "telefone": "1",
             "cnarh": "-", "descricao": "teste",
             "_anexo": {"nome": "print.png", "tipo": "image/png", "dados_b64": ""}}
    texto, html = _corpo(dados, "PROTO123")
    assert "print.png" in texto and "print.png" in html


def _cleanup():
    try:
        os.remove("./_test_widget.db")
    except OSError:
        pass


if __name__ == "__main__":
    test_navegacao_menu_e_info()
    test_funil_de_botoes()
    test_texto_livre_dentro_de_tela_info()
    test_abrir_chamado_por_texto_livre()
    test_opcoes_clicaveis()
    test_chamado_restrito_a_coint_e_aguas_brasil()
    test_roteamento_por_topico()
    test_texto_livre_classifica_e_responde()
    test_fluxo_chamado_completo()
    test_reset_global_cancela_chamado()
    test_log_pergunta_nao_respondida()
    test_feedback_negativo_em_resposta_de_faq()
    test_anexo_no_fluxo_de_chamado()
    test_anexo_entra_no_corpo_do_email()
    _cleanup()
    print("TESTES DE FLUXO OK")
