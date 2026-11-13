# Atendimento, Internação e Leitos (MV — DBAMV)

## Tabelas principais e chaves de junção (`WHERE`)
- `DBAMV.ATENDIME` (alias `a`): Atendimentos hospitalares (PA, Internação, Ambulatório, Externo).
  - Chave primária: `CD_ATENDIMENTO`
  - Chaves estrangeiras: `CD_PACIENTE` → `PACIENTE.CD_PACIENTE`, `CD_CONVENIO` → `CONVENIO.CD_CONVENIO`, `CD_PRESTADOR` → `PRESTADOR.CD_PRESTADOR`, `CD_LEITO` → `LEITO.CD_LEITO`, `CD_ORI_ATE` → `ORI_ATE.CD_ORI_ATE`, `CD_MOT_ALT` → `MOT_ALT.CD_MOT_ALT`, `CD_ESPECIALID` → `ESPECIALID.CD_ESPECIALID`
  - Datas e tipos: `DT_ATENDIMENTO`, `HR_ATENDIMENTO`, `DT_ALTA`, `DT_ALTA_MEDICA`, `TP_ATENDIMENTO` (`'I'`=Internação, `'U'`=Urgência/PA, `'A'`=Ambulatório, `'E'`=Externo)
- `DBAMV.PACIENTE` (alias `p`): Cadastro de pacientes (`CD_PACIENTE`, `DT_NASCIMENTO`, `TP_SEXO`, `CD_CIDADE`).
- `DBAMV.LEITO` (alias `l`): Leitos (`CD_LEITO`, `DS_LEITO`, `CD_UNID_INT`, `TP_SITUACAO`).
- `DBAMV.UNID_INT` (alias `u`): Unidades de internação (`CD_UNID_INT`, `DS_UNID_INT`, `CD_SETOR`).
- `DBAMV.ORI_ATE` (alias `o`): Origem do atendimento (`CD_ORI_ATE`, `DS_ORI_ATE`, `CD_SETOR`).
- `DBAMV.MOT_ALT` (alias `m`): Motivo de alta (`CD_MOT_ALT`, `DS_MOT_ALT`).
- `DBAMV.SETOR` (alias `s`): Setores (`CD_SETOR`, `NM_SETOR`).

## Exemplo de junção implícita (padrão MV)
```sql
SELECT u.ds_unid_int, COUNT(DISTINCT a.cd_atendimento) AS qtd_atendimentos
FROM dbamv.atendime a, dbamv.leito l, dbamv.unid_int u
WHERE a.cd_leito = l.cd_leito
  AND l.cd_unid_int = u.cd_unid_int
  AND a.tp_atendimento = 'I'
  AND TRUNC(a.dt_atendimento) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))
GROUP BY u.ds_unid_int
```
