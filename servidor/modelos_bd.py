"""Tabelas do banco (fase 2): centros de custo, usuários, sessões, relatórios e auditoria.
Modelo de dados completo planejado em DOCS/16 §5. Migrações (Alembic) entram quando o esquema
estabilizar; por ora o schema é criado por `bd.criar_schema()`."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .bd import Base

ADM, GESTOR, USUARIO = "ADM", "GESTOR", "USUARIO"
PAPEIS = (ADM, GESTOR, USUARIO)

RASCUNHO, PUBLICADA, SUBSTITUIDA = "RASCUNHO", "PUBLICADA", "SUBSTITUIDA"


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
    email: Mapped[str | None] = mapped_column(String(160))                # opcional; dado pessoal (LGPD)
    cor_avatar: Mapped[str | None] = mapped_column(String(9))             # cor da bolinha (hex da paleta)
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
    modelo: Mapped[str | None] = mapped_column(String(64))   # slug do modelo (config/modelos/*.toml)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Carga(Base):
    """Uma planilha enviada para um relatório. O arquivo bruto fica no volume com nome aleatório
    (UUID), nunca o nome original (DOCS/18 §4)."""
    __tablename__ = "cargas"
    id: Mapped[int] = mapped_column(primary_key=True)
    relatorio_id: Mapped[int] = mapped_column(ForeignKey("relatorios.id"), index=True)
    centro_custo_id: Mapped[int] = mapped_column(Integer, index=True)   # denormalizado p/ o escopo
    enviado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    nome_original: Mapped[str] = mapped_column(String(255))
    hash_sha256: Mapped[str] = mapped_column(String(64))
    arquivo_uuid: Mapped[str] = mapped_column(String(64))               # nome no disco (sem o nome real)
    tamanho: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=RASCUNHO)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    publicado_em: Mapped[dt.datetime | None] = mapped_column(DateTime)
    correcoes: Mapped[str | None] = mapped_column(Text)   # JSON {coluna: papel} corrigido na prévia


class AcessoTemporario(Base):
    """Empréstimo de um relatório a alguém de OUTRO setor, por prazo e (em geral) anonimizado.
    O convidado age como Usuário (só leitura) naquele relatório — DOCS/16 §3.3."""
    __tablename__ = "acessos_temporarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    relatorio_id: Mapped[int] = mapped_column(ForeignKey("relatorios.id"), index=True)
    usuario_destino: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    autorizado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    expira_em: Mapped[dt.datetime] = mapped_column(DateTime)
    anonimizar: Mapped[bool] = mapped_column(Boolean, default=True)
    revogado: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class ConhecimentoColuna(Base):
    """O que o Cérebro APRENDEU: cabeçalho (assinatura normalizada) → papel, por contexto
    ("SETOR/tipo de documento"; "" = vale para tudo). Só estrutura — nunca valor de célula (LGPD)."""
    __tablename__ = "conhecimento"
    __table_args__ = (UniqueConstraint("contexto", "assinatura", name="uq_conhecimento_ctx_assinatura"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    contexto: Mapped[str] = mapped_column(String(160), default="", index=True)
    assinatura: Mapped[str] = mapped_column(String(160), index=True)
    rotulo: Mapped[str] = mapped_column(String(200))
    papel: Mapped[str] = mapped_column(String(24))
    agregacao: Mapped[str | None] = mapped_column(String(24))
    confirmacoes: Mapped[int] = mapped_column(Integer, default=1)
    origem: Mapped[str] = mapped_column(String(24))          # leitura_inicial | correcao | publicacao
    atualizado_em: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    atualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


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
