# Análise Dinâmica de Planilhas — Proposta de Arquitetura e Governança

> ⚠️ **Documento histórico — proposta inicial (desenho Streamlit).** O projeto depois mudou de rumo:
> virou **programa-base desktop PyQt6 + Nuitka**, adaptável por **modelo de cliente** (`config/modelos/*.toml`).
> A documentação **vigente** está em [DOCS/](DOCS/README.md). Mantido aqui apenas como registro da proposta
> original; onde este texto citar Streamlit ou inferência como caminho único, prevalece o `DOCS/`.

> Baseada nas práticas do projeto `garantia_atendimento` (camadas `app/` × `src/`, `servico.py` como
> orquestrador único, `config/` editável fora do código, `DOCS/` com POPs, SemVer, LGPD, testes offline).
> **Diferença central:** lá o modelo de planilha é conhecido (colunas mapeadas em `config.py`); aqui a
> estrutura é **desconhecida**, então o "mapa de colunas" é substituído por um **motor de inferência**.

---

## 1. Diretrizes e Stack

### 1.1 Princípios (herdados da referência)

| Princípio | Aplicação neste projeto |
|---|---|
| Lógica independente de interface | Nenhum `import streamlit` dentro de `src/`. UI, CLI e pasta monitorada só chamam `servico.py`. |
| Dicionário de análise como contrato | O motor devolve **um único objeto** (`Analise`) consumido por UI, HTML exportado e futuros PDF/DOCX. |
| Regras fora do código | Limiares de inferência, formatos de data e regras visuais em `config/*.toml`/`*.csv`. |
| Rastreabilidade | Toda linha carrega `arquivo_origem`, `aba_origem`, `linha_origem`. |
| Local e offline | Sem rede/servidor; dados nunca saem da máquina (LGPD). |
| Funções puras | Inferência e perfilamento recebem `DataFrame` e devolvem dados; sem efeito colateral. |

### 1.2 Fluxo

```
entrada/  (upload na UI  OU  pasta monitorada)
   │  leitura.py        detecta formato, encoding, separador, aba e linha de cabeçalho
   ▼
DataFrame bruto (tudo como texto, + colunas de origem)
   │  inferencia.py     decide o TIPO SEMÂNTICO de cada coluna (com score de confiança)
   ▼
DataFrame tipado + Esquema (coluna → tipo, confiança, evidências)
   │  perfil.py         estatísticas por coluna, qualidade, correlações, séries temporais
   ▼
Perfil
   │  regras_visuais.py (tipo + cardinalidade → que gráfico/KPI/tabela usar)
   ▼
Analise  { kpis[], paineis[], alertas[], esquema, qualidade }
   │  graficos.py + app/ (Streamlit)  ou  relatorio_html.py (exportação)
   ▼
Dashboard interativo / HTML exportado
```

### 1.3 Stack recomendada

| Camada | Biblioteca | Por quê |
|---|---|---|
| Leitura | `pandas`, `openpyxl` (.xlsx), `odfpy` (.ods), `xlrd` (.xls), `charset-normalizer` (encoding de CSV) | Mesmos formatos da referência; `charset-normalizer` resolve CSV legado em cp1252/latin-1 |
| Inferência | `pandas` + regras próprias (regex, `pd.to_datetime`, `pd.to_numeric`) | Controle total sobre pt-BR (`1.234,56`, `dd/mm/aaaa`, `R$`, `%`); evita "mágica" opaca |
| Validação de contrato | `pydantic` v2 (modelos `Esquema`, `ColunaInferida`, `Analise`) | Contrato tipado e serializável (JSON) entre camadas |
| Visualização | `plotly` | Interativo (hover/zoom/filtro), exporta HTML autônomo, integra com Streamlit e Dash |
| Interface | **`streamlit`** (recomendado) | Ver 1.4 |
| Pasta monitorada | `watchdog` | Eventos de arquivo nativos no Windows, sem polling |
| Exportação | `jinja2` (HTML), futuramente `python-docx`/`weasyprint` | Mesmo padrão `templates/*.j2` da referência |
| Qualidade | `pytest`, `ruff`, `mypy` (opcional) | Suíte offline + estilo único |
| Distribuição | Nuitka (como na referência) + `streamlit` empacotado via launcher | Ver nota em 1.5 |

