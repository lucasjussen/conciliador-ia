"""Fase 3 com um extrator FALSO que devolve o gabarito: testa leitura do .eml e do PDF,
a conferência contra o banco e a avaliação. A qualidade da extração real se mede com
`python -m app.documentos` e a API."""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app.conciliar import conciliar
from app.db import connect
from app.documentos import Extracao, avaliar, como_texto, conferir, ler_eml, processar
from app.gerar_dados import gerar, gravar
from app.gerar_documentos import CAIXA, GABARITO_DOCS, gerar_documentos

try:
    connect().close()
    TEM_BANCO = True
except Exception:
    TEM_BANCO = False

pytestmark = pytest.mark.skipif(not TEM_BANCO, reason="sem Postgres")
D = date(2026, 11, 16)


def preparar():
    dados = gerar(7, D)
    gravar(dados)
    gerar_documentos(dados, D)
    conciliar(D)
    return json.loads(GABARITO_DOCS.read_text(encoding="utf-8"))


def extracao_do_gabarito(g):
    v = float(g["valor"]) if g["valor"] else None
    return Extracao(tipo=g["tipo"], cnpj_cliente=g["cnpj"], notas_citadas=g["notas"],
                    valor_pago=v if g["tipo"] == "comprovante" else None,
                    valor_correto_alegado=v if g["tipo"] == "contestacao" else None,
                    resumo="teste", contem_instrucoes=g["injecao"])


class Oraculo:
    def __init__(self, por_assunto):
        self.por_assunto = por_assunto

    def invoke(self, msgs, config=None):
        assunto = re.search(r"Assunto: (.*)", msgs[1][1]).group(1).strip()
        return self.por_assunto[assunto]


def test_le_corpo_e_pdf():
    gab = preparar()
    comp = next(g for g in gab if g["tipo"] == "comprovante")
    doc = ler_eml(CAIXA / comp["arquivo"])
    assert doc["anexos"] and "COMPROVANTE" in doc["anexos"][0][1]
    assert "<email>" in como_texto(doc)


def test_pipeline_com_extrator_perfeito():
    gab = preparar()
    por_assunto = {ler_eml(CAIXA / g["arquivo"])["assunto"]: extracao_do_gabarito(g) for g in gab}
    res = processar(Oraculo(por_assunto), sorted(CAIXA.glob("*.eml")))
    status = {r["status"] for r in res}
    assert {"confere", "cliente_tem_razao", "alerta_seguranca", "ignorado", "registrado"} <= status
    a = avaliar(res)
    assert all(v == a["total"] for v in a["campos"].values()), a


def test_conferencia_pega_valor_errado_e_nota_de_outro_cliente():
    gab = preparar()
    comp = next(g for g in gab if g["tipo"] == "comprovante" and len(g["notas"]) == 1)
    with connect() as conn:
        e = extracao_do_gabarito(comp)
        errado = e.model_copy(update={"valor_pago": float(Decimal(comp["valor"]) + 10)})
        assert conferir(conn, errado)[0] == "valor_diverge"
        outro = conn.execute("SELECT cnpj FROM clientes WHERE left(cnpj,8) <> left(%s,8) LIMIT 1",
                             (comp["cnpj"],)).fetchone()["cnpj"]
        assert conferir(conn, e.model_copy(update={"cnpj_cliente": outro}))[0] == "nota_de_outro_cliente"
