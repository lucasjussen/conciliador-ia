"""Ferramentas que o agente pode chamar. Todas são SOMENTE LEITURA.

Decisões que valem defender:
- O agente não escreve no banco. Ele só consulta; quem grava é o nó `gravar`,
  depois da aprovação humana.
- O agente não faz conta. Somar notas para achar um pagamento agrupado é trabalho
  da ferramenta `combinacoes_de_notas` (código determinístico). LLM erra soma;
  SQL e Python não.
- Respostas curtas e estruturadas (listas de dicts) para gastar pouco token.
"""
from itertools import combinations
from decimal import Decimal

from langchain_core.tools import tool

from .db import connect

LIMITE = 15  # no máximo isso de linhas por resposta: protege o contexto do modelo


def _rows(sql: str, params: tuple) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{k: (str(v) if not isinstance(v, (int, str, type(None))) else v) for k, v in r.items()} for r in rows]


@tool
def buscar_clientes(texto: str) -> list[dict]:
    """Procura clientes pelo nome (parte do nome serve) ou pelo começo do CNPJ.
    Para achar a empresa de uma filial, passe só os 8 primeiros dígitos do CNPJ (a raiz)."""
    digitos = "".join(ch for ch in texto if ch.isdigit())
    return _rows(
        """SELECT cl.id AS cliente_id, cl.nome, cl.cnpj, count(c.id) AS contratos
           FROM clientes cl LEFT JOIN contratos c ON c.cliente_id = cl.id
           WHERE cl.nome ILIKE %s OR (%s <> '' AND cl.cnpj LIKE %s)
           GROUP BY cl.id ORDER BY cl.nome LIMIT %s""",
        (f"%{texto.strip()}%", digitos, f"{digitos}%", LIMITE),
    )


_SQL_ABERTAS = """
    SELECT n.numero, n.competencia, n.valor, n.vencimento, c.id AS contrato_id, c.descricao
    FROM notas_fiscais n JOIN contratos c ON c.id = n.contrato_id
    WHERE c.cliente_id = %s AND NOT n.cancelada
      AND NOT EXISTS (SELECT 1 FROM conciliacao_pagamentos cp WHERE cp.nota_id = n.id)
    ORDER BY n.competencia, n.numero
"""


@tool
def notas_em_aberto(cliente_id: int) -> list[dict]:
    """Lista as notas do cliente que ainda não têm nenhum pagamento ligado."""
    return _rows(_SQL_ABERTAS + " LIMIT %s", (cliente_id, LIMITE))


@tool
def combinacoes_de_notas(cliente_id: int, valor: str) -> list[dict]:
    """Encontra combinações de 1 a 3 notas em aberto do cliente cuja soma é EXATAMENTE
    o valor informado (ex.: "3120.00"). Use para pagamentos que podem quitar mais de uma nota.
    Lista vazia = nenhuma combinação fecha o valor."""
    alvo = Decimal(str(valor))
    with connect() as conn:
        abertas = conn.execute(_SQL_ABERTAS, (cliente_id,)).fetchall()
    achadas = []
    for k in (1, 2, 3):
        for combo in combinations(abertas, k):
            if abs(sum(n["valor"] for n in combo) - alvo) <= Decimal("0.01"):
                achadas.append({"notas": [n["numero"] for n in combo],
                                "competencias": [str(n["competencia"]) for n in combo]})
    return achadas[:LIMITE]


@tool
def pagamentos_do_pagador(cnpj: str) -> list[dict]:
    """Histórico de pagamentos feitos por um CNPJ e a quais clientes eles foram ligados."""
    return _rows(
        """SELECT p.id, p.data, p.valor, p.referencia, cl.nome AS cliente_ligado
           FROM pagamentos p
           LEFT JOIN conciliacao_pagamentos cp ON cp.pagamento_id = p.id AND cp.nota_id IS NOT NULL
           LEFT JOIN notas_fiscais n ON n.id = cp.nota_id
           LEFT JOIN contratos c ON c.id = n.contrato_id
           LEFT JOIN clientes cl ON cl.id = c.cliente_id
           WHERE p.cnpj_pagador = %s ORDER BY p.data DESC LIMIT %s""",
        (cnpj, LIMITE),
    )


FERRAMENTAS = [buscar_clientes, notas_em_aberto, combinacoes_de_notas, pagamentos_do_pagador]
