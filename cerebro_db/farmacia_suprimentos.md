# Farmácia, Estoque e Suprimentos (MV — DBAMV)

## Tabelas principais e chaves de junção (`WHERE`)
- `DBAMV.PRODUTO` (alias `pr`): Produtos/medicamentos (`CD_PRODUTO`, `DS_PRODUTO`, `CD_ESPECIE`, `CD_CLASSE`, `VL_CUSTO_MEDIO`, `SN_CONSIGNADO`).
- `DBAMV.ESTOQUE` (alias `es`): Estoques/farmácias (`CD_ESTOQUE`, `DS_ESTOQUE`, `CD_SETOR`).
- `DBAMV.EST_PRO` (alias `ep`): Saldo por estoque e produto (`CD_ESTOQUE`, `CD_PRODUTO`, `QT_ESTOQUE_ATUAL`).
- `DBAMV.MVTO_ESTOQUE` (alias `mv`) / `DBAMV.ITMVTO_ESTOQUE` (alias `imv`): Movimentações (`CD_MVTO_ESTOQUE`, `CD_ESTOQUE`, `CD_SETOR`, `CD_ATENDIMENTO`, `DT_MVTO_ESTOQUE`, `TP_MVTO_ESTOQUE`, `CD_PRODUTO`, `QT_MOVIMENTACAO`).
- `DBAMV.FORNECEDOR` (alias `fn`): Fornecedores (`CD_FORNECEDOR`, `NM_FORNECEDOR`).
- `DBAMV.SETOR` (alias `s`): Setores solicitantes (`CD_SETOR`, `NM_SETOR`).

## Exemplo de junção implícita (padrão MV)
```sql
SELECT s.nm_setor, pr.ds_produto, SUM(imv.qt_movimentacao) AS qtd
FROM dbamv.mvto_estoque mv, dbamv.itmvto_estoque imv, dbamv.produto pr, dbamv.setor s
WHERE mv.cd_mvto_estoque = imv.cd_mvto_estoque
  AND imv.cd_produto = pr.cd_produto
  AND mv.cd_setor = s.cd_setor
  AND TRUNC(mv.dt_mvto_estoque) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))
GROUP BY s.nm_setor, pr.ds_produto
```
