"""Fórmulas do dashboard de Feedback/NPS (layout fixo da Diretoria). Fixa a INTERPRETAÇÃO do CSV cru
para podermos validar/ajustar os números com segurança."""
from analise_planilha import feedback

CABECALHO = ("Nome,Data de Nascimento,Escala de Recomendação,Tempo para Atendimento,"
             "Atingiu as Expectativas?,Serviço(s) utilizado(s),Data de envio")


def _csv(*linhas: str) -> str:
    return "\n".join([CABECALHO, *linhas])


def test_reconhece_feedback_pelas_colunas():
    assert feedback.e_feedback(CABECALHO.split(","))
    assert not feedback.e_feedback(["Conta", "Valor", "Mês"])


def test_total_atendimentos_editavel_vira_campo():
    rows = feedback.ler_csv(_csv('A,,9,bom,sim,Concierge,2026-09-14 10:00:00'))
    d = feedback.calcular(rows)
    # sem edição: mostra o valor cru
    assert "SETEMBRO DE 2026: 4428" in feedback.render_html(d, "SETEMBRO DE 2026", 4428)
    # editável e vazio: vira input para o usuário preencher à mão, apontando para a rota de salvar
    editavel = feedback.render_html(d, "SETEMBRO DE 2026", None, fragmento=True, editavel=True, slug="feedback-nps")
    assert 'id="fb-aten"' in editavel
    assert "/web/r/feedback-nps/feedback/atendimentos" in editavel


def test_nps_faixas_e_sem_resposta():
    rows = feedback.ler_csv(_csv(
        'A,,6,bom,sim,Concierge,2026-09-01 10:00:00',    # detrator (0-6)
        'B,,7,regular,sim,Concierge,2026-09-01 10:00:00',  # neutro (7-8)
        'C,,8,bom,sim,Concierge,2026-09-01 10:00:00',      # neutro
        'D,,9,ótimo,sim,Concierge,2026-09-01 10:00:00',    # promotor (9-10)
        'E,,10,ótimo,não,Concierge,2026-09-01 10:00:00',   # promotor
        'F,,,bom,sim,Concierge,2026-09-01 10:00:00',       # sem resposta (escala vazia)
    ))
    d = feedback.calcular(rows)
    assert (d["det"], d["neu"], d["pro"], d["sem"]) == (1, 2, 2, 1)
    assert d["total"] == 6
    assert feedback.pct(d["pro"], d["total"]) == 33     # 2/6


def test_tempo_e_expectativas():
    rows = feedback.ler_csv(_csv(
        'A,,9,ruim,sim,Concierge,2026-09-01 10:00:00',
        'B,,9,regular,não,Concierge,2026-09-01 10:00:00',
        'C,,9,bom,sim,Concierge,2026-09-01 10:00:00',
        'D,,9,ótimo,sim,Concierge,2026-09-01 10:00:00',
    ))
    d = feedback.calcular(rows)
    assert dict(d["tempo"]) == {"ruim": 1, "regular": 1, "bom": 1, "ótimo": 1}
    assert (d["exp_sim"], d["exp_nao"]) == (3, 1)


def test_servico_multivalorado_conta_por_item():
    rows = feedback.ler_csv(_csv(
        'A,,9,bom,sim,"Concierge, Enfermagem Pronto Atendimento",2026-09-01 10:00:00',
        'B,,9,bom,não,Concierge,2026-09-01 10:00:00',
    ))
    d = feedback.calcular(rows)
    assert d["serv"]["Concierge"] == {"sim": 1, "nao": 1}
    assert d["serv"]["Enfermagem Pronto Atendimento"] == {"sim": 1, "nao": 0}


def test_periodo_do_mes_mais_frequente():
    rows = feedback.ler_csv(_csv(
        'A,,9,bom,sim,Concierge,2026-09-14 10:00:00',
        'B,,9,bom,sim,Concierge,2026-09-15 10:00:00',
    ))
    assert feedback.periodo(rows) == "SETEMBRO DE 2026"


def test_ler_csv_robusto_nao_quebra():
    # CSV normal (não feedback) com campo multilinha entre aspas — não pode estourar e não é feedback
    rows = feedback.ler_csv('Conta,Obs\n"100","linha1\nlinha2"\n')
    assert len(rows) == 1
    assert not feedback.e_feedback(rows[0].keys())
    # conteúdo binário (ex.: xlsx) — decodifica sem crashar e não é reconhecido como feedback
    import os
    r = feedback.ler_csv(os.urandom(256))
    assert not (r and feedback.e_feedback(r[0].keys()))


def test_render_html_tem_as_quatro_paginas():
    rows = feedback.ler_csv(_csv('A,,9,bom,sim,Concierge,2026-09-14 10:00:00'))
    html = feedback.render_html(feedback.calcular(rows), feedback.periodo(rows), 4428)
    assert html.count('class="pg') == 4
    assert "NPS (Net Promoter Score)" in html
    assert "TOTAL DE ATENDIMENTOS EM SETEMBRO DE 2026: 4428" in html
