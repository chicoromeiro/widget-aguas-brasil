# -*- coding: utf-8 -*-
"""Testes do classificador de intencao."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import classifier as c


def test_mapeia_intencoes_conhecidas():
    casos = {
        "esqueci minha senha da plataforma": c.RESET_SENHA,
        "meu boleto esta em atraso, como pagar?": c.COBRANCA_DEBITOS,
        "como preencher a durh?": c.DURH,
        "preciso trocar a titularidade da outorga": c.TROCA_TITULARIDADE,
        "a plataforma nao abre, da erro 500": c.ACESSO_PLATAFORMA,
        "preciso de um modelo de procuracao": c.PROCURACAO,
        # intencao mais comum (65,7% da demanda): acesso/senha em varias formas
        "nao estou conseguindo entrar no sistema": c.RESET_SENHA,
        "nao consigo acessar o sistema": c.RESET_SENHA,
        # troca de procurador/representante (era mal roteado para procuracao)
        "mudanca de procurador de usuario": c.REPRESENTACAO,
        "quero trocar o procurador": c.REPRESENTACAO,
        "quero ser representado": c.REPRESENTACAO,
    }
    for texto, esperado in casos.items():
        r = c.classify(texto)
        assert r.categoria == esperado, f"{texto!r} -> {r.categoria} (esperado {esperado})"
        assert r.confianca >= 0.5


def test_representacao_separada_de_procuracao():
    # "procurador/representar" -> REPRESENTACAO; "procuracao" (documento) -> PROCURACAO
    assert c.classify("quero mudar o procurador").categoria == c.REPRESENTACAO
    assert c.classify("preciso do modelo de procuracao").categoria == c.PROCURACAO


def test_texto_sem_relacao_e_desconhecido():
    r = c.classify("qual a receita de bolo de cenoura")
    assert r.categoria == c.DESCONHECIDO
    assert r.confianca == 0.0


def test_vazio():
    assert c.classify("").categoria == c.DESCONHECIDO


if __name__ == "__main__":
    test_mapeia_intencoes_conhecidas()
    test_representacao_separada_de_procuracao()
    test_texto_sem_relacao_e_desconhecido()
    test_vazio()
    print("TESTES DE CLASSIFICADOR OK")
