"""Geração do relatório pela linha de comando (útil para agendamento/RPA).

Mesmo padrão do projeto Garantia de Atendimento: lê as planilhas da pasta do relatório
(dados/<pasta do modelo>/), aplica filtros e grava o HTML em saida/.

Exemplos:
    python gerar_relatorio.py --listar
    python gerar_relatorio.py --relatorio "Contas Convênio"
    python gerar_relatorio.py --relatorio "Contas Convênio" --anonimizar
    python gerar_relatorio.py --relatorio "Contas Convênio" --dim "Convênio=AMIL" --dim "Ano=2026"
    python gerar_relatorio.py --inicio 2026-07-01 --fim 2026-07-31      # "Sem modelo" (dados/entrada/)
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from analise_planilha import __version__, config, relatorio_html, servico  # noqa: E402
from analise_planilha.modelo import carregar_modelo, listar_modelos  # noqa: E402
from analise_planilha.modelos import Filtros  # noqa: E402
from analise_planilha.normalizacao import chave_texto  # noqa: E402

SEM_MODELO = "Sem modelo"
FMT_TIPO = {"moeda": "moeda", "percentual": "pct", "inteiro": "int", "decimal": "dec"}


def main() -> int:
    p = argparse.ArgumentParser(description=f"Relatório — {config.NOME_APLICACAO} v{__version__}")
    p.add_argument("--relatorio", default=SEM_MODELO, help='nome do relatório (modelo); padrão: "Sem modelo"')
    p.add_argument("--listar", action="store_true", help="lista os relatórios e suas pastas, e sai")
    p.add_argument("--saida", type=Path, default=None, help="pasta de destino do relatório")
    p.add_argument("--inicio", type=date.fromisoformat, help="data inicial AAAA-MM-DD")
    p.add_argument("--fim", type=date.fromisoformat, help="data final AAAA-MM-DD")
    p.add_argument("--data-base", default=None, help="coluna de data do período (padrão: a principal)")
    p.add_argument("--dim", action="append", default=[], metavar="COLUNA=VALOR",
                   help="filtro por dimensão, repetível (ex.: --dim \"Convênio=AMIL\")")
    p.add_argument("--anonimizar", action="store_true", help="mascara nomes (iniciais)")
    args = p.parse_args()

    modelos = listar_modelos()
    if args.listar:
        for nome, caminho in modelos.items():
            m = carregar_modelo(caminho)
            print(f"{nome:40s} dados\\{m.subpasta}\\  ({len(config.listar_arquivos(config.pasta_relatorio(m.subpasta)))} arquivo(s))")
        print(f"{SEM_MODELO:40s} dados\\entrada\\  ({len(config.listar_arquivos(config.PASTA_ENTRADA))} arquivo(s))")
        return 0

    modelo = None
    if args.relatorio != SEM_MODELO:
        if args.relatorio not in modelos:
            print(f"Relatório «{args.relatorio}» não encontrado. Use --listar.")
            return 2
        modelo = carregar_modelo(modelos[args.relatorio])
    pasta = config.pasta_relatorio(modelo.subpasta if modelo else None)
    arquivos = config.listar_arquivos(pasta)
    if not arquivos:
        print(f"Nenhuma planilha em {pasta}")
        return 1

    ds = servico.carregar_arquivos(arquivos, modelo=modelo)
    selecao: dict[str, list] = {}
    for item in args.dim:
        if "=" in item:
            col, val = item.split("=", 1)
            col, val = col.strip(), val.strip()
            if col in ds.df.columns:   # compara pelo texto, aceitando o valor como está na base
                casam = [v for v in ds.df[col].dropna().unique() if str(v).upper() == val.upper()]
                selecao.setdefault(col, []).extend(casam or [val])
    periodo = None
    if args.inicio or args.fim:
        col = args.data_base or servico.coluna_periodo(ds)
        datas = ds.df[col].dropna() if col in ds.df.columns else []
        ini = args.inicio or (datas.min().date() if len(datas) else date.min)
        fim = args.fim or (datas.max().date() if len(datas) else date.max)
        periodo = (ini.isoformat(), fim.isoformat())
    filtros = Filtros(periodo=periodo, selecao=selecao, anonimizar=args.anonimizar, coluna_data=args.data_base)

    analise = servico.analisar(ds, filtros)
    base = servico.visiveis(servico.aplicar_filtros(ds, filtros)).reset_index(drop=True)
    fmt = {c.nome: FMT_TIPO[c.tipo] for c in ds.esquema.colunas if c.tipo in FMT_TIPO}
    destino = None
    if args.saida:
        args.saida.mkdir(parents=True, exist_ok=True)
        destino = args.saida / f"relatorio_{chave_texto(args.relatorio) or 'planilhas'}_{date.today():%Y%m%d}.html"
    caminho = relatorio_html.gerar(analise, args.relatorio, destino=destino, base=base, formatos_base=fmt,
                                   prefixo=f"relatorio_{chave_texto(args.relatorio) or 'planilhas'}",
                                   ds=ds, filtros=filtros)
    ocorr = 0 if ds.problemas is None else len(ds.problemas)
    print(f"[{args.relatorio}] {len(ds.df)} registros lidos de {len(arquivos)} arquivo(s) · "
          f"{analise.linhas} no recorte · {ocorr} ocorrências de qualidade")
    print("Relatório:", caminho)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
