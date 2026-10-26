"""Acesso a dados SEMPRE filtrado pelo escopo do usuário — a trava de isolamento (DOCS/18 §5).
As rotas não recebem a sessão crua do banco; recebem repositórios que já nascem filtrados, para que
"esquecer o WHERE centro_custo_id" seja estruturalmente difícil."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .modelos_bd import Relatorio
from .seguranca import Escopo


class RepoRelatorios:
    def __init__(self, sessao: Session, escopo: Escopo):
        self._s = sessao
        self._e = escopo

    def _base(self):
        q = select(Relatorio).where(Relatorio.ativo.is_(True))
        if not self._e.eh_adm:                      # ADM vê todos (e tudo fica auditado)
            q = q.where(Relatorio.centro_custo_id == self._e.centro_custo_id)
        return q

    def listar(self) -> list[Relatorio]:
        return list(self._s.scalars(self._base().order_by(Relatorio.nome)))

    def obter(self, slug: str) -> Relatorio | None:
        """Relatório do escopo pelo slug; None se não existe OU é de outro centro de custo (→ 404)."""
        return self._s.scalar(self._base().where(Relatorio.slug == slug))
