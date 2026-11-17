"""Gera uma base fictícia de faturamento com erros PLANTADOS e um gabarito.

Por que plantar erros: sem gabarito não dá para medir nada. Com ele, cada versão
do conciliador (só regras, regras + agente, agente com outro prompt...) recebe
uma nota objetiva de precisão e recall. É a base das evals do projeto.

Uso:  python -m app.gerar_dados [--seed 7] [--data-base 2026-11-16]
"""
import argparse
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .db import apply_sql, connect

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
EMPRESAS = ["Alfa", "Brava", "Cedro", "Delta", "Esfera", "Faro", "Gaia", "Horizonte", "Ipê", "Jade",
            "Kappa", "Lumen", "Maré", "Norte", "Ômega", "Prisma", "Quartzo", "Rota", "Sigma", "Tríade",
            "Urbe", "Vértice", "Xisto", "Zênite", "Áurea", "Bússola", "Cume", "Duna"]
RAMOS = ["Logística", "Clínica", "Engenharia", "Alimentos", "Contabilidade", "Varejo", "Educação"]
SERVICOS = ["Suporte de TI mensal", "Licença de software", "Manutenção predial", "Consultoria fiscal",
            "Monitoramento", "Hospedagem e backup"]
PLANO_DE_ERROS = {  # tipo -> quantidade
    "VALOR_DIVERGENTE": 6, "NOTA_FALTANTE": 4, "NOTA_DUPLICADA": 3,
    "PAGAMENTO_DIVERGENTE": 4, "NAO_PAGO_VENCIDO": 5, "PAGAMENTO_NAO_IDENTIFICADO": 3,
}


def add_month(d: date, n: int = 1) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def cnpj(rng: random.Random) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(14))


