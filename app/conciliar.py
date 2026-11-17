"""Executa a conciliação de ponta a ponta.

    python -m app.conciliar --data-base 2026-11-16

1. casa pagamentos com notas (app/casamento.py)
2. roda as regras SQL (db/regras.sql -> divergencias())
3. grava data/divergencias.csv e, se houver gabarito, mede precisão e recall
"""
import argparse
import csv
from datetime import date
from pathlib import Path

from . import avaliar, casamento
from .db import apply_sql, connect

OUT = Path(__file__).resolve().parents[1] / "data" / "divergencias.csv"


def conciliar(data_base: date) -> tuple[dict, list[dict]]:
    with connect() as conn:
        apply_sql(conn, "regras.sql", "bi.sql")  # garante a versão atual das regras e das visões do painel
        resumo = casamento.executar(conn, data_base)
        divs = conn.execute("SELECT * FROM divergencias(%s) ORDER BY tipo, ref", (data_base,)).fetchall()
        conn.execute("SELECT registrar_historico(%s)", (data_base,))  # retrato do dia para o painel
        conn.commit()
    return resumo, divs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-base", type=date.fromisoformat, default=date(2026, 11, 16))
    a = ap.parse_args()
    resumo, divs = conciliar(a.data_base)

    print("Casamento de pagamentos:", ", ".join(f"{k}={v}" for k, v in sorted(resumo.items())))
    print(f"{len(divs)} divergências encontradas")
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(divs[0].keys()) if divs else ["tipo"])
        w.writeheader()
        w.writerows(divs)
    print(f"-> {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")

    gab = avaliar.carregar_gabarito()
    if gab:
        avaliar.imprimir(avaliar.avaliar(divs, gab))


if __name__ == "__main__":
    main()
