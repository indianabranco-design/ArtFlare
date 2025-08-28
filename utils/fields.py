"""
Mapeamento de campos para normalização (sem alterar o design).
Edita este dicionário para alinhar nomes antigos e novos.
"""
FIELD_MAP = {
    # Datas
    "DATA ORÇAMENTO": "data_orcamento",
    "Data Orçamento": "data_orcamento",
    "data orçamento": "data_orcamento",
    "data_orçamento": "data_orcamento",
    "data_orcamento": "data_orcamento",
    "DATA": "data_orcamento",  # se for usado nesse contexto
    # Cliente
    "Cliente": "cliente",
    "cliente": "cliente",
    "nome_cliente": "cliente",
    "cliente_nome": "cliente",
    # Nº Cliente
    "Nº cliente": "numero_cliente",
    "numero_cliente": "numero_cliente",
    "n_cliente": "numero_cliente",
    "num_cliente": "numero_cliente",
    # Identificadores
    "id_orcamento": "id_orcamento",
    "orcamento_id": "id_orcamento",
    "id": "id",
    # Status
    "Aprovado": "aprovado",
    "aprovado": "aprovado",
    "aprovacao": "aprovado",
    "aprovacao_status": "aprovado",
    # Valores
    "valor_final": "valor_final",
    "Valor Final": "valor_final",
    "total_orcamento": "valor_final",
    "total_com_desconto": "total_com_desconto",
    "desconto": "desconto",
    "custo_total": "custo_total",
    "custos": "custo_total",
    # Notas
    "descricao": "descricao",
    "descrição": "descricao",
    "descricao_geral": "descricao",
    "observacoes": "observacoes",
    "observações": "observacoes",
}
# Campos mínimos esperados em orçamentos
QUOTE_DEFAULTS = {
    "id_orcamento": None,
    "data_orcamento": None,
    "cliente": "",
    "numero_cliente": None,
    "aprovado": None,  # "SIM" | "NAO"/"NÃO" | None
    "valor_final": 0.0,
    "total_com_desconto": None,
    "desconto": 0.0,
    "custo_total": 0.0,
    "descricao": "",
    "observacoes": "",
}
# Campos mínimos esperados em planeamento
PLAN_DEFAULTS = {
    "id_planeamento": None,
    "id_orcamento": None,
    "cliente": "",
    "numero_cliente": None,
    "estado": "Em curso",  # ex.: "Em curso", "Concluído"
    "data_inicio": None,
    "data_fim": None,
    "descricao": "",
    "observacoes": "",
}
# Campos mínimos esperados em arquivo
ARCHIVE_DEFAULTS = {
    "id_arquivo": None,
    "id_orcamento": None,
    "cliente": "",
    "numero_cliente": None,
    "data_conclusao": None,
    "valor_final": 0.0,
    "custo_total": 0.0,
    "percent_gastos": None,
    "aprovado": None,
    "descricao": "",
    "observacoes": "",
}
