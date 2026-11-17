"""API HTTP do conciliador (FastAPI).

    uvicorn app.api:app --port 8000          (documentação interativa em /docs)

Segurança:
- Toda rota, menos /saude, exige o cabeçalho X-API-Key igual a CONCILIADOR_API_KEY do .env.
- Sem chave configurada, a API recusa tudo (falha fechada): esquecer a variável não abre o sistema.
- Comparação em tempo constante (secrets.compare_digest).
- Só POST /conciliar escreve no banco, e o que ele escreve é idempotente.
"""
from __future__ import annotations

import os
import secrets
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from . import servico

app = FastAPI(title="Conciliador de Faturamento com IA", version="4.0",
              description="Regras SQL + agente LangGraph + extração de documentos, expostos por HTTP.")


def exigir_chave(x_api_key: Optional[str] = Header(default=None)) -> None:
    esperada = os.getenv("CONCILIADOR_API_KEY", "")
    if not esperada:
        raise HTTPException(503, "CONCILIADOR_API_KEY não configurada no servidor")
    if not x_api_key or not secrets.compare_digest(x_api_key, esperada):
        raise HTTPException(401, "X-API-Key ausente ou inválida")


@app.get("/saude")
def saude() -> dict:
    return {"ok": True}


@app.post("/conciliar", dependencies=[Depends(exigir_chave)])
def conciliar(data_base: Optional[date] = None, incluir_divergencias: bool = False) -> dict:
    """Roda a conciliação e devolve o resumo (total, por tipo, valor em risco, HTML para e-mail)."""
    r = servico.executar_conciliacao(data_base)
    if not incluir_divergencias:
        r.pop("divergencias")
    return r


@app.get("/divergencias", dependencies=[Depends(exigir_chave)])
def divergencias(data_base: Optional[date] = None, tipo: Optional[str] = None,
                 limite: int = Query(100, ge=1, le=1000)) -> list[dict]:
    try:
        return servico.listar_divergencias(data_base, tipo, limite)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/propostas", dependencies=[Depends(exigir_chave)])
def propostas() -> list[dict]:
    """Propostas do agente esperando aprovação humana."""
    return servico.propostas_pendentes()


@app.get("/documentos", dependencies=[Depends(exigir_chave)])
def documentos(status: Optional[str] = None) -> list[dict]:
    return servico.listar_documentos(status)
