# pages/Importar_Orcamentos_Arquivo.py
import io
from datetime import datetime, date
import pandas as pd
import streamlit as st
from sqlmodel import select

from app.db import get_session, Client, Quote, QuoteItem  # usa os teus modelos

# Sidebar (import robusto)
try:
    from app.sidebar import show_sidebar
except Exception:
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.sidebar import show_sidebar
show_sidebar()

st.title("📥 Importar Orçamentos Antigos → Arquivo (BD)")

# ===== Helpers de leitura (CSV sempre, Excel se openpyxl existir) =====
def read_table(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    bio = io.BytesIO(data)
    try_xlsx = name.endswith(".xlsx") or name.endswith(".xls")
    if try_xlsx:
        try:
            import openpyxl  # noqa: F401
            return pd.read_excel(bio).fillna("")
        except Exception:
            st.warning("Não consegui ler Excel (openpyxl não instalado). Vou tentar CSV.")
    # CSV: separador automático
    text = data.decode("utf-8", errors="ignore")
    sep = ";" if text.count(";") > text.count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep).fillna("")

def parse_date(val):
    if isinstance(val, (datetime, date)):
        return datetime(val.year, val.month, val.day)
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return datetime(dt.year, dt.month, dt.day)
        except Exception:
            pass
    return None

def to_float(v, default=0.0):
    try:
        if isinstance(v, str):
            v = v.replace("€", "").replace(",", ".").strip()
        return float(v)
    except Exception:
        return default


import re

_num_rx = re.compile(r"\D+")

# ===== Normalização automática de cabeçalhos (ajuda no mapeamento) =====
# Mapas separados para Orçamentos e Itens, para evitar colisões de nomes
_alias_map_q = {
    "numero": ["numero","nº","n°","num","nr","n","no","n.º","n.o","orcamento","n_orcamento","n orcamento","nº orçamento","n orc","numero orcamento","número"],
    "data": ["data","data orçamento","data_orc","emissao","data emissao","emissão","data criacao","data criação"],
    "cliente_numero": ["cliente nº","cliente_numero","nº cliente","cod cliente","id cliente","codigo cliente","cód cliente"],
    "cliente_nome": ["cliente","cliente nome","nome cliente","cliente_nome"],
    "estado": ["estado","status","situação","situacao"],
    "lingua": ["lingua","idioma","língua"],
    "descricao": ["descricao","descrição","descr","descrição do trabalho","descricao do trabalho"],
    "observ": ["observ","observacoes","observações","obs","notas","observacoes internas","observações internas"],
    "desconto_total": ["desconto","desconto total","desconto_total"],
    "iva_percent": ["iva","iva %","iva_percent","taxa iva","taxa de iva"],
    "data_entrega": ["data entrega","entrega","data_entrega","data de entrega"],
    "total_final": ["total","total final","valor final","total_final","total cliente"],
    "total_cost": ["custo total","custo_total","custos","total custos","total de custos","custo orçamento","custo orcamento"],
    "aprovacao": ["aprovacao","aprovado","aprov.","aprov","foi aprovado","resultado","status aprovacao","estado aprovacao", "aprovação"],
    "data_aprovacao": [
        "data aprovação", "data aprovacao", "aprovado em", "data de aprovação", "data de aprovacao", "aprov em"
    ],
}

_alias_map_i = {
    "quote_id": ["id orçamento","id orcamento","orcamento id","quote id","id_quote","quote_id"],
    "quote_numero": ["nº orçamento","numero orçamento","num orçamento","n orcamento","numero orcamento","orcamento","orçamento","n orc","nº orc","orc nº","orc no","orc n°"],
    "tipo_item": ["tipo","tipo item","tipo_item","material/servico","material/serviço"],
    "code": ["codigo","código","ref","referencia","referência","sku","code","cód"],
    "categoria": ["categoria","família","familia","grupo","secção","seccao","seção"],
    "unidade": ["unidade","un.","unid","un","uni","ud"],
    "largura_cm": ["largura","larg (cm)","largura (cm)","larg_cm","largura_cm","larg"],
    "altura_cm": ["altura","alt (cm)","altura (cm)","alt_cm","altura_cm","alt"],
    "quantidade": ["quantidade","qtd","quant","qtde","qte","qtd."],
    "preco_unit": ["preco","preço","preco unitario","preço unitário","pv unit","p.u.","pvu","valor unit","valor unitário"],
    "percent_uso": ["% uso","percent uso","%", "% utilizado","percentagem uso","percentual uso"],
    "desconto_item": ["desconto item","desconto linha","desc linha","desc item","desconto","desc"],
    "nome_pt": ["nome","designação","designacao","descricao item","descrição item","titulo","título"],
}

