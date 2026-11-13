"""Gera modelos `.toml` em `dominio/modelos/mv_*.toml` a partir de `config/mv_reports_catalogo.json`.

Regras:
- Nunca sobrescreve modelos curados existentes (usa prefixo `mv_`).
- Aplica `apenas_mapeadas = true` e exclui colunas PII diretas (LGPD: nome de paciente, CPF,
  RG, nascimento, carteira, endereço, telefone, e-mail, mãe/pai, CNS).
- Usa `nomes_mv.rotular()` + tipo Stimulsoft para inferir rótulo e tipo físico válido.
- Valida todos os `.toml` gerados com `carregar_modelo()`.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

from analise_planilha import config
from analise_planilha.cerebro import nomes_mv
from analise_planilha.modelo import carregar_modelo
from analise_planilha.normalizacao import sem_acento

PII_DIRETO = {
    "NM_PACIENTE", "PACIENTE", "NOME_PACIENTE", "NR_CPF", "CPF", "NR_RG", "RG",
    "NR_CARTEIRA", "CARTEIRA", "DT_NASCIMENTO", "DATA_NASCIMENTO", "NASCIMENTO",
    "ENDERECO", "DS_ENDERECO", "LOGRADOURO", "TELEFONE", "NR_FONE", "FONE",
    "CELULAR", "EMAIL", "NM_MAE", "NM_PAI", "CNS", "NR_CNS", "PIS", "CNH",
}

DOMINIO_PASTA = {
    "Atendimento / Internação / Leitos": "Atendimento Hospitalar",
    "Cirurgia / Centro Cirúrgico": "Centro Cirúrgico",
    "Farmácia / Estoque / Suprimentos": "Farmácia e Suprimentos",
    "Faturamento / Convênio / Glosa": "Faturamento",
    "Exames / Laboratório / Imagem": "Exames e Laboratório",
    "Prescrição / Enfermagem": "Prescrição e Enfermagem",
    "Outros / Geral": "MV — Geral",
}


def _slug(texto: str) -> str:
    s = sem_acento(texto).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:64] or "relatorio"


def _escapar_toml(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ").strip()


def _inferir_tipo_e_rotulo(nome: str, tipo_sti: str) -> tuple[str, str]:
    up = nome.upper().strip()
    rot_mv = nomes_mv.rotular(up)
    rotulo = rot_mv[0] if rot_mv else nome.replace("_", " ").title()
    tipo = rot_mv[1] if rot_mv else None

    if tipo is None:
        if "DateTime" in tipo_sti:
            tipo = "data_hora" if up.startswith(("DH_", "HR_", "HORA_")) else "data"
        elif "Boolean" in tipo_sti:
            tipo = "booleano"
        elif any(k in tipo_sti for k in ("Int32", "Int64", "Int16")):
            tipo = "identificador" if up.startswith(("CD_", "COD_", "NR_", "ID_", "SEQ_")) else "inteiro"
        elif any(k in tipo_sti for k in ("Double", "Decimal", "Single")):
            if any(k in up for k in ("VL_", "VALOR", "CUSTO", "PRECO", "TOTAL", "SALDO", "GLOSA")):
                tipo = "moeda"
            elif up.startswith(("CD_", "COD_", "NR_", "ID_")):
                tipo = "identificador"
            else:
                tipo = "decimal"
        elif any(k in up for k in ("SETOR", "CONVENIO", "PRESTADOR", "ESPECIALID", "TIPO", "STATUS", "UNID", "LEITO", "ORIGEM", "MOT_", "SEXO")):
            tipo = "categorico"
        else:
            tipo = "texto_livre"
    return rotulo, tipo


def gerar() -> tuple[int, int]:
    catalogo = json.loads(pathlib.Path("config/mv_reports_catalogo.json").read_text(encoding="utf-8"))
    pasta_modelos = config.PASTA_MODELOS
    pasta_modelos.mkdir(parents=True, exist_ok=True)

    gerados = 0
    invalidos = 0
    usados_slug: set[str] = {p.stem for p in pasta_modelos.glob("*.toml") if not p.stem.startswith("mv_")}

    for rep in catalogo["relatorios"]:
        cols_filtradas = [c for c in rep["colunas"] if c["nome"].upper().strip() not in PII_DIRETO]
        if len(cols_filtradas) < 2:
            continue

        base_slug = f"mv_{_slug(rep['report_name'])}"
        slug = base_slug
        if slug in usados_slug:
            slug = f"{base_slug}_{rep['report_id']}"
        usados_slug.add(slug)

        usados_can: set[str] = set()
        linhas_col: list[str] = []
        data_base = ""
        dimensoes: list[str] = []
        tem_pac = False
        tem_atd = False

        for c in cols_filtradas:
            orig = c["nome"].strip()
            up = orig.upper()
            rotulo, tipo = _inferir_tipo_e_rotulo(orig, c.get("tipo_stimulsoft", ""))
            can = _slug(orig)
            if can in usados_can:
                i = 2
                while f"{can}_{i}" in usados_can:
                    i += 1
                can = f"{can}_{i}"
            usados_can.add(can)

            papel = ""
            if up == "CD_PACIENTE":
                tem_pac = True
                papel = "entidade"
                rotulo = "Paciente (código)"
                tipo = "identificador"
            elif up == "CD_ATENDIMENTO":
                tem_atd = True
                tipo = "identificador"

            if not data_base and tipo in ("data", "data_hora"):
                data_base = can
            if tipo == "categorico" and len(dimensoes) < 6:
                dimensoes.append(can)

            bloco = [
                "[[coluna]]",
                f'canonico = "{can}"',
                f'rotulo = "{_escapar_toml(rotulo)}"',
                f'tipo = "{tipo}"',
            ]
            if papel:
                bloco.append(f'papel = "{papel}"')
            bloco.append(f'sinonimos = ["{_escapar_toml(orig)}"]')
            linhas_col.append("\n".join(bloco))

        ent, ent_pl = (
            ("paciente", "pacientes") if tem_pac
            else ("atendimento", "atendimentos") if tem_atd
            else ("registro", "registros")
        )
        pasta = DOMINIO_PASTA.get(rep["dominio"], "MV — Geral")
        nome_rel = _escapar_toml(rep["report_name"])

        conteudo = [
            f"# Gerado automaticamente a partir do MV REMWEB.REPORT (ID {rep['report_id']} / {rep['module_id']})",
            f'nome = "{nome_rel}"',
            f'pasta = "{pasta}"',
            "apenas_mapeadas = true",
            "",
            "[analise]",
            f'entidade = "{ent}"',
            f'entidade_plural = "{ent_pl}"',
        ]
        if data_base:
            conteudo.append(f'data_base = "{data_base}"')
        if dimensoes:
            dims_str = ", ".join(f'"{d}"' for d in dimensoes)
            conteudo.append(f"dimensoes = [{dims_str}]")
        conteudo.append("")
        conteudo.extend(linhas_col)
        conteudo.append("")

        destino = pasta_modelos / f"{slug}.toml"
        destino.write_text("\n".join(conteudo), encoding="utf-8")
        try:
            carregar_modelo(destino)
            gerados += 1
        except Exception as exc:
            print(f"Inválido {destino.name}: {exc}", file=sys.stderr)
            destino.unlink(missing_ok=True)
            invalidos += 1

    return gerados, invalidos


if __name__ == "__main__":
    g, inv = gerar()
    print(f"Modelos gerados e validados: {g} | Inválidos removidos: {inv}")
