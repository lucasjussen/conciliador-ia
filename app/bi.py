"""Fase 6: prepara o banco para o Power BI.

    python -m app.bi                                  histórico de 15/10 a 16/11/2026
    python -m app.bi --de 2026-11-01 --ate 2026-11-16

Aplica as visões (db/bi.sql), roda a conciliação na data final e grava um retrato por dia
no histórico, olhando o banco como ele estava em cada data. Em uso real, quem grava o
retrato diário é a própria conciliação (API chamada pelo n8n toda manhã).
"""
import argparse
from datetime import date, timedelta

from . import casamento
from .db import apply_sql, connect


def preencher(de: date, ate: date) -> int:
    with connect() as conn:
        apply_sql(conn, "regras.sql", "bi.sql")
        casamento.executar(conn, ate)
        d, dias = de, 0
        while d <= ate:
            conn.execute("SELECT registrar_historico(%s)", (d,))
            d += timedelta(days=1)
            dias += 1
        conn.commit()
    return dias


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", type=date.fromisoformat, default=date(2026, 10, 15))
    ap.add_argument("--ate", type=date.fromisoformat, default=date(2026, 11, 16))
    a = ap.parse_args()
    dias = preencher(a.de, a.ate)
    with connect() as conn:
        r = conn.execute("""SELECT data_base, sum(quantidade) AS divergencias, sum(valor_em_risco) AS risco
                            FROM historico_conciliacao WHERE data_base IN (%s, %s)
                            GROUP BY data_base ORDER BY data_base""", (a.de, a.ate)).fetchall()
        n = conn.execute("SELECT count(*) AS n FROM vw_bi_divergencias").fetchone()["n"]
    print(f"{dias} dias no histórico ({a.de:%d/%m} a {a.ate:%d/%m})")
    for x in r:
        risco = f"{x['risco']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        print(f"  {x['data_base']:%d/%m/%Y}: {x['divergencias']} divergências, R$ {risco} em risco")
    print(f"vw_bi_divergencias: {n} linhas na data de referência")
    print("Pronto para o Power BI: usuário 'powerbi' (somente leitura), banco 'conciliador', 127.0.0.1:5432")


if __name__ == "__main__":
    main()