### 1.4 Streamlit × Dash

| Critério | Streamlit | Dash |
|---|---|---|
| Dashboard **gerado** dinamicamente (widgets/abas criados em loop a partir dos dados) | Natural: o script é re-executado e a UI é código imperativo | Exige *callbacks* declarados com IDs fixos; layout dinâmico é trabalhoso |
| Upload de arquivo | `st.file_uploader` pronto | `dcc.Upload` + callback com base64 |
| Curva de aprendizado para a equipe | Baixa | Média |
| Controle fino de layout/CSS | Médio | Alto |
| Estado entre interações | `st.session_state` + `st.cache_data` | `dcc.Store` + callbacks |

**Recomendação: Streamlit.** O caso de uso (UI criada a partir de um esquema que só se conhece em
runtime) é exatamente onde Dash mais pesa. Como a lógica fica em `src/` sem acoplamento, trocar para Dash
no futuro significa reescrever só `app/`.

### 1.5 Observação sobre empacotamento

Streamlit é um servidor web local; não é um app de janela como o PyQt6 da referência. Duas opções:
(a) distribuir a pasta + `iniciar.bat` que cria `.venv` e abre `http://localhost:8501` (mais simples,
recomendado na v0.1); (b) empacotar com Nuitka/PyInstaller um *launcher* que sobe o Streamlit — frágil,
deixar para depois. Se a equipe exigir `.exe` de janela única, considerar `pywebview` encapsulando o Streamlit.

### 1.6 Motor de inferência — como decidir o tipo

Toda coluna é lida **como texto** e testada em cascata; vence o primeiro tipo com taxa de acerto ≥ limiar
(padrão 95% dos valores não nulos, configurável). O resultado guarda `tipo`, `confianca` e `evidencias`.

| Ordem | Tipo semântico | Regra de detecção |
|---|---|---|
| 1 | `vazio` | ≥ 98% nulos/brancos → ignorada |
| 2 | `identificador` | Texto/inteiro, unicidade ≥ 95% e nome sugere (`id`, `cod`, `protocolo`, `cpf`…) → **não** é agregada |
| 3 | `booleano` | Conjunto ⊆ {sim/não, s/n, true/false, 0/1, x/vazio} |
| 4 | `data` / `data_hora` | Padrões `dd/mm/aaaa`, `aaaa-mm-dd`, serial do Excel; desambiguação dia/mês pela maioria das linhas |
| 5 | `percentual` | Sufixo `%` ou faixa 0–1 com nome sugestivo |
| 6 | `moeda` | Prefixo `R$`, ou decimal pt-BR com nome (`valor`, `preco`, `custo`…) |
| 7 | `inteiro` / `decimal` | `to_numeric` após normalizar `1.234,56` → `1234.56` |
| 8 | `categorico` | Cardinalidade ≤ max(20, 5% das linhas) |
| 9 | `texto_livre` | Resto (alta cardinalidade, textos longos) |

Heurísticas adicionais: localizar a **linha de cabeçalho** (primeira linha com maioria de células não
nulas e tipo texto, seguida de dados), descartar linhas/colunas de total, normalizar nomes de coluna
(`strip`, acentos, duplicatas → `nome_2`), e **sempre permitir override manual do tipo na UI** (o usuário
corrige; a escolha é gravada em `config/overrides.json` por "assinatura" de colunas).

### 1.7 Do tipo ao gráfico (regras visuais)

