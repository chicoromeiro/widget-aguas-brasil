"""
Armazenamento de sessoes e chamados em banco de dados.

Aprimoramento sobre o bot original: a sessao vive no BANCO, nao num dicionario
em memoria por telefone. Isso e o que permite uma aplicacao web multiusuario
(varias conversas simultaneas, sobrevive a reinicio do processo).

Por padrao usa SQLite local (nenhuma instalacao necessaria); troque DATABASE_URL
por Postgres em producao.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, String, Text, DateTime, Integer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker, Mapped, mapped_column

from app.config import DATABASE_URL

Base = declarative_base()

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
_engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, future=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConversaSessao(Base):
    __tablename__ = "conversa_sessoes"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    step: Mapped[str] = mapped_column(String(64), default="novo")
    dados_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Chamado(Base):
    __tablename__ = "chamados"
    protocolo: Mapped[str] = mapped_column(String(32), primary_key=True)
    dados_json: Mapped[str] = mapped_column(Text, default="{}")
    ip_hash: Mapped[str] = mapped_column(String(32), default="", index=True)
    email_enviado: Mapped[str] = mapped_column(String(8), default="nao")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DuvidaNaoRespondida(Base):
    """
    Log de perguntas em texto livre que o bot NAO respondeu (rede de seguranca
    acionada) ou que o usuario marcou como mal respondidas (feedback negativo
    numa resposta de FAQ). Alimenta a revisao humana de gaps de conteudo -
    nunca influencia a conversa em si.
    """
    __tablename__ = "duvidas_nao_respondidas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), default="")
    # "ia_nomatch" | "sem_correspondencia" (fallback deterministico tambem
    # nao achou nada) | "feedback_negativo" (resposta de FAQ marcada como
    # nao util pelo usuario).
    motivo: Mapped[str] = mapped_column(String(32), default="")
    texto: Mapped[str] = mapped_column(Text, default="")   # pergunta (anonimizada) ou, no
    faq_id: Mapped[str] = mapped_column(String(64), default="")  # feedback, a P&R do FAQ
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)


class SessionState:
    """Estado da conversa manipulado pelo motor (nao e a linha do banco)."""
    def __init__(self, session_id: str, step: str, dados: dict):
        self.session_id = session_id
        self.step = step
        self.dados = dados


class Repository:
    """Acesso a sessoes e chamados."""

    def get_or_create(self, session_id: str) -> SessionState:
        with _SessionLocal() as s:
            row = s.get(ConversaSessao, session_id)
            if row is None:
                return SessionState(session_id, "novo", {})
            return SessionState(session_id, row.step, json.loads(row.dados_json or "{}"))

    def save(self, state: SessionState) -> None:
        with _SessionLocal() as s:
            row = s.get(ConversaSessao, state.session_id)
            if row is None:
                row = ConversaSessao(session_id=state.session_id)
                s.add(row)
            row.step = state.step
            row.dados_json = json.dumps(state.dados, ensure_ascii=False)
            row.updated_at = _now()
            s.commit()

    def criar_chamado(self, dados: dict, ip_hash: str = "") -> str:
        """
        Cria o chamado e retorna o protocolo (AAAAMMDD + sequencial diario).

        A geracao e a insercao ocorrem juntas, com retentativa em caso de
        colisao de protocolo (a chave primaria garante unicidade mesmo sob
        confirmacoes concorrentes) - corrige a corrida do 'count()+1'.
        """
        hoje = _now().strftime("%Y%m%d")
        payload = json.dumps(dados, ensure_ascii=False)
        with _SessionLocal() as s:
            for _ in range(8):
                n = s.query(Chamado).filter(Chamado.protocolo.like(f"{hoje}%")).count()
                protocolo = f"{hoje}{n + 1:04d}"
                s.add(Chamado(protocolo=protocolo, dados_json=payload,
                              ip_hash=ip_hash, email_enviado="nao"))
                try:
                    s.commit()
                    return protocolo
                except IntegrityError:
                    s.rollback()
                    continue
        raise RuntimeError("Nao foi possivel gerar um protocolo unico.")

    def marcar_email_enviado(self, protocolo: str) -> None:
        with _SessionLocal() as s:
            row = s.get(Chamado, protocolo)
            if row:
                row.email_enviado = "sim"
                s.commit()

    def contar_chamados_por_ip(self, ip_hash: str, desde: datetime) -> int:
        if not ip_hash:
            return 0
        with _SessionLocal() as s:
            return (s.query(Chamado)
                    .filter(Chamado.ip_hash == ip_hash, Chamado.created_at >= desde)
                    .count())

    def registrar_duvida(self, session_id: str, motivo: str, texto: str = "", faq_id: str = "") -> None:
        with _SessionLocal() as s:
            s.add(DuvidaNaoRespondida(session_id=session_id, motivo=motivo,
                                      texto=(texto or "")[:500], faq_id=faq_id))
            s.commit()

    def listar_duvidas(self, limite: int = 500) -> list:
        with _SessionLocal() as s:
            rows = (s.query(DuvidaNaoRespondida)
                    .order_by(DuvidaNaoRespondida.created_at.desc())
                    .limit(limite).all())
            return [{"id": r.id, "session_id": r.session_id, "motivo": r.motivo,
                     "texto": r.texto, "faq_id": r.faq_id,
                     "created_at": r.created_at.isoformat()} for r in rows]
