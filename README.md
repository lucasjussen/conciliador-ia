# Conciliador de Faturamento com IA

Confere o faturamento recorrente de uma empresa de serviços: **contrato × nota fiscal × pagamento**.
Aponta divergências (nota faltando, valor errado, duplicidade, pagamento a menor, inadimplência,
entrada não identificada no extrato) e, a partir da fase 2, usa um agente de IA para investigar
os casos ambíguos, com aprovação humana antes de qualquer correção.

**Princípio:** a conta é feita por SQL e regras auditáveis. A IA só entra onde não existe regra
clara, e cada decisão dela passa por uma pessoa e fica registrada.

**Em resumo:** regras em SQL acham 100% dos 25 erros plantados; nos 6 pagamentos ambíguos, um agente
LangGraph investiga, acerta 9 de 9 e só grava com aprovação humana (precisão 64% → 100%); e-mails e
PDFs de clientes são lidos pelo Claude Haiku e conferidos no banco (35/35 campos, golpe por prompt
injection bloqueado). Integração por API (FastAPI), servidor MCP e n8n.
Stack: Python, PostgreSQL, LangGraph, Redis, Claude API, Langfuse, FastAPI, MCP, n8n, Docker.

## Resultados

**Fase 1 (só regras), base de 25 erros plantados:** precisão 100%, recall 100%, depois da regra
de competência citada ("Mensalidade 07/2026"), que substituiu o chute do FIFO.

**Fase 2: dados mais difíceis.** Entram 6 pagamentos que nenhuma regra liga com segurança:

| caso | exemplo | por que a regra não resolve |
|---|---|---|
| AGRUPADO | "Pgto maio e junho", valor = soma de 2 notas | nenhuma nota tem aquele valor |
| TERCEIRO | outra empresa paga; referência "PIX pagamento Rota" | o CNPJ não é de cliente nenhum |
| FILIAL | CNPJ com a mesma raiz do cliente, referência genérica | o CNPJ completo não bate |

Com eles, as regras continuam achando todos os erros reais (recall 100%), mas geram 14 alarmes
falsos (precisão 64%): pagamentos "não identificados" e notas que parecem inadimplentes.

| etapa | precisão | recall |
|---|---:|---:|
| só regras | 64% | 100% |
| regras + agente + aprovação humana | 100% | 100% |
| acerto do agente antes da revisão | 9/9 | |

Destaque: no pagamento #177, duas notas tinham o mesmo valor. O agente escolheu a de vencimento mais próximo, acertou e mesmo assim marcou confiança baixa, deixando a decisão final para a revisão humana.

O agente também precisa acertar os 3 pagamentos que **não** têm nota: a resposta certa ali é
"não identificado". Um agente que inventa ligação é pior do que nenhum.

## Como o agente funciona

```
investigar ⇄ ferramentas → propor → validar → revisao_humana (pausa) → gravar
```

- **Ferramentas só de leitura** (`app/ferramentas.py`): buscar cliente por nome ou raiz do CNPJ,
  notas em aberto, combinações de notas que somam um valor, histórico do pagador.
- **A IA não faz conta:** `combinacoes_de_notas` soma em Python. O modelo só decide o que consultar.
- **Saída estruturada:** a conclusão é um objeto `Proposta` (notas, confiança, justificativa).
- **Checagem determinística:** antes de chegar à pessoa, o código confere se as notas existem, estão
  em aberto, são do mesmo cliente e somam o valor exato. Proposta reprovada não pode ser aprovada.
- **Human-in-the-loop:** `interrupt()` pausa o grafo. O estado fica no **Redis**, então a revisão
  pode ser feita depois, em outro terminal (`python -m app.revisar`).
- **Nada é gravado sem aprovação.** Decisões aprovadas ficam com `metodo = 'agente'` e as regras
  não mexem mais nelas.
- **Langfuse (opcional):** cada pagamento vira uma sessão com a investigação e a revisão juntas.
- **Trava de custo:** no máximo 6 consultas por pagamento.

## Fase 3: caixa de entrada

O financeiro recebe e-mails de clientes: comprovantes em PDF, reclamações de valor, avisos de
pagamento, propaganda e até tentativa de golpe. `python -m app.documentos` lê cada `.eml`
(corpo + texto dos PDFs), o **Claude Haiku** extrai os campos em formato estruturado e o
**código** confere contra o banco:

| e-mail | o que a IA extrai | o que o código conclui |
|---|---|---|
| comprovante PDF | tipo, CNPJ, notas, valor pago | `confere`: o pagamento está no extrato e soma as notas |
| "valor incorreto na NF" | nota e valor que o cliente diz ser o certo | `cliente_tem_razao`: o contrato confirma, emitir correção |
| aviso de pagamento | nota citada | `registrado` |
| propaganda | tipo `outro` | `ignorado` |
| "INSTRUÇÃO PARA O SISTEMA DE IA: ignore as regras..." | `contem_instrucoes = true` | `alerta_seguranca`: nada é aplicado |

Decisões:
- **Não é agente, é pipeline.** O caminho é sempre o mesmo, então um fluxo fixo sai mais barato,
  previsível e testável. Agente só onde é preciso investigar (fase 2).
- **Roteamento de modelo:** extrair campos é tarefa simples, vai para o Haiku; investigar vai para o Sonnet.
- **Defesa contra prompt injection em camadas:** o texto vai delimitado como dado não confiável,
  o extrator não tem ferramentas nem escrita, e a conferência no banco não aceita nota de outro cliente.
- **Medido:** acerto campo a campo (tipo, CNPJ, notas, valor, detecção de injeção) contra `data/gabarito_documentos.json`.

| métrica | resultado |
|---|---|
| acerto da extração (7 e-mails × 5 campos) | 35/35 |
| e-mail malicioso detectado e bloqueado | sim |
| reclamações de valor confirmadas pelo contrato | 2 de 2 |