| Situação | Visual padrão |
|---|---|
| Moeda/decimal/inteiro | KPI (soma, média, mediana, mín/máx) + histograma + boxplot |
| Data + métrica | Série temporal (granularidade automática dia/semana/mês conforme o intervalo) |
| Categórico + métrica | Ranking Top-N (barras horizontais) + "Outros" |
| Categórico isolado | Barras de frequência / rosca (≤ 6 categorias) |
| Duas métricas | Dispersão + correlação |
| Várias métricas | Heatmap de correlação |
| Booleano | Taxa (%) em KPI |
| Texto livre / identificador | Apenas contagem de preenchimento e únicos — **sem gráfico** |
| Qualquer | Aba **Qualidade**: nulos, duplicatas, outliers, tipos mistos, datas inválidas |

Layout para leitura: linha de KPIs no topo → abas (**Visão geral**, **Tendência**, **Distribuições**,
**Categorias**, **Qualidade**, **Dados**) → filtros globais na barra lateral (período + categorias) →
máximo de ~6 gráficos por aba, com gráficos "candidatos" ranqueados por pontuação de relevância.
Todo número formatado em pt-BR (`fmt_int`, `fmt_pct`, `fmt_moeda`), como na referência.

---

## 2. Documentação

### 2.1 Estrutura de diretórios

```
analise-planilhas/
├── main.py                      # ponto de entrada: `python main.py` abre a UI; --autoteste
├── analisar.py                  # CLI: `python analisar.py arquivo.xlsx` → HTML (RPA/agendamento)
├── monitorar.py                 # CLI: observa a pasta de entrada e gera saída a cada arquivo novo
├── iniciar.bat                  # cria .venv, instala dependências e abre o Streamlit
├── pyproject.toml               # metadados, ruff, pytest
├── requirements.txt
├── README.md
├── CONTRIBUTING.md
├── .gitignore                   # dados/, saida/, planilhas — LGPD
│
├── app/                         # SÓ interface (Streamlit) — nenhuma regra de negócio
│   ├── __init__.py
│   ├── pagina.py                # layout: upload, barra lateral, abas
│   ├── componentes.py           # render de KPI, gráfico, tabela, alerta
│   └── tema.py                  # tokens de cor/tipografia (marca num lugar só)
│
├── src/analise_planilha/        # lógica pura, sem import de streamlit
│   ├── __init__.py              # __version__ — fonte única da versão
│   ├── config.py                # caminhos, limiares, carregamento de config/*.toml
│   ├── modelos.py               # pydantic: ColunaInferida, Esquema, Perfil, Analise
│   ├── leitura.py               # formato, encoding, separador, aba, cabeçalho
│   ├── inferencia.py            # cascata de tipos semânticos
│   ├── normalizacao.py          # números/datas pt-BR, nomes de colunas
│   ├── perfil.py                # estatísticas, qualidade, correlações
│   ├── regras_visuais.py        # tipo → visual (registro de "geradores")
│   ├── graficos.py              # fábrica de figuras Plotly
│   ├── formatacao.py            # fmt_int / fmt_pct / fmt_moeda (pt-BR)
│   ├── relatorio_html.py        # exportação HTML autônoma (Jinja2)
│   ├── monitor.py               # watchdog (pasta monitorada)
│   └── servico.py               # orquestra: caminho → Analise (usado por UI/CLI/monitor)
│
├── config/
│   ├── inferencia.toml          # limiares, dicas de nome (id, valor, data…)
│   ├── formatos_data.csv        # formatos aceitos
│   └── overrides.json           # tipos corrigidos pelo usuário (por assinatura de colunas)
│
├── templates/
│   └── relatorio.html.j2
├── assets/                      # ícone, logo
├── dados/                       # planilhas de entrada (NÃO versionar)
│   └── entrada/                 # pasta monitorada
├── saida/                       # relatórios gerados (NÃO versionar)
├── testes/
│   ├── conftest.py
│   ├── fixtures/                # planilhas SINTÉTICAS (nunca dados reais)
│   ├── test_leitura.py
│   ├── test_inferencia.py
│   ├── test_perfil.py
│   └── test_servico.py
└── DOCS/
    ├── README.md                # índice
    ├── 01_visao_geral.md
    ├── 02_arquitetura.md
    ├── 03_motor_de_inferencia.md
    ├── 04_regras_visuais.md
    ├── 05_diretrizes_desenvolvimento.md
    ├── CHANGELOG.md             # Keep a Changelog
    ├── ROADMAP.md
    └── pops/
        ├── POP-01_operacao_ferramenta.md
        └── POP-02_manutencao_e_novos_modulos.md
```

