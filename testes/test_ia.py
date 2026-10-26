"""Testes do Modo IA — tudo OFFLINE: a chamada HTTP é substituída por uma resposta fixa.

Garante três coisas: (1) a anonimização não deixa PII vazar; (2) o JSON da IA vira um `.toml`
que `carregar_modelo` aceita, com as regras de negócio; (3) o modelo gerado aplica no pipeline.
"""
import json

import pytest

from analise_planilha import ia, servico


# ---- anonimização ----------------------------------------------------------
@pytest.mark.parametrize("entrada, proibido", [
    ("João Carlos da Silva", "João Carlos"),      # nome vira iniciais
    ("fulano@unimed.coop.br", "@"),               # e-mail some
    ("12345678900", "12345678900"),               # CPF vira #
    ("Protocolo 2024-000123", "000123"),          # dígitos longos viram #
])
def test_mascarar_remove_pii(entrada, proibido):
    assert proibido not in ia._mascarar(entrada)


def test_mascarar_preserva_rotulo_de_categoria():
    assert ia._mascarar("Deferido") == "Deferido"


def test_resumo_nao_envia_valor_bruto(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv")
    cfg = ia.ConfigIA(amostra="anonimizada")
    resumo = ia.resumo_estrutura(ds, cfg)
    texto = json.dumps(resumo, ensure_ascii=False)
    assert "Observação" in texto                    # a ESTRUTURA (nome da coluna) vai
    assert "texto livre número 1" not in texto      # o VALOR bruto, não


def test_resumo_so_estrutura_nao_tem_exemplos(csv_ptbr):
    ds = servico.carregar(csv_ptbr, "base.csv")
    resumo = ia.resumo_estrutura(ds, ia.ConfigIA(amostra="nenhuma"))
    assert all("exemplos" not in c for c in resumo["colunas"])


# ---- JSON da IA → modelo ----------------------------------------------------
_RESPOSTA = {
    "nome": "Base Sintética", "aba": None,
    "colunas": [
        {"canonico": "protocolo", "rotulo": "Protocolo", "tipo": "identificador", "validar": "numerico"},
        {"canonico": "cidade", "rotulo": "Cidade", "tipo": "categorico", "papel": "dimensao"},
        {"canonico": "valor", "rotulo": "Valor", "tipo": "moeda", "papel": "medida"},
        {"canonico": "autorizado", "rotulo": "Autorizado", "tipo": "booleano"},
    ],
    "analise": {"medida_principal": "Valor", "dimensoes": ["Cidade"]},
    "taxas": [{"canonico": "aut", "rotulo": "Taxa de autorização", "coluna": "Autorizado",
               "valores": ["Sim"], "sentido": ">="}],
    "metas": [{"indicador": "aut", "alvo": 0.7, "sentido": ">="}],
}


def test_json_para_toml_roundtrip():
    toml = ia.json_para_toml(_RESPOSTA)
    assert "[[coluna]]" in toml and "[[taxa]]" in toml and "[[meta]]" in toml


def test_gerar_aplica_no_pipeline(csv_ptbr, monkeypatch):
    ds = servico.carregar(csv_ptbr, "base.csv")
    cfg = ia.ConfigIA(ativo=True, dialeto="openai", base_url="http://x", modelo="m", api_key="k")
    monkeypatch.setattr(ia, "_chamar", lambda cfg, s, i, aviso=None, **_: json.dumps(_RESPOSTA))
    res = ia.gerar(ds, cfg)
    assert res.modelo.nome == "Base Sintética"
    assert {"taxa", "meta"} <= set(res.modelo.regras)
    # o modelo gerado tem de passar pelo pipeline normal
    ds2 = servico.carregar(csv_ptbr, "base.csv", modelo=res.modelo)
    analise = servico.analisar(ds2)
    assert analise.kpis and analise.metas


@pytest.mark.parametrize("chave, esperado", [
    ("sk-ant-abc", "anthropic"), ("AIzaSyXXX", "gemini"),
    ("sk-proj-123", "openai"), ("qualquer-coisa", None),
])
def test_detectar_dialeto(chave, esperado):
    assert ia.detectar_dialeto(chave) == esperado


def test_escolher_modelo_evita_exp_e_pega_familia():
    modelos = ["gemini-1.0-pro", "gemini-2.0-flash-exp", "gemini-2.0-flash", "gemini-1.5-flash"]
    assert ia.escolher_modelo("gemini", modelos) == "gemini-2.0-flash"  # evita -exp, fica em flash


def test_escolher_modelo_prefere_latest():
    modelos = ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-flash-latest"]
    assert ia.escolher_modelo("gemini", modelos) == "gemini-flash-latest"


def test_escolher_modelo_maior_versao_sem_latest():
    modelos = ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-1.5-flash"]
    assert ia.escolher_modelo("gemini", modelos) == "gemini-3.8-flash"


def test_gemini_recupera_modelo_aposentado(monkeypatch):
    urls = []

    def fake(url, headers, payload, timeout, aviso=None, **_):
        urls.append(url)
        if "gemini-2.5-flash" in url:   # modelo aposentado: API sugere o substituto
            raise RuntimeError("A API respondeu erro HTTP 404. models/gemini-2.5-flash is no longer "
                               "available. Please update your code to use models/gemini-3.8-flash ...")
        return {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}

    monkeypatch.setattr(ia, "_http_json", fake)
    cfg = ia.ConfigIA(dialeto="gemini", modelo="gemini-2.5-flash", api_key="k")
    texto = ia._chamar(cfg, "s", "i")
    assert ia._extrair_json(texto) == {"ok": True}
    assert any("gemini-3.8-flash" in u for u in urls)


def test_autoconfigurar_gemini_so_com_chave(monkeypatch):
    def fake_get(url, headers, timeout):
        assert url.endswith("/models") and "x-goog-api-key" in headers
        return {"models": [
            {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
        ]}
    monkeypatch.setattr(ia, "_http_get", fake_get)
    monkeypatch.setattr(ia, "_testar_modelo", lambda cfg: None)   # todo modelo responde
    cfg = ia.ConfigIA(api_key="AIzaSyABC")   # só a chave; dialeto detectado
    pronto = ia.autoconfigurar(cfg)
    assert pronto.dialeto == "gemini" and pronto.modelo == "gemini-2.0-flash"
    assert pronto.pronto()[0]


def test_detectar_chave_nova_do_ai_studio():
    assert ia.detectar_dialeto("AQ.Ab8RN6LxyzExemplo") == "gemini"


def test_autoconfigurar_pula_modelos_sobrecarregados(monkeypatch):
    """Caso real: os 3 mais novos davam 503; o 4º (3.6) respondia — a detecção tem de achá-lo."""
    lista = ["gemini-flash-latest", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
             "gemini-3.5-flash", "gemini-2.5-flash"]
    monkeypatch.setattr(ia, "_listar_modelos_remotos", lambda cfg: lista)
    lotados = {"gemini-flash-latest", "gemini-3.8-flash", "gemini-3.7-flash"}
    testados = []

    def testar(cfg):
        testados.append(cfg.modelo)
        return ia.ErroAPI("high demand", 503) if cfg.modelo in lotados else None

    monkeypatch.setattr(ia, "_testar_modelo", testar)
    pronto = ia.autoconfigurar(ia.ConfigIA(api_key="AQ.chave"))
    assert pronto.modelo == "gemini-3.6-flash"   # o mais bem colocado que respondeu
    # testes rodam em paralelo: todos os mais bem colocados foram de fato testados
    assert {"gemini-flash-latest", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"} <= set(testados)


def test_autoconfigurar_nada_responde_da_erro_claro(monkeypatch):
    monkeypatch.setattr(ia, "_listar_modelos_remotos", lambda cfg: ["gemini-3.8-flash", "gemini-3.7-flash"])
    monkeypatch.setattr(ia, "_testar_modelo", lambda cfg: ia.ErroAPI("high demand", 503))
    with pytest.raises(ia.ErroAPI, match="Nenhum modelo respondeu"):
        ia.autoconfigurar(ia.ConfigIA(api_key="AQ.chave"))


def test_tempo_esgotado_troca_de_modelo(monkeypatch):
    """Caso real: o modelo lotado travou até o timeout (408) em vez de recusar com 503."""
    monkeypatch.setattr(ia, "_listar_modelos_remotos", lambda cfg: ["gemini-flash-latest", "gemini-3.6-flash"])

    def chamar(cfg, s, i, aviso=None, **_):
        if cfg.modelo == "gemini-flash-latest":
            raise ia.ErroAPI("A API não respondeu em 90s.", 408)
        return "ok"

    monkeypatch.setattr(ia, "_chamar", chamar)
    cfg = ia.ConfigIA(dialeto="gemini", modelo="gemini-flash-latest", api_key="k")
    assert ia._chamar_com_alternativas(cfg, "s", "i") == ("ok", "gemini-3.6-flash")


def test_geracao_alcanca_alternativa_alem_da_segunda(monkeypatch):
    """O fallback antigo parava em 2 alternativas (ambas lotadas) — agora chega no 3.6."""
    lista = ["gemini-flash-latest", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"]
    monkeypatch.setattr(ia, "_listar_modelos_remotos", lambda cfg: lista)

    def chamar(cfg, s, i, aviso=None, **_):
        if cfg.modelo != "gemini-3.6-flash":
            raise ia.ErroAPI("high demand", 503)
        return "ok"

    monkeypatch.setattr(ia, "_chamar", chamar)
    cfg = ia.ConfigIA(dialeto="gemini", modelo="gemini-flash-latest", api_key="k")
    assert ia._chamar_com_alternativas(cfg, "s", "i") == ("ok", "gemini-3.6-flash")


def test_autoconfigurar_sem_chave_falha():
    with pytest.raises(RuntimeError):
        ia.autoconfigurar(ia.ConfigIA())


def test_gemini_chama_endpoint_e_parseia(monkeypatch):
    captura = {}

    def fake(url, headers, payload, timeout, aviso=None, **_):
        captura["url"], captura["headers"] = url, headers
        return {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}

    monkeypatch.setattr(ia, "_http_json", fake)
    cfg = ia.ConfigIA(dialeto="gemini", api_key="k")
    texto = ia._chamar(cfg, "sis", "inst")
    assert "generativelanguage.googleapis.com" in captura["url"]
    assert "gemini-2.0-flash:generateContent" in captura["url"]
    assert "x-goog-api-key" in captura["headers"]
    assert ia._extrair_json(texto) == {"ok": True}


# ---- resiliência: sobrecarga (503) ------------------------------------------
def test_retentar_recupera_de_503(monkeypatch):
    monkeypatch.setattr(ia.time, "sleep", lambda s: None)
    avisos, tentativas = [], {"n": 0}

    def fazer():
        tentativas["n"] += 1
        if tentativas["n"] < 3:
            raise ia.ErroAPI("ocupado", 503)
        return {"ok": True}

    assert ia._retentar(fazer, avisos.append) == {"ok": True}
    assert tentativas["n"] == 3 and len(avisos) == 2   # avisou cada nova tentativa


def test_retentar_nao_repete_erro_definitivo(monkeypatch):
    monkeypatch.setattr(ia.time, "sleep", lambda s: None)
    tentativas = {"n": 0}

    def fazer():
        tentativas["n"] += 1
        raise ia.ErroAPI("requisição inválida", 400)

    with pytest.raises(ia.ErroAPI):
        ia._retentar(fazer)
    assert tentativas["n"] == 1


def test_sobrecarga_troca_para_outro_modelo(monkeypatch):
    usados, avisos = [], []

    def fake_chamar(cfg, s, i, aviso=None, **_):
        usados.append(cfg.modelo)
        if cfg.modelo == "gemini-3.8-flash":
            raise ia.ErroAPI("This model is currently experiencing high demand.", 503)
        return '{"colunas": []}'

    monkeypatch.setattr(ia, "_chamar", fake_chamar)
    monkeypatch.setattr(ia, "_listar_modelos_remotos",
                        lambda cfg: ["gemini-3.8-flash", "gemini-3.5-flash", "embedding-001"])
    cfg = ia.ConfigIA(dialeto="gemini", modelo="gemini-3.8-flash", api_key="k")
    assert ia._chamar_com_alternativas(cfg, "s", "i", avisos.append) == ('{"colunas": []}', "gemini-3.5-flash")
    assert usados == ["gemini-3.8-flash", "gemini-3.5-flash"] and avisos


def test_sobrecarga_total_da_mensagem_clara(monkeypatch):
    def sempre_ocupado(cfg, s, i, aviso=None, **_):
        raise ia.ErroAPI("high demand", 503)

    monkeypatch.setattr(ia, "_chamar", sempre_ocupado)
    monkeypatch.setattr(ia, "_listar_modelos_remotos", lambda cfg: ["gemini-3.8-flash", "gemini-3.5-flash"])
    cfg = ia.ConfigIA(dialeto="gemini", modelo="gemini-3.8-flash", api_key="k")
    with pytest.raises(ia.ErroAPI, match="sobrecarregado"):
        ia._chamar_com_alternativas(cfg, "s", "i")


def test_mensagem_erro_extrai_texto_do_json():
    corpo = '{"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}'
    assert ia._mensagem_erro(corpo) == "high demand"


def test_gerar_sem_colunas_falha(csv_ptbr, monkeypatch):
    ds = servico.carregar(csv_ptbr, "base.csv")
    cfg = ia.ConfigIA(ativo=True, base_url="http://x", modelo="m", api_key="k")
    monkeypatch.setattr(ia, "_chamar", lambda cfg, s, i, aviso=None, **_: json.dumps({"colunas": []}))
    with pytest.raises(RuntimeError):
        ia.gerar(ds, cfg)


def test_config_pronto_exige_chave():
    ok, motivo = ia.ConfigIA(dialeto="openai", base_url="http://x", modelo="m").pronto()
    assert not ok and "chave" in motivo.lower()


# ---- salvar/carregar config -------------------------------------------------
def test_config_roundtrip(tmp_path, monkeypatch):
    arq = tmp_path / "ia.toml"
    monkeypatch.setattr(ia, "ARQ_CONFIG", arq)
    cfg = ia.ConfigIA(ativo=True, dialeto="anthropic", base_url="http://b", modelo="m",
                      api_key="segredo", amostra="nenhuma")
    ia.salvar_config(cfg)
    lido = ia.carregar_config()
    assert lido.dialeto == "anthropic" and lido.amostra == "nenhuma" and lido.api_key == "segredo"
