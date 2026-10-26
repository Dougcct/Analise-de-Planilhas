"""Validação de arquivo enviado (DOCS/18 §4): extensão, tamanho, assinatura real e proteção contra
zip bomb. Puro e testável — não toca em disco nem em banco."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

EXT_OK = {".xlsx", ".ods", ".csv", ".tsv", ".txt"}   # .xlsm fica de fora (macros); .xls legado idem
MAX_BYTES = 25 * 1024 * 1024          # arquivo enviado
MAX_DESCOMP = 300 * 1024 * 1024       # soma descompactada (xlsx/ods são ZIP)
MAX_RAZAO = 100                       # razão de compressão suspeita
MAX_ENTRADAS = 5000


class ErroArquivo(ValueError):
    pass


def validar(nome: str, conteudo: bytes) -> None:
    """Levanta ErroArquivo se o arquivo não puder ser aceito; devolve None se estiver OK."""
    ext = Path(nome).suffix.lower()
    if ext not in EXT_OK:
        raise ErroArquivo(f"Extensão não aceita: {ext or '(sem extensão)'}. Use .xlsx, .ods ou .csv.")
    if not conteudo:
        raise ErroArquivo("Arquivo vazio.")
    if len(conteudo) > MAX_BYTES:
        raise ErroArquivo(f"Arquivo acima do limite de {MAX_BYTES // (1024 * 1024)} MB.")
    if ext in (".csv", ".tsv", ".txt"):
        _validar_texto(conteudo)
    else:
        _validar_zip(conteudo)


def _validar_texto(conteudo: bytes) -> None:
    if b"\x00" in conteudo[:200_000]:
        raise ErroArquivo("Arquivo de texto com bytes nulos — não parece um CSV.")


def _validar_zip(conteudo: bytes) -> None:
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as e:
        raise ErroArquivo("Arquivo .xlsx/.ods inválido (não é um pacote ZIP).") from e
    infos = z.infolist()
    if not infos:
        raise ErroArquivo("Pacote vazio.")
    if len(infos) > MAX_ENTRADAS:
        raise ErroArquivo("Pacote com arquivos demais (suspeito).")
    total = sum(i.file_size for i in infos)
    if total > MAX_DESCOMP:
        raise ErroArquivo("Conteúdo descompactado grande demais (possível zip bomb).")
    if len(conteudo) and total / len(conteudo) > MAX_RAZAO:
        raise ErroArquivo("Razão de compressão suspeita (possível zip bomb).")
