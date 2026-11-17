"""Casamento pagamento -> nota fiscal.

É a parte "difícil" da conciliação: o extrato só traz CNPJ, valor, data e uma
referência em texto livre. Duas regras determinísticas, em ordem de confiança:

  1. numero:     a referência cita o número da nota ("NF 1023", "nota 1023") e o
                 CNPJ do pagador é o do cliente da nota.

 2. ler_data:   ler MM/AAAA na referência e ligue o pagamento à nota daquela competência e daquele cnpj.
 
  3. cnpj_valor: mesmo CNPJ e valor exato de uma nota ainda em aberto; havendo
                 mais de uma, a de competência mais antiga (FIFO).

O que não casa fica com nota_id NULL e vira PAGAMENTO_NAO_IDENTIFICADO.
Esses casos são a fila do agente de IA na fase 2.
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

NF_RE = re.compile(r"\b(?:nf|nfs-?e|nota)\D{0,4}(\d{3,7})\b", re.IGNORECASE)

MES_RE = re.compile(r"\b(0[1-9]|1[0-2])/(20\d{2})\b")


def competencia_citada(referencia):
    m = MES_RE.search(referencia or "")
    if not m:
        return None
    mes, ano = int(m.group(1)), int(m.group(2))
    return date(ano, mes, 1)


@dataclass
class Match:
    pagamento_id: int
    nota_id: Optional[int]
    metodo: Optional[str]


def numero_citado(referencia: str) -> Optional[int]:
    m = NF_RE.search(referencia or "")
    return int(m.group(1)) if m else None


def casar(notas: list[dict], pagamentos: list[dict]) -> list[Match]:
    """Função pura (listas de dicts in, lista de Match out): testável sem banco."""
    por_numero = {n["numero"]: n for n in notas}
    abertas = sorted(notas, key=lambda n: (n["competencia"], n["numero"]))
    usadas_por_valor: set[int] = set()
    out: list[Match] = []

    for p in sorted(pagamentos, key=lambda p: (p["data"], p["id"])):
        num = numero_citado(p["referencia"])
        nota = por_numero.get(num) if num else None
        if nota and nota["cnpj"] == p["cnpj_pagador"]:
            out.append(Match(p["id"], nota["id"], "numero"))
            usadas_por_valor.add(nota["id"])
            continue
        comp = competencia_citada(p["referencia"])
        if comp:
            candidatas = [
                n for n in abertas
                if n["id"] not in usadas_por_valor
                and n["cnpj"] == p["cnpj_pagador"]
                and n["competencia"] == comp
            ]
            if candidatas:
                # cliente com 2 contratos: prefere a nota de mesmo valor
                cand = next((n for n in candidatas if n["valor"] == p["valor"]), candidatas[0])
                out.append(Match(p["id"], cand["id"], "competencia"))
                usadas_por_valor.add(cand["id"])
                continue
        
        cand = next(
            (n for n in abertas
             if n["id"] not in usadas_por_valor
             and n["cnpj"] == p["cnpj_pagador"]
             and n["valor"] == p["valor"]
             and n["emissao"] <= p["data"]),
            None,
        )
        if cand:
            out.append(Match(p["id"], cand["id"], "cnpj_valor"))
            usadas_por_valor.add(cand["id"])
        else:
            out.append(Match(p["id"], None, None))
    return out


def executar(conn, data_base) -> dict[str, int]:
    """Lê do banco, casa e grava em conciliacao_pagamentos. Idempotente."""
    notas = conn.execute(
        """SELECT n.id, n.numero, n.valor, n.competencia, n.emissao, cl.cnpj
           FROM notas_fiscais n JOIN contratos c ON c.id = n.contrato_id
           JOIN clientes cl ON cl.id = c.cliente_id
           WHERE NOT n.cancelada"""
    ).fetchall()
    pagamentos = conn.execute(
        "SELECT id, data, valor, cnpj_pagador, referencia FROM pagamentos WHERE data <= %s", (data_base,)
    ).fetchall()
    matches = casar(notas, pagamentos)
    with conn.cursor() as cur:
        # preserva decisões tomadas por humano/agente (fase 2); refaz só as automáticas
        cur.execute("DELETE FROM conciliacao_pagamentos WHERE metodo IS DISTINCT FROM 'agente'")
        cur.executemany(
            """INSERT INTO conciliacao_pagamentos (pagamento_id, nota_id, metodo) VALUES (%s, %s, %s)
               ON CONFLICT (pagamento_id) DO NOTHING""",
            [(m.pagamento_id, m.nota_id, m.metodo) for m in matches],
        )
    conn.commit()
    resumo: dict[str, int] = {}
    for m in matches:
        k = m.metodo or "nao_identificado"
        resumo[k] = resumo.get(k, 0) + 1
    return resumo
