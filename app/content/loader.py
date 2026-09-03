"""Carrega e valida o conteudo estruturado (fonte unica de verdade)."""
import json
from functools import lru_cache
from app.config import CONTENT_DIR


def _load(nome: str) -> dict:
    with open(CONTENT_DIR / nome, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_menus() -> dict:
    return _load("menus.json")


@lru_cache(maxsize=1)
def get_contacts() -> dict:
    return _load("contacts.json")


@lru_cache(maxsize=1)
def get_faq() -> dict:
    """Corpus de perguntas e respostas aprovadas (fonte: FAQ v1.1). id -> entry."""
    return _load("faq.json")


def validate_content() -> list:
    """Valida a integridade referencial do conteudo. Retorna lista de erros."""
    erros = []
    menus = get_menus()
    contacts = get_contacts()
    faq = get_faq()

    if "inicio" not in menus:
        erros.append("menus.json: no 'inicio' ausente.")

    destinos_especiais = {"abrir_chamado"}
    for node_id, node in menus.items():
        tipo = node.get("type")
        if tipo == "menu":
            for opt in node.get("options", []):
                alvo = opt.get("goto")
                if alvo in destinos_especiais:
                    continue
                if alvo not in menus:
                    erros.append(f"menus.json: opcao '{opt.get('key')}' de '{node_id}' aponta para '{alvo}' inexistente.")
        if tipo == "info":
            ref = node.get("contact")
            if ref and ref not in contacts:
                erros.append(f"menus.json: '{node_id}' referencia contato '{ref}' inexistente.")
            for fid in node.get("faq", []):
                if fid not in faq:
                    erros.append(f"menus.json: '{node_id}' referencia FAQ '{fid}' inexistente.")
    return erros
