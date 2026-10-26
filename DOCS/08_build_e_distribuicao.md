# 08 · Build e distribuição (.exe)

> Esta etapa fica para a **finalização** do projeto. Durante o desenvolvimento, use `python main.py`.

## Por que Nuitka + PyQt6

Mesmo padrão do projeto de referência da organização. O Nuitka traduz o Python para C e compila para
binário nativo (dificulta a engenharia reversa). O PyQt6 dá uma janela desktop nativa, sem servidor web
embutido — por isso os gráficos ficam no relatório HTML e não dentro da janela (mantém o `.exe` leve).

## Pré-requisito: compilador C (MSVC)

Sem o MSVC, o Nuitka baixa um compilador alternativo (muito mais lento). Instalar (PowerShell como admin):

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --override ^
  "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

Confirme no log do build: `Backend C compiler: cl (cl 14.3)` (correto) vs. `...zig.exe` (faltou o MSVC).

## Compilar

```powershell
build.bat            # roda os testes, compila, monta a pasta e roda o autoteste
build.bat --rapido   # pula os testes (só para iterar)
```

O `build.bat` faz, em ordem: (1) `pytest`; (2) limpa `build_nuitka/`; (3) Nuitka standalone com o plugin
`pyqt6`; (4) monta a pasta de distribuição e roda `AnalisePlanilhas.exe --autoteste`. *Compilar não é
funcionar* — o autoteste pós-build é a segunda barreira (exercita o que só existe empacotado).

## Pasta de distribuição

Saída em `build_nuitka\main.dist\`. Ao lado do `.exe`, o build cria/copia (graváveis):

```
AnalisePlanilhas.exe
config\modelos\*.toml      modelos de cliente (a equipe edita)
dados\<relatório>\         planilhas a analisar (uma subpasta por relatório; "Sem modelo" = entrada\)
templates\                 relatório HTML (Jinja2) — embutido pelo build
assets\icon.ico            ícone da janela/barra de tarefas — embutido pelo build
autoteste.txt              resultado do último --autoteste (diagnóstico)
saida\                     relatórios gerados
```

`config.py` detecta a execução compilada e resolve esses caminhos ao lado do binário. **Entregue a pasta
inteira** — o `.exe` depende dos arquivos ao lado.

## Ícone (opcional)

Se existir `assets/icon.ico`, o build o usa; senão, compila sem ícone. Para personalizar, coloque o
arquivo em `assets/icon.ico`.

## Versão

Fonte única: `__version__` em `src/analise_planilha/__init__.py`. O `build.bat` lê de lá a versão do
executável (`0.2.0` → `0.2.0.0`) e o `pyproject.toml` aponta para o mesmo lugar.

## Lançar uma versão (build automático no GitHub)

O código fica no repositório **privado** `Dougcct/Analise-de-Planilhas-privado`; os executáveis, nas
Releases do repositório **público** `Dougcct/Analise-de-Planilhas` (só o `.zip`, sem código).

```powershell
# 1. ajuste __version__ (ex.: "0.2.0") e o CHANGELOG; commit
git tag v0.2.0
git push origin main v0.2.0
```

A tag dispara `.github/workflows/release.yml` (Windows): confere que a tag bate com `__version__`, roda o
`build.bat` (testes → Nuitka → autoteste do `.exe`) e publica `AnalisePlanilhas-v0.2.0.zip` +
`.zip.sha256` como Release no repositório público. Acompanhe em *Actions* no repositório privado. Se
qualquer etapa falhar, nada é publicado.

**Pré-requisito (uma vez):** secret `RELEASES_TOKEN` no repositório privado (*Settings › Secrets and
variables › Actions*) com um token *fine-grained* que só tenha **Contents: Read and write** no
repositório público. O token fica no GitHub — nunca dentro do `.exe`.

## Atualização automática do .exe

`analise_planilha/atualizacao.py` (lógica) + `app/atualizador.py` (tela). Só age no executável:

1. ~1,5 s depois de abrir, consulta em segundo plano a última Release (tempo-limite 5 s). Sem rede,
   proxy bloqueando ou GitHub fora: segue em silêncio, na versão atual.
2. Versão maior que a instalada → **pergunta** ao usuário (com as notas da Release, se houver).
3. Sim → baixa o `.zip`, confere o **SHA-256** publicado junto (arquivo corrompido ou adulterado é
   recusado), extrai numa pasta temporária e confere que o pacote traz o `.exe`.
4. Fecha o programa; um script (`robocopy`) espera ele sair, copia o programa novo por cima e reabre.
   **Nunca toca em `dados\` e `saida\`**; de `config\` só copia arquivos **que ainda não existem** (ex.: um
   modelo novo) — modelos, metas e `ia.toml` já existentes ficam como estão. Registro em `atualizacao.log`.

**O que sai da máquina:** só GETs em `api.github.com`/`github.com` (qual a última versão + o download).
Nenhum dado de planilha, caminho ou identificação é enviado. Para desligar (ex.: pedido da TI), crie
`config\atualizacao.toml` com `verificar = false`.

Limites conhecidos: arquivos que uma versão nova **deixou de usar** ficam na pasta (a cópia não apaga
nada, para nunca arriscar `dados\`); a pasta do programa precisa ser gravável pelo usuário (ela já é, por
causa de `dados\` e `saida\`).

## Checklist de release

- [ ] `pytest` e `--autoteste` OK
- [ ] versão incrementada em `__init__.py` e CHANGELOG atualizado
- [ ] tag `vX.Y.Z` enviada e o fluxo *Release* concluiu (ou, local: `build.bat` concluiu e o autoteste
      pós-build passou)
- [ ] pasta `main.dist` (ou o `.zip` da Release) testada em uma máquina limpa (sem Python)
