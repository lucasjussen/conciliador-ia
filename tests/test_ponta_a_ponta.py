"""Integração: precisa de Postgres (docker compose up -d). Pulado se não houver banco."""
from datetime import date

import pytest

from app import avaliar
from app.conciliar import conciliar
from app.db import connect
from app.gerar_dados import gerar, gravar

try:
    connect().close()
    TEM_BANCO = True
except Exception:
    TEM_BANCO = False


@pytest.mark.skipif(not TEM_BANCO, reason="sem Postgres")
def test_regras_baseline():
    """Só regras: acham todos os erros (recall 100%), mas os casos difíceis da fase 2
    geram alarmes falsos. Trava essa linha de base; quem fecha a precisão é o agente."""
    d = date(2026, 11, 16)
    dados = gerar(7, d)
    gravar(dados)
    _, divs = conciliar(d)
    r = avaliar.avaliar(divs, dados["gabarito"])["geral"]
    assert r["recall"] == 1.0 and r["precisao"] >= 0.6
