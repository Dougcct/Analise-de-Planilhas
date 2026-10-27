"""Acesso a dados SEMPRE filtrado pelo escopo do usuário — a trava de isolamento (DOCS/18 §5).
As rotas não recebem a sessão crua do banco; recebem repositórios que já nascem filtrados, para que
"esquecer o WHERE centro_custo_id" seja estruturalmente difícil."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .modelos_bd import AcessoTemporario, Carga, Relatorio, Usuario, utcnow
from .seguranca import Escopo


class RepoRelatorios:
    def __init__(self, sessao: Session, escopo: Escopo):
        self._s = sessao
        self._e = escopo

    def _compartilhados_comigo(self):
        return (select(AcessoTemporario.relatorio_id)
                .where(AcessoTemporario.usuario_destino == self._e.usuario_id,
                       AcessoTemporario.revogado.is_(False),
                       AcessoTemporario.expira_em > utcnow()))

    def _base(self):
        """Relatórios que o usuário PODE LER: do próprio setor + os compartilhados vigentes."""
        q = select(Relatorio).where(Relatorio.ativo.is_(True))
        if not self._e.eh_adm:                      # ADM vê todos (e tudo fica auditado)
            q = q.where(or_(Relatorio.centro_custo_id == self._e.centro_custo_id,
                            Relatorio.id.in_(self._compartilhados_comigo())))
        return q

    def listar(self) -> list[Relatorio]:
        return list(self._s.scalars(self._base().order_by(Relatorio.nome)))

    def obter(self, slug: str) -> Relatorio | None:
        """Relatório que o usuário pode LER (próprio setor ou compartilhado vigente); senão None (→ 404)."""
        return self._s.scalar(self._base().where(Relatorio.slug == slug))

    def obter_proprio(self, slug: str) -> Relatorio | None:
        """Só relatório do PRÓPRIO setor (ADM: qualquer). Para ações de dono: exportar, enviar, publicar,
        compartilhar. Garante que convidado (acesso temporário) NÃO faça essas ações no relatório alheio."""
        q = select(Relatorio).where(Relatorio.slug == slug, Relatorio.ativo.is_(True))
        if not self._e.eh_adm:
            q = q.where(Relatorio.centro_custo_id == self._e.centro_custo_id)
        return self._s.scalar(q)


class RepoUsuarios:
    """Gestão de usuários dentro do escopo: o Gestor só alcança usuários do PRÓPRIO centro de custo."""

    def __init__(self, sessao: Session, escopo: Escopo):
        self._s = sessao
        self._e = escopo

    def obter(self, usuario_id: int) -> Usuario | None:
        q = select(Usuario).where(Usuario.id == usuario_id)
        if not self._e.eh_adm:                       # Gestor: só o próprio setor
            q = q.where(Usuario.centro_custo_id == self._e.centro_custo_id)
        return self._s.scalar(q)

    def listar(self) -> list[Usuario]:
        """Gestor vê os usuários do próprio setor; ADM vê todos. Ordenado por nome."""
        q = select(Usuario)
        if not self._e.eh_adm:
            q = q.where(Usuario.centro_custo_id == self._e.centro_custo_id)
        return list(self._s.scalars(q.order_by(Usuario.nome)))


class RepoCargas:
    """Cargas (planilhas enviadas) dentro do escopo do usuário."""

    def __init__(self, sessao: Session, escopo: Escopo):
        self._s = sessao
        self._e = escopo

    def _base(self):
        q = select(Carga)
        if not self._e.eh_adm:
            q = q.where(Carga.centro_custo_id == self._e.centro_custo_id)
        return q

    def obter(self, carga_id: int) -> Carga | None:
        return self._s.scalar(self._base().where(Carga.id == carga_id))

    def do_relatorio(self, relatorio_id: int) -> list[Carga]:
        return list(self._s.scalars(self._base().where(Carga.relatorio_id == relatorio_id)
                                    .order_by(Carga.id.desc())))

    def publicada(self, relatorio_id: int) -> Carga | None:
        from .modelos_bd import PUBLICADA
        return self._s.scalar(self._base().where(Carga.relatorio_id == relatorio_id,
                                                 Carga.status == PUBLICADA).order_by(Carga.id.desc()))
