"""Resolução de sessão compartilhada: do TOKEN para o Escopo do usuário.

Usada tanto pela API (token no cabeçalho Authorization) quanto pela versão web (token num cookie).
O token é o mesmo mecanismo das duas: opaco, guardado como hash no banco, revogável na hora."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .modelos_bd import SessaoUsuario, Usuario, utcnow
from .seguranca import Escopo, hash_token


def escopo_por_token(s: Session, token: str) -> Escopo | None:
    """Escopo do usuário dono do token, ou None se o token é inválido/expirado/revogado."""
    if not token:
        return None
    sess = s.scalar(select(SessaoUsuario).where(SessaoUsuario.token_hash == hash_token(token)))
    if sess is None or sess.revogada or sess.expira_em < utcnow():
        return None
    u = s.get(Usuario, sess.usuario_id)
    if u is None or not u.ativo:
        return None
    return Escopo(usuario_id=u.id, papel=u.papel, centro_custo_id=u.centro_custo_id,
                  ip=sess.ip, precisa_trocar_senha=u.precisa_trocar_senha)
