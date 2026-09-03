# -*- coding: utf-8 -*-
"""Testes dos validadores (digito verificador de CPF/CNPJ, etc.)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.validators import validar_cpf, validar_cnpj, validar_cpf_cnpj, validar_email, validar_telefone, sanitizar


def test_cpf_valido_e_invalido():
    assert validar_cpf("529.982.247-25") is True        # CPF valido conhecido
    assert validar_cpf("111.111.111-11") is False       # todos iguais
    assert validar_cpf("12345678901") is False          # digito verificador errado
    assert validar_cpf("123") is False


def test_cnpj_valido_e_invalido():
    assert validar_cnpj("11.222.333/0001-81") is True    # CNPJ valido conhecido
    assert validar_cnpj("11.111.111/1111-11") is False
    assert validar_cnpj("12345678000190") is False       # dv errado


def test_cpf_cnpj_roteia_por_tamanho():
    assert validar_cpf_cnpj("52998224725") is True
    assert validar_cpf_cnpj("11222333000181") is True
    assert validar_cpf_cnpj("000") is False


def test_email_e_telefone():
    assert validar_email("a@b.com") is True
    assert validar_email("invalido") is False
    assert validar_telefone("(61) 99999-8888") is True
    assert validar_telefone("123") is False


def test_sanitizar_escapa_html():
    out = sanitizar("<script>alert(1)</script>")
    assert "<script>" not in out and "&lt;script&gt;" in out


if __name__ == "__main__":
    test_cpf_valido_e_invalido()
    test_cnpj_valido_e_invalido()
    test_cpf_cnpj_roteia_por_tamanho()
    test_email_e_telefone()
    test_sanitizar_escapa_html()
    print("TESTES DE VALIDADORES OK")