### 2.2 `README.md` (conteúdo base)

````markdown
# Análise Dinâmica de Planilhas

Ferramenta **local** que recebe uma planilha de estrutura qualquer (xlsx, xls, ods, csv), **infere os
tipos de dados** de cada coluna e gera automaticamente um **dashboard interativo** com KPIs, gráficos
e diagnóstico de qualidade. Não usa servidor externo: os dados ficam na máquina do usuário.

**Versão:** 0.1.0 · **Python:** 3.10+ (testado em 3.12) · **Saídas:** dashboard na tela, HTML

## O que faz

- Lê Excel/ODS/CSV e localiza sozinho aba, encoding, separador e linha de cabeçalho.
- Classifica cada coluna (número, moeda, percentual, data, categoria, booleano, texto, identificador).
- Monta KPIs, séries temporais, rankings, distribuições e correlações adequados a cada tipo.
- Mostra alertas de qualidade (nulos, duplicatas, outliers, datas inválidas).
- Permite corrigir o tipo de uma coluna e filtrar por período e categorias.
- Exporta o dashboard como HTML autônomo.

## Uso (usuário final)

1. Execute `iniciar.bat` (abre o navegador em `http://localhost:8501`).
2. Arraste a planilha para a área de upload **ou** coloque-a em `dados\entrada\` (modo pasta monitorada).
3. Confira os tipos detectados, aplique filtros e navegue pelas abas.
4. Clique em **Exportar HTML**.

Passo a passo completo: [POP-01](DOCS/pops/POP-01_operacao_ferramenta.md).

## Desenvolvimento

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py                  # abre a interface
python main.py --autoteste      # diagnóstico do ambiente (sem janela)
python analisar.py dados\entrada\exemplo.xlsx   # gera HTML por linha de comando
python monitorar.py             # observa dados\entrada\ e gera saida\ automaticamente
pytest                          # suíte offline
```

## Arquitetura em uma linha

`leitura → inferência → perfil → regras visuais → Analise → (UI | HTML)`; a UI nunca contém regra de
negócio. Detalhes: [DOCS/02_arquitetura.md](DOCS/02_arquitetura.md).

## LGPD

Planilhas podem conter dados pessoais/sensíveis. `dados/` e `saida/` **nunca** são versionados; não
anexe bases reais em chamados ou e-mails; use dados sintéticos em `testes/fixtures/`.

## Documentação

[DOCS/README.md](DOCS/README.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG](DOCS/CHANGELOG.md) · [ROADMAP](DOCS/ROADMAP.md)
````

### 2.3 `CONTRIBUTING.md` (conteúdo base)

````markdown
# Guia de Contribuição

## Ambiente

```powershell
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install        # ruff + checagem de arquivos de dados
```

Execute sempre a partir da raiz do projeto.

## Regras de código

- Código, nomes e comentários em **português**, coerentes com o domínio.
- PEP 8; linhas ≤ 120 caracteres; `ruff check` e `ruff format` sem pendências.
- **Nenhum `import streamlit` em `src/`.** UI só em `app/`.
- Funções de `inferencia`, `perfil` e `regras_visuais` são **puras** (entrada: DataFrame/config; saída: dados).
- Regra ajustável (limiar, dica de nome, formato) vai em `config/`, não em `if` no código.
- Todo número exibido passa por `formatacao.py` (pt-BR).
- Na UI, estilo via `app/tema.py`; sem CSS solto espalhado.

## Fluxo de trabalho

