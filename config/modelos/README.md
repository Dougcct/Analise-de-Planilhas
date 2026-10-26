# Modelos de cliente

Cada arquivo `*.toml` desta pasta é um **modelo de planilha** e aparece no seletor da interface.
O programa-base vem **em branco** (sem nenhum modelo ativo) — por padrão usa a inferência automática.

## Criar o modelo de um cliente

- **Pela interface (recomendado):** abra a planilha sem modelo, corrija os tipos na aba **Tipos** e
  clique em **Salvar como modelo…**.
- **À mão:** copie [`exemplo.toml.sample`](exemplo.toml.sample) para `<cliente>.toml` e edite.

> O arquivo `exemplo.toml.sample` termina em `.sample` de propósito: serve de template e **não** entra
> no seletor de modelos. Só arquivos `.toml` são carregados.

Guia completo do formato: [../../DOCS/04_modelo_de_cliente.md](../../DOCS/04_modelo_de_cliente.md).
