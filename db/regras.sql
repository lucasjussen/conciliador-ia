-- Regras determinísticas de conciliação.
--
-- Princípio do projeto: CONTA quem faz é o SQL, não a IA. Tudo o que tem regra
-- clara (valor esperado, nota faltando, duplicidade, vencimento) é resolvido aqui,
-- de forma auditável e reproduzível. A IA (fase 2) só entra no que sobra de
-- ambíguo, como pagamentos sem referência que não casam com nenhuma nota.
--
-- Uso:  SELECT * FROM divergencias('2026-11-16');

CREATE OR REPLACE FUNCTION valor_esperado(c contratos) RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$
    SELECT round(c.valor_mensal * (1 - c.desconto_pct / 100), 2)
$$;

CREATE OR REPLACE FUNCTION divergencias(data_base date)
RETURNS TABLE (
    tipo             text,
    ref              text,      -- chave estável: C<contrato>-<AAAA-MM> ou P<pagamento>
    contrato_id      int,
    competencia      date,
    nota_numero      int,
    pagamento_id     int,
    valor_esperado   numeric,
    valor_encontrado numeric,
    detalhe          text
)
LANGUAGE sql STABLE AS $$
WITH
-- Competências que já deveriam ter nota: do início do contrato até o mês anterior à data-base.
esperadas AS (
    SELECT c.id AS contrato_id, gs::date AS competencia, valor_esperado(c) AS esperado
    FROM contratos c,
         generate_series(date_trunc('month', c.inicio),
                         date_trunc('month', data_base) - interval '1 month',
                         interval '1 month') gs
    WHERE c.fim IS NULL OR gs <= c.fim
),
notas_validas AS (
    SELECT n.*,
           row_number() OVER (PARTITION BY contrato_id, competencia ORDER BY numero) AS ordem,
           count(*)     OVER (PARTITION BY contrato_id, competencia)                 AS qtd
    FROM notas_fiscais n
    WHERE NOT n.cancelada AND n.emissao <= data_base           -- e só notas já emitidas naquela data
),
pagos AS (
    SELECT cp.nota_id, sum(coalesce(cp.valor_alocado, p.valor)) AS total_pago, string_agg(p.id::text, ',') AS pagamentos
    FROM conciliacao_pagamentos cp JOIN pagamentos p ON p.id = cp.pagamento_id
    WHERE cp.nota_id IS NOT NULL AND p.data <= data_base   -- olhando o passado: só o que já tinha sido pago
    GROUP BY cp.nota_id
)
-- 1. Contrato vigente sem nota na competência
SELECT 'NOTA_FALTANTE', format('C%s-%s', e.contrato_id, to_char(e.competencia, 'YYYY-MM')),
       e.contrato_id, e.competencia, NULL::int, NULL::int, e.esperado, NULL::numeric,
       'Nenhuma nota emitida para a competência'
FROM esperadas e
WHERE NOT EXISTS (SELECT 1 FROM notas_validas n
                  WHERE n.contrato_id = e.contrato_id AND n.competencia = e.competencia)

UNION ALL
-- 2. Mais de uma nota válida para o mesmo contrato e competência
SELECT 'NOTA_DUPLICADA', format('C%s-%s', n.contrato_id, to_char(n.competencia, 'YYYY-MM')),
       n.contrato_id, n.competencia, n.numero, NULL, NULL, n.valor,
       format('%s notas válidas para a mesma competência', n.qtd)
FROM notas_validas n
WHERE n.qtd > 1 AND n.ordem = 2

UNION ALL
-- 3. Valor da nota diferente do contrato (valor mensal menos desconto)
SELECT 'VALOR_DIVERGENTE', format('C%s-%s', n.contrato_id, to_char(n.competencia, 'YYYY-MM')),
       n.contrato_id, n.competencia, n.numero, NULL, valor_esperado(c), n.valor,
       format('Diferença de R$ %s', n.valor - valor_esperado(c))
FROM notas_validas n JOIN contratos c ON c.id = n.contrato_id
WHERE n.ordem = 1 AND abs(n.valor - valor_esperado(c)) > 0.01

UNION ALL
-- 4. Nota paga com valor diferente do faturado
SELECT 'PAGAMENTO_DIVERGENTE', format('C%s-%s', n.contrato_id, to_char(n.competencia, 'YYYY-MM')),
       n.contrato_id, n.competencia, n.numero, NULL, n.valor, pg.total_pago,
       format('Pago R$ %s de R$ %s (pagamentos %s)', pg.total_pago, n.valor, pg.pagamentos)
FROM notas_validas n JOIN pagos pg ON pg.nota_id = n.id
WHERE abs(pg.total_pago - n.valor) > 0.01

UNION ALL
-- 5. Nota vencida sem nenhum pagamento (cópias duplicadas ficam de fora: já viram NOTA_DUPLICADA)
SELECT 'NAO_PAGO_VENCIDO', format('C%s-%s', n.contrato_id, to_char(n.competencia, 'YYYY-MM')),
       n.contrato_id, n.competencia, n.numero, NULL, n.valor, 0,
       format('Vencida em %s, %s dias em atraso', to_char(n.vencimento, 'DD/MM/YYYY'), data_base - n.vencimento)
FROM notas_validas n
WHERE n.ordem = 1 AND n.vencimento < data_base
  AND NOT EXISTS (SELECT 1 FROM pagos pg WHERE pg.nota_id = n.id)

UNION ALL
-- 6. Entrada no extrato que não foi ligada a nenhuma nota (nem por regra, nem pelo agente)
SELECT 'PAGAMENTO_NAO_IDENTIFICADO', format('P%s', p.id),
       NULL, NULL, NULL, p.id, NULL, p.valor,
       format('Pagador %s, referência "%s"', p.cnpj_pagador, p.referencia)
FROM pagamentos p
WHERE p.data <= data_base
  AND NOT EXISTS (SELECT 1 FROM conciliacao_pagamentos cp
                  WHERE cp.pagamento_id = p.id AND cp.nota_id IS NOT NULL)
$$;
