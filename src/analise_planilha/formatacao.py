"""Formatação de números em pt-BR (1.234,56)."""
import math


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def fmt_int(v) -> str:
    return f"{int(round(v)):,}".replace(",", ".") if _ok(v) else "—"


def fmt_dec(v, casas: int = 2) -> str:
    if not _ok(v):
        return "—"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(v, casas: int = 1) -> str:
    """Recebe fração (0.253) e devolve '25,3%'."""
    return f"{fmt_dec(v * 100, casas)}%" if _ok(v) else "—"


def fmt_moeda(v) -> str:
    return f"R$ {fmt_dec(v, 2)}" if _ok(v) else "—"


def formatar(v, formato: str | None) -> str:
    """Valor cru → texto pt-BR segundo o formato do painel (int | dec | pct | moeda | dias)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    try:
        if v != v:  # pd.NA / NaN de tipos estendidos
            return "—"
    except TypeError:
        return "—"
    if formato == "int":
        return fmt_int(v)
    if formato == "dec":
        return fmt_dec(v)
    if formato == "pct":
        return fmt_pct(v)
    if formato == "moeda":
        return fmt_moeda(v)
    if formato == "dias":
        return fmt_dec(v, 0 if float(v).is_integer() else 1)
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    return str(v)


def formatar_tabela(df, formatos: dict[str, str]):
    """Cópia da tabela com as colunas convertidas para texto pt-BR (para HTML/exportação)."""
    saida = df.copy().astype(object)
    for col in saida.columns:
        saida[col] = [formatar(v, formatos.get(col)) for v in df[col]]
    return saida


def fmt_compacto(v) -> str:
    """1.234.567 -> '1,23 mi' para KPIs."""
    if not _ok(v):
        return "—"
    a = abs(v)
    if a >= 1e9:
        return f"{fmt_dec(v / 1e9)} bi"
    if a >= 1e6:
        return f"{fmt_dec(v / 1e6)} mi"
    if a >= 1e4:
        return f"{fmt_dec(v / 1e3, 1)} mil"
    return fmt_dec(v, 0 if float(v).is_integer() else 2)
