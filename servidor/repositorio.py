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

    def _escopada(self):
        q = select(Usuario)
        if not self._e.eh_adm:                           # Gestor: só o próprio setor
            q = q.where(Usuario.centro_custo_id == self._e.centro_custo_id)
        return q

    def listar(self) -> list[Usuario]:
        """Gestor vê os usuários do próprio setor; ADM vê todos. Ordenado por nome."""
        return list(self._s.scalars(self._escopada().order_by(Usuario.nome)))

    def listar_paginado(self, busca: str = "", papel: str = "", centro_id: int | None = None,
                        pagina: int = 1, por_pagina: int = 8) -> tuple[list[Usuario], int, int]:
        """Lista filtrada e paginada. Devolve (itens, total, total_de_paginas).
        Os filtros vivem DENTRO do escopo (o Gestor nunca enxerga fora do próprio setor)."""
        from sqlalchemy import func, or_
        cond = self._escopada().subquery()
        q = select(Usuario).where(Usuario.id.in_(select(cond.c.id)))
        if busca.strip():
            alvo = f"%{busca.strip().lower()}%"
            q = q.where(or_(func.lower(Usuario.nome).like(alvo), func.lower(Usuario.login).like(alvo)))
        if papel:
            q = q.where(Usuario.papel == papel)
        if centro_id is not None:
            q = q.where(Usuario.centro_custo_id == centro_id)
        total = self._s.scalar(select(func.count()).select_from(q.subquery())) or 0
        por_pagina = max(1, por_pagina)
        paginas = max(1, (total + por_pagina - 1) // por_pagina)
        pagina = min(max(1, pagina), paginas)
        itens = list(self._s.scalars(q.order_by(Usuario.nome)
                                      .offset((pagina - 1) * por_pagina).limit(por_pagina)))
        return itens, total, paginas

    def definir_ativo(self, alvo: Usuario, ativo: bool) -> None:
        alvo.ativo = ativo

    def resetar_senha(self, alvo: Usuario, nova_hash: str) -> None:
        alvo.senha_hash = nova_hash
        alvo.precisa_trocar_senha = True                 # obriga a trocar no próximo acesso
        alvo.tentativas_falhas = 0

    def editar(self, alvo: Usuario, *, nome: str | None = None, email: str | None = None,
               papel: str | None = None, centro_custo_id: int | None = None) -> None:
        if nome is not None:
            alvo.nome = nome
        if email is not None:
            alvo.email = email or None
        if papel is not None:
            alvo.papel = papel
        if centro_custo_id is not None:
            alvo.centro_custo_id = centro_custo_id


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
