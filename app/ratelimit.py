"""
Rate limiting e identificacao de origem (Sprint 2).

O limitador usa janela deslizante em memoria - suficiente para uma instancia.
Em implantacao multi-instancia, trocar por um backend compartilhado (ex.: Redis);
o ponto de troca e a classe RateLimiter.

O IP e sempre HASHEADO (SHA-256 + sal) antes de armazenar ou registrar, para
nao guardar o endereco em claro (privacidade / LGPD).
"""
import time
import hashlib
import threading

from app import config


class RateLimiter:
    def __init__(self, max_events: int, window_seconds: int):
        self.max_events = max_events
        self.window = window_seconds
        self._store = {}
        self._lock = threading.Lock()

    def allow(self, chave: str) -> bool:
        agora = time.time()
        with self._lock:
            eventos = [t for t in self._store.get(chave, []) if agora - t < self.window]
            if len(eventos) >= self.max_events:
                self._store[chave] = eventos
                return False
            eventos.append(agora)
            self._store[chave] = eventos
            return True


def get_client_ip(request) -> str:
    """Extrai o IP do cliente, respeitando X-Forwarded-For (atras de proxy)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"


def hash_ip(ip: str) -> str:
    return hashlib.sha256((config.IP_HASH_SALT + (ip or "")).encode("utf-8")).hexdigest()[:32]