1. Crie a branch a partir de `develop`: `feature/<tema>` ou `fix/<tema>` (ver `DOCS/05_...`).
2. Faça commits no padrão **Conventional Commits** (`feat(inferencia): detecta moeda com prefixo R$`).
3. Escreva/ajuste testes em `testes/` para toda regra nova ou corrigida.
4. Rode `pytest` e `ruff check .` localmente.
5. Atualize `DOCS/CHANGELOG.md` (seção *Não lançado*).
6. Abra o Pull Request para `develop` usando o modelo; peça revisão de ao menos 1 pessoa.

## Testes

- Suíte **offline**: sem rede e sem dados reais. Fixtures são planilhas **sintéticas** em
  `testes/fixtures/` (gere com `testes/gerar_fixtures.py`).
- Bug corrigido = teste de regressão que falhava antes.
- Mudança em regra de inferência exige caso novo em `test_inferencia.py` e atualização de
  `DOCS/03_motor_de_inferencia.md` **antes** do código.

## Dados e segurança (LGPD)

- Nunca faça commit de `dados/`, `saida/`, `.xlsx`, `.ods`, `.csv` (exceto `config/*.csv` e fixtures sintéticas).
- Nunca cole conteúdo de planilha real em issues, PRs ou logs.
- Logs não registram valores de células, apenas nomes de colunas, tipos e contagens.

## Versionamento

SemVer `MAIOR.MENOR.CORREÇÃO`; versão em `src/analise_planilha/__init__.py`. MAIOR: quebra contrato
(`Analise`/config). MENOR: funcionalidade compatível. CORREÇÃO: ajuste sem mudar contrato.

## Checklist do Pull Request

- [ ] Testes passando e novos testes incluídos
- [ ] `ruff` sem pendências
- [ ] CHANGELOG atualizado
- [ ] Docs afetadas atualizadas
- [ ] Nenhum dado real no diff
````

---

## 3. Versionamento

### 3.1 Estratégia de ramificação (Git Flow simplificado)

| Branch | Origem → destino | Função |
|---|---|---|
| `main` | — | Sempre estável; cada commit é um release com tag `vX.Y.Z` |
| `develop` | `main` | Integração das próximas entregas |
| `feature/<tema>` | `develop` → `develop` | Nova funcionalidade (ex.: `feature/detector-moeda`) |
| `fix/<tema>` | `develop` → `develop` | Correção não urgente |
| `release/X.Y.Z` | `develop` → `main` + `develop` | Congelamento: ajustes finais, CHANGELOG, versão |
| `hotfix/<tema>` | `main` → `main` + `develop` | Correção urgente em produção |

Regras: PR obrigatório para `develop` e `main`; *squash merge* em `feature/*` e `fix/*`; `main` e
`develop` protegidas; tag anotada no merge de release (`git tag -a v0.2.0 -m "..."`); branches curtas
(< 1 semana) para reduzir conflito.

### 3.2 Padrão de commits — Conventional Commits

```
<tipo>(<escopo>): <resumo imperativo em até 72 caracteres>

[corpo opcional: o quê e por quê]

[rodapé: BREAKING CHANGE: ... | Refs #123]
```

| Tipo | Uso | Efeito de versão |
|---|---|---|
| `feat` | Nova funcionalidade | MENOR |
| `fix` | Correção de bug | CORREÇÃO |
| `perf` | Ganho de desempenho | CORREÇÃO |
| `refactor` | Reestruturação sem mudar comportamento | — |
| `test` | Testes | — |
| `docs` | Documentação/POPs | — |
| `build` / `ci` | Empacotamento, dependências, pipeline | — |
| `chore` | Manutenção geral | — |
| `BREAKING CHANGE` (rodapé ou `!`) | Quebra de contrato | MAIOR |

Escopos sugeridos: `leitura`, `inferencia`, `perfil`, `visual`, `app`, `monitor`, `config`, `docs`.

Exemplos:
```
feat(inferencia): reconhece percentuais com sufixo % e faixa 0-1
fix(leitura): detecta cabeçalho quando há título mesclado nas 3 primeiras linhas
docs(pop): adiciona passo de override manual de tipo no POP-01
feat(modelos)!: renomeia Analise.paineis para Analise.secoes
```

---

## 4. POPs

