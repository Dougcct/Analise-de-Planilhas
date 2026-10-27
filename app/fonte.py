"""De onde a interface tira a Analise: local (v1) ou remota (servidor v2).

`FonteLocal` chama o motor direto (comportamento da v1). `FonteRemota` fala com a API e reconstrói a
Analise do JSON (serializacao), para a tela renderizar com o mesmo código. Assim a janela não sabe se os
dados vêm do disco ou do servidor.

Nota: `trust_env=False` no httpx — proxy corporativo não deve interceptar o servidor interno (foi o que
travou o cliente httpx no teste local)."""
from __future__ import annotations

import httpx

from analise_planilha import __version__, serializacao, servico
from analise_planilha.atualizacao import versao_tupla
from analise_planilha.modelos import Analise, Filtros


class ErroServidor(Exception):
    pass


def avaliar_versao(local: str, status: dict) -> str:
    """Compara a versão local com a política do servidor (fase 6, DOCS/17 §4).
    Devolve 'obrigatoria' (abaixo da mínima → barra o login), 'opcional' (dá para seguir, mas há
    versão nova recomendada) ou 'ok'."""
    l = versao_tupla(local)
    m = versao_tupla(status.get("versao_minima_cliente"))
    r = versao_tupla(status.get("versao_recomendada_cliente"))
    if m is not None and (l is None or l < m):
        return "obrigatoria"
    if r is not None and l is not None and l < r:
        return "opcional"
    return "ok"


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

    def status_versao(self) -> dict:
        """Checagem pública (sem login) da política de versão do servidor — antes de entrar."""
        try:
            r = self._c.get(self._url("/api/v1/status/versao"), headers=self._cab())
        except httpx.HTTPError as e:
            raise ErroServidor(f"Não foi possível falar com o servidor: {e}") from e
        r.raise_for_status()
        return r.json()

    def login(self, login: str, senha: str) -> dict:
        try:
            r = self._c.post(self._url("/api/v1/sessao"), json={"login": login, "senha": senha}, headers=self._cab())
        except httpx.HTTPError as e:
            raise ErroServidor(f"Não foi possível falar com o servidor: {e}") from e
        if r.status_code == 426:
            raise ErroServidor("Esta versão do cliente não é mais aceita pelo servidor. Atualize para continuar.")
        if r.status_code == 401:
            raise ErroServidor("Login ou senha inválidos.")
        r.raise_for_status()
        dados = r.json()
        self._token = dados["token"]
        self.papel = dados.get("papel")
        return dados

    def trocar_senha(self, senha_atual: str, nova: str) -> None:
        r = self._c.post(self._url("/api/v1/sessao/senha"),
                         json={"senha_atual": senha_atual, "nova": nova}, headers=self._cab())
        if r.status_code == 401:
            raise ErroServidor("Senha atual incorreta.")
        if r.status_code == 422:
            raise ErroServidor(r.json().get("detail", "Senha inválida."))
        r.raise_for_status()

    def logout(self) -> None:
        """Encerra a sessão no servidor (revoga o token). Ignora erro de rede: o token expira sozinho."""
        if not self._token:
            return
        try:
            self._c.delete(self._url("/api/v1/sessao"), headers=self._cab())
        except httpx.HTTPError:
            pass
        self._token = None
        self.papel = None

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

    # ---- gestão de usuários (Gestor/ADM) ----
    def _detalhe(self, r: httpx.Response, padrao: str) -> str:
        try:
            return r.json().get("detail", padrao)
        except Exception:
            return padrao

    def _get(self, caminho: str) -> list | dict:
        r = self._c.get(self._url(caminho), headers=self._cab())
        if r.status_code in (401, 403):
            raise ErroServidor(self._detalhe(r, "Acesso negado."))
        r.raise_for_status()
        return r.json()

    def listar_usuarios(self) -> list[dict]:
        return self._get("/api/v1/usuarios")

    def listar_centros(self) -> list[dict]:
        return self._get("/api/v1/centros")

    def criar_usuario(self, login: str, nome: str, senha: str, papel: str,
                      centro_custo_id: int | None = None) -> dict:
        r = self._c.post(self._url("/api/v1/usuarios"), headers=self._cab(),
                         json={"login": login, "nome": nome, "senha": senha, "papel": papel,
                               "centro_custo_id": centro_custo_id})
        if r.status_code not in (200, 201):
            raise ErroServidor(self._detalhe(r, "Não foi possível criar o usuário."))
        return r.json()

    def bloquear_usuario(self, usuario_id: int) -> None:
        r = self._c.post(self._url(f"/api/v1/usuarios/{usuario_id}/bloquear"), headers=self._cab())
        if r.status_code != 200:
            raise ErroServidor(self._detalhe(r, "Não foi possível bloquear o usuário."))

    # ---- envio e publicação de planilhas (Gestor/ADM) ----
    def listar_cargas(self, slug: str) -> list[dict]:
        return self._get(f"/api/v1/relatorios/{slug}/cargas")

    def enviar_carga(self, slug: str, nome_arquivo: str, conteudo: bytes) -> dict:
        r = self._c.post(self._url("/api/v1/cargas"), headers=self._cab(),
                         data={"slug": slug}, files={"arquivo": (nome_arquivo, conteudo)})
        if r.status_code not in (200, 201):
            raise ErroServidor(self._detalhe(r, "Não foi possível enviar a planilha."))
        return r.json()

    def testar_carga(self, carga_id: int) -> Analise:
        r = self._c.post(self._url(f"/api/v1/cargas/{carga_id}/analise"), json={}, headers=self._cab())
        if r.status_code != 200:
            raise ErroServidor(self._detalhe(r, "Não foi possível ler a planilha."))
        return serializacao.analise_de_json(r.json())

    def publicar_carga(self, carga_id: int) -> dict:
        r = self._c.post(self._url(f"/api/v1/cargas/{carga_id}/publicar"), headers=self._cab())
        if r.status_code != 200:
            raise ErroServidor(self._detalhe(r, "Não foi possível publicar a planilha."))
        return r.json()
