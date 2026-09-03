"""
Validadores de entrada do usuario.

Aprimoramento sobre o bot original: a validacao de CPF/CNPJ agora confere os
DIGITOS VERIFICADORES (o bot de WhatsApp so conferia a quantidade de digitos).
Isso reduz a entrada de documentos aleatorios, embora nao verifique posse.
Tambem oferece sanitizacao para quando os campos forem compostos em e-mail
(Sprint 2), evitando injecao de conteudo.
"""
import re
import html


def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def validar_cpf(cpf: str) -> bool:
    cpf = so_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(cpf[n]) * ((i + 1) - n) for n in range(i))
        dv = (soma * 10) % 11
        dv = 0 if dv == 10 else dv
        if dv != int(cpf[i]):
            return False
    return True


def validar_cnpj(cnpj: str) -> bool:
    cnpj = so_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, pos in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(cnpj[n]) * pesos[n] for n in range(pos))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(cnpj[pos]):
            return False
    return True


def validar_cpf_cnpj(documento: str) -> bool:
    d = so_digitos(documento)
    if len(d) == 11:
        return validar_cpf(d)
    if len(d) == 14:
        return validar_cnpj(d)
    return False


def validar_email(email: str) -> bool:
    return re.match(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$", (email or "").strip()) is not None


def validar_telefone(telefone: str) -> bool:
    t = so_digitos(telefone)
    return 10 <= len(t) <= 11


def sanitizar(texto: str, limite: int = 2000) -> str:
    """Escapa HTML e limita tamanho, para compor mensagens/e-mails com seguranca."""
    if not texto:
        return ""
    return html.escape(texto.strip())[:limite]
