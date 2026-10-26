"""De onde a interface tira a Analise: local (v1) ou remota (servidor v2).

`FonteLocal` chama o motor direto (comportamento da v1). `FonteRemota` fala com a API e reconstrói a
Analise do JSON (serializacao), para a tela renderizar com o mesmo código. Assim a janela não sabe se os
dados vêm do disco ou do servidor.

Nota: `trust_env=False` no httpx — proxy corporativo não deve interceptar o servidor interno (foi o que
travou o cliente httpx no teste local)."""
from __future__ import annotations

import httpx

from analise_planilha import __version__, serializacao, servico
from analise_planilha.modelos import Analise, Filtros


class ErroServidor(Exception):
    pass


def _filtros_json(f: Filtros | None) -> dict:
    if f is None:
        return {}
    return {"periodo": list(f.periodo) if f.periodo else None,
            "selecao": f.selecao or {}, "anonimizar": f.anonimizar, "coluna_data": f.coluna_data}


class FonteLocal:
    """v1: o motor roda na própria máquina sobre um Dataset já carregado."""

    def __init__(self, ds):
        self._ds = ds

    def analisar(self, filtros: Filtros | None = None) -> Analise:
        return servico.analisar(self._ds, filtros)


class FonteRemota:
    """v2: a Analise vem do servidor (login + consulta)."""

    def __init__(self, base_url: str, cliente: httpx.Client | None = None):
        self._base = base_url.rstrip("/")
        self._c = cliente or httpx.Client(trust_env=False, timeout=30)
        self._token: str | None = None
        self.papel: str | None = None          # preenchido no login (a tela usa para mostrar/ocultar ações)

    def _cab(self) -> dict:
        cab = {"X-Client-Version": __version__}
        if self._token:
            cab["Authorization"] = f"Bearer {self._token}"
        return cab

    def _url(self, caminho: str) -> str:
        return f"{self._base}{caminho}"

    def login(self, login: str, senha: str) -> dict:
        try:
            r = self._c.post(self._url("/api/v1/sessao"), json={"login": login, "senha": senha}, headers=self._cab())
        except httpx.HTTPError as e:
            raise ErroServidor(f"Não foi possível falar com o servidor: {e}") from e
        if r.status_code == 401:
            raise ErroServidor("Login ou senha inválidos.")
        r.raise_for_status()
        dados = r.json()
        self._token = dados["token"]
        self.papel = dados.get("papel")
        return dados

    def relatorios(self) -> list[dict]:
        r = self._c.get(self._url("/api/v1/relatorios"), headers=self._cab())
        r.raise_for_status()
        return r.json()

    def analisar(self, slug: str, filtros: Filtros | None = None) -> Analise:
        r = self._c.post(self._url(f"/api/v1/relatorios/{slug}/analise"),
                         json=_filtros_json(filtros), headers=self._cab())
        if r.status_code == 404:
            raise ErroServidor("Relatório não encontrado (ou de outro setor).")
        if r.status_code == 401:
            raise ErroServidor("Sessão expirada. Entre de novo.")
        r.raise_for_status()
        return serializacao.analise_de_json(r.json())

    def exportar_html(self, slug: str) -> str:
        r = self._c.get(self._url(f"/api/v1/relatorios/{slug}/html"), headers=self._cab())
        if r.status_code == 403:
            raise ErroServidor("Seu papel não permite exportar.")
        if r.status_code == 404:
            raise ErroServidor("Relatório não encontrado (ou de outro setor).")
        r.raise_for_status()
        return r.text