def _clean_hdr(h: str) -> str:
    return str(h or "").strip().lower().replace("\n"," ").replace("\t"," ").replace("  "," ")

def _normalize_cols_with_alias(df: pd.DataFrame, alias_map: dict) -> pd.DataFrame:
    cols = list(df.columns)
    mapped = {}
    used = set()
    for c in cols:
        key = _clean_hdr(c)
        target = None
        for canon, variants in alias_map.items():
            if key in variants:
                target = canon
                break
        if target is None:
            mapped[c] = c
            continue
        # evitar colisões: se já existir essa coluna canónica no DF, não renomear
        if target in used or target in cols:
            mapped[c] = c
        else:
            mapped[c] = target
            used.add(target)
    try:
        return df.rename(columns=mapped)
    except Exception:
        return df

def normalize_cols_quotes(df: pd.DataFrame) -> pd.DataFrame:
    return _normalize_cols_with_alias(df, _alias_map_q)

def normalize_cols_items(df: pd.DataFrame) -> pd.DataFrame:
    return _normalize_cols_with_alias(df, _alias_map_i)

def normalize_num_with_year(raw_num: str | int | float, dt: datetime | None, entrega_dt: datetime | None) -> str:
    """Devolve número no formato YY####.
    - Se já vier no formato YY####, respeita-o.
    - Caso contrário, usa o ano de `dt` (ou `entrega_dt`, senão ano atual) e o número limpo, zero-padded a 4.
    """
    s = str(raw_num or "").strip()
    if not s:
        return ""
    # se já estiver no formato 6 dígitos (YY + 4 dígitos), mantém
    if s.isdigit() and len(s) == 6:
        return s
    # limpar para só dígitos
    digits = _num_rx.sub("", s)
    if not digits.isdigit():
        return ""  # não conseguimos normalizar
    try:
        base_n = int(digits)
    except Exception:
        return ""
    if dt:
        yy = f"{dt.year % 100:02d}"
    elif entrega_dt:
        yy = f"{entrega_dt.year % 100:02d}"
    else:
        yy = datetime.utcnow().strftime("%y")
    return f"{yy}{base_n:04d}"

# ===== Upload dos ficheiros =====
col_up1, col_up2 = st.columns(2)
with col_up1:
    f_quotes = st.file_uploader("Ficheiro de ORÇAMENTOS (obrigatório)", type=["csv","xlsx"])
with col_up2:
    f_items = st.file_uploader("Ficheiro de ITENS (opcional)", type=["csv","xlsx"])

if not f_quotes:
    st.info("Carrega pelo menos o ficheiro de **Orçamentos**.")
    st.stop()

df_q = normalize_cols_quotes(read_table(f_quotes))
df_i = normalize_cols_items(read_table(f_items)) if f_items else pd.DataFrame()

st.subheader("Pré-visualização")
st.write("Orçamentos:", df_q.shape, "linhas")
st.dataframe(df_q.head(10), use_container_width=True)
if not df_i.empty:
    st.write("Itens:", df_i.shape, "linhas")
    st.dataframe(df_i.head(10), use_container_width=True)

# ===== Mapeamento de colunas =====
st.markdown("### Mapeamento de colunas (Orçamentos)")

def sb(label, options, pref=None, key=None):
    idx = 0
    if pref and pref in options:
        idx = options.index(pref)
    return st.selectbox(label, options, index=idx, key=key)

cols_q = ["—"] + list(df_q.columns)
m_q = {}
c1, c2, c3 = st.columns(3)
with c1:
    m_q["numero"]         = sb("Número do orçamento", cols_q, key="q_numero")
    m_q["data"]           = sb("Data do orçamento", cols_q, key="q_data")
    m_q["cliente_numero"] = sb("Cliente Nº", cols_q, key="q_cli_num")
    m_q["cliente_nome"]   = sb("Cliente Nome", cols_q, key="q_cli_nome")
with c2:
    m_q["estado"]         = sb("Estado (ARQUIVADO/ENTREGUE/REJEITADO…)", cols_q, key="q_estado")
    m_q["lingua"]         = sb("Língua (PT/EN/FR)", cols_q, key="q_lang")
    m_q["descricao"]      = sb("Descrição", cols_q, key="q_desc")
    m_q["observ"]         = sb("Observações internas", cols_q, key="q_obs")