### POP 01 — Uso e operação da ferramenta pelo usuário final

| Campo | Valor |
|---|---|
| Código | POP-01 |
| Versão | 1.0 |
| Executante | Usuário final (analista/gestor) |
| Frequência | Sob demanda |

**Objetivo.** Gerar um dashboard a partir de uma planilha qualquer e interpretar os resultados.

**Pré-requisitos.** Ferramenta instalada (pasta da distribuição); planilha em xlsx, xls, ods ou csv; acesso
autorizado aos dados (LGPD).

**Procedimento — modo interface**

1. Execute `iniciar.bat`. O navegador abre em `http://localhost:8501` (aguarde ~10 s na primeira vez).
2. Arraste a planilha para **Enviar planilha** (ou clique e selecione).
3. Se o arquivo tiver várias abas, escolha a aba na barra lateral.
4. Em **Tipos detectados**, confira cada coluna. Se alguma estiver errada (ex.: CEP lido como número),
   altere o tipo no seletor e clique em **Reprocessar**.
5. Defina os **filtros** (período e categorias) na barra lateral.
6. Navegue pelas abas: **Visão geral** (KPIs), **Tendência**, **Distribuições**, **Categorias**,
   **Qualidade** e **Dados**.
7. Passe o mouse sobre os gráficos para ver valores; clique na legenda para ocultar séries.
8. Clique em **Exportar HTML**; o arquivo é salvo em `saida\analise_AAAAMMDD_HHMMSS.html`.

**Procedimento — modo pasta monitorada**

