"""Importador e curador oficial da base de KPIs do CeosGo para o sistema (Etapa 3 / v3).

Lê um CSV exportado do CeosGo (`Título do indicador;Unidade;Polaridade / Sentido;Fórmula ou campos`),
higieniza os textos, aplica a curadoria universal de polaridade (>= maior melhor, <= menor melhor,
neutro), extrai fórmulas estruturadas (numerador/denominador/fator) e classifica os setores
assistenciais/operacionais, gravando em `config/kpis_ceosgo.json`.

Uso:
    python scripts/importar_kpis_ceosgo.py
    python scripts/importar_kpis_ceosgo.py --entrada "A:/Relatórios/KPI base.csv"
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = RAIZ / "config" / "kpis_ceosgo.json"
ENTRADA_PADRAO = Path(r"A:\Relatórios\KPI base.csv")

# Padrões universais de polaridade na saúde / gestão hospitalar
TERMOS_MENOR_MELHOR = (
    "isc", "iscs", "infeccao", "infec", "obito", "mortalidade", "letalidade",
    "extubacao acidental", "extubacoes acidentais", "lesao por pressao", "ulcera",
    "acidente de trabalho", "acidentes de trabalho", "acidentes ocorridos",
    "evento adverso", "eventos adversos", "queda", "quedas", "glosa", "glosas",
    "reinternacao", "retorno para internacao", "tempo de espera", "permanencia",
    "atraso", "alta apos", "absenteismo", "turnover", "rotatividade", "custo",
    "gasto", "despesa", "nao trabalhadas", "cancelamento", "suspensao cirurgica",
    "erro", "nao conformidade", "flebite", "pav", "ipcs", "itu",
)

TERMOS_MAIOR_MELHOR_EXCECAO = (
    "adequado", "adequados", "adequadedados", "adequacao", "adesao", "conformidade",
    "acolhimento com classificacao", "classificacao de risco", "higiene das maos",
    "taxa de sucesso", "sobrevida", "eficacia", "satisfacao", "resolutividade",
    "cirurgia segura",
)

SETORES_REGRAS: dict[str, tuple[str, ...]] = {
    "CCIH / Segurança do Paciente": (
        "isc", "infec", "bundle", "ipcs", "itu", "pav", "extub", "queda",
        "lesao por pressao", "evento adverso", "higiene", "flebite", "cirurgia segura",
    ),
    "Internação / Leitos / Permanência": (
        "paciente-dia", "pacientes-dia", "leito", "permanencia", "ocupacao",
        "saida", "internac", "alta apos", "retorno para internacao",
    ),
    "Centro Cirúrgico": (
        "cirurg", "asa", "cesariana", "parto", "anestes", "centro cirurgico",
    ),
    "Urgência / Emergência (PA)": (
        "urgencia", "emergencia", "classificacao de risco", "pronto atendimento",
        "tempo de espera", "oriundas do setor de pa",
    ),
    "Enfermagem / RH Assistencial": (
        "enfermagem", "enfermeiro", "tecnico de enfermagem", "colaborador",
        "horas trabalhadas", "horas nao trabalhadas", "horas potenciais", "acidente de trabalho",
    ),
    "Oncologia / Terapia Antineoplásica": (
        "oncolog", "antineoplas", "quimioterap", "hematolog", "prostata",
        "mama", "terapia antineoplasica",
    ),
    "Financeiro / Custos / Faturamento / OPME": (
        "custo", "receita", "fatur", "glosa", "opme", "gasto", "orcado", "realizado",
    ),
}

UNIDADE_MOTOR = {
    "QUANTIDADE": "inteiro",
    "PERCENTUAL": "percentual",
    "MOEDA": "moeda",
    "RESULTADO": "decimal",
}


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _chave_texto(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _sem_acento(texto).lower())


def _limpar_texto(texto) -> str:
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    s = str(texto)
    if s.lower() == "nan":
        return ""
    s = html.unescape(s).replace("¿", "–")
    return re.sub(r"\s+", " ", s).strip()


def _slugify(texto: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "_", _sem_acento(texto).lower()).strip("_")
    return t[:80]


def classificar_sentido(titulo: str, sentido_orig: str) -> tuple[str, bool, str]:
    """Determina o sentido padronizado (`>=`, `<=`, `neutro`) aplicando a curadoria universal."""
    t_norm = _sem_acento(titulo).lower()

    if "1" in sentido_orig or "maior" in sentido_orig.lower():
        orig = ">="
    elif "3" in sentido_orig or "menor" in sentido_orig.lower():
        orig = "<="
    else:
        orig = "neutro"

    if any(exc in t_norm for exc in TERMOS_MAIOR_MELHOR_EXCECAO):
        if orig != ">=":
            return ">=", True, "Exceção positiva universal (adesão/adequação/conformidade)"
        return ">=", False, ""

    for neg in TERMOS_MENOR_MELHOR:
        if re.search(rf"\b{re.escape(neg)}", t_norm):
            if neg == "custo" and "receita" in t_norm:
                continue
            if orig != "<=":
                return "<=", True, f"Padrão universal menor-melhor (termo '{neg}')"
            return "<=", False, ""

    return orig, False, ""


def classificar_setores(titulo: str, formula: str) -> list[str]:
    texto = _sem_acento(f"{titulo} {formula}").lower()
    encontrados = [
        setor
        for setor, kws in SETORES_REGRAS.items()
        if any(re.search(rf"\b{re.escape(kw)}", texto) for kw in kws)
    ]
    return encontrados or ["Geral / Outros"]


def extrair_formula(formula: str, unidade: str) -> dict | None:
    """Extrai numerador, denominador e fator multiplicador quando o texto descreve uma razão."""
    if not formula:
        return None
    f_norm = _sem_acento(formula).upper()

    m_div = re.search(
        r"F[ÓO]RMULA\s*:\s*\(?([^/()]+)\s*/\s*([^/()]+)\)?\s*(?:[X*]\s*(\d+))?",
        formula,
        re.IGNORECASE,
    )
    if m_div:
        return {
            "tipo": "razao",
            "numerador": _limpar_texto(m_div.group(1)),
            "denominador": _limpar_texto(m_div.group(2)),
            "fator": int(m_div.group(3)) if m_div.group(3) else (100 if unidade == "PERCENTUAL" else 1),
            "origem_extracao": "formula_explicita",
        }

    m_txt = re.search(
        r"([^.:;]+?)\s+DIVIDID[OA]\s+PEL[OA]\s+([^.:;]+?)(?:\s+MULTIPLICAD[OA]\s+POR\s+(\d+))?(?:[.;]|$)",
        f_norm,
    )
    if m_txt:
        return {
            "tipo": "razao",
            "numerador": m_txt.group(1).strip().title(),
            "denominador": m_txt.group(2).strip().title(),
            "fator": int(m_txt.group(3)) if m_txt.group(3) else (100 if unidade == "PERCENTUAL" else 1),
            "origem_extracao": "texto_divisao",
        }

    m_rel = re.search(
        r"RELACAO(?:\s+PERCENTUAL)?\s+ENTRE\s+(?:O\s+|A\s+)?(.+?)\s+E\s+(?:O\s+|A\s+)?([^.:;]+)",
        f_norm,
    )
    if m_rel:
        return {
            "tipo": "razao",
            "numerador": m_rel.group(1).strip().title(),
            "denominador": m_rel.group(2).strip().title(),
            "fator": 100 if ("PERCENTUAL" in f_norm or unidade == "PERCENTUAL") else 1,
            "origem_extracao": "texto_relacao",
        }

    return None


def eh_variavel_componente(titulo: str, unidade: str, formula_struct: dict | None) -> bool:
    if unidade != "QUANTIDADE" or formula_struct is not None:
        return False
    t = _sem_acento(titulo).lower()
    return t.startswith(("numero de ", "numero total ", "somatorio ", "total de ", "horas "))


def importar(entrada: Path, saida: Path) -> dict:
    """Lê o CSV do CeosGo, cura os registros e grava o catálogo JSON."""
    try:
        df = pd.read_csv(entrada, sep=";", encoding="latin1")
    except UnicodeDecodeError:
        df = pd.read_csv(entrada, sep=";", encoding="utf-8")

    df.columns = [c.strip() for c in df.columns]
    catalogo: list[dict] = []
    vistas: set[str] = set()

    for _, row in df.iterrows():
        titulo = _limpar_texto(row.get("Título do indicador"))
        if not titulo or titulo.upper() == "NÃO INFORMADO":
            continue
        assinatura = _chave_texto(titulo)
        if not assinatura or assinatura in vistas:
            continue
        vistas.add(assinatura)

        unidade = _limpar_texto(row.get("Unidade")) or "NÃO INFORMADO"
        sentido_orig = _limpar_texto(row.get("Polaridade / Sentido"))
        formula_txt = _limpar_texto(row.get("Fórmula ou campos"))

        sentido, corrigido, motivo = classificar_sentido(titulo, sentido_orig)
        setores = classificar_setores(titulo, formula_txt)
        formula_struct = extrair_formula(formula_txt, unidade)
        componente = eh_variavel_componente(titulo, unidade, formula_struct)

        catalogo.append({
            "id": _slugify(titulo),
            "titulo": titulo,
            "assinatura": assinatura,
            "unidade": unidade,
            "tipo_motor": UNIDADE_MOTOR.get(unidade, "decimal"),
            "sentido": sentido,
            "sentido_original": sentido_orig,
            "sentido_corrigido": corrigido,
            "motivo_correcao": motivo,
            "setores": setores,
            "eh_componente": componente,
            "formula": formula_struct,
            "descricao": formula_txt,
        })

    payload = {"versao": 1, "total": len(catalogo), "kpis": catalogo}
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa e cura KPIs do CeosGo para config/kpis_ceosgo.json")
    parser.add_argument("--entrada", type=Path, default=ENTRADA_PADRAO, help="Caminho do KPI base.csv")
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO, help="Caminho do JSON de saída")
    args = parser.parse_args()

    if not args.entrada.exists():
        print(f"Erro: arquivo não encontrado em {args.entrada}", file=sys.stderr)
        return 1

    payload = importar(args.entrada, args.saida)
    kpis = payload["kpis"]
    print(f"Catálogo gerado em: {args.saida}")
    print(f"Total de KPIs únicos: {len(kpis)}")
    print(f"Polaridades corrigidas: {sum(1 for k in kpis if k['sentido_corrigido'])}")
    print(f"Fórmulas extraídas: {sum(1 for k in kpis if k['formula'])}")
    print(f"Componentes de coleta: {sum(1 for k in kpis if k['eh_componente'])}")
    print("Sentidos:", dict(Counter(k["sentido"] for k in kpis)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
