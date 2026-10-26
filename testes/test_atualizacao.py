"""Atualizador do .exe — offline: a rede é simulada; o script de troca roda de verdade (Windows)."""
import hashlib
import io
import json
import subprocess
import sys
import zipfile

import pytest

from analise_planilha import atualizacao, config


def _rede(respostas: dict):
    """Substitui atualizacao._abrir: cada URL devolve os bytes dados (ou levanta, se for exceção)."""
    def abrir(url, timeout, api=False):
        r = respostas[url]
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(r)
    return abrir


def _release(*nomes) -> bytes:
    return json.dumps({"tag_name": "v0.2.0", "body": "Novidades da versão",
                       "assets": [{"name": n, "browser_download_url": f"https://exemplo/{n}"} for n in nomes]}).encode()


def test_comparacao_de_versoes():
    assert atualizacao.eh_mais_nova("0.2.0", "0.1.0")
    assert atualizacao.eh_mais_nova("v0.10.0", "0.9.1")          # numérico, não alfabético
    assert not atualizacao.eh_mais_nova("v0.1.0", "0.1.0")
    assert not atualizacao.eh_mais_nova("0.0.9", "0.1.0")
    assert not atualizacao.eh_mais_nova("beta", "0.1.0")          # tag fora do padrão nunca atualiza


def test_so_verifica_no_executavel_e_respeita_config(tmp_path, monkeypatch):
    assert not atualizacao.verificacao_ativa()                    # desenvolvimento: nunca consulta
    monkeypatch.setattr(config, "EMPACOTADO", True)
    monkeypatch.setattr(atualizacao, "ARQ_CONFIG", tmp_path / "atualizacao.toml")
    assert atualizacao.verificacao_ativa()                        # sem arquivo: ligado
    (tmp_path / "atualizacao.toml").write_text("verificar = false\n", encoding="utf-8")
    assert not atualizacao.verificacao_ativa()


def test_buscar_ultima(monkeypatch):
    monkeypatch.setattr(atualizacao, "_abrir", _rede({atualizacao.URL_ULTIMA: _release(
        "AnalisePlanilhas-v0.2.0.zip", "AnalisePlanilhas-v0.2.0.zip.sha256")}))
    v = atualizacao.buscar_ultima()
    assert v.versao == "0.2.0" and v.notas == "Novidades da versão"
    assert v.url_zip.endswith(".zip") and v.url_sha256.endswith(".zip.sha256")


def test_release_sem_sha256_e_ignorada(monkeypatch):
    monkeypatch.setattr(atualizacao, "_abrir", _rede({atualizacao.URL_ULTIMA: _release("AnalisePlanilhas-v0.2.0.zip")}))
    assert atualizacao.buscar_ultima() is None


def test_sem_rede_vira_erro_tratavel(monkeypatch):
    monkeypatch.setattr(atualizacao, "_abrir", _rede({atualizacao.URL_ULTIMA: OSError("sem rede")}))
    with pytest.raises(atualizacao.ErroAtualizacao, match="consultar"):
        atualizacao.buscar_ultima()


def test_baixar_confere_sha256(tmp_path, monkeypatch):
    pacote = b"conteudo do zip"
    v = atualizacao.Versao("0.2.0", "https://exemplo/a.zip", "https://exemplo/a.zip.sha256")
    certo = ("﻿" + hashlib.sha256(pacote).hexdigest() + "  a.zip\n").encode("utf-8")   # com BOM
    monkeypatch.setattr(atualizacao, "_abrir", _rede({v.url_zip: pacote, v.url_sha256: certo}))
    assert atualizacao.baixar(v, tmp_path).read_bytes() == pacote

    monkeypatch.setattr(atualizacao, "_abrir", _rede({v.url_zip: b"adulterado", v.url_sha256: certo}))
    with pytest.raises(atualizacao.ErroAtualizacao, match="SHA-256"):
        atualizacao.baixar(v, tmp_path)
    assert not (tmp_path / "atualizacao.zip").exists()           # nada fica para trás


def _zip(caminho, arquivos: dict):
    with zipfile.ZipFile(caminho, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)


def test_pacote_sem_o_executavel_e_recusado(tmp_path):
    _zip(tmp_path / "atualizacao.zip", {"leia-me.txt": "x"})
    with pytest.raises(atualizacao.ErroAtualizacao, match="não contém"):
        atualizacao.preparar_instalacao(tmp_path / "atualizacao.zip", tmp_path / "app", tmp_path / "app" / "Programa.exe")


@pytest.mark.skipif(sys.platform != "win32", reason="script de troca é do Windows (cmd/robocopy)")
def test_script_troca_programa_e_preserva_dados_e_config(tmp_path):
    raiz = tmp_path / "Análise instalada"                         # acento no caminho, como na máquina real
    for rel, txt in {"Programa.exe": "velho", "lib.dll": "velho",
                     "config/modelos/existente.toml": "editado pelo usuário",
                     "dados/HUNF/planilha.xlsx": "dados reais", "saida/relatorio.html": "relatório"}.items():
        (raiz / rel).parent.mkdir(parents=True, exist_ok=True)
        (raiz / rel).write_text(txt, encoding="utf-8")
    temp = tmp_path / "temp"
    temp.mkdir()
    _zip(temp / "atualizacao.zip", {"Programa.exe": "novo", "lib.dll": "novo", "templates/relatorio.html.j2": "novo",
                                     "config/modelos/existente.toml": "versão de fábrica",
                                     "config/modelos/novo.toml": "modelo novo",
                                     "dados/intruso.csv": "não deve entrar", "saida/intruso.html": "não deve entrar"})
    script, amb = atualizacao.preparar_instalacao(temp / "atualizacao.zip", raiz, raiz / "Programa.exe")
    assert script.read_bytes().isascii()                          # caminhos chegam por variável de ambiente
    morto = subprocess.Popen(["cmd", "/c", "exit 0"])             # PID de um processo que já terminou
    morto.wait()
    amb.update(PID_APP=str(morto.pid), REABRIR="0")
    subprocess.run(["cmd", "/c", str(script)], env=amb, timeout=120, check=False)

    ler = lambda rel: (raiz / rel).read_text(encoding="utf-8")   # noqa: E731
    assert ler("Programa.exe") == "novo" and ler("lib.dll") == "novo" and ler("templates/relatorio.html.j2") == "novo"
    assert ler("config/modelos/existente.toml") == "editado pelo usuário"   # editado não é sobrescrito
    assert ler("config/modelos/novo.toml") == "modelo novo"                 # modelo novo entra
    assert ler("dados/HUNF/planilha.xlsx") == "dados reais" and ler("saida/relatorio.html") == "relatório"
    assert not (raiz / "dados/intruso.csv").exists() and not (raiz / "saida/intruso.html").exists()
    assert (raiz / "atualizacao.log").exists()
    assert not script.parent.exists() or not script.exists()      # o script apaga a pasta temporária
