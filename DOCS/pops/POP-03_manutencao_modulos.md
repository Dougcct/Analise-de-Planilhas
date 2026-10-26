# POP-03 · Manutenção e novos módulos (desenvolvedor)

| Campo | Valor |
|---|---|
| Código | POP-03 |
| Versão | 1.0 |
| Executante | Desenvolvedor |
| Frequência | Quando o modelo de cliente não basta |

## Objetivo

Estender o programa quando a adaptação por modelo ([POP-02](POP-02_adaptar_novo_cliente.md)) não resolve:
tipo semântico novo, gráfico/painel novo ou formato de saída novo.

## A. Preparação

1. `.venv` ativo; `python -m pytest` verde antes de começar.
2. Branch `feature/<tema>` (ou `fix/<tema>`).

## B. Novo tipo semântico (ex.: `cpf`, `cep`, `telefone`)

1. Documente a regra em [03_motor_de_inferencia.md](../03_motor_de_inferencia.md) **antes** (padrão,
   posição na cascata, limiar).
2. Adicione a detecção em `inferencia.py`, na posição correta da cascata, e as dicas de nome em `config.py`.
3. Se precisar de conversão, trate em `normalizacao.py`.
4. Se o tipo pedir indicador próprio, calcule em `indicadores.py` (ver C).
5. Inclua o novo tipo na constante `TIPOS` de `modelos.py` para que o modelo e a aba Tipos o reconheçam.

## C. Novo gráfico/painel

1. Calcule a tabela em `indicadores.py` (`gerar_paineis`), com a condição de aplicabilidade e o mapa
   `formatos` (int | dec | pct | moeda | dias).
2. Gráfico (opcional) em `graficos.py`: **SVG/HTML puro** (`colunas`, `barras` ou função nova no mesmo
   estilo — cores por variável CSS `--s1…`, tooltip `data-tip`). **Sem bibliotecas JavaScript.**
3. O painel entra em `Analise.paineis`: vira aba na janela e seção no relatório HTML automaticamente.

## D. Novo formato de saída (PDF/DOCX)

1. Crie `relatorio_<formato>.py` recebendo o objeto `Analise` — **nunca recalcule números**.
2. Ligue a um botão em `app/janela.py`.

## E. Testes e qualidade

1. Fixture **sintética** em `testes/conftest.py` cobrindo o caso (inclusive o limite).
2. Teste unitário (detector/função) e de ponta a ponta (`servico.carregar`/`analisar`).
3. `python -m pytest` e `python main.py --autoteste` sem falhas.

## F. Entrega

1. Atualize [CHANGELOG.md](../CHANGELOG.md) e os docs afetados; incremente a versão se for release.
2. Commits em Conventional Commits; abra PR; revisão; merge.

## Mudança que altera contrato

Mexer em `Analise`/`Esquema`/formato do modelo é **MAIOR** (SemVer): registre nota de migração no
CHANGELOG e verifique os `.toml` existentes.