with c3:
    m_q["desconto_total"] = sb("Desconto total €", cols_q, key="q_desc_total")
    m_q["iva_percent"]    = sb("IVA %", cols_q, key="q_iva")
    m_q["data_entrega"]   = sb("Data de entrega", cols_q, key="q_entrega")
    m_q["total_final"]    = sb("Total final € (opcional)", cols_q, key="q_total")

# Campos adicionais (opcionais) para gravar no Quote
c7, c8, c9 = st.columns(3)
with c7:
    m_q["total_mat_cost"] = sb("Custo materiais € (opcional)", cols_q, key="q_mat_cost")
    m_q["total_srv_cost"] = sb("Custo serviços € (opcional)", cols_q, key="q_srv_cost")
with c8:
    m_q["profit"]      = sb("Lucro € (opcional)", cols_q, key="q_profit")
    m_q["expense_pct"] = sb("% gastos (opcional)", cols_q, key="q_expense_pct")
    m_q["aprovacao"]  = sb("Aprovação (SIM/NÃO) (opcional)", cols_q, key="q_aprov")
with c9:
    m_q["data_conclusao"] = sb("Data de conclusão (opcional)", cols_q, key="q_dt_conc")
    m_q["data_arquivado"] = sb("Data arquivado (opcional)", cols_q, key="q_dt_arch")
    m_q["total_cost"] = sb("Custo total € (opcional)", cols_q, key="q_total_cost")
    m_q["data_aprovacao"] = sb("Data de aprovação (opcional)", cols_q, key="q_dt_aprov")

st.markdown("### Mapeamento de colunas (Itens) — opcional")
cols_i = ["—"] + list(df_i.columns) if not df_i.empty else ["—"]
m_i = {}

c4, c5, c6 = st.columns(3)
with c4:
    m_i["quote_id"]       = sb("ID orçamento (ligação, opcional)", cols_i, key="i_qid")
    m_i["quote_numero"]   = sb("Nº orçamento (ligação)", cols_i, key="i_qnum")
    m_i["tipo_item"]      = sb("Tipo (MATERIAL/SERVICO)", cols_i, key="i_tipo")
    m_i["code"]           = sb("Código do item", cols_i, key="i_code")
    m_i["categoria"]      = sb("Categoria", cols_i, key="i_cat")
with c5:
    m_i["unidade"]        = sb("Unidade (cm2/PC/min)", cols_i, key="i_uni")
    m_i["largura_cm"]     = sb("Largura (cm)", cols_i, key="i_larg")
    m_i["altura_cm"]      = sb("Altura (cm)", cols_i, key="i_alt")
    m_i["quantidade"]     = sb("Quantidade", cols_i, key="i_qtd")
with c6:
    m_i["preco_unit"]     = sb("Preço unitário cliente €", cols_i, key="i_preco")
    m_i["percent_uso"]    = sb("% uso", cols_i, key="i_uso")
    m_i["desconto_item"]  = sb("Desconto item €", cols_i, key="i_desc")
    m_i["nome_pt"]        = sb("Nome PT (opcional)", cols_i, key="i_nomept")

st.caption("Se mapear **ID orçamento**, ele tem prioridade para ligar os itens; caso contrário usamos o **Nº orçamento**.")

st.markdown("### Opções")
estado_default = st.selectbox("Estado padrão para importação", ["ARQUIVADO","ENTREGUE","REJEITADO","PAGO","ENVIADO","RASCUNHO"], index=0)
gerar_numero_se_faltar = st.toggle("Gerar número de orçamento se não vier no ficheiro", True)

