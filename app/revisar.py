"""Revisão humana das propostas do agente (human-in-the-loop).

    python -m app.revisar

Para cada proposta pendente: [a]provar, [r]ejeitar, [e]ditar as notas ou [p]ular.
A decisão retoma a thread pausada no Redis com Command(resume=...), e o grafo segue
para o nó `gravar`. No fim, a conciliação roda de novo e mostra o efeito.
"""
from __future__ import annotations

from datetime import date

from langgraph.types import Command

from . import avaliar, observabilidade
from .conciliar import conciliar
from .db import connect
from .grafo import validar_proposta


def _ler_notas(texto: str) -> list[int]:
    return [int(x) for x in texto.replace(";", ",").replace(" ", ",").split(",") if x.strip()]


def revisar(graph, entrada=input, data_base: date = date(2026, 11, 16)) -> None:
    with connect() as conn:
        props = conn.execute(
            """SELECT pa.*, p.data, p.valor, p.cnpj_pagador, p.referencia
               FROM propostas_agente pa JOIN pagamentos p ON p.id = pa.pagamento_id
               WHERE pa.status = 'pendente' ORDER BY pa.pagamento_id""").fetchall()
    if not props:
        print("Nenhuma proposta pendente.")
        return
    print(f"\n{len(props)} propostas para revisar\n")
    for pr in props:
        notas = ", ".join(map(str, pr["nota_numeros"])) or "não identificado"
        print("-" * 70)
        print(f"Pagamento #{pr['pagamento_id']}: R$ {pr['valor']} em {pr['data']} | CNPJ {pr['cnpj_pagador']}")
        print(f"Referência: \"{pr['referencia']}\"")
        print(f"Agente propõe: {notas}  (confiança {pr['confianca']})")
        print(f"Justificativa: {pr['justificativa']}")
        print("Checagem automática: " + ("ok" if pr["valida"] else f"REPROVADA ({pr['problema']})"))
        while True:
            op = entrada("[a]provar  [r]ejeitar  [e]ditar notas  [p]ular > ").strip().lower()[:1]
            if op in ("a", "r", "p"):
                if op == "a" and not pr["valida"]:
                    print("Não dá para aprovar uma proposta reprovada na checagem. Edite ou rejeite.")
                    continue
                break
            if op == "e":
                try:
                    numeros = _ler_notas(entrada("Números das notas, separados por vírgula: "))
                except ValueError:
                    print("Use só números, ex.: 1045, 1078")
                    continue
                with connect() as conn:
                    v = validar_proposta(conn, {"valor": pr["valor"]}, numeros)
                if v["valida"]:
                    break
                print(f"Não fecha: {v['problema']}")
        if op == "p":
            continue
        decisao = {"aprovar": op in ("a", "e")}
        if op == "e":
            decisao["nota_numeros"] = numeros
        thread = pr["thread_id"]
        with observabilidade.rastrear(thread, "revisao-humana", ["conciliador", "revisao"]) as cbs:
            graph.invoke(Command(resume=decisao), {"configurable": {"thread_id": thread}, "callbacks": cbs})
        if not decisao["aprovar"]:
            print("Rejeitado: o pagamento continua na fila.")
        elif decisao.get("nota_numeros", pr["nota_numeros"]):
            print("Ligação gravada.")
        else:
            print("Confirmado como não identificado.")

    _, divs = conciliar(data_base)
    gab = avaliar.carregar_gabarito()
    if gab:
        print("\nConciliação depois da revisão:")
        avaliar.imprimir(avaliar.avaliar(divs, gab))


def main() -> None:
    from .agente import checkpointer, make_llm
    from .grafo import build_graph

    with checkpointer() as cp:
        revisar(build_graph(make_llm(), cp))
    observabilidade.fechar()


if __name__ == "__main__":
    main()