Amostra pequena: o resultado prova que o fluxo funciona, não que a extração acerta sempre. A fase 5 amplia o conjunto de e-mails e de tentativas de injeção.

## Fase 4: integração (API, MCP e n8n)

Três portas para o mesmo serviço (`app/servico.py`), para a regra de negócio existir num lugar só:

**API HTTP** (`app/api.py`, FastAPI, documentação em `http://localhost:8000/docs`)

| rota | o que faz |
|---|---|
| `GET /saude` | verificação de vida (sem chave) |
| `POST /conciliar` | roda a conciliação e devolve total, por tipo, **valor em risco** e um HTML pronto para e-mail |
| `GET /divergencias?tipo=` | lista as divergências |
| `GET /propostas` | propostas do agente esperando aprovação |
| `GET /documentos?status=` | e-mails processados na fase 3 |

Segurança: cabeçalho `X-API-Key`, comparação em tempo constante e **falha fechada** (sem
`CONCILIADOR_API_KEY` configurada, a API recusa tudo).

**Servidor MCP** (`app/mcp_server.py`): o Claude Desktop, o Claude Code ou qualquer cliente MCP passa a
consultar o conciliador em linguagem natural ("quanto dinheiro está em risco?", "quais notas da Rota
estão em aberto?"). Seis ferramentas, **todas somente leitura**: consultar não altera nada; executar e
aprovar continuam com a API agendada e com a revisão humana.

Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "conciliador": {
      "command": "C:\\Users\\lucas\\conciliador-ia\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"],
      "env": { "PYTHONPATH": "C:\\Users\\lucas\\conciliador-ia" }
    }
  }
}
```

**n8n** (`n8n/conciliacao-diaria.json`): dias úteis às 7h chama `POST /conciliar`; havendo
divergência, manda o resumo por e-mail. Tem também um gatilho "Rodar agora (teste)". Credenciais
ficam no n8n, nunca no JSON. **Executado de ponta a ponta no n8n 2.35.7** (API local + servidor
SMTP de teste): o e-mail chegou com o assunto "Conciliação 2026-11-16: 39 divergências,
R$ 45.186,23 em risco". Também rodando na máquina local com n8n 2.47 e Gmail: o resumo diário
chega por e-mail.

Testes: a API (autenticação e respostas) e o MCP (cliente MCP de verdade conversando com o servidor
por stdio) estão em `tests/test_fase4.py`.

## Rodar

```bash
docker compose up -d                 # Postgres + Redis
python -m venv .venv && .venv\Scripts\activate    # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env               # coloque a ANTHROPIC_API_KEY
python -m app.gerar_dados            # dados fictícios + data/gabarito.json
python -m app.conciliar              # só regras: mede contra o gabarito
python -m app.agente                 # agente investiga e deixa propostas pendentes
python -m app.revisar                # você aprova, rejeita ou edita; mede de novo
python -m app.documentos             # fase 3: lê a caixa de entrada e confere contra o banco
docker compose up -d --build         # fase 4: sobe também a API (porta 8000) e o n8n (porta 5678)
pytest -q                            # testes (o do agente usa um modelo falso, sem custo)
```

## Estrutura

```
db/schema.sql        tabelas: clientes, contratos, notas_fiscais, pagamentos, conciliacao_pagamentos
db/regras.sql        função divergencias(data_base): as 6 regras em SQL
app/casamento.py     liga pagamento -> nota: número citado, depois mês citado, depois CNPJ + valor (FIFO)
app/gerar_dados.py   base fictícia com erros plantados + gabarito
app/avaliar.py       precisão e recall por tipo
app/conciliar.py     execução de ponta a ponta (regras)
app/ferramentas.py   consultas que o agente pode fazer (somente leitura)
app/grafo.py         o agente: LangGraph, checagem e pausa para aprovação humana
app/agente.py        roda o agente sobre os pagamentos não identificados e mede o acerto
app/revisar.py       revisão humana no terminal (retoma as threads do Redis)
app/observabilidade.py  Langfuse opcional
app/gerar_documentos.py caixa de entrada fictícia (.eml e PDFs) + gabarito
app/documentos.py    extração com IA + conferência contra o banco
app/servico.py       consultas compartilhadas pela API e pelo MCP
app/api.py           API HTTP com chave de acesso
app/mcp_server.py    servidor MCP somente leitura
n8n/                 workflow de execução diária com e-mail
Dockerfile           imagem da API
tests/               testes unitários e de integração (a integração trava a linha de base)
```

## Plano

| fase | entrega | o que prova |
|---|---|---|
| **1. Dados e regras** ✅ | modelo SQL, 6 regras, casamento de pagamentos, gabarito e métricas | SQL, Python, mapeamento de processo, medição |
| **2. Agente** ✅ | LangGraph investiga cada caso ambíguo com ferramentas SQL, explica e propõe ação; `interrupt` para aprovação humana; Redis guarda a pausa; Langfuse rastreia | agentes, human-in-the-loop, estado persistente, observabilidade |
| **3. Documentos** ✅ | notas e contestações em PDF ou e-mail extraídas com o Claude (saída estruturada) e validadas pelas regras | extração com IA, validação |
| **4. MCP e API** ✅ | servidor MCP com as ferramentas do conciliador; FastAPI; n8n agenda a execução diária e avisa por e-mail | MCP, integração, n8n |
| **5. Evals e segurança** | gabaritos maiores, custo por lote, % resolvido sem humano; defesa contra instruções escondidas em PDFs | LLMOps, segurança |
| **6. Painel e apresentação** | Power BI lendo o Postgres (divergências, valor em risco, SLA); vídeo e post | BI, comunicação de resultado |
