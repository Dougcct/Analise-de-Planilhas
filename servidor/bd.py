"""Conexão com o banco. PostgreSQL no container; SQLite nos testes (via DATABASE_URL)."""
from __future__ import annotations

import os
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

URL = os.getenv("DATABASE_URL", "postgresql+psycopg://analise:analise@db:5432/analise")


class Base(DeclarativeBase):
    pass


_args = {"check_same_thread": False} if URL.startswith("sqlite") else {}
engine = create_engine(URL, connect_args=_args, pool_pre_ping=True, future=True)
Sessao = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def esperar_banco(tentativas: int = 30, intervalo: float = 1.0) -> None:
    """Postgres pode demorar a aceitar conexões ao subir o compose — espera um pouco."""
    from sqlalchemy import text
    for i in range(tentativas):
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            return
        except Exception:
            if i == tentativas - 1:
                raise
            time.sleep(intervalo)


def criar_schema() -> None:
    import servidor.modelos_bd  # noqa: F401  (registra as tabelas no metadata)
    Base.metadata.create_all(engine)
