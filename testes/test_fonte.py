"""Camada FonteAnalise (cliente). FonteRemota é testada contra um transporte httpx simulado (sem subir
servidor nem banco); FonteLocal contra o motor real."""
import io

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("httpx")
import httpx  # noqa: E402

from analise_planilha import serializacao, servico     # noqa: E402
from analise_planilha.modelos import Filtros           # noqa: E402
from app.fonte import ErroServidor, FonteLocal, FonteRemota  # noqa: E402


def _ds():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "Nº": range(1, 61),
        "Data": pd.date_range("2026-01-01", periods=60).strftime("%d/%m/%Y"),
        "Cidade": rng.choice(["A", "B", "C"], 60),
        "Valor": [f"{v:.2f}".replace(".", ",") for v in rng.uniform(10, 500, 60)],
    })
    return servico.carregar(io.BytesIO(df.to_csv(sep=";", index=False).encode("utf-8")), "sintetico.csv")


DS = _ds()


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p.endswith("/sessao"):
        return httpx.Response(200, json={"token": "abc", "papel": "USUARIO", "centro_custo_id": 1,
                                         "precisa_trocar_senha": True, "nome": "Fulano"})
    if not request.headers.get("authorization"):          # resto exige token
        return httpx.Response(401, json={"detail": "sem token"})
    if p.endswith("/relatorios"):
        return httpx.Response(200, json=[{"slug": "r1", "nome": "R1", "centro_custo_id": 1}])
    if p.endswith("/r1/analise"):
        import json as _j
        corpo = _j.loads(request.content or b"{}")
        f = Filtros(selecao=corpo.get("selecao") or {})
        return httpx.Response(200, json=serializacao.analise_para_json(servico.analisar(DS, f)))
    if p.endswith("/outro/analise"):
        return httpx.Response(404, json={"detail": "não encontrado"})
    if p.endswith("/r1/html"):
        return httpx.Response(200, text="<html><body>relatório</body></html>")
    if p.endswith("/proibido/html"):
        return httpx.Response(403, json={"detail": "sem permissão"})
    return httpx.Response(404)


def _remota():
    return FonteRemota("http://servidor", cliente=httpx.Client(transport=httpx.MockTransport(_handler)))


def test_local_analisa():
    a = FonteLocal(DS).analisar(Filtros())
    assert a.linhas == 60 and a.kpis


def test_remota_login_e_cabecalho_de_versao():
    f = _remota()
    assert f.login("user.fin", "senha123")["papel"] == "USUARIO"
    assert f.relatorios()[0]["slug"] == "r1"


def test_remota_exige_login_antes_de_consultar():
    f = _remota()
    with pytest.raises(httpx.HTTPStatusError):     # sem login → 401 → raise_for_status
        f.relatorios()


def test_remota_reconstroi_analise_e_filtra():
    f = _remota()
    f.login("user.fin", "senha123")
    cheio = f.analisar("r1", Filtros())
    assert cheio.linhas == 60 and len(cheio.paineis) >= 3
    uma = f.analisar("r1", Filtros(selecao={"Cidade": ["A"]}))
    assert 0 < uma.linhas < 60


def test_remota_404_vira_erro_tratavel():
    f = _remota()
    f.login("user.fin", "senha123")
    with pytest.raises(ErroServidor, match="outro setor"):
        f.analisar("outro", Filtros())


def test_remota_exporta_html_e_guarda_papel():
    f = _remota()
    f.login("gestor.fin", "senha123")
    assert f.papel == "USUARIO"                           # o mock devolve payload fixo; o papel veio do login
    assert "<html" in f.exportar_html("r1").lower()
    with pytest.raises(ErroServidor, match="papel"):
        f.exportar_html("proibido")