st.markdown("---")
if st.button("🚀 Importar para a BD"):
    imp_q = 0
    imp_i = 0
    dup_q = 0
    erros = []

    with get_session() as s:
        # cache de clientes por (numero, nome)
        cache_num = {}
        cache_nome = {}

        def get_or_create_client(num, nome):
            num_i = None
            if num is not None and str(num).strip():
                try:
                    num_i = int(str(num).strip())
                    if num_i in cache_num:
                        return cache_num[num_i]
                    c = s.exec(select(Client).where(Client.numero_cliente == num_i)).first()
                    if c:
                        cache_num[num_i] = c
                        cache_nome[getattr(c,"nome","").lower()] = c
                        return c
                except Exception:
                    num_i = None
            if nome and str(nome).strip():
                key = str(nome).strip().lower()
                if key in cache_nome:
                    return cache_nome[key]
                c = s.exec(select(Client).where(Client.nome == str(nome).strip())).first()
                if c:
                    cache_nome[key] = c
                    if getattr(c,"numero_cliente",None) is not None:
                        cache_num[int(c.numero_cliente)] = c
                    return c
                # criar novo
                c = Client(
                    numero_cliente = (num_i if num_i is not None else None),
                    nome = str(nome).strip(),
                    created_at = datetime.now(),
                    updated_at = datetime.now(),
                )
                # se não tem número, atribuir um novo
                if getattr(c, "numero_cliente", None) in (None, 0):
                    try:
                        mx = s.exec(select(Client).order_by(Client.numero_cliente.desc())).first()
                        c.numero_cliente = (getattr(mx, "numero_cliente", 0) or 0) + 1
                    except Exception:
                        c.numero_cliente = 1
                s.add(c); s.commit(); s.refresh(c)
                cache_nome[key] = c
                cache_num[int(c.numero_cliente)] = c
                return c
            return None

        # -------- Orçamentos --------
        for idx, row in df_q.iterrows():
            try:
                num = row.get(m_q["numero"], "") if m_q["numero"] != "—" else ""
                dt  = parse_date(row.get(m_q["data"], "")) if m_q["data"] != "—" else None
                cli_num = row.get(m_q["cliente_numero"], "") if m_q["cliente_numero"] != "—" else ""
                cli_nom = row.get(m_q["cliente_nome"], "") if m_q["cliente_nome"] != "—" else ""
                estado = row.get(m_q["estado"], "") if m_q["estado"] != "—" else estado_default
                lingua = (row.get(m_q["lingua"], "") if m_q["lingua"] != "—" else "PT") or "PT"
                desc   = row.get(m_q["descricao"], "") if m_q["descricao"] != "—" else ""
                obs    = row.get(m_q["observ"], "") if m_q["observ"] != "—" else ""
                desc_total = to_float(row.get(m_q["desconto_total"], 0)) if m_q["desconto_total"] != "—" else 0.0
                iva_pct    = to_float(row.get(m_q["iva_percent"], 0)) if m_q["iva_percent"] != "—" else 0.0
                entrega    = parse_date(row.get(m_q["data_entrega"], "")) if m_q["data_entrega"] != "—" else None
                total_fin  = to_float(row.get(m_q["total_final"], 0)) if m_q["total_final"] != "—" else None

                # opcionais extra
                tot_mat  = to_float(row.get(m_q.get("total_mat_cost","—"), 0)) if m_q.get("total_mat_cost","—") != "—" else None
                tot_srv  = to_float(row.get(m_q.get("total_srv_cost","—"), 0)) if m_q.get("total_srv_cost","—") != "—" else None
                profit_v = to_float(row.get(m_q.get("profit","—"), 0)) if m_q.get("profit","—") != "—" else None
                exp_pct  = to_float(row.get(m_q.get("expense_pct","—"), 0)) if m_q.get("expense_pct","—") != "—" else None
                dt_conc  = parse_date(row.get(m_q.get("data_conclusao","—"), "")) if m_q.get("data_conclusao","—") != "—" else None
                dt_arch  = parse_date(row.get(m_q.get("data_arquivado","—"), "")) if m_q.get("data_arquivado","—") != "—" else None
                dt_aprov = parse_date(row.get(m_q.get("data_aprovacao","—"), "")) if m_q.get("data_aprovacao","—") != "—" else None
                tot_cost = to_float(row.get(m_q.get("total_cost","—"), 0)) if m_q.get("total_cost","—") != "—" else None
                # aprovação (SIM/NÃO)
                aprov_raw = row.get(m_q.get("aprovacao","—"), "") if m_q.get("aprovacao","—") != "—" else ""
                def _parse_aprov(v):
                    s = str(v or "").strip().upper()
                    if s in ("SIM","YES","Y","TRUE","1","APROVADO","OK"): return True
                    if s in ("NAO","NÃO","NO","N","FALSE","0","REJEITADO"): return False
                    return None
                aprov_val = _parse_aprov(aprov_raw)

                # cliente
                cli = get_or_create_client(cli_num, cli_nom)
                if not cli:
                    erros.append(f"Linha {idx+1}: sem cliente (número/nome).")
                    continue

                # número do orçamento (respeitar número do ficheiro mas com prefixo do ano → YY####)
                numero_ok = ""
                raw_num = str(num).strip()
                if raw_num:
                    numero_ok = normalize_num_with_year(raw_num, dt, entrega)
                # se ainda vazio e a opção permitir, gerar sequencial do ano atual
                if not numero_ok and gerar_numero_se_faltar:
                    yy = datetime.utcnow().strftime("%y")
                    existentes = s.exec(select(Quote).where(Quote.numero.like(f"{yy}%"))).all()
                    seq = 0
                    if existentes:
                        try:
                            seq = max([int(str(q.numero)[2:]) for q in existentes if getattr(q, 'numero', None) and len(str(q.numero)) >= 6])
                        except Exception:
                            seq = 0
                    numero_ok = f"{yy}{seq+1:04d}"

                # duplicado?
                if numero_ok:
                    dup = s.exec(select(Quote).where(Quote.numero == numero_ok)).first()
                    if dup:
                        dup_q += 1
                        continue

                q = Quote(
                    numero = numero_ok if numero_ok else None,
                    cliente_id = cli.id,
                    lingua = lingua,
                    descricao = desc,
                    desconto_total = desc_total,
                    iva_percent = iva_pct,
                    data_criacao = dt or datetime.utcnow(),
                    data_entrega_prevista = entrega,
                    estado = estado or estado_default,
                    observacoes = obs if hasattr(Quote, "observacoes") else None,
                )
                # se o teu modelo tiver 'total' e forneceste:
                if hasattr(Quote, "total") and total_fin is not None:
                    setattr(q, "total", total_fin)

                s.add(q); s.commit(); s.refresh(q)

                # aplicar campos opcionais mapeados, apenas se o modelo tiver esses atributos
                changed = False
                try:
                    if total_fin is not None and hasattr(q, "final_total_eur"):
                        setattr(q, "final_total_eur", float(total_fin))
                        changed = True
                except Exception:
                    pass
                try:
                    if tot_mat is not None and hasattr(q, "total_material_cost_eur"):
                        setattr(q, "total_material_cost_eur", float(tot_mat))
                        changed = True
                except Exception:
                    pass
                try:
                    if tot_srv is not None and hasattr(q, "total_service_cost_eur"):
                        setattr(q, "total_service_cost_eur", float(tot_srv))
                        changed = True
                except Exception:
                    pass
                try:
                    if profit_v is not None and hasattr(q, "profit_eur"):
                        setattr(q, "profit_eur", float(profit_v))
                        changed = True
                except Exception:
                    pass
                try:
                    if exp_pct is not None and hasattr(q, "expense_percent"):
                        setattr(q, "expense_percent", float(exp_pct))
                        changed = True
                except Exception:
                    pass
                # datas opcionais
                try:
                    if dt_conc and (hasattr(q, "data_conclusao") or hasattr(q, "concluded_at")):
                        if hasattr(q, "data_conclusao"):
                            setattr(q, "data_conclusao", dt_conc)
                        elif hasattr(q, "concluded_at"):
                            setattr(q, "concluded_at", dt_conc)
                        changed = True
                except Exception:
                    pass
                try:
                    if dt_arch and (hasattr(q, "archived_at") or hasattr(q, "data_arquivado")):
                        if hasattr(q, "archived_at"):
                            setattr(q, "archived_at", dt_arch)
                        elif hasattr(q, "data_arquivado"):
                            setattr(q, "data_arquivado", dt_arch)
                        changed = True
                except Exception:
                    pass
                try:
                    if tot_cost is not None and hasattr(q, "total_cost_eur"):
                        setattr(q, "total_cost_eur", float(tot_cost))
                        changed = True
                except Exception:
                    pass
                try:
                    if aprov_val is not None:
                        if hasattr(q, "aprovado"):
                            setattr(q, "aprovado", bool(aprov_val)); changed = True
                        elif hasattr(q, "foi_aprovado"):
                            setattr(q, "foi_aprovado", bool(aprov_val)); changed = True
                        elif hasattr(q, "status"):
                            setattr(q, "status", "APROVADO" if aprov_val else "REJEITADO"); changed = True
                except Exception:
                    pass
                try:
                    if dt_aprov and hasattr(q, "approved_at"):
                        setattr(q, "approved_at", dt_aprov)
                        changed = True
                    elif (aprov_val is True) and hasattr(q, "approved_at") and getattr(q, "approved_at", None) is None:
                        # Se marcado como aprovado mas sem data, usar a data do orçamento ou agora
                        setattr(q, "approved_at", dt or datetime.utcnow())
                        changed = True
                except Exception:
                    pass
                if changed:
                    s.add(q); s.commit(); s.refresh(q)

                imp_q += 1
            except Exception as e:
                erros.append(f"Linha {idx+1} (orçamento): {e}")

        # -------- Itens (opcional) --------
        if not df_i.empty and imp_q > 0:
            # criar índices por ID e por número
            all_quotes = s.exec(select(Quote)).all()
            quotes_by_id = {int(q.id): q for q in all_quotes if getattr(q, 'id', None) is not None}
            quotes_by_num = {str(q.numero).strip(): q for q in all_quotes if getattr(q, 'numero', None)}
            # mapa por sufixo de 4 dígitos (para itens antigos que só trazem 1..82)
            suffix_map = {}
            for q in all_quotes:
                num = str(getattr(q, 'numero', '') or '').strip()
                if len(num) >= 6 and num.isdigit():
                    suffix = num[-4:]
                    suffix_map.setdefault(suffix, []).append(q)

            for idx, row in df_i.iterrows():
                try:
                    # 1) Tentar por ID interno
                    q = None
                    if m_i.get("quote_id") and m_i["quote_id"] != "—":
                        raw_id = row.get(m_i["quote_id"], "")
                        try:
                            qid = int(str(raw_id).strip())
                            q = quotes_by_id.get(qid)
                        except Exception:
                            q = None

                    # 2) Fallback: tentar por número
                    if q is None:
                        qnum = row.get(m_i.get("quote_numero", "—"), "") if m_i.get("quote_numero", "—") != "—" else ""
                        raw = str(qnum).strip()
                        if raw:
                            # manter tentativa direta primeiro
                            q = quotes_by_num.get(raw)
                            if q is None:
                                # limpar só dígitos
                                digits = ''.join(ch for ch in raw if ch.isdigit())
                                if len(digits) == 6 and digits in quotes_by_num:
                                    q = quotes_by_num.get(digits)
                                elif 1 <= len(digits) <= 4:
                                    suf = digits.zfill(4)
                                    candidates = suffix_map.get(suf, [])
                                    if len(candidates) == 1:
                                        q = candidates[0]
                    if q is None:
                        continue

                    tipo = str(row.get(m_i["tipo_item"], "MATERIAL")).upper() if m_i["tipo_item"] != "—" else "MATERIAL"
                    code = row.get(m_i["code"], "") if m_i["code"] != "—" else ""
                    cat  = row.get(m_i["categoria"], "") if m_i["categoria"] != "—" else ""
                    uni  = row.get(m_i["unidade"], "") if m_i["unidade"] != "—" else "PC"
                    larg = to_float(row.get(m_i["largura_cm"], 0)) if m_i["largura_cm"] != "—" else 0.0
                    alt  = to_float(row.get(m_i["altura_cm"], 0)) if m_i["altura_cm"] != "—" else 0.0
                    qtd  = to_float(row.get(m_i["quantidade"], 1)) if m_i["quantidade"] != "—" else 1.0
                    pvu  = to_float(row.get(m_i["preco_unit"], 0)) if m_i["preco_unit"] != "—" else 0.0
                    uso  = to_float(row.get(m_i["percent_uso"], 100)) if m_i["percent_uso"] != "—" else 100.0
                    dsc  = to_float(row.get(m_i["desconto_item"], 0)) if m_i["desconto_item"] != "—" else 0.0
                    nome_pt = row.get(m_i["nome_pt"], "") if m_i["nome_pt"] != "—" else ""

                    qi = QuoteItem(
                        quote_id = q.id,
                        categoria_item = cat,
                        tipo_item = tipo,
                        ref_id = None,
                        code = code,
                        nome_pt = nome_pt,
                        nome_en = None,
                        nome_fr = None,
                        unidade = uni,
                        largura_cm = larg,
                        altura_cm = alt,
                        quantidade = qtd,
                        preco_unitario_cliente = pvu,
                        percent_uso = uso,
                        desconto_item = dsc,
                    )
                    s.add(qi); s.commit()
                    imp_i += 1
                except Exception as e:
                    erros.append(f"Linha {idx+1} (item): {e}")

    st.success(f"Importação concluída: {imp_q} orçamentos, {imp_i} itens. Duplicados ignorados: {dup_q}.")
    if erros:
        with st.expander("Ver registos com erro"):
            for e in erros[:200]:
                st.write("•", e)