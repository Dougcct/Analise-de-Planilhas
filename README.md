# Análise de Planilhas — Estrutura Base

Ferramenta **local de desktop** (Windows, PyQt6) que lê as planilhas da equipe (xlsx, ods, csv), padroniza
os dados, mostra os indicadores na tela e gera um relatório analítico — no mesmo desenho do projeto
**Garantia de Atendimento e Reembolso**. No topo da barra lateral o usuário escolhe o **Relatório**:

| Relatório | Lê de | O que é |
|---|---|---|
| **um por modelo do cliente** (`config/modelos/*.toml`) | `dados\<pasta do modelo>\` | colunas + regras de negócio do cliente (taxas, tempos, metas…) |
| **Sem modelo (inferência automática)** | `dados\entrada\` | qualquer planilha: tipos e indicadores deduzidos |

Exemplo pronto: **Contas Convênio** (contas hospitalares em blocos — [DOCS/12](DOCS/12_contas_convenio.md)).

Não usa rede nem servidor: tudo roda na máquina do usuário (o **Modo I.A** opcional é a única exceção, e
envia só a estrutura anonimizada — [DOCS/11](DOCS/11_modo_ia.md)). É entregue como executável (`.exe`).

**Versão:** 0.1.0 · **Saídas:** HTML (PDF e DOCX previstos na v0.2)

## Uso (usuário final)

Execute **`AnalisePlanilhas.exe`**, escolha o **Relatório**, coloque as planilhas na pasta indicada (ou use
**Adicionar…**), marque os arquivos, ajuste os filtros, **Aplicar filtros** e **Gerar HTML**. Metas do
gestor em **⚙ Editar metas**. Ver [POP-01](DOCS/pops/POP-01_operacao.md).

## Desenvolvimento

```powershell
pip install -r requirements.txt
python main.py                 # abre a interface
python main.py --autoteste     # diagnóstico do ambiente (sem janela) — grava autoteste.txt
python gerar_relatorio.py      # relatório pela linha de comando (RPA/agendamento) — --listar, --relatorio, --dim…
python analisar.py arq.xlsx    # resumo da inferência de uma planilha no terminal
python -m pytest               # suíte offline (fixtures sintéticas)
```

Requisitos: Python 3.11+ (testado em 3.12).

## Build do executável

```powershell
build.bat                      # roda a suíte de testes, compila com Nuitka, monta a pasta e autotesta
build.bat --rapido             # pula a suíte (só para iterar)
```

Saída: `build_nuitka\main.dist\AnalisePlanilhas.exe`. Detalhes em
[DOCS/08_build_e_distribuicao.md](DOCS/08_build_e_distribuicao.md).

## Como adaptar a um novo cliente

1. Copie `config/modelos/exemplo.toml.sample` para `config/modelos/<cliente>.toml` (ou use
   **Salvar como modelo…** / **Modo I.A** na janela).
2. Ajuste colunas e regras de negócio ([DOCS/04](DOCS/04_modelo_de_cliente.md)); `pasta = "…"` define a
   subpasta de `dados\` (padrão: o nome do modelo).
3. Pronto — aparece no seletor **Relatório**. Nenhuma mudança de código.

## Estrutura

```
main.py                 ponto de entrada (interface + --autoteste)
gerar_relatorio.py      linha de comando (relatório HTML com filtros)
analisar.py             linha de comando (resumo da inferência)
build.bat               compilação com Nuitka
app/                    interface desktop (janela.py, componentes.py, dialogo_*.py, tema.py)
src/analise_planilha/   lógica (leitura, modelo, inferência, especificação, indicadores, metas, relatório)
templates/              modelo do relatório HTML (Jinja2)
assets/                 ícone (barra de tarefas e janelas)
config/                 modelos de cliente (.toml); locais, não versionados: metas.json, ia.toml
testes/                 suíte offline (sem rede, sem dados reais)
dados/<Relatório>/      planilhas a analisar, uma subpasta por relatório (não versionar — LGPD)
saida/                  relatórios gerados (não versionar — LGPD)
DOCS/                   documentação, POPs, changelog e roadmap
```

Documentação completa: [DOCS/README.md](DOCS/README.md).

## LGPD

`dados/` e `saida/` nunca são versionados. Use apenas dados sintéticos em `testes/`. O relatório HTML
contém dados pessoais — uso interno; não publicar em serviços externos. Marque **Anonimizar nomes** antes
de mostrar a tela ou o relatório a terceiros.