def money(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def gerar(seed: int, data_base: date) -> dict:
    rng = random.Random(seed)
    ultimo_mes = add_month(date(data_base.year, data_base.month, 1), -1)

    clientes = [{"id": i + 1, "nome": f"{n} {rng.choice(RAMOS)} Ltda", "cnpj": cnpj(rng)}
                for i, n in enumerate(EMPRESAS)]
    contratos = []
    for cl in clientes:
        for _ in range(2 if rng.random() < 0.25 else 1):  # alguns clientes têm 2 contratos
            inicio = date(2026, rng.randint(4, 8), 1)
            fim = add_month(inicio, rng.randint(3, 4)) if rng.random() < 0.1 else None
            contratos.append({
                "id": len(contratos) + 1, "cliente_id": cl["id"], "descricao": rng.choice(SERVICOS),
                "valor_mensal": money(rng.choice([890, 1200, 1490, 2350, 3100, 4800, 7250]) + rng.randint(0, 9) * 10),
                "desconto_pct": Decimal(rng.choice([0, 0, 0, 5, 10])),
                "dia_vencimento": rng.choice([5, 10, 15, 20, 25]), "inicio": inicio, "fim": fim,
            })
    cnpj_de = {c["id"]: next(cl["cnpj"] for cl in clientes if cl["id"] == c["cliente_id"]) for c in contratos}

    # todas as competências que deveriam ter nota
    slots = []
    for c in contratos:
        m = c["inicio"]
        while m <= ultimo_mes and (c["fim"] is None or m <= c["fim"]):
            slots.append((c, m))
            m = add_month(m)
    rng.shuffle(slots)

    def venc(c, comp):
        return date(add_month(comp).year, add_month(comp).month, c["dia_vencimento"])

    # sorteia slots distintos para cada tipo de erro
    gabarito, erro_do_slot = [], {}
    livres = list(slots)
    for tipo, qtd in PLANO_DE_ERROS.items():
        if tipo == "PAGAMENTO_NAO_IDENTIFICADO":
            continue  # não depende de slot
        precisa_vencida = tipo in ("NAO_PAGO_VENCIDO", "PAGAMENTO_DIVERGENTE")
        escolhidos = [s for s in livres if not precisa_vencida or venc(*s) < data_base - timedelta(days=3)][:qtd]
        for s in escolhidos:
            livres.remove(s)
            erro_do_slot[(s[0]["id"], s[1])] = tipo
            gabarito.append({"tipo": tipo, "ref": f"C{s[0]['id']}-{s[1]:%Y-%m}"})

    notas, pagamentos, numero = [], [], 1000
    ordem_emissao = sorted(slots, key=lambda s: (s[1], s[0]["id"]))
    for c, comp in ordem_emissao:
        erro = erro_do_slot.get((c["id"], comp))
        if erro == "NOTA_FALTANTE":
            continue
        esperado = money(float(c["valor_mensal"]) * (1 - float(c["desconto_pct"]) / 100))
        valor = esperado
        if erro == "VALOR_DIVERGENTE":
            # erro típico: esqueceram o desconto, ou aplicaram reajuste que não estava no contrato
            valor = c["valor_mensal"] if c["desconto_pct"] > 0 else money(float(esperado) * 1.05)
        numero += 1
        emissao = add_month(comp)
        nota = {"id": len(notas) + 1, "numero": numero, "contrato_id": c["id"], "competencia": comp,
                "valor": valor, "emissao": emissao, "vencimento": venc(c, comp)}
        notas.append(nota)
        if erro == "NOTA_DUPLICADA":
            numero += 1
            notas.append({**nota, "id": len(notas) + 1, "numero": numero})

        # pagamento
        if erro == "NAO_PAGO_VENCIDO":
            continue
        data_pg = nota["vencimento"] + timedelta(days=rng.randint(-3, 2))
        if nota["vencimento"] < data_base:
            data_pg = min(data_pg, data_base - timedelta(days=1))
        elif data_pg > data_base:
            continue  # ainda não venceu nem foi pago: normal
        valor_pg = nota["valor"]
        estilo = rng.random()
        ref = (f"NF {nota['numero']}" if estilo < .55 else
               f"Pagto NF{nota['numero']}" if estilo < .70 else
               f"Ref. nota {nota['numero']}" if estilo < .85 else
               f"Mensalidade {comp:%m/%Y}")
        if erro == "PAGAMENTO_DIVERGENTE":
            valor_pg = money(float(nota["valor"]) * rng.choice([0.95, 0.9, 0.85]))  # reteve imposto / desconto por conta própria
            if sum(1 for g in gabarito if g["tipo"] == "PAGAMENTO_DIVERGENTE" and g.get("sem_ref")) == 0:
                ref = f"Mensalidade {comp:%m/%Y}"  # um caso sem número: as regras não conseguem casar
                next(g for g in gabarito if g["ref"] == f"C{c['id']}-{comp:%Y-%m}")["sem_ref"] = True
        pagamentos.append({"id": len(pagamentos) + 1, "data": data_pg, "valor": valor_pg,
                           "cnpj_pagador": cnpj_de[c["id"]], "referencia": ref, "_nota": nota["numero"]})

    # entradas no extrato sem nota correspondente
    for _ in range(PLANO_DE_ERROS["PAGAMENTO_NAO_IDENTIFICADO"]):
        cl = rng.choice(clientes)
        pid = len(pagamentos) + 1
        pagamentos.append({"id": pid, "data": data_base - timedelta(days=rng.randint(5, 60)),
                           "valor": money(rng.randint(150, 900) + 0.37), "cnpj_pagador": cl["cnpj"],
                           "referencia": rng.choice(["Adiantamento", f"NF {rng.randint(9000, 9999)}", "Acerto"])})
        gabarito.append({"tipo": "PAGAMENTO_NAO_IDENTIFICADO", "ref": f"P{pid}"})

    ligacoes = [{"pagamento_id": int(g["ref"][1:]), "notas": []} for g in gabarito
                if g["tipo"] == "PAGAMENTO_NAO_IDENTIFICADO"]  # o certo aqui é "não sei"
    casos_dificeis(rng, data_base, clientes, contratos, notas, pagamentos, erro_do_slot, ligacoes)

    return {"clientes": clientes, "contratos": contratos, "notas": notas,
            "pagamentos": sorted(pagamentos, key=lambda p: p["id"]), "gabarito": gabarito,
            "ligacoes": ligacoes}


MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


def casos_dificeis(rng, data_base, clientes, contratos, notas, pagamentos, erro_do_slot, ligacoes, n=2):
    """Fase 2: pagamentos que NENHUMA regra consegue ligar com segurança.

    - AGRUPADO: um pagamento quita duas notas ("Pgto julho e agosto").
    - TERCEIRO: quem paga é outra empresa; só o nome do cliente aparece na referência.
    - FILIAL:   pago pelo CNPJ de uma filial (mesma raiz de 8 dígitos), sem referência útil.

    Não são erros de faturamento: ligados corretamente, não geram divergência.
    O gabarito guarda a ligação certa para medir o agente.
    """
    cliente_de = {c["id"]: next(cl for cl in clientes if cl["id"] == c["cliente_id"]) for c in contratos}
    usadas = set()

    def elegivel(nt):
        pg = [p for p in pagamentos if p.get("_nota") == nt["numero"]]
        return (nt["vencimento"] < data_base - timedelta(days=3) and nt["numero"] not in usadas
                and (nt["contrato_id"], nt["competencia"]) not in erro_do_slot and len(pg) == 1
                and pg[0]["valor"] == nt["valor"])

    def tirar_pagamento(nt):
        usadas.add(nt["numero"])
        pagamentos[:] = [p for p in pagamentos if p.get("_nota") != nt["numero"]]

    def novo_id():
        return max(p["id"] for p in pagamentos) + 1

    candidatas = [nt for nt in notas if elegivel(nt)]
    rng.shuffle(candidatas)

    # AGRUPADO: duas notas seguidas do mesmo contrato
    feitos = 0
    for a in candidatas:
        b = next((x for x in notas if x["contrato_id"] == a["contrato_id"]
                  and x["competencia"] == add_month(a["competencia"]) and elegivel(x)), None)
        if feitos == n or not b or not elegivel(a):
            continue
        tirar_pagamento(a), tirar_pagamento(b)
        pid = novo_id()
        pagamentos.append({"id": pid, "data": min(b["vencimento"] + timedelta(days=rng.randint(0, 3)),
                                                   data_base - timedelta(days=1)),
                           "valor": a["valor"] + b["valor"], "cnpj_pagador": cliente_de[a["contrato_id"]]["cnpj"],
                           "referencia": f"Pgto {MESES[a['competencia'].month - 1]} e {MESES[b['competencia'].month - 1]}"})
        ligacoes.append({"pagamento_id": pid, "notas": [a["numero"], b["numero"]], "caso": "AGRUPADO"})
        feitos += 1

    for caso in ("TERCEIRO", "FILIAL"):
        for nt in [x for x in candidatas if elegivel(x)][:n]:
            cl = cliente_de[nt["contrato_id"]]
            tirar_pagamento(nt)
            pid = novo_id()
            if caso == "TERCEIRO":
                cnpj_pg, ref = cnpj(rng), f"PIX pagamento {cl['nome'].split()[0]}"
            else:
                cnpj_pg, ref = cl["cnpj"][:8] + "".join(str(rng.randint(0, 9)) for _ in range(6)), "Pagamento de servicos"
            pagamentos.append({"id": pid, "data": nt["vencimento"] + timedelta(days=rng.randint(0, 2)),
                               "valor": nt["valor"], "cnpj_pagador": cnpj_pg, "referencia": ref})
            ligacoes.append({"pagamento_id": pid, "notas": [nt["numero"]], "caso": caso})


def gravar(dados: dict) -> None:
    with connect() as conn:
        apply_sql(conn, "schema.sql", "regras.sql")
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO clientes (id, nome, cnpj) VALUES (%(id)s, %(nome)s, %(cnpj)s)", dados["clientes"])
            cur.executemany(
                """INSERT INTO contratos (id, cliente_id, descricao, valor_mensal, desconto_pct, dia_vencimento, inicio, fim)
                   VALUES (%(id)s, %(cliente_id)s, %(descricao)s, %(valor_mensal)s, %(desconto_pct)s,
                           %(dia_vencimento)s, %(inicio)s, %(fim)s)""", dados["contratos"])
            cur.executemany(
                """INSERT INTO notas_fiscais (id, numero, contrato_id, competencia, valor, emissao, vencimento)
                   VALUES (%(id)s, %(numero)s, %(contrato_id)s, %(competencia)s, %(valor)s, %(emissao)s, %(vencimento)s)""",
                dados["notas"])
            cur.executemany(
                """INSERT INTO pagamentos (id, data, valor, cnpj_pagador, referencia)
                   VALUES (%(id)s, %(data)s, %(valor)s, %(cnpj_pagador)s, %(referencia)s)""", dados["pagamentos"])
            for t in ("clientes", "contratos", "notas_fiscais", "pagamentos"):
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT max(id) FROM {t}))")
        conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--data-base", type=date.fromisoformat, default=date(2026, 11, 16))
    a = ap.parse_args()
    dados = gerar(a.seed, a.data_base)
    gravar(dados)
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "gabarito.json").write_text(
        json.dumps({"seed": a.seed, "data_base": a.data_base.isoformat(), "divergencias": dados["gabarito"],
                    "ligacoes": dados["ligacoes"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    from .gerar_documentos import gerar_documentos
    docs = gerar_documentos(dados, a.data_base)
    print(f"{len(docs)} e-mails na caixa de entrada -> data/caixa_entrada/")
    print(f"{len(dados['clientes'])} clientes, {len(dados['contratos'])} contratos, {len(dados['notas'])} notas, "
          f"{len(dados['pagamentos'])} pagamentos, {len(dados['gabarito'])} erros plantados, "
          f"{sum(1 for l in dados['ligacoes'] if l['notas'])} casos difíceis -> data/gabarito.json")


if __name__ == "__main__":
    main()
