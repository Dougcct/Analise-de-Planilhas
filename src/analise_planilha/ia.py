"""Modo IA (opcional): usa uma API de LLM para GERAR o modelo do cliente a partir da planilha.

Fluxo: estrutura da planilha (+ amostra anonimizada) → prompt → LLM devolve JSON → o JSON é
serializado para o MESMO formato `.toml` de modelo que o programa já entende → `carregar_modelo`
valida e o pipeline normal (servico/especificacao) aplica. Ou seja, a IA só MOLDA o modelo; o
motor de análise não muda.

Privacidade (LGPD): por padrão só a ESTRUTURA é enviada (nomes de coluna + tipos + contagens).
Com amostra, os exemplos passam por `_mascarar` (nomes viram iniciais, dígitos viram `#`, e-mails
somem) ANTES de sair da máquina. Nenhum valor bruto é transmitido. Camada genérica: fala com
endpoints compatíveis com OpenAI (OpenAI, Azure, Ollama, gateways) ou com o formato nativo da
Anthropic, escolhido na configuração — nada de SDK pesado (só `urllib`, para o .exe ficar leve).
"""
from __future__ import annotations

import json
import os
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd

from . import config
from .modelo import Modelo, carregar_modelo
from .modelos import BOOLEANO, CATEGORICO, TEXTO_LIVRE, TIPOS, TIPOS_DATA, TIPOS_NUMERICOS
from .normalizacao import chave_texto

ARQ_CONFIG = config.RAIZ / "config" / "ia.toml"
DIALETOS = ("openai", "anthropic", "gemini")
PADROES = {
    "openai": {"base_url": "https://api.openai.com/v1", "modelo": "gpt-4o-mini"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "modelo": "claude-opus-5-5"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta",
               "modelo": "gemini-2.0-flash"},
}
ENV_CHAVE = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}
AMOSTRAS = ("nenhuma", "anonimizada")
PAPEIS = ("dimensao", "medida", "entidade", "texto")


# ---- configuração ----------------------------------------------------------
@dataclass
class ConfigIA:
    ativo: bool = False
    dialeto: str = ""                  # "" = automático (detectado pela chave) | openai | anthropic | gemini
    base_url: str = ""
    modelo: str = ""
    api_key: str = ""
    amostra: str = "anonimizada"       # nenhuma | anonimizada
    max_exemplos: int = 8
    timeout: int = 90

    def base_efetiva(self) -> str:
        return (self.base_url or PADROES.get(self.dialeto, {}).get("base_url", "")).rstrip("/")

    def modelo_efetivo(self) -> str:
        return self.modelo or PADROES.get(self.dialeto, {}).get("modelo", "")

    def chave_efetiva(self) -> str:
        if self.api_key:
            return self.api_key
        chave = os.environ.get(ENV_CHAVE.get(self.dialeto, "OPENAI_API_KEY"), "")
        if not chave and self.dialeto == "gemini":
            chave = os.environ.get("GOOGLE_API_KEY", "")
        return chave

    def pronto(self) -> tuple[bool, str]:
        """(ok, motivo) — diz se dá para chamar a API."""
        if not self.dialeto:
            return False, "Provedor não definido — clique em «Detectar» ou escolha o dialeto."
        if self.dialeto not in DIALETOS:
            return False, f"Dialeto inválido: {self.dialeto}."
        if not self.base_efetiva():
            return False, "Endereço da API (base_url) não configurado."
        if not self.modelo_efetivo():
            return False, "Modelo da IA não configurado."
        if not self.chave_efetiva():
            return False, "Chave de API não configurada (nem no painel, nem na variável de ambiente)."
        return True, ""


