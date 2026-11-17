-- Modelo de dados do faturamento recorrente de uma empresa de serviços.
-- Cada contrato gera uma nota fiscal por mês (competência); cada nota deve
-- ser paga até o vencimento. A conciliação cruza contrato x nota x pagamento.

DROP VIEW IF EXISTS vw_divergencias CASCADE;
DROP TABLE IF EXISTS documentos, propostas_agente, conciliacao_pagamentos, pagamentos, notas_fiscais, contratos, clientes CASCADE;

CREATE TABLE clientes (
    id      serial PRIMARY KEY,
    nome    text NOT NULL,
    cnpj    char(14) NOT NULL UNIQUE
);

CREATE TABLE contratos (
    id              serial PRIMARY KEY,
    cliente_id      int NOT NULL REFERENCES clientes(id),
    descricao       text NOT NULL,
    valor_mensal    numeric(12,2) NOT NULL CHECK (valor_mensal > 0),
    desconto_pct    numeric(5,2) NOT NULL DEFAULT 0 CHECK (desconto_pct BETWEEN 0 AND 100),
    dia_vencimento  int NOT NULL CHECK (dia_vencimento BETWEEN 1 AND 28),
    inicio          date NOT NULL,
    fim             date            -- NULL = vigente
);

CREATE TABLE notas_fiscais (
    id           serial PRIMARY KEY,
    numero       int NOT NULL UNIQUE,
    contrato_id  int NOT NULL REFERENCES contratos(id),
    competencia  date NOT NULL CHECK (extract(day FROM competencia) = 1),
    valor        numeric(12,2) NOT NULL,
    emissao      date NOT NULL,
    vencimento   date NOT NULL,
    cancelada    boolean NOT NULL DEFAULT false
);
CREATE INDEX ON notas_fiscais (contrato_id, competencia);

-- Extrato bancário: o pagador nem sempre informa a nota. A referência é texto livre.
CREATE TABLE pagamentos (
    id             serial PRIMARY KEY,
    data           date NOT NULL,
    valor          numeric(12,2) NOT NULL,
    cnpj_pagador   char(14) NOT NULL,
    referencia     text NOT NULL DEFAULT ''
);

-- Ligação pagamento -> nota(s). Um pagamento pode quitar várias notas (pagamento
-- agrupado), por isso valor_alocado diz quanto dele vai para cada nota.
-- metodo: 'numero', 'competencia', 'cnpj_valor' (regras), 'agente' (aprovado por
-- humano na fase 2) ou NULL quando não foi possível identificar.
CREATE TABLE conciliacao_pagamentos (
    id             serial PRIMARY KEY,
    pagamento_id   int NOT NULL REFERENCES pagamentos(id),
    nota_id        int REFERENCES notas_fiscais(id),
    metodo         text,
    valor_alocado  numeric(12,2),          -- NULL = o pagamento inteiro
    executado_em   timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (pagamento_id, nota_id)
);

-- Propostas do agente aguardando (ou já com) decisão humana.
CREATE TABLE propostas_agente (
    pagamento_id   int PRIMARY KEY REFERENCES pagamentos(id),
    thread_id      text NOT NULL,          -- conversa do agente no checkpointer (Redis)
    nota_numeros   int[] NOT NULL DEFAULT '{}',
    confianca      text,
    justificativa  text,
    valida         boolean,                -- passou na checagem determinística?
    problema       text,                   -- por que não passou
    status         text NOT NULL DEFAULT 'pendente',   -- pendente | aprovada | rejeitada
    criado_em      timestamptz NOT NULL DEFAULT now(),
    decidido_em    timestamptz
);

-- Fase 3: e-mails da caixa de entrada, com o que a IA extraiu e o que o código conferiu.
CREATE TABLE documentos (
    arquivo                text PRIMARY KEY,
    remetente              text,
    assunto                text,
    tipo                   text,          -- comprovante | contestacao | aviso_pagamento | outro
    cnpj                   text,
    notas_citadas          int[] NOT NULL DEFAULT '{}',
    valor_pago             numeric(12,2),
    valor_correto_alegado  numeric(12,2),
    resumo                 text,
    contem_instrucoes      boolean NOT NULL DEFAULT false,   -- a IA achou instruções no texto?
    padroes_suspeitos      text[] NOT NULL DEFAULT '{}',     -- o que o detector por regra achou
    status                 text,          -- resultado da conferência (ver app/documentos.py)
    detalhe                text,
    processado_em          timestamptz NOT NULL DEFAULT now()
);
