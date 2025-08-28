
# AI Fixes — 2025-08-28

- `pages/3_Orcamentos.py`: ao clicar **"Guardar rascunho e enviar para Planeamento"**, agora grava também:
  - `final_total_eur` (total_final),
  - `total_material_cost_eur`,
  - `total_service_internal_cost_eur`,
  - `profit_eur`,
  - `expense_percent`,
  - mantém `desconto_percent` quando disponível.
  Isto assegura que, ao entrar no Planeamento/Arquivo, os dados agregados já vão completos.

- Adicionada pasta `utils/` (pack opcional) com utilitários de normalização e leitura/gravação segura (para futuras integrações; **não altera o design**).
