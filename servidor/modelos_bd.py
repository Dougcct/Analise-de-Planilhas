"""Tabelas do banco (fase 2): centros de custo, usuários, sessões, relatórios e auditoria.
Modelo de dados completo planejado em DOCS/16 §5. Migrações (Alembic) entram quando o esquema
estabilizar; por ora o schema é criado por `bd.criar_schema()`."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .bd import Base

ADM, GESTOR, USUARIO = "ADM", "GESTOR", "USUARIO"
PAPEIS = (ADM, GESTOR, USUARIO)


def utcnow() -> dt.datetime:
    """UTC "ingênuo" (sem tzinfo): consistente entre SQLite dos testes e Postgres do container."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class CentroCusto(Base):
    __tablename__ = "centros_custo"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(32), unique=True)
    nome: Mapped[str] = mapped_column(String(120))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(120))
    senha_hash: Mapped[str] = mapped_column(String(255))
    papel: Mapped[str] = mapped_column(String(16))                       # ADM | GESTOR | USUARIO
    centro_custo_id: Mapped[int | None] = mapped_column(ForeignKey("centros_custo.id"))  # ADM = None
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    precisa_trocar_senha: Mapped[bool] = mapped_column(Boolean, default=True)
    tentativas_falhas: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_acesso: Mapped[dt.datetime | None] = mapped_column(DateTime)


class SessaoUsuario(Base):
    __tablename__ = "sessoes"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # SHA-256 do token
    criada_em: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expira_em: Mapped[dt.datetime] = mapped_column(DateTime)
    revogada: Mapped[bool] = mapped_column(Boolean, default=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    versao_cliente: Mapped[str | None] = mapped_column(String(32))


class Relatorio(Base):
    __tablename__ = "relatorios"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(160))
    centro_custo_id: Mapped[int] = mapped_column(ForeignKey("centros_custo.id"), index=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Auditoria(Base):
    """Append-only (a aplicação só INSERE; nunca UPDATE/DELETE) — ver DOCS/18 §6."""
    __tablename__ = "auditoria"
    id: Mapped[int] = mapped_column(primary_key=True)
    quando: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    centro_custo_id: Mapped[int | None] = mapped_column(Integer)
    acao: Mapped[str] = mapped_column(String(48))
    alvo: Mapped[str | None] = mapped_column(String(160))
    ip: Mapped[str | None] = mapped_column(String(64))
    detalhes: Mapped[str | None] = mapped_column(Text)
