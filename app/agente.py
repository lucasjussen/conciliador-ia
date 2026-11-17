"""Roda o agente sobre todos os pagamentos que as regras não conseguiram ligar.

    python -m app.agente                 investiga e deixa as propostas pendentes de aprovação
    python -m app.agente --revisar-aqui  investiga e já abre a revisão no mesmo terminal

Cada pagamento vira uma thread no checkpointer (Redis): `pagamento-<id>`. O grafo para
em `revisao_humana`; a aprovação pode ser feita depois com `python -m app.revisar`.
No fim, compara as propostas com o gabarito (acerto do agente ANTES da revisão humana).
"""
from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from datetime import date

from . import casamento, observabilidade
from .avaliar import GABARITO
from .db import apply_sql, connect
from .grafo import build_graph

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")


def make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), max_tokens=1500)


@contextmanager
def checkpointer(memoria: bool = False):
    """Redis em uso normal; memória só para testes ou demonstração num processo só."""
    if memoria:
        from langgraph.checkpoint.memory import InMemorySaver
        yield InMemorySaver()
        return
    from langgraph.checkpoint.redis import RedisSaver
    with RedisSaver.from_conn_string(REDIS_URL, ttl={"default_ttl": 60 * 24 * 30}) as saver:
        saver.setup()
        yield saver


def pendentes(conn) -> list[dict]:
    """Pagamentos sem nota ligada e ainda sem proposta do agente."""
    rows = conn.execute(
        """SELECT p.id, p.data, p.valor, p.cnpj_pagador, p.referencia FROM pagamentos p
           WHERE NOT EXISTS (SELECT 1 FROM conciliacao_pagamentos cp
                             WHERE cp.pagamento_id = p.id AND cp.nota_id IS NOT NULL)
             AND NOT EXISTS (SELECT 1 FROM propostas_agente pa WHERE pa.pagamento_id = p.id)
           ORDER BY p.id""").fetchall()
    # strings: o estado vai para o checkpointer e para o Langfuse, então nada de Decimal/date
    return [{**r, "data": str(r["data"]), "valor": str(r["valor"])} for r in rows]


def investigar_todos(graph, data_base: date) -> list[dict]:
    with connect() as conn:
        apply_sql(conn, "regras.sql")
        casamento.executar(conn, data_base)
        casos = pendentes(conn)
    print(f"{len(casos)} pagamentos para investigar\n")
    for pag in casos:
        thread = f"pagamento-{pag['id']}"
        with observabilidade.rastrear(thread, "investigar-pagamento", ["conciliador", "agente"]) as cbs:
            estado = graph.invoke({"pagamento": pag}, {"configurable": {"thread_id": thread}, "callbacks": cbs})
        p, v = estado["proposta"], estado["validacao"]
        notas = ", ".join(map(str, p["nota_numeros"])) or "não identificado"
        alerta = "" if v["valida"] else f"  [REPROVADA NA CHECAGEM: {v['problema']}]"
        print(f"#{pag['id']:<4} {pag['referencia'][:32]:32} -> {notas:16} ({p['confianca']}){alerta}")
    return casos


def avaliar_agente() -> None:
    if not GABARITO.exists():
        return
    esperado = {l["pagamento_id"]: (sorted(l["notas"]), l.get("caso", "SEM_NOTA"))
                for l in json.loads(GABARITO.read_text(encoding="utf-8")).get("ligacoes", [])}
    with connect() as conn:
        props = {r["pagamento_id"]: sorted(r["nota_numeros"])
                 for r in conn.execute("SELECT pagamento_id, nota_numeros FROM propostas_agente").fetchall()}
    linhas = [(pid, caso, props.get(pid), notas) for pid, (notas, caso) in esperado.items()]
    certos = sum(1 for _, _, prop, notas in linhas if prop == notas)
    print(f"\nAcerto do agente (antes da revisão humana): {certos}/{len(linhas)}")
    for pid, caso, prop, notas in linhas:
        ok = "ok " if prop == notas else "ERRO"
        print(f"  {ok} #{pid:<4} {caso:9} esperado {notas or 'não identificado'}, proposto {prop if prop else 'não identificado'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-base", type=date.fromisoformat, default=date(2026, 11, 16))
    ap.add_argument("--revisar-aqui", action="store_true", help="revisa no mesmo processo (aceita checkpointer em memória)")
    ap.add_argument("--memoria", action="store_true", help="usa checkpointer em memória em vez do Redis")
    a = ap.parse_args()
    with checkpointer(a.memoria) as cp:
        graph = build_graph(make_llm(), cp)
        investigar_todos(graph, a.data_base)
        avaliar_agente()
        if a.revisar_aqui:
            from .revisar import revisar
            revisar(graph)
        else:
            print("\nPróximo passo: python -m app.revisar")
    observabilidade.fechar()


if __name__ == "__main__":
    main()
