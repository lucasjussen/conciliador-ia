-- Fase 6: camada de leitura para o Power BI.
--
-- Decisão: o cálculo fica no banco, não no Power BI. As visões já entregam valor em risco,
-- cliente, dias de atraso e faixa; o painel só soma e desenha. Assim o número do painel é o
-- mesmo da API, do e-mail do n8n e do MCP, porque todos leem a mesma função divergencias().

-- Retrato diário: uma linha por (dia, tipo). Gravado a cada conciliação (API/n8n) e pelo
-- `python -m app.bi`, que também preenche dias passados.
CREATE TABLE IF NOT EXISTS historico_conciliacao (
    data_base       date NOT NULL,
    tipo            text NOT NULL,
    quantidade      int NOT NULL,
    valor_em_risco  numeric(14,2) NOT NULL,
    gerado_em       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (data_base, tipo)
);

-- Valor que pode não entrar no caixa, por divergência (mesma regra de app/servico.py).
CREATE OR REPLACE FUNCTION risco_da_divergencia(tipo text, esperado numeric, encontrado numeric)
RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN tipo IN ('NAO_PAGO_VENCIDO', 'NOTA_FALTANTE') THEN coalesce(esperado, 0)
        WHEN tipo = 'PAGAMENTO_DIVERGENTE' THEN greatest(coalesce(esperado, 0) - coalesce(encontrado, 0), 0)
        ELSE 0
    END
$$;

CREATE OR REPLACE FUNCTION registrar_historico(d date) RETURNS int LANGUAGE sql AS $$
    WITH divs AS (SELECT * FROM divergencias(d)),
    tipos(tipo) AS (VALUES ('NOTA_FALTANTE'), ('NOTA_DUPLICADA'), ('VALOR_DIVERGENTE'),
                           ('PAGAMENTO_DIVERGENTE'), ('NAO_PAGO_VENCIDO'), ('PAGAMENTO_NAO_IDENTIFICADO')),
    agreg AS (
        SELECT t.tipo, count(dv.ref)::int AS quantidade,
               coalesce(sum(risco_da_divergencia(dv.tipo, dv.valor_esperado, dv.valor_encontrado)), 0) AS risco
        FROM tipos t LEFT JOIN divs dv ON dv.tipo = t.tipo
        GROUP BY t.tipo
    ),
    ins AS (
        INSERT INTO historico_conciliacao (data_base, tipo, quantidade, valor_em_risco)
        SELECT d, tipo, quantidade, risco FROM agreg
        ON CONFLICT (data_base, tipo) DO UPDATE
            SET quantidade = EXCLUDED.quantidade, valor_em_risco = EXCLUDED.valor_em_risco, gerado_em = now()
        RETURNING 1
    )
    SELECT count(*)::int FROM ins
$$;

-- Data de referência do painel: o último dia registrado (ou hoje, se não houver histórico).
CREATE OR REPLACE VIEW vw_bi_data_base AS
SELECT coalesce((SELECT max(data_base) FROM historico_conciliacao), current_date) AS data_base;

-- Divergências da data de referência, prontas para o painel.
CREATE OR REPLACE VIEW vw_bi_divergencias AS
SELECT
    db.data_base,
    dv.tipo,
    CASE dv.tipo
        WHEN 'NOTA_FALTANTE' THEN 'Nota não emitida'
        WHEN 'NOTA_DUPLICADA' THEN 'Nota duplicada'
        WHEN 'VALOR_DIVERGENTE' THEN 'Nota com valor errado'
        WHEN 'PAGAMENTO_DIVERGENTE' THEN 'Pago a menor'
        WHEN 'NAO_PAGO_VENCIDO' THEN 'Vencida sem pagamento'
        WHEN 'PAGAMENTO_NAO_IDENTIFICADO' THEN 'Pagamento não identificado'
    END AS tipo_descricao,
    dv.ref,
    coalesce(cl.nome, clp.nome, 'Pagador desconhecido') AS cliente,
    c.descricao AS servico,
    dv.competencia,
    dv.nota_numero,
    dv.pagamento_id,
    dv.valor_esperado,
    dv.valor_encontrado,
    risco_da_divergencia(dv.tipo, dv.valor_esperado, dv.valor_encontrado) AS valor_em_risco,
    CASE WHEN dv.tipo = 'NAO_PAGO_VENCIDO' THEN db.data_base - n.vencimento END AS dias_atraso,
    CASE
        WHEN dv.tipo <> 'NAO_PAGO_VENCIDO' THEN NULL
        WHEN db.data_base - n.vencimento <= 15 THEN '1 a 15 dias'
        WHEN db.data_base - n.vencimento <= 30 THEN '16 a 30 dias'
        WHEN db.data_base - n.vencimento <= 60 THEN '31 a 60 dias'
        ELSE 'mais de 60 dias'
    END AS faixa_atraso,
    dv.detalhe
FROM vw_bi_data_base db
CROSS JOIN LATERAL divergencias(db.data_base) dv
LEFT JOIN contratos c ON c.id = dv.contrato_id
LEFT JOIN clientes cl ON cl.id = c.cliente_id
LEFT JOIN notas_fiscais n ON n.numero = dv.nota_numero
LEFT JOIN pagamentos p ON p.id = dv.pagamento_id
LEFT JOIN clientes clp ON clp.cnpj = p.cnpj_pagador;

-- Evolução diária (gráfico de linha).
CREATE OR REPLACE VIEW vw_bi_historico AS
SELECT data_base, tipo, quantidade, valor_em_risco FROM historico_conciliacao;

-- Agente: o que ele propôs e o que a pessoa decidiu.
CREATE OR REPLACE VIEW vw_bi_agente AS
SELECT pa.pagamento_id, p.valor, p.referencia, cardinality(pa.nota_numeros) AS qtd_notas,
       pa.confianca, pa.valida, pa.status, pa.criado_em, pa.decidido_em,
       (pa.confianca = 'alta' AND pa.valida) AS resolvivel_sem_humano
FROM propostas_agente pa JOIN pagamentos p ON p.id = pa.pagamento_id;

-- Caixa de entrada: o que chegou e como foi classificado.
CREATE OR REPLACE VIEW vw_bi_documentos AS
SELECT arquivo, assunto, tipo, status, contem_instrucoes,
       cardinality(padroes_suspeitos) > 0 AS pego_pela_regra,
       (status = 'alerta_seguranca') AS alerta_seguranca, processado_em
FROM documentos;

-- Usuário só de leitura para o Power BI: o painel não precisa (nem deve) poder escrever.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'powerbi') THEN
        CREATE ROLE powerbi LOGIN PASSWORD 'powerbi';
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO powerbi;
GRANT SELECT ON vw_bi_data_base, vw_bi_divergencias, vw_bi_historico, vw_bi_agente, vw_bi_documentos TO powerbi;
GRANT SELECT ON historico_conciliacao, clientes, contratos, notas_fiscais, pagamentos,
                conciliacao_pagamentos, propostas_agente, documentos TO powerbi;
GRANT EXECUTE ON FUNCTION divergencias(date), valor_esperado(contratos), risco_da_divergencia(text, numeric, numeric)
    TO powerbi;
