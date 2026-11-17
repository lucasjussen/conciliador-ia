# Conciliador de Faturamento com IA

Confere o faturamento recorrente de uma empresa de serviços: **contrato × nota fiscal × pagamento**.
Aponta divergências (nota faltando, valor errado, duplicidade, pagamento a menor, inadimplência,
entrada não identificada no extrato) e, a partir da fase 2, usa um agente de IA para investigar
os casos ambíguos, com aprovação humana antes de qualquer correção.

**Princípio:** a conta é feita por SQL e regras auditáveis. A IA só entra onde não existe regra
clara, e cada decisão dela passa por uma pessoa e fica registrada.

## Resultado atual (fase 1: só regras)

Base fictícia com 28 clientes, 38 contratos, 189 notas, 174 pagamentos e **25 erros plantados**:

| tipo | reais | apontadas | acertos | precisão | recall |
|---|---:|---:|---:|---:|---:|
| NOTA_FALTANTE | 4 | 4 | 4 | 100% | 100% |
| NOTA_DUPLICADA | 3 | 3 | 3 | 100% | 100% |
| VALOR_DIVERGENTE | 6 | 6 | 6 | 100% | 100% |
| PAGAMENTO_DIVERGENTE | 4 | 3 | 3 | 100% | 75% |
| NAO_PAGO_VENCIDO | 5 | 6 | 4 | 67% | 80% |
| PAGAMENTO_NAO_IDENTIFICADO | 3 | 4 | 3 | 75% | 100% |
| **Geral** | **25** | **26** | **23** | **88%** | **92%** |

O que as regras erram é exatamente o que exige julgamento:
- um pagamento a menor **sem número de nota** na referência: não casa com nada;
- um pagamento sem referência casado por **FIFO** com uma nota antiga em aberto, quando era da
  competência atual. Resultado: uma nota parece paga e outra parece inadimplente.

Essa é a fila do agente na fase 2. A meta é subir o geral para 100% sem piorar nenhum tipo.

## Rodar

```bash
docker compose up -d
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.gerar_dados        # cria tabelas, dados fictícios e data/gabarito.json
python -m app.conciliar          # concilia, grava data/divergencias.csv e mede contra o gabarito
pytest -q
```

## Estrutura

```
db/schema.sql        tabelas: clientes, contratos, notas_fiscais, pagamentos, conciliacao_pagamentos
db/regras.sql        função divergencias(data_base): as 6 regras em SQL
app/casamento.py     liga pagamento -> nota (número citado, depois CNPJ + valor em FIFO)
app/gerar_dados.py   base fictícia com erros plantados + gabarito
app/avaliar.py       precisão e recall por tipo
app/conciliar.py     execução de ponta a ponta
tests/               testes unitários e de integração (a integração trava a linha de base)
```

## Plano

| fase | entrega | o que prova |
|---|---|---|
| **1. Dados e regras** ✅ | modelo SQL, 6 regras, casamento de pagamentos, gabarito e métricas | SQL, Python, mapeamento de processo, medição |
| **2. Agente** | LangGraph investiga cada caso ambíguo com ferramentas SQL, explica e propõe ação; `interrupt` para aprovação humana; Redis guarda a pausa; Langfuse rastreia | agentes, human-in-the-loop, estado persistente, observabilidade |
| **3. Documentos** | notas e contestações em PDF ou e-mail extraídas com o Claude (saída estruturada) e validadas pelas regras | extração com IA, validação |
| **4. MCP e API** | servidor MCP com as ferramentas do conciliador; FastAPI; n8n agenda a execução diária e avisa por e-mail | MCP, integração, n8n |
| **5. Evals e segurança** | gabaritos maiores, custo por lote, % resolvido sem humano; defesa contra instruções escondidas em PDFs | LLMOps, segurança |
| **6. Painel e apresentação** | Power BI lendo o Postgres (divergências, valor em risco, SLA); vídeo e post | BI, comunicação de resultado |