def carregar_config() -> ConfigIA:
    if not ARQ_CONFIG.exists():
        return ConfigIA()
    try:
        import tomllib
        dados = tomllib.loads(ARQ_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ConfigIA()
    cfg = ConfigIA()
    for campo in ("dialeto", "base_url", "modelo", "api_key", "amostra"):
        if campo in dados:
            setattr(cfg, campo, str(dados[campo]))
    cfg.ativo = bool(dados.get("ativo", False))
    cfg.max_exemplos = int(dados.get("max_exemplos", cfg.max_exemplos))
    cfg.timeout = int(dados.get("timeout", cfg.timeout))
    if cfg.dialeto and cfg.dialeto not in DIALETOS:
        cfg.dialeto = ""   # inválido → volta para automático
    if cfg.amostra not in AMOSTRAS:
        cfg.amostra = "anonimizada"
    return cfg


def salvar_config(cfg: ConfigIA) -> Path:
    ARQ_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    linhas = [
        "# Configuração do Modo IA. NÃO versionar (contém chave de API) — já ignorado no .gitignore.",
        f"ativo       = {str(cfg.ativo).lower()}",
        f"dialeto     = {_txt(cfg.dialeto)}",
        f"base_url    = {_txt(cfg.base_url)}",
        f"modelo      = {_txt(cfg.modelo)}",
        f"api_key     = {_txt(cfg.api_key)}",
        f"amostra     = {_txt(cfg.amostra)}",
        f"max_exemplos = {cfg.max_exemplos}",
        f"timeout     = {cfg.timeout}",
    ]
    ARQ_CONFIG.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return ARQ_CONFIG


# ---- anonimização ----------------------------------------------------------
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_DIGITOS = re.compile(r"\d{3,}")


def _mascarar(valor) -> str:
    """Oculta PII de um exemplo: e-mails somem, dígitos longos viram `#`, nomes viram iniciais."""
    s = str(valor).strip()
    if not s:
        return s
    s = _RE_EMAIL.sub("«e-mail»", s)
    s = _RE_DIGITOS.sub(lambda m: "#" * len(m.group()), s)
    palavras = s.split()
    maiusculas = sum(1 for p in palavras if p[:1].isupper() and p[:1].isalpha())
    if len(palavras) >= 2 and maiusculas >= 2:   # provável nome próprio → iniciais
        s = " ".join((p[0].upper() + ".") if (p[:1].isupper() and p[:1].isalpha()) else p
                     for p in palavras)
    return s


def _exemplos(serie: pd.Series, col, maxn: int) -> list[str]:
    s = serie.dropna()
    if s.empty:
        return []
    if col.tipo in TIPOS_DATA:
        try:
            return [f"intervalo {s.min():%d/%m/%Y} a {s.max():%d/%m/%Y}"]
        except (ValueError, TypeError):
            return []
    if col.tipo in TIPOS_NUMERICOS:
        v = pd.to_numeric(s, errors="coerce").dropna()
        if v.empty:
            return []
        return [f"min {v.min():g}", f"mediana {v.median():g}", f"max {v.max():g}"]
    if col.tipo == TEXTO_LIVRE:
        # texto livre pode conter narrativa sensível: NUNCA enviar conteúdo, só a forma
        comp = s.astype(str).str.len()
        return [f"texto livre (~{int(comp.mean())} caracteres; conteúdo não enviado)"]
    if col.tipo in (CATEGORICO, BOOLEANO) and col.n_unicos <= 25:
        return [_mascarar(x) for x in list(pd.Series(s.unique()))[:maxn]]
    vistos, saida = set(), []
    for x in s.astype(str):
        m = _mascarar(x)
        if m not in vistos:
            vistos.add(m)
            saida.append(m)
        if len(saida) >= maxn:
            break
    return saida


def resumo_estrutura(ds, cfg: ConfigIA) -> dict:
    """Payload enviado à IA: só estrutura (+ amostra anonimizada, se habilitada)."""
    df = ds.df
    derivadas = {config.COL_LINHA, config.COL_ABA, config.COL_ARQUIVO}
    if ds.spec is not None:  # colunas que o próprio programa cria (classificações, tempos) não são da planilha
        derivadas |= {c.rotulo for c in ds.spec.classificacoes}
        for t in ds.spec.tempos:
            derivadas |= {t.col_dias, t.col_uteis, t.col_meta}
    colunas = []
    for c in ds.esquema.colunas:
        if c.tipo == "vazio" or c.nome in derivadas:
            continue
        info = {"nome": str(c.nome), "tipo": c.tipo, "preenchidos": int(c.n_validos),
                "nulos": int(c.n_nulos), "unicos": int(c.n_unicos)}
        if cfg.amostra == "anonimizada" and c.nome in df.columns:
            ex = _exemplos(df[c.nome], c, cfg.max_exemplos)
            if ex:
                info["exemplos"] = ex
        colunas.append(info)
    return {"arquivo": ds.meta.arquivo, "aba": ds.meta.aba, "linhas": int(len(df)), "colunas": colunas}


# ---- prompt ----------------------------------------------------------------
def _sistema() -> str:
    return (
        "Você é um analista de dados de uma operadora de saúde (cooperativa Unimed). Recebe a "
        "ESTRUTURA de uma planilha operacional (nomes de coluna, tipos detectados, contagens e, às "
        "vezes, exemplos já anonimizados) e deve produzir um MODELO DE ANÁLISE para ela.\n"
        "Responda SOMENTE com um objeto JSON válido (sem comentários, sem texto fora do JSON, sem "
        "cercas de código). Use exatamente as chaves do esquema. Em português. Se não tiver certeza "
        "de uma seção, devolva-a vazia — melhor omitir do que inventar."
    )


def _instrucao(resumo: dict) -> str:
    esquema = {
        "nome": "nome curto do modelo (ex.: 'Autorizações 2024')",
        "aba": "nome da aba ou null",
        "colunas": [{
            "canonico": "identificador_sem_acento_minusculo",
            "rotulo": "Rótulo legível da coluna",
            "tipo": f"um de: {', '.join(TIPOS)}",
            "sinonimos": ["outras grafias do cabeçalho"],
            "papel": f"opcional, um de: {', '.join(PAPEIS)} (ou null)",
            "obrigatoria": "bool — vazio vira alerta de qualidade",
            "validar": "null ou 'numerico' (só dígitos, ex.: nº de guia)",
        }],
        "analise": {
            "entidade": "coluna que identifica a pessoa/cliente (ou null)",
            "data_base": "coluna de data principal para o filtro de período (ou null)",
            "medida_principal": "coluna de valor principal (ou null)",
            "dimensoes": ["colunas categóricas para quebrar/filtrar"],
            "estatistica_tempo": "mediana | media | p90 | p95",
            "top": 15,
        },
        "classificacoes": [{
            "rotulo": "Nome da coluna derivada (ex.: 'Situação')",
            "origem": "coluna de onde vem o texto",
            "vazio": "Não informado", "outros": "Outros",
            "regras": [["trecho_no_texto", "Categoria"]],
        }],
        "taxas": [{
            "canonico": "id_taxa", "rotulo": "Nome legível",
            "coluna": "coluna booleana/categórica", "valores": ["valores que contam como verdadeiro"],
            "sentido": ">= (maior é melhor) | <= (menor é melhor) | null",
        }],
        "tempos": [{
            "canonico": "id_tempo", "rotulo": "Abertura → Conclusão",
            "inicio": "coluna de data inicial", "fim": "coluna de data final",
            "dias_uteis": False, "meta": "nº de dias ou null", "em_aberto": False,
        }],
        "cruzamentos": [{"rotulo": "A × B", "linhas": "coluna", "colunas": "coluna"}],
        "qualidade": {"duplicidade": ["colunas que juntas não devem repetir"],
                      "grafias_parecidas": ["colunas de texto a conferir grafia"]},
        "metas": [{"indicador": "id de taxa/tempo ou 'registros'", "alvo": 0.9, "sentido": ">="}],
    }
    return (
        "ESTRUTURA DA PLANILHA (JSON):\n" + json.dumps(resumo, ensure_ascii=False, indent=1)
        + "\n\nResponda com um JSON NESTE formato (preencha o que fizer sentido, deixe vazio o que não):\n"
        + json.dumps(esquema, ensure_ascii=False, indent=1)
    )


def montar_mensagens(resumo: dict) -> tuple[str, str]:
    return _sistema(), _instrucao(resumo)


# ---- chamada HTTP (genérica) -----------------------------------------------
# Falhas temporárias do provedor (limite de taxa, sobrecarga, instabilidade): vale tentar de novo.
TRANSITORIOS = {429, 500, 502, 503, 504}
# ...e as que justificam TROCAR de modelo. Inclui tempo esgotado (408): modelo sobrecarregado às vezes
# trava em vez de recusar — repetir o mesmo dobraria a espera, mas outro modelo costuma responder.
TROCAR_MODELO = TRANSITORIOS | {408}


class ErroAPI(RuntimeError):
    """Erro da API com o código HTTP (None = rede) — permite separar falha temporária de definitiva."""

    def __init__(self, mensagem: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(mensagem)
        self.status = status
        self.retry_after = retry_after


def _mensagem_erro(corpo: str) -> str:
    """Extrai a mensagem legível do JSON de erro (formato comum a OpenAI, Anthropic e Gemini)."""
    try:
        erro = json.loads(corpo).get("error")
    except (ValueError, AttributeError):
        return corpo[:500]
    if isinstance(erro, dict) and erro.get("message"):
        return erro["message"]
    return corpo[:500]


def _executar(req: urllib.request.Request, timeout: int) -> dict:
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        corpo = ""
        try:
            corpo = e.read().decode("utf-8")
        except Exception:
            pass
        espera = None
        try:
            espera = min(float(e.headers.get("Retry-After")), 30.0) if e.headers.get("Retry-After") else None
        except (TypeError, ValueError):
            pass
        raise ErroAPI(f"A API respondeu erro HTTP {e.code}: {_mensagem_erro(corpo)}", e.code, espera) from e
    except TimeoutError as e:
        raise ErroAPI(f"A API não respondeu em {timeout}s. Tente de novo.", 408) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise ErroAPI(f"A API não respondeu em {timeout}s. Tente de novo.", 408) from e
        raise ErroAPI(f"Não foi possível falar com a API: {e.reason}. "
                      "Confira o endereço (base_url) e a conexão.") from e


def _retentar(fazer, aviso=None, tentativas: int = 3, espera: float = 2.0):
    """Repete `fazer()` em falha temporária, com espera crescente (2s, 4s…) ou a pedida pelo provedor."""
    for i in range(tentativas):
        try:
            return fazer()
        except ErroAPI as e:
            if e.status not in TRANSITORIOS or i == tentativas - 1:
                raise
            pausa = e.retry_after or espera * 2 ** i
            if aviso:
                aviso(f"Provedor ocupado (HTTP {e.status}); nova tentativa em {pausa:.0f}s "
                      f"({i + 2}/{tentativas})…")
            time.sleep(pausa)


def _http_json(url: str, headers: dict, payload: dict, timeout: int, aviso=None, tentativas: int = 3) -> dict:
    corpo = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=corpo, method="POST",
                                 headers={**headers, "Content-Type": "application/json"})
    return _retentar(lambda: _executar(req, timeout), aviso, tentativas)


def _http_get(url: str, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, method="GET", headers=headers)
    return _retentar(lambda: _executar(req, timeout))


def _chamar(cfg: ConfigIA, sistema: str, instrucao: str, aviso=None, tentativas: int = 3) -> str:
    base, modelo, chave = cfg.base_efetiva(), cfg.modelo_efetivo(), cfg.chave_efetiva()
    if cfg.dialeto == "gemini":
        def chamar_gemini(mod: str) -> str:
            resp = _http_json(
                f"{base}/models/{mod}:generateContent",
                {"x-goog-api-key": chave},
                {"systemInstruction": {"parts": [{"text": sistema}]},
                 "contents": [{"role": "user", "parts": [{"text": instrucao}]}],
                 "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}},
                cfg.timeout, aviso=aviso, tentativas=tentativas,
            )
            cands = resp.get("candidates", [])
            partes = cands[0].get("content", {}).get("parts", []) if cands else []
            return "".join(p.get("text", "") for p in partes)

        try:
            return chamar_gemini(modelo)
        except RuntimeError as e:
            # o Gemini aposenta modelos e sugere o substituto na mensagem ("use models/X"): tenta uma vez
            sug = re.search(r"use models/([A-Za-z0-9.\-]+)", str(e))
            if sug and sug.group(1) != modelo:
                return chamar_gemini(sug.group(1))
            raise
    if cfg.dialeto == "anthropic":
        resp = _http_json(
            f"{base}/messages",
            {"x-api-key": chave, "anthropic-version": "2023-06-01"},
            {"model": modelo, "max_tokens": 8000, "system": sistema,
             "messages": [{"role": "user", "content": instrucao}]},
            cfg.timeout, aviso=aviso, tentativas=tentativas,
        )
        partes = [b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"]
        return "".join(partes)
    # openai-compatível (OpenAI, Azure, Ollama, gateways)
    resp = _http_json(
        f"{base}/chat/completions",
        {"Authorization": f"Bearer {chave}"},
        {"model": modelo, "temperature": 0,
         "response_format": {"type": "json_object"},
         "messages": [{"role": "system", "content": sistema},
                      {"role": "user", "content": instrucao}]},
        cfg.timeout, aviso=aviso, tentativas=tentativas,
    )
    return resp["choices"][0]["message"]["content"]


# ---- autodetecção (só a chave basta) ---------------------------------------
# Família preferida por dialeto: modelo rápido/barato e suficiente para gerar o modelo.
# Nomes de VERSÃO não são fixados (envelhecem e são aposentados) — a escolha é dinâmica:
# prefere o alias "*-latest"; senão, a MAIOR versão listada para a chave.
_FAMILIA = {"gemini": "flash", "openai": "mini", "anthropic": "haiku"}
_EVITAR = ("exp", "preview", "vision", "embedding", "image", "audio", "tts", "realtime",
           "thinking", "-lite", "deprecated", "-8b", "nano")


def _versao(nome: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", nome))


def detectar_dialeto(api_key: str) -> str | None:
    """Reconhece o provedor pelo formato da chave. None se não der para ter certeza."""
    k = (api_key or "").strip()
    if k.startswith("sk-ant"):
        return "anthropic"
    if k.startswith(("AIza", "AQ.")):   # formato clássico e o novo do Google AI Studio
        return "gemini"
    if k.startswith("sk-"):
        return "openai"
    return None


def _listar_modelos_remotos(cfg: ConfigIA) -> list[str]:
    """IDs de modelos que a chave pode usar para gerar texto, lidos da própria API."""
    base, chave = cfg.base_efetiva(), cfg.chave_efetiva()
    if cfg.dialeto == "gemini":
        resp = _http_get(f"{base}/models", {"x-goog-api-key": chave}, cfg.timeout)
        return [m["name"].split("/")[-1] for m in resp.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]
    if cfg.dialeto == "anthropic":
        resp = _http_get(f"{base}/models", {"x-api-key": chave, "anthropic-version": "2023-06-01"},
                         cfg.timeout)
        return [m["id"] for m in resp.get("data", [])]
    resp = _http_get(f"{base}/models", {"Authorization": f"Bearer {chave}"}, cfg.timeout)
    return [m["id"] for m in resp.get("data", []) if isinstance(m, dict) and m.get("id")]


def escolher_modelo(dialeto: str, modelos: list[str]) -> str:
    """O melhor modelo disponível para a chave, de forma robusta a renomeações/aposentadorias:

    1. descarta variantes especiais (experimental, visão, embedding, lite…);
    2. fica na família rápida do dialeto (flash/mini/haiku), se houver;
    3. prefere um alias «*-latest» (sempre aponta para o atual);
    4. senão, a MAIOR versão (evita pegar um modelo antigo/aposentado por acaso).
    """
    ordem = ordenar_modelos(dialeto, modelos)
    return ordem[0] if ordem else ""


def ordenar_modelos(dialeto: str, modelos: list[str]) -> list[str]:
    """Modelos do melhor para o pior pelo critério de `escolher_modelo` — os seguintes servem de
    alternativa quando o primeiro está sobrecarregado."""
    simples = [m for m in modelos if not any(x in m.lower() for x in _EVITAR)] or list(modelos)
    familia = _FAMILIA.get(dialeto)

    def nota(m: str) -> tuple:
        n = m.lower()
        latest = "latest" in n
        # entre aliases latest, o mais genérico (curto) primeiro; nos demais, maior versão e nome mais curto
        return (bool(familia and familia in n), latest, -len(m) if latest else 0, _versao(m), -len(m))

    return sorted(simples, key=nota, reverse=True)


MAX_MODELOS_TESTADOS = 6   # na detecção: quantos candidatos testar até achar um que responda
TIMEOUT_TESTE = 15         # s — um pedido mínimo bom volta em 1–3s; mais que isso é modelo travado


def _testar_modelo(cfg: ConfigIA) -> ErroAPI | None:
    """Um pedido mínimo, sem retentativa e com tempo curto. None = respondeu; senão, o erro."""
    try:
        _chamar(replace(cfg, timeout=min(cfg.timeout, TIMEOUT_TESTE)), "Responda somente com JSON.",
                'Devolva exatamente {"ok": true} em JSON.', tentativas=1)
        return None
    except ErroAPI as e:
        return e


def autoconfigurar(cfg: ConfigIA, testar: bool = True) -> ConfigIA:
    """A partir da chave (e opcionalmente do dialeto/endereço), descobre dialeto e melhor modelo.

    Com `testar`, não confia só no nome: manda um pedido mínimo aos candidatos (na ordem de
    preferência) e fica com o PRIMEIRO QUE RESPONDE — pula os sobrecarregados (503), sem cota (429)
    ou aposentados (404). Levanta RuntimeError com mensagem clara se nada servir.
    """
    chave = cfg.chave_efetiva()
    if not chave:
        raise RuntimeError("Informe a chave de API primeiro.")
    dialeto = cfg.dialeto if cfg.dialeto in DIALETOS else detectar_dialeto(chave)
    if not dialeto:
        raise RuntimeError("Não reconheci o provedor pelo formato da chave. "
                           "Escolha o dialeto (openai/anthropic/gemini) manualmente.")
    sonda = ConfigIA(dialeto=dialeto, base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.timeout)
    modelos = _listar_modelos_remotos(sonda)
    if not modelos:
        raise RuntimeError("A chave respondeu, mas nenhum modelo compatível foi listado para ela.")
    ordem = ordenar_modelos(dialeto, modelos)
    escolhido = ordem[0]
    if testar:
        # testa os candidatos EM PARALELO (um travado não segura os outros) e fica com o mais bem
        # colocado na ordem de preferência que respondeu — pior caso ≈ TIMEOUT_TESTE, não N × timeout
        candidatos = ordem[:MAX_MODELOS_TESTADOS]
        pool = ThreadPoolExecutor(max_workers=len(candidatos))
        try:
            futuros = [pool.submit(_testar_modelo, replace(sonda, modelo=m)) for m in candidatos]
            falhas = []
            for m, fut in zip(candidatos, futuros):   # na ordem de preferência
                erro = fut.result()
                if erro is None:
                    escolhido = m
                    break
                if erro.status in (401, 403):
                    raise RuntimeError(f"A chave foi recusada pelo provedor: {erro}") from erro
                falhas.append(f"{m} (HTTP {erro.status or 'rede'})")
            else:
                raise ErroAPI("Nenhum modelo respondeu agora: " + ", ".join(falhas) + ". O provedor "
                              "parece sobrecarregado ou sem cota — tente de novo em alguns minutos.", 503)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)   # não espera os testes que ficaram travados
    return ConfigIA(ativo=True, dialeto=dialeto, base_url=cfg.base_url, modelo=escolhido,
                    api_key=cfg.api_key, amostra=cfg.amostra, max_exemplos=cfg.max_exemplos,
                    timeout=cfg.timeout)


def _extrair_json(texto: str) -> dict:
    t = texto.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t[3:]
        t = t[4:] if t[:4].lower() == "json" else t
    ini, fim = t.find("{"), t.rfind("}")
    if ini == -1 or fim == -1:
        raise RuntimeError("A IA não devolveu um JSON reconhecível.")
    return json.loads(t[ini:fim + 1])


# ---- JSON da IA → .toml de modelo (formato que o programa já entende) -------
def _txt(v) -> str:
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _lista(vs) -> str:
    return "[" + ", ".join(_txt(v) for v in vs) + "]"


def _escalar(v) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return repr(v)
    return _txt(v)


def json_para_toml(dados: dict) -> str:
    """Serializa o JSON da IA no mesmo .toml que `carregar_modelo` + `de_modelo` consomem."""
    L: list[str] = [f"nome = {_txt(dados.get('nome') or 'Modelo IA')}"]
    if dados.get("aba"):
        L.append(f"aba  = {_txt(dados['aba'])}")

    for c in dados.get("colunas", []):
        if not c.get("rotulo") and not c.get("canonico"):
            continue
        rot = c.get("rotulo") or c["canonico"]
        tipo = c.get("tipo") if c.get("tipo") in TIPOS else "texto_livre"
        L += ["", "[[coluna]]",
              f"canonico  = {_txt(c.get('canonico') or chave_texto(rot))}",
              f"rotulo    = {_txt(rot)}",
              f"tipo      = {_txt(tipo)}",
              f"sinonimos = {_lista(c.get('sinonimos', []))}"]
        if c.get("papel") in PAPEIS:
            L.append(f"papel     = {_txt(c['papel'])}")
        if c.get("obrigatoria"):
            L.append("obrigatoria = true")
        if c.get("validar") == "numerico":
            L.append('validar   = "numerico"')

    an = dados.get("analise") or {}
    chaves_an = [(k, an.get(k)) for k in ("entidade", "data_base", "medida_principal")]
    if any(v for _, v in chaves_an) or an.get("dimensoes") or an.get("estatistica_tempo"):
        L += ["", "[analise]"]
        for k, v in chaves_an:
            if v:
                L.append(f"{k} = {_txt(v)}")
        if an.get("dimensoes"):
            L.append(f"dimensoes = {_lista(an['dimensoes'])}")
        if an.get("estatistica_tempo"):
            L.append(f"estatistica_tempo = {_txt(an['estatistica_tempo'])}")
        if an.get("top"):
            L.append(f"top = {int(an['top'])}")

    for c in dados.get("classificacoes", []):
        if not c.get("rotulo") or not c.get("origem") or not c.get("regras"):
            continue
        L += ["", "[[classificacao]]",
              f"rotulo = {_txt(c['rotulo'])}",
              f"origem = {_txt(c['origem'])}"]
        if c.get("vazio"):
            L.append(f"vazio  = {_txt(c['vazio'])}")
        if c.get("outros"):
            L.append(f"outros = {_txt(c['outros'])}")
        regras = [r for r in c["regras"] if isinstance(r, list) and 2 <= len(r) <= 3]
        L.append("regras = [" + ", ".join("[" + ", ".join(_txt(x) for x in r) + "]" for r in regras) + "]")

    for t in dados.get("taxas", []):
        rot = t.get("rotulo") or t.get("canonico")
        if not rot:
            continue
        L += ["", "[[taxa]]",
              f"canonico = {_txt(t.get('canonico') or chave_texto(rot))}",
              f"rotulo   = {_txt(rot)}"]
        if t.get("numerador") and t.get("denominador"):
            L += [f"numerador   = {_txt(t['numerador'])}", f"denominador = {_txt(t['denominador'])}"]
        elif t.get("coluna"):
            L.append(f"coluna   = {_txt(t['coluna'])}")
            if t.get("valores"):
                L.append(f"valores  = {_lista(t['valores'])}")
        else:
            L.pop(); L.pop(); L.pop(); L.pop()  # taxa incompleta: desfaz
            continue
        if t.get("sentido") in (">=", "<="):
            L.append(f"sentido  = {_txt(t['sentido'])}")

    for t in dados.get("tempos", []):
        rot = t.get("rotulo") or t.get("canonico")
        if not rot or not t.get("inicio") or not t.get("fim"):
            continue
        L += ["", "[[tempo]]",
              f"canonico  = {_txt(t.get('canonico') or chave_texto(rot))}",
              f"rotulo    = {_txt(rot)}",
              f"inicio    = {_txt(t['inicio'])}",
              f"fim       = {_txt(t['fim'])}"]
        if t.get("dias_uteis"):
            L.append("dias_uteis = true")
        if isinstance(t.get("meta"), (int, float)):
            L.append(f"meta      = {_escalar(t['meta'])}")
        if t.get("em_aberto"):
            L.append("em_aberto = true")

    for c in dados.get("cruzamentos", []):
        if not c.get("linhas") or not c.get("colunas"):
            continue
        L += ["", "[[cruzamento]]",
              f"rotulo  = {_txt(c.get('rotulo') or 'Cruzamento')}",
              f"linhas  = {_txt(c['linhas'])}",
              f"colunas = {_txt(c['colunas'])}"]

    q = dados.get("qualidade") or {}
    if q.get("duplicidade") or q.get("grafias_parecidas"):
        L += ["", "[qualidade]"]
        if q.get("duplicidade"):
            L.append(f"duplicidade = {_lista(q['duplicidade'])}")
        if q.get("grafias_parecidas"):
            L.append(f"grafias_parecidas = {_lista(q['grafias_parecidas'])}")

    for m in dados.get("metas", []):
        if not m.get("indicador") or m.get("alvo") is None:
            continue
        L += ["", "[[meta]]",
              f"indicador = {_txt(m['indicador'])}",
              f"alvo      = {_escalar(m['alvo'])}",
              f"sentido   = {_txt(m.get('sentido') or '>=')}"]

    return "\n".join(L) + "\n"


# ---- orquestração ----------------------------------------------------------
@dataclass
class ResultadoIA:
    modelo: Modelo
    toml: str
    enviado: dict                      # exatamente o que foi mandado à IA (transparência/LGPD)
    bruto: str = ""                    # resposta crua da IA
    json: dict = field(default_factory=dict)
    modelo_usado: str = ""             # o modelo de IA que respondeu (pode ser uma alternativa)


MAX_ALTERNATIVAS = 5   # sobrecarga costuma atingir só os modelos mais novos; os anteriores respondem


def _alternativas(cfg: ConfigIA, limite: int = MAX_ALTERNATIVAS) -> list[str]:
    """Outros modelos da mesma chave, na ordem de preferência (sem o atual). Vazio se não listar."""
    try:
        modelos = _listar_modelos_remotos(cfg)
    except ErroAPI:
        return []
    atual = cfg.modelo_efetivo()
    return [m for m in ordenar_modelos(cfg.dialeto, modelos) if m != atual][:limite]


def _chamar_com_alternativas(cfg: ConfigIA, sistema: str, instrucao: str,
                             aviso=None) -> tuple[str, str]:
    """Chama o modelo configurado (com 1 retentativa); se seguir sobrecarregado ou sem cota, percorre
    outros modelos da mesma chave com UMA tentativa cada (um 503 volta em <1s, então é barato).
    Devolve (texto, modelo que respondeu). Só desiste, com mensagem clara, quando todos falham."""
    principal = cfg.modelo_efetivo()
    try:
        return _chamar(cfg, sistema, instrucao, aviso, tentativas=2), principal
    except ErroAPI as e:
        if e.status not in TROCAR_MODELO:
            raise
        falhas = [f"{principal} (HTTP {e.status})"]
        ultimo = e
    for alt in _alternativas(cfg):
        if aviso:
            aviso(f"«{principal}» indisponível agora; tentando «{alt}»…")
        try:
            return _chamar(replace(cfg, modelo=alt), sistema, instrucao, aviso, tentativas=1), alt
        except ErroAPI as e:
            if e.status in (401, 403):      # chave sem permissão: não adianta trocar de modelo
                raise
            falhas.append(f"{alt} (HTTP {e.status or 'rede'})")
            ultimo = e
    raise ErroAPI("O provedor de IA está sobrecarregado agora (muita demanda). Isso costuma ser "
                  "temporário — tente de novo em alguns minutos.\n\nModelos tentados: "
                  + ", ".join(falhas) + ".", ultimo.status) from ultimo


def gerar(ds, cfg: ConfigIA, aviso=None) -> ResultadoIA:
    """Consulta a IA e devolve um Modelo pronto para aplicar. Levanta RuntimeError em falha.

    `aviso(texto)` (opcional) recebe mensagens de progresso — retentativas e troca de modelo.
    """
    ok, motivo = cfg.pronto()
    if not ok:
        raise RuntimeError(motivo)
    resumo = resumo_estrutura(ds, cfg)
    sistema, instrucao = montar_mensagens(resumo)
    bruto, usado = _chamar_com_alternativas(cfg, sistema, instrucao, aviso)
    dados = _extrair_json(bruto)
    if not dados.get("colunas"):
        raise RuntimeError("A IA não descreveu nenhuma coluna. Tente novamente ou revise o modelo da IA.")
    toml = json_para_toml(dados)
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
        f.write(toml)
        caminho = Path(f.name)
    try:
        modelo = carregar_modelo(caminho)   # reusa validação (tipos, papéis) do formato oficial
    finally:
        caminho.unlink(missing_ok=True)
    return ResultadoIA(modelo=modelo, toml=toml, enviado=resumo, bruto=bruto, json=dados,
                       modelo_usado=usado)