1. Execute `monitorar.bat` (mantenha a janela aberta).
2. Copie a planilha para `dados\entrada\` (aguarde terminar de copiar).
3. Em instantes o relatório aparece em `saida\`; a planilha processada vai para `dados\entrada\processados\`.
4. Em caso de erro, veja `saida\erros\<arquivo>.txt`.

**Verificação.** Confira se o número de linhas exibido bate com o da planilha original e se a aba
**Qualidade** não aponta datas inválidas ou tipos mistos relevantes.

**Problemas comuns**

| Sintoma | Causa provável | Ação |
|---|---|---|
| Colunas com nomes `Unnamed: 3` | Cabeçalho não detectado | Informar a linha do cabeçalho em **Opções avançadas** |
| Acentos quebrados em CSV | Encoding atípico | Escolher o encoding em **Opções avançadas** |
| Datas trocadas (dia/mês) | Ambiguidade `03/04/2026` | Forçar formato `dd/mm/aaaa` no tipo da coluna |
| Número lido como texto | Mistura de `.` e `,` ou "R$" solto | Forçar tipo *decimal*/*moeda* |
| Nenhum gráfico gerado | Só colunas de texto/identificador | Verificar a aba **Dados**; ajustar tipos |

**Cuidados (LGPD).** Não envie o HTML exportado a destinatários externos sem autorização; ative
**Anonimizar colunas sensíveis** quando o relatório sair da equipe; apague a planilha de `dados\` após o uso
se não houver necessidade de guarda.

---

### POP 02 — Manutenção e adição de novos módulos pelos desenvolvedores

| Campo | Valor |
|---|---|
| Código | POP-02 |
| Versão | 1.0 |
| Executante | Desenvolvedor |
| Frequência | A cada nova necessidade / correção |

**Objetivo.** Alterar o sistema de forma controlada: novo tipo de dado, novo gráfico, novo formato de
entrada/saída ou correção.

**A. Preparação**

1. `git checkout develop && git pull`.
2. `git checkout -b feature/<tema>` (ou `fix/<tema>`).
3. Ative o `.venv` e rode `pytest` — a base deve estar verde antes de começar.

**B. Adicionar um novo tipo semântico (ex.: `cpf`, `cep`, `telefone`)**

1. Documente a regra em `DOCS/03_motor_de_inferencia.md` (padrão, posição na cascata, limiar).
2. Crie o detector em `inferencia.py` como função pura `detectar_<tipo>(serie, ctx) -> Resultado | None`
   e registre-o em `DETECTORES` **na posição correta da ordem**.
3. Se o tipo exigir tratamento, adicione a conversão em `normalizacao.py`.
4. Defina o visual em `regras_visuais.py` (registrar gerador no mapa `tipo → geradores`) e, se necessário,
   o gráfico em `graficos.py`.
5. Se for dado sensível, marque-o em `config/inferencia.toml` (`sensivel = true`) para anonimização.

**C. Adicionar um novo gráfico/painel**

1. Crie a função em `graficos.py` (entrada: DataFrame + colunas; saída: figura Plotly).
2. Registre em `regras_visuais.py` com a condição de aplicabilidade e a **pontuação de relevância**.
3. Garanta que o painel apareça em `Analise.paineis` — a UI renderiza genericamente, **sem** tocar em `app/`.

**D. Adicionar formato de entrada ou saída**

- *Entrada:* novo leitor em `leitura.py` registrado em `LEITORES[extensao]`, devolvendo DataFrame bruto
  com colunas de origem.
- *Saída:* novo `relatorio_<formato>.py` que consome o objeto `Analise` (nunca recalcula números).

**E. Testes e qualidade**

1. Inclua fixture sintética em `testes/fixtures/` cobrindo o caso (inclusive o caso-limite).
2. Escreva testes unitários (detector) e de ponta a ponta (`servico.analisar(caminho)`).
3. `pytest` e `ruff check .` sem falhas; `python main.py --autoteste` OK.

**F. Entrega**

1. Atualize `CHANGELOG.md` e os docs afetados; incremente a versão se for release.
2. Commits no padrão Conventional Commits; abra PR para `develop`.
3. Revisão (checklist do CONTRIBUTING); *squash merge*.
4. Release: `release/X.Y.Z` → `main`, tag `vX.Y.Z`, merge de volta em `develop`.

**Mudança que altera contrato** (`Analise`, `config/*.toml`): bump MAIOR, nota de migração no CHANGELOG e
atualização de `overrides.json` legados.

---

## 5. Melhorias — Roadmap

| # | Melhoria | Descrição | Valor | Esforço |
|---|---|---|---|---|
| 1 | **Insights por IA** | Resumo em linguagem natural ("Receita caiu 12% em março, concentrada em 2 cidades"), detecção de anomalias e perguntas em texto sobre a planilha. Preferir execução local/privada (LGPD) ou enviar apenas agregados, nunca linhas. | Alto | Médio |
| 2 | **ETL automatizado e reutilizável** | Perfis por "assinatura" de planilha: limpeza (trim, deduplicação, tratamento de totais), junção de várias planilhas e agendamento (Task Scheduler), com saída para Parquet/SQLite. | Alto | Médio |
| 3 | **Exportação PDF/DOCX/PPTX e agendamento de relatórios** | Mesmo objeto `Analise` renderizado em novos formatos; envio por e-mail interno. | Médio | Baixo |
| 4 | **Comparação entre períodos/arquivos e histórico** | Diferença mês a mês, *drill-down* e armazenamento do histórico de análises (DuckDB/SQLite) com versão do esquema. | Alto | Médio |
| 5 | **Governança de dados e LGPD embutida** | Detecção automática de colunas sensíveis (CPF, nome, telefone), mascaramento/anonimização, trilha de auditoria de acessos e perfis de usuário. | Alto | Médio |

Candidatas adicionais: dicionário de aliases/sinônimos para categorias (como `config/*_alias.csv` da
referência), modelos de dashboard salvos por usuário, suporte a bases grandes (Polars/DuckDB), integração
com bancos e APIs.

---

## Próximo passo sugerido

Criar o esqueleto físico do projeto (pastas, `requirements.txt`, `.gitignore`, `pyproject.toml`, módulos
vazios com docstrings, `servico.py` mínimo e uma fixture sintética) e implementar a primeira fatia vertical:
`leitura → inferencia (inteiro/decimal/data/categorico) → 1 KPI + 1 gráfico` no Streamlit.
