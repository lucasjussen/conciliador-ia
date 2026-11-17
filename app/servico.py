"""Camada de serviço: as consultas que a API e o servidor MCP oferecem.

As duas portas de entrada (HTTP e MCP) chamam as mesmas funções daqui, então a regra de
negócio existe em um lugar só. Tudo devolve tipos simples (str, int, float, listas e
dicts), prontos para virar JSON.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

from .db import connect

TIPOS = ("NOTA_FALTANTE", "NOTA_DUPLICADA", "VALOR_DIVERGENTE", "PAGAMENTO_DIVERGENTE",
         "NAO_PAGO_VENCIDO", "PAGAMENTO_NAO_IDENTIFICADO")


def data_base_padrao() -> date:
    """DATA_BASE no .env fixa a data dos dados fictícios (2026-11-16); sem ela, usa hoje."""
    v = os.getenv("DATA_BASE")
    return date.fromisoformat(v) if v else date.today()


def _json(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _linhas(rows) -> list[dict]:
    return [{k: _json(v) for k, v in r.items()} for r in rows]


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def valor_em_risco(divs: list[dict]) -> float:
    """Dinheiro que pode não entrar: nota vencida sem pagamento, nota que nem foi emitida e
    diferença paga a menor. VALOR_DIVERGENTE fica de fora (é erro de emissão, não de recebimento)."""
    total = 0.0
    for d in divs:
        esp, enc = d.get("valor_esperado") or 0, d.get("valor_encontrado") or 0
        if d["tipo"] in ("NAO_PAGO_VENCIDO", "NOTA_FALTANTE"):
            total += esp
        elif d["tipo"] == "PAGAMENTO_DIVERGENTE" and enc < esp:
            total += esp - enc
    return round(total, 2)


def listar_divergencias(data_base: date | None = None, tipo: str | None = None, limite: int = 100) -> list[dict]:
    """Só leitura: consulta a função SQL sem rodar o casamento de pagamentos de novo."""
    if tipo and tipo not in TIPOS:
        raise ValueError(f"tipo inválido; use um de {', '.join(TIPOS)}")
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM divergencias(%s) WHERE %s::text IS NULL OR tipo = %s ORDER BY tipo, ref LIMIT %s",
            (data_base or data_base_padrao(), tipo, tipo, limite)).fetchall()
    return _linhas(rows)


def resumo(divs: list[dict], data_base: date) -> dict:
    por_tipo = {t: sum(1 for d in divs if d["tipo"] == t) for t in TIPOS}
    risco = valor_em_risco(divs)
    linhas = "".join(f"<tr><td>{t}</td><td align='right'>{n}</td></tr>" for t, n in por_tipo.items() if n)
    return {
        "data_base": data_base.isoformat(),
        "total": len(divs),
        "por_tipo": por_tipo,
        "valor_em_risco": risco,
        "texto": f"{len(divs)} divergências, {brl(risco)} em risco",
        "html": (f"<p><b>Conciliação de {data_base:%d/%m/%Y}</b>: {len(divs)} divergências, "
                 f"{brl(risco)} em risco.</p><table border='1' cellpadding='4' cellspacing='0'>"
                 f"<tr><th>tipo</th><th>qtd</th></tr>{linhas}</table>"),
    }


def executar_conciliacao(data_base: date | None = None) -> dict:
    """Escreve: refaz o casamento de pagamentos (idempotente) e devolve o resumo."""
    from .conciliar import conciliar

    d = data_base or data_base_padrao()
    _, divs = conciliar(d)
    divs = _linhas(divs)
    return {**resumo(divs, d), "divergencias": divs}


def propostas_pendentes() -> list[dict]:
    with connect() as conn:
        return _linhas(conn.execute(
            """SELECT pa.pagamento_id, p.valor, p.referencia, pa.nota_numeros, pa.confianca, pa.justificativa,
                      pa.valida, pa.problema
               FROM propostas_agente pa JOIN pagamentos p ON p.id = pa.pagamento_id
               WHERE pa.status = 'pendente' ORDER BY pa.pagamento_id""").fetchall())


def listar_documentos(status: str | None = None) -> list[dict]:
    with connect() as conn:
        return _linhas(conn.execute(
            """SELECT arquivo, assunto, tipo, notas_citadas, status, detalhe FROM documentos
               WHERE %s::text IS NULL OR status = %s ORDER BY arquivo""", (status, status)).fetchall())


def buscar_clientes(texto: str) -> list[dict]:
    from .ferramentas import buscar_clientes as tool
    return tool.invoke({"texto": texto})


def notas_em_aberto(cliente_id: int) -> list[dict]:
    from .ferramentas import notas_em_aberto as tool
    return tool.invoke({"cliente_id": cliente_id})
