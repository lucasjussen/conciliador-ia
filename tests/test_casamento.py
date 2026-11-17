from datetime import date
from decimal import Decimal as D

from app.casamento import casar, numero_citado


def nota(id, numero, cnpj, valor, comp):
    return {"id": id, "numero": numero, "cnpj": cnpj, "valor": D(valor), "competencia": comp, "emissao": comp}


def pag(id, cnpj, valor, ref, dia=date(2026, 9, 10)):
    return {"id": id, "cnpj_pagador": cnpj, "valor": D(valor), "referencia": ref, "data": dia}


def test_numero_citado_variantes():
    assert numero_citado("NF 1023") == 1023
    assert numero_citado("Pagto NF1023") == 1023
    assert numero_citado("Ref. nota 1023") == 1023
    assert numero_citado("NFS-e 1023") == 1023
    assert numero_citado("Mensalidade 10/2026") is None


def test_casa_por_numero_so_se_cnpj_bate():
    notas = [nota(1, 1001, "A", "100.00", date(2026, 8, 1))]
    r = casar(notas, [pag(1, "A", "100.00", "NF 1001"), pag(2, "B", "100.00", "NF 1001")])
    assert (r[0].nota_id, r[0].metodo) == (1, "numero")
    assert r[1].nota_id is None  # outro CNPJ citando a nota: não confia


def test_fifo_por_cnpj_valor():
    notas = [nota(1, 1001, "A", "100.00", date(2026, 7, 1)), nota(2, 1002, "A", "100.00", date(2026, 8, 1))]
    r = casar(notas, [pag(1, "A", "100.00", "mensalidade"), pag(2, "A", "100.00", "mensalidade", date(2026, 9, 11))])
    assert [m.nota_id for m in r] == [1, 2]
    assert {m.metodo for m in r} == {"cnpj_valor"}


def test_valor_diferente_sem_referencia_fica_nao_identificado():
    notas = [nota(1, 1001, "A", "100.00", date(2026, 8, 1))]
    r = casar(notas, [pag(1, "A", "90.00", "mensalidade")])
    assert r[0].nota_id is None and r[0].metodo is None


def test_casa_pela_competencia_citada():
    notas = [nota(1, 1001, "A", "100.00", date(2026, 7, 1)), nota(2, 1002, "A", "100.00", date(2026, 8, 1))]
    r = casar(notas, [pag(1, "A", "100.00", "Mensalidade 08/2026")])
    assert (r[0].nota_id, r[0].metodo) == (2, "competencia")
