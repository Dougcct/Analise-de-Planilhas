# Análise de Planilhas — Estrutura Base

> **O problema:** cada setor mantém planilhas no seu próprio formato, e transformar isso em indicadores
> confiáveis é um trabalho manual e repetido a cada mês. **A ideia:** uma base única que lê a planilha do
> cliente como ela é, reconhece os tipos de dado, aplica as regras de negócio daquele relatório e entrega
> os indicadores prontos — sem reprogramar para cada planilha nova, bastando descrever o cliente num
> arquivo de modelo.
>
> Este repositório **documenta e apresenta** essa base. O código é aberto aqui.

Produto: um **servidor web** (FastAPI + Docker) com login e **controle por setor** — cada equipe envia
suas planilhas (xlsx, ods, csv), o sistema padroniza os dados e publica um **relatório analítico HTML** no
navegador, no mesmo desenho do projeto **Garantia de Atendimento e Reembolso**. Cada relatório é:

| Relatório | O que é |
|---|---|
| **um por modelo do cliente** (`config/modelos/*.toml`) | colunas + regras de negócio do cliente (taxas, tempos, metas…) |
| **Sem modelo (inferência automática)** | qualquer planilha: tipos e indicadores deduzidos |

Exemplo pronto: **Contas Convênio** (contas hospitalares em blocos — [DOCS/12](DOCS/12_contas_convenio.md)).
Um relatório pode **somar várias planilhas** (ex.: um ano por arquivo) e oferece filtros por período e por
dimensão (Convênio, Ano, Arquivo de origem…) na própria tela.

Rede: só o servidor na LAN (o **Modo I.A** opcional envia apenas estrutura anonimizada —
[DOCS/11](DOCS/11_modo_ia.md)).

**Versão:** 1.4.0 · **Saídas:** HTML (PDF e DOCX previstos)

## Uso

```powershell
docker compose up              # sobe o servidor (banco + API/web); abra http://localhost:8000/web
```

No navegador: faça login, abra o **Relatório**, ou (gestor) **Enviar** uma planilha → prévia → publicar.
Filtros de período/dimensão e metas do gestor ficam na própria tela. Ver [POP-01](DOCS/pops/POP-01_operacao.md).

## Desenvolvimento

```powershell
pip install -r requirements-dev.txt
python gerar_relatorio.py      # relatório pela linha de comando (sem servidor) — --listar, --relatorio, --dim…
python analisar.py arq.xlsx    # resumo da inferência de uma planilha no terminal
python -m pytest               # suíte offline (fixtures sintéticas)
ruff check .                   # lint
```

Requisitos: Python 3.11+ (testado em 3.12); Docker para subir o servidor.

## Como adaptar a um novo cliente

1. Copie `config/modelos/exemplo.toml.sample` para `config/modelos/<cliente>.toml` (ou gere pelo **Cérebro**
   a partir das planilhas de `Setores/`).
2. Ajuste colunas e regras de negócio ([DOCS/04](DOCS/04_modelo_de_cliente.md)).
3. Pronto — aparece como relatório. Nenhuma mudança de código.

## Estrutura

```
gerar_relatorio.py      linha de comando (relatório HTML com filtros)
analisar.py             linha de comando (resumo da inferência)
src/analise_planilha/   lógica (leitura, modelo, inferência, especificação, indicadores, metas, relatório)
servidor/               servidor web v2 (FastAPI + Docker): web.py (rotas), app.py (API), bd, segurança…
templates/              relatório HTML (Jinja2) + casca web (templates/web/)
assets/                 ícone
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
