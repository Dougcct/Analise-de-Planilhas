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

## Checklist de release

- [ ] `pytest` e `--autoteste` OK
- [ ] versão incrementada em `__init__.py` e CHANGELOG atualizado
- [ ] `build.bat` concluiu e o autoteste pós-build passou
- [ ] pasta `main.dist` testada em uma máquina limpa (sem Python)
