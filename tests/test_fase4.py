"""Fase 4: API (com autenticação) e servidor MCP (cliente MCP de verdade, via stdio)."""
import json
import os
import sys
from datetime import date
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.db import connect
from app.gerar_dados import gerar, gravar

try:
    connect().close()
    TEM_BANCO = True
except Exception:
    TEM_BANCO = False

pytestmark = pytest.mark.skipif(not TEM_BANCO, reason="sem Postgres")
D = date(2026, 11, 16)
RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def base(monkeypatch):
    gravar(gerar(7, D))
    monkeypatch.setenv("CONCILIADOR_API_KEY", "chave-de-teste")
    monkeypatch.setenv("DATA_BASE", "2026-11-16")


def test_api_exige_chave_e_falha_fechada(monkeypatch):
    c = TestClient(app)
    assert c.get("/saude").json() == {"ok": True}
    assert c.post("/conciliar").status_code == 401
    assert c.post("/conciliar", headers={"X-API-Key": "errada"}).status_code == 401
    monkeypatch.setenv("CONCILIADOR_API_KEY", "")
    assert c.post("/conciliar", headers={"X-API-Key": ""}).status_code == 503


def test_api_conciliar_e_consultar():
    c = TestClient(app)
    h = {"X-API-Key": "chave-de-teste"}
    r = c.post("/conciliar", headers=h).json()
    assert r["total"] == 39 and r["por_tipo"]["NOTA_FALTANTE"] == 4
    assert r["valor_em_risco"] > 0 and "<table" in r["html"] and "divergencias" not in r
    d = c.get("/divergencias", params={"tipo": "NOTA_DUPLICADA"}, headers=h).json()
    assert len(d) == 3 and all(x["tipo"] == "NOTA_DUPLICADA" for x in d)
    assert c.get("/divergencias", params={"tipo": "X"}, headers=h).status_code == 422


def test_mcp_por_stdio():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    TestClient(app).post("/conciliar", headers={"X-API-Key": "chave-de-teste"})  # casamento gravado
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(RAIZ),
        env={**os.environ, "DATA_BASE": "2026-11-16"})

    async def run():
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            nomes = {t.name for t in (await s.list_tools()).tools}
            resumo = await s.call_tool("resumo_conciliacao", {})
            clientes = await s.call_tool("buscar_clientes", {"texto": "Rota"})
            return nomes, resumo, clientes

    nomes, resumo, clientes = anyio.run(run)
    assert {"resumo_conciliacao", "listar_divergencias", "buscar_clientes", "notas_em_aberto",
            "propostas_pendentes", "documentos_recebidos"} <= nomes
    dados = resumo.structured_content or json.loads(resumo.content[0].text)
    assert dados["total"] == 39
    assert "Rota" in clientes.content[0].text
