"""PONTO DE ENTRADA — Análise de Planilhas.

Interface local em PyQt6. Toda a lógica de análise vive em `src/analise_planilha`.

Uso:
    python main.py                # abre a interface
    python main.py --autoteste    # diagnóstico sem abrir janela (usado no build)

O `--autoteste` confere, sem gerar nada para o usuário, se o pacote tem tudo o que precisa
(templates, ícone, dependências, pasta gravável) e exercita a análise de ponta a ponta. É o
primeiro diagnóstico a pedir quando algo falha na máquina do cliente. Grava `autoteste.txt`.
"""
import sys
from pathlib import Path

# src/ e app/ no caminho de importação, tanto em desenvolvimento quanto compilado
# (o build declara o mesmo em PYTHONPATH para a análise estática do Nuitka).
RAIZ = Path(__file__).resolve().parent
for sub in ("src", "app"):
    if (RAIZ / sub).exists():
        sys.path.insert(0, str(RAIZ / sub))


def _pipeline_sintetico() -> tuple[bool, str]:
    """Análise ponta a ponta numa planilha sintética (independe de haver dados na máquina)."""
    import io

    import numpy as np
    import pandas as pd

    from analise_planilha import relatorio_html, servico

    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "Nº": range(1, 61),
        "Data": pd.date_range("2026-01-01", periods=60).strftime("%d/%m/%Y"),
        "Cidade": rng.choice(["A", "B", "C"], 60),
        "Valor": [f"{v:.2f}".replace(".", ",") for v in rng.uniform(10, 500, 60)],
    })
    ds = servico.carregar(io.BytesIO(df.to_csv(sep=";", index=False).encode("utf-8")), "autoteste.csv")
    a = servico.analisar(ds, metas_cfg={})
    html = relatorio_html.montar_html(a, "Autoteste")
    tipo_no = ds.esquema.tipo_de("Nº")
    ok = a.linhas == 60 and len(a.paineis) >= 3 and tipo_no == "identificador" and "<html" in html
    return ok, f"{a.linhas} linhas, {len(a.paineis)} painéis, Nº→{tipo_no}"


def autoteste() -> int:
    """Confere o ambiente/pacote sem abrir janela. Grava autoteste.txt ao lado do executável."""
    linhas: list[str] = []
    falhas = 0

    def checar(descricao, condicao, detalhe=""):
        nonlocal falhas
        ok = bool(condicao)
        falhas += not ok
        linhas.append(f"{'[ok]' if ok else '[X ]'} {descricao}{(' — ' + detalhe) if detalhe and not ok else ''}")

    from analise_planilha import __version__, config
    compilado = getattr(sys, "frozen", False) or "__compiled__" in globals()
    linhas.append(f"Autoteste — {config.NOME_APLICACAO} v{__version__}")
    linhas.append(f"Empacotado: {'sim' if compilado else 'não (desenvolvimento)'}")
    linhas.append(f"RAIZ:  {config.RAIZ}")
    linhas.append("-" * 60)

    # Recursos embutidos
    checar("Template do relatório", (config.PASTA_TEMPLATES / "relatorio.html.j2").exists())
    checar("Ícone da aplicação", config.ICONE.exists())

    # Dependências
    for nome, modulo in (("Análise (pandas)", "pandas"), ("Relatório (jinja2, markupsafe)", "jinja2"),
                         ("Leitura .xlsx (openpyxl)", "openpyxl"), ("Leitura .ods (odfpy)", "odf"),
                         ("Interface gráfica (PyQt6)", "PyQt6.QtWidgets")):
        try:
            __import__(modulo)
            checar(nome, True)
        except Exception as exc:
            checar(nome, False, str(exc))

    # Pastas graváveis
    try:
        config.PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
        teste = config.PASTA_SAIDA / ".escrita_teste"
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
        checar("Escrita na pasta de saída", True)
    except Exception as exc:
        checar("Escrita na pasta de saída", False, str(exc))

    # Pipeline: sintético (sempre) + cada relatório que tiver planilha na sua pasta
    try:
        ok, det = _pipeline_sintetico()
        checar(f"Análise ponta a ponta (sintética: {det})", ok, det)
    except Exception as exc:
        checar("Análise ponta a ponta (sintética)", False, str(exc))
    try:
        from analise_planilha import leitura, servico
        from analise_planilha.modelo import carregar_modelo, listar_modelos
        relatorios = [(nome, carregar_modelo(c)) for nome, c in listar_modelos().items()] + [("Sem modelo", None)]
        for nome, modelo in relatorios:
            pasta = config.pasta_relatorio(modelo.subpasta if modelo else None)
            arqs = config.listar_arquivos(pasta)
            if modelo and modelo.aba:   # navegação por arquivo: testa 1 arquivo que tenha a aba do relatório
                arqs = [a for a in arqs if modelo.aba in leitura.listar_abas(a.read_bytes(), a.name)] or arqs
            if not arqs:
                linhas.append(f"[--] {nome}: sem planilha em {pasta.relative_to(config.RAIZ)}\\")
                continue
            p = arqs[0]
            ds = servico.carregar(p.read_bytes(), p.name, aba=(modelo.aba if modelo else None), modelo=modelo)
            a = servico.analisar(ds)
            checar(f"Relatório '{nome}' ({a.linhas} registros, arquivo {p.name})", a.linhas > 0)
    except Exception as exc:
        checar("Relatórios com planilha", False, f"{type(exc).__name__}: {exc}")

    linhas.append("-" * 60)
    linhas.append("RESULTADO: " + ("TUDO OK" if falhas == 0 else f"{falhas} FALHA(S)"))
    relatorio = "\n".join(linhas)
    if hasattr(sys.stdout, "reconfigure"):   # console cp1252 não tem «→»: troca por «?» em vez de quebrar
        sys.stdout.reconfigure(errors="replace")
    print(relatorio)
    try:
        (config.RAIZ / "autoteste.txt").write_text(relatorio, encoding="utf-8")
    except Exception:
        pass
    return 1 if falhas else 0


def main() -> int:
    if "--autoteste" in sys.argv:
        return autoteste()
    from janela import executar
    return executar()


if __name__ == "__main__":
    raise SystemExit(main())
