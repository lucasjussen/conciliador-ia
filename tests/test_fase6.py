"""Fase 6: as visões do painel batem com o serviço e o histórico olha o passado direito."""
from datetime import date

import psycopg

from app import bi, servico
from app.db import DATABASE_URL, connect


def test_painel_bate_com_a_api():
    bi.preencher(date(2026, 11, 1), date(2026, 11, 16))
    with connect() as conn:
        painel = conn.execute("SELECT count(*) n, sum(valor_em_risco) r FROM vw_bi_divergencias").fetchone()
        hist = conn.execute("""SELECT sum(quantidade) n, sum(valor_em_risco) r FROM historico_conciliacao
                               WHERE data_base = '2026-11-16'""").fetchone()
    divs = servico.listar_divergencias(date(2026, 11, 16), limite=1000)
    api = servico.resumo(divs, date(2026, 11, 16))
    assert painel["n"] == hist["n"] == api["total"]
    assert round(float(painel["r"]), 2) == round(float(hist["r"]), 2) == api["valor_em_risco"]


def test_historico_nao_enxerga_o_futuro():
    with connect() as conn:
        n = conn.execute("""SELECT count(*) n FROM divergencias('2026-11-01') d
                            JOIN notas_fiscais nf ON nf.numero = d.nota_numero
                            WHERE nf.emissao > '2026-11-01'""").fetchone()["n"]
    assert n == 0


def test_usuario_do_painel_so_le():
    url = DATABASE_URL.replace("conc:conc@", "powerbi:powerbi@")
    with psycopg.connect(url) as c:
        assert c.execute("SELECT count(*) FROM vw_bi_divergencias").fetchone()[0] > 0
        try:
            c.execute("DELETE FROM pagamentos")
            raise AssertionError("o usuário do painel conseguiu apagar dados")
        except psycopg.errors.InsufficientPrivilege:
            pass
