# 23 · Inteligência de KPIs do CeosGo & Agente Assistencial (v3)

> **Etapa 3** do aprimoramento da inteligência do sistema (após **Etapa 1**: leitura + `Conhecimento`; **Etapa 2**: ajustes manuais + `Agentes` de Faturamento e Custos).

## 1. Visão Geral

A v3 incorpora o catálogo oficial de indicadores do **CeosGo** ao motor de análise (`cerebro/kpis_ceosgo.py`) e adiciona o **Agente Assistencial** (`dominio/Agentes/assistencial/`), especializado em planilhas de atendimento, internação, CCIH, centro cirúrgico, enfermagem, PA e oncologia.

## 2. Ingestão e Curadoria Universal

O script [importar_kpis_ceosgo.py](../../scripts/importar_kpis_ceosgo.py) lê o CSV exportado do CeosGo (`KPI base.csv`), higieniza codificação/HTML e gera [kpis_ceosgo.json](../../config/kpis_ceosgo.json):

- **683 KPIs únicos** processados.
- **Curadoria universal de polaridade:** 122 indicadores exportados como `Quanto maior, melhor (1)` ou sem sentido foram corrigidos para `<=` (ex.: *ISCs, lesões por pressão, extubações acidentais, acidentes de trabalho, custos, glosas*), preservando exceções positivas como `>=` (*adesão/adequação a bundles, classificação de risco, conformidade cirúrgica*).
- **88 fórmulas estruturadas** extraídas (`numerador`, `denominador`, `fator`) para cálculo automático de indicadores derivados.
- **330 variáveis de coleta** marcadas com `eh_componente = true` para evitar falsos alertas de meta isolada.

## 3. Pontos de Integração no Motor

1. **Cérebro (`src/analise_planilha/cerebro/kpis_ceosgo.py`):**
   - `reconhecer_coluna(nome)`: match exato por assinatura normalizada ou similaridade de tokens (Dice ≥ 0.75).
   - `analisar_texto(texto)`: busca semântica sobre títulos e definições oficiais (Objetivo/Definição/Critérios).
   - `calcular_derivados(df)`: calcula automaticamente `(soma(numerador) / soma(denominador)) * fator` quando a planilha traz os campos componentes separados.
2. **Papéis (`papeis.py`):** respeita a hierarquia `Correção Humana / Conhecimento > Modelo .toml > Catálogo CeosGo > Léxico > Valores`, injetando papel e agregação corretos (`média` para percentuais/resultados, `soma` para moeda/quantidade).
3. **Metas (`metas.py`):** sugere automaticamente o sentido (`>=` ou `<=`) de taxas e medidas principais reconhecidas no CeosGo.
4. **Agente Assistencial (`dominio/Agentes/assistencial/`):** registrado no `router.py`; entrega métricas de atendimento, tempo de permanência (mediana, média, P90, internações > 7 dias), altas após 10h, quebras por setor/especialidade/risco, **KPIs Derivados (CeosGo)** e **KPIs Relacionados e Definições (CeosGo)**.

## 4. Testes e LGPD

Todos os testes em [test_kpis_ceosgo.py](../../testes/test_kpis_ceosgo.py) usam exclusivamente DataFrames sintéticos e cobrem curadoria, reconhecimento por texto, cálculo de derivados (inclusive divisão por zero), prioridade do `Conhecimento`, `metas.py` e `AgenteAssistencial`.
