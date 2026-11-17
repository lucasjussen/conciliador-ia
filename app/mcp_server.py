"""Servidor MCP do conciliador.

Qualquer cliente MCP (Claude Desktop, Claude Code, outros agentes) passa a consultar o
conciliador em linguagem natural: "quanto dinheiro está em risco?", "quais notas da Rota
estão em aberto?", "tem proposta do agente esperando aprovação?".

    python -m app.mcp_server        (transporte stdio; quem inicia é o cliente MCP)

Decisão de segurança: este servidor é SOMENTE LEITURA. Nenhuma ferramenta aprova proposta,
grava ligação ou roda o casamento. Executar e aprovar continuam com a API agendada (n8n)
e com a revisão humana. Um assistente pode consultar à vontade sem risco de alterar dados.
"""
from __future__ import annotations

from typing import Optional

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import servico

mcp = MCPServer(
    name="conciliador",
    instructions=("Consulta a conciliação de faturamento (contrato x nota fiscal x pagamento). "
                  "Somente leitura. Valores em reais. Datas no formato AAAA-MM-DD."),
)
LEITURA = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


@mcp.tool(annotations=LEITURA)
def resumo_conciliacao(data_base: Optional[str] = None) -> dict:
    """Panorama da conciliação: total de divergências, quantidade por tipo e valor em risco
    (notas vencidas sem pagamento, notas não emitidas e pagamentos a menor)."""
    from datetime import date

    d = date.fromisoformat(data_base) if data_base else servico.data_base_padrao()
    r = servico.resumo(servico.listar_divergencias(d, limite=1000), d)
    r.pop("html")
    return r


@mcp.tool(annotations=LEITURA)
def listar_divergencias(tipo: Optional[str] = None, limite: int = 20) -> list[dict]:
    """Lista divergências. tipo (opcional): NOTA_FALTANTE, NOTA_DUPLICADA, VALOR_DIVERGENTE,
    PAGAMENTO_DIVERGENTE, NAO_PAGO_VENCIDO ou PAGAMENTO_NAO_IDENTIFICADO."""
    return servico.listar_divergencias(None, tipo, min(max(limite, 1), 200))


@mcp.tool(annotations=LEITURA)
def buscar_clientes(texto: str) -> list[dict]:
    """Procura clientes por parte do nome ou pelo começo do CNPJ."""
    return servico.buscar_clientes(texto)


@mcp.tool(annotations=LEITURA)
def notas_em_aberto(cliente_id: int) -> list[dict]:
    """Notas fiscais do cliente que ainda não têm pagamento ligado."""
    return servico.notas_em_aberto(cliente_id)


@mcp.tool(annotations=LEITURA)
def propostas_pendentes() -> list[dict]:
    """Propostas do agente de IA que estão esperando aprovação humana."""
    return servico.propostas_pendentes()


@mcp.tool(annotations=LEITURA)
def documentos_recebidos(status: Optional[str] = None) -> list[dict]:
    """E-mails da caixa de entrada já processados. status (opcional): confere, cliente_tem_razao,
    alerta_seguranca, ignorado, registrado, valor_diverge, remetente_desconhecido."""
    return servico.listar_documentos(status)


if __name__ == "__main__":
    mcp.run("stdio")
