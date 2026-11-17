# Painel no Power BI: passo a passo

O alvo é a imagem `referencia-painel.png` (mesmos números do banco). Leva uns 40 minutos na primeira vez.

## 1. Preparar o banco (uma vez)

No cmd, dentro de `C:\Users\lucas\conciliador-ia`, com o venv ativo e o Docker rodando:

```
docker compose up -d postgres
python -m app.gerar_dados
python -m app.bi
```

O último comando mostra `33 dias no histórico` e `R$ 45.186,23 em risco`. Se mostrou, o banco está pronto.

## 2. Conectar o Power BI ao Postgres

1. Power BI Desktop > **Obter dados** > **Banco de dados PostgreSQL**.
2. Servidor: `127.0.0.1:5432` · Banco: `conciliador` · Modo: **Importar**.
3. Credenciais: aba **Banco de dados**, usuário `powerbi`, senha `powerbi`.
   Esse usuário só lê. O painel não precisa escrever nada, então não use o `conc`.
4. Se aparecer aviso de criptografia (SSL), confirme a conexão sem criptografia: é um banco local.
5. Marque as 4 visões e clique em **Carregar**:
   `vw_bi_divergencias`, `vw_bi_historico`, `vw_bi_agente`, `vw_bi_documentos`.

Se o Power BI pedir um driver (Npgsql), instale o que ele indicar e reinicie o Power BI.

## 3. Ajustar tipos (Transformar dados)

- `vw_bi_historico[data_base]` e `vw_bi_divergencias[data_base]`: tipo **Data**.
- Colunas `valor_*`: **Número decimal fixo** e formato **Moeda R$**.
- **Fechar e aplicar**.

Não crie relacionamento entre as visões: cada visual usa uma visão só.

## 4. Medidas

**Página inicial > Inserir dados**, crie uma tabela vazia chamada `Medidas`. Em cada medida de
`medidas.dax`: clique na tabela `Medidas` > **Nova medida** > cole uma por vez.

Formatos: `Valor em risco` como moeda; `% resolvível sem humano` e `Variação do risco em 7 dias` como porcentagem.

## 5. Visuais (canvas 16:9)

| Visual | Tipo | Campos |
|---|---|---|
| 4 cartões no topo | Cartão | `Valor em risco`, `Divergências`, `Clientes afetados`, `Vencidas sem pagamento` |
| Valor em risco por dia | Gráfico de área | Eixo X: `vw_bi_historico[data_base]` (desligue a hierarquia de data) · Y: `Risco no histórico` |
| Valor em risco por tipo | Barras horizontais | Eixo Y: `tipo_descricao` · X: `Valor em risco` · Rótulo de dados ligado |
| Clientes com mais valor em risco | Tabela | `cliente`, `Divergências`, `Valor em risco` · Filtro Top N = 7 por `Valor em risco` |
| Faixa de atraso | Colunas | Eixo X: `faixa_atraso` (filtre para tirar o vazio) · Y: `Valor em risco` |

Opcional, em uma 2ª página "IA": cartões com `Propostas do agente`, `% resolvível sem humano`
e `Alertas de segurança`; tabela de `vw_bi_documentos` com `assunto`, `tipo`, `status`.
Antes, rode `python -m app.revisar` (fase 2) e `python -m app.documentos` (fase 3) para essas visões terem dados.

Ordenar as faixas: em `faixa_atraso`, a ordem alfabética já sai certa (`1 a 15`, `16 a 30`, `31 a 60`, `mais de 60`).

## 6. Cores

Uma cor de destaque só: vermelho `#B42318` no valor em risco e nas faixas de atraso; azul `#2563EB` no resto.
Fundo da página `#EEF1F5`, visuais brancos com cantos arredondados.

## 7. Conferir

O cartão `Valor em risco` precisa mostrar **R$ 45.186,23**, o mesmo número da API (`/divergencias`) e do e-mail do n8n.
Se der diferente, a conta está sendo feita no Power BI e não no banco: use sempre a coluna `valor_em_risco`.

## 8. Atualizar

Com o n8n rodando, a conciliação diária grava um retrato novo no histórico. No Power BI, **Atualizar** busca o dia novo.
Salve como `powerbi/conciliacao.pbix` e tire um print do painel para o README e o post.
