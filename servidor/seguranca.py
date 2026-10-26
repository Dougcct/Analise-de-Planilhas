"""Senhas (Argon2id), tokens de sessão e escopo do usuário autenticado."""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()
DURACAO_SESSAO = dt.timedelta(hours=8)        # um turno de trabalho (DOCS/18 §7)
MAX_TENTATIVAS = 5


def hash_senha(senha: str) -> str:
    return _ph.hash(senha)


def conferir_senha(hash_: str, senha: str) -> bool:
    try:
        _ph.verify(hash_, senha)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def gerar_token() -> str:
    """Token opaco entregue ao cliente (vai no cabeçalho Authorization)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """No banco guardamos só o hash do token (como senha): vazar o banco não vaza sessões."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Escopo:
    """Quem é o usuário autenticado — montado SEMPRE a partir da sessão, nunca do que a tela envia."""
    usuario_id: int
    papel: str
    centro_custo_id: int | None
    ip: str | None = None

    @property
    def eh_adm(self) -> bool:
        return self.papel == "ADM"
