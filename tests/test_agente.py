"""Agente de ponta a ponta com um modelo FALSO (sem API, sem custo) e Postgres real.

O modelo falso é um "oráculo": consulta a ferramenta certa e conclui o que o gabarito
manda. Assim o teste prova o encanamento (ferramentas, checagem, pausa para aprovação,
retomada e gravação), não a inteligência do Claude. A inteligência se mede com
`python -m app.agente` e a API de verdade.
"""
import re
from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from app import avaliar
from app.agente import investigar_todos
from app.conciliar import conciliar
from app.db import connect
from app.gerar_dados import gerar, gravar
from app.grafo import Proposta, build_graph, validar_proposta
from app.revisar import revisar

try:
    connect().close()
    TEM_BANCO = True
except Exception:
    TEM_BANCO = False

pytestmark = pytest.mark.skipif(not TEM_BANCO, reason="sem Postgres")
D = date(2026, 11, 16)


class Oraculo:
    def __init__(self, respostas):  # pagamento_id -> (cliente_id | None, [notas])
        self.respostas = respostas

    def bind_tools(self, _):
        return self

    def with_structured_output(self, _, **__):
        oraculo = self

        class S:
            def invoke(self, msgs):
                _, notas = oraculo.respostas[oraculo._pid(msgs)]
                return Proposta(nota_numeros=notas, confianca="alta", justificativa="oráculo de teste")
        return S()

    def _pid(self, msgs):
        h = next(m for m in msgs if isinstance(m, HumanMessage))
        return int(re.search(r"Pagamento #(\d+)", h.content).group(1))

    def invoke(self, msgs):
        pid = self._pid(msgs)
        cliente, _ = self.respostas[pid]
        valor = re.search(r"R\$ ([\d.]+)", msgs[1].content).group(1)
        if cliente and not any(isinstance(m, ToolMessage) for m in msgs):
            return AIMessage("", tool_calls=[{"id": f"t{pid}", "name": "combinacoes_de_notas",
                                              "args": {"cliente_id": cliente, "valor": valor}}])
        return AIMessage("Concluído.")


def test_checagem_reprova_soma_errada():
    gravar(gerar(7, D))
    with connect() as conn:
        n = conn.execute("SELECT numero, valor FROM notas_fiscais ORDER BY id LIMIT 1").fetchone()
        assert validar_proposta(conn, {"valor": str(n["valor"] + 1)}, [n["numero"]])["valida"] is False
        assert validar_proposta(conn, {"valor": "1"}, [999999])["problema"] == "nota inexistente ou cancelada"


def test_agente_com_aprovacao_humana_fecha_em_100():
    dados = gerar(7, D)
    gravar(dados)
    conciliar(D)  # linha de base: só regras
    with connect() as conn:
        cliente_da_nota = {r["numero"]: r["cliente_id"] for r in conn.execute(
            "SELECT n.numero, c.cliente_id FROM notas_fiscais n JOIN contratos c ON c.id = n.contrato_id")}
    respostas = {l["pagamento_id"]: (cliente_da_nota[l["notas"][0]] if l["notas"] else None, l["notas"])
                 for l in dados["ligacoes"]}

    graph = build_graph(Oraculo(respostas), InMemorySaver())
    casos = investigar_todos(graph, D)
    assert {c["id"] for c in casos} == set(respostas)

    with connect() as conn:
        props = conn.execute("SELECT * FROM propostas_agente").fetchall()
    assert len(props) == len(respostas) and all(p["valida"] for p in props)
    assert all(p["status"] == "pendente" for p in props)  # nada gravado sem humano

    revisar(graph, entrada=lambda _: "a", data_base=D)    # pessoa aprova tudo

    _, divs = conciliar(D)
    r = avaliar.avaliar(divs, dados["gabarito"])["geral"]
    assert r["precisao"] == 1.0 and r["recall"] == 1.0
