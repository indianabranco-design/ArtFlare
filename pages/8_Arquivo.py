import os
import pandas as pd
import streamlit as st
from datetime import datetime
from sqlmodel import select


def to_float0(v):
    """Convert values like '€ 12,34' or None into a safe float (>=0), defaulting to 0.0."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except Exception:
            return 0.0
    try:
        s = str(v).strip().replace("€", "").replace("\u00a0", " ")
        s = s.replace(" ", "")
        # remove thousands dot and use comma as decimal
        s = s.replace(".", "").replace(",", ".")
        return float(s) if s else 0.0
    except Exception:
        return 0.0

# Import robusto do sidebar
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

# Importar modelos e utils da BD (NÃO redefinir modelos aqui)
from app.db import (
    get_session,
    Quote,
    QuoteItem,
    QuoteVersion,
    Client,
    Settings,
    StockMovement,
    Material,
    upgrade_quotes_metrics,
)
from app.pdf_utils import gerar_pdf_orcamento

st.title("📚 Arquivo de Orçamentos")

# Garantir que as colunas novas existem (migração idempotente)
try:
    upgrade_quotes_metrics()
except Exception:
    pass

# Carregar orçamentos arquivados
with get_session() as s:
    qs = s.exec(select(Quote).where(Quote.estado == "ARQUIVADO").order_by(Quote.id.desc())).all()

if not qs:
    st.info("Ainda não existem orçamentos arquivados.")
    st.stop()

# Mapa de clientes para labeling
with get_session() as s:
    clients = s.exec(select(Client)).all()
client_map = {c.id: c for c in clients}

qsel = st.selectbox(
    "Escolha um orçamento",
    qs,
    format_func=lambda o: f"{o.numero or '—'} — {getattr(client_map.get(o.cliente_id), 'nome', 'Cliente desconhecido')} — "
                          f"{(o.data_criacao.date().isoformat() if getattr(o,'data_criacao',None) else '')}",
)

# Resumo do orçamento selecionado
st.divider()
st.subheader("Resumo")
cli = client_map.get(qsel.cliente_id)
c1, c2, c3, c4 = st.columns([1,1,1,1])
c1.metric("Nº", qsel.numero or "—")
c2.metric("Cliente", getattr(cli, 'nome', '—'))
c3.metric("Estado", getattr(qsel, 'estado', '—'))
c4.metric("Criado em", (qsel.data_criacao.date().isoformat() if getattr(qsel,'data_criacao',None) else '—'))
c1b, c2b = st.columns([1,1])
c1b.metric("Entrega prevista", (qsel.data_entrega_prevista.date().isoformat() if getattr(qsel,'data_entrega_prevista',None) else '—'))

# Métricas agregadas (robustas)
# Material, Serviços (preferir campo interno; cair para antigo se existir), Total final
cmat = to_float0(getattr(qsel, 'total_material_cost_eur', None))
csrv_raw = getattr(qsel, 'total_service_internal_cost_eur', None)
if csrv_raw is None:
    csrv_raw = getattr(qsel, 'total_service_cost_eur', None)  # retro-compatibilidade
csrv = to_float0(csrv_raw)
final = to_float0(getattr(qsel, 'final_total_eur', None))

# Custo total = material + serviços (sempre)
tcost = cmat + csrv

# % gastos só se houver total final > 0
exp_pct = None
if final > 0:
    try:
        exp_pct = (tcost / final) * 100.0
    except Exception:
        exp_pct = None

# Lucro (fallback quando não existe): final - custos
profit = getattr(qsel, 'profit_eur', None)
if profit is None:
    profit = max(0.0, final - tcost)

# Se algum destes campos estiver em falta na BD, grava agora (apenas campos existentes no modelo)
new_vals = {}
if getattr(qsel, 'total_material_cost_eur', None) is None:
    new_vals['total_material_cost_eur'] = float(cmat)
if getattr(qsel, 'final_total_eur', None) is None and final is not None:
    new_vals['final_total_eur'] = float(final)
if getattr(qsel, 'expense_percent', None) is None and exp_pct is not None:
    new_vals['expense_percent'] = float(exp_pct)
if getattr(qsel, 'profit_eur', None) is None and profit is not None:
    new_vals['profit_eur'] = float(profit)

if new_vals:
    with get_session() as s:
        q = s.get(Quote, qsel.id)
        if q:
            for k, v in new_vals.items():
                setattr(q, k, v)
            s.add(q)
            s.commit()

# Descrição e Observações
desc_txt = (getattr(qsel,'descricao','') or None)
obs_txt = (getattr(qsel,'observacoes','') or None) if hasattr(qsel,'observacoes') else None
# Datas para cálculo de dias
dt_created = getattr(qsel,'data_criacao', None)
dt_conc = getattr(qsel,'data_conclusao', None) if hasattr(qsel,'data_conclusao') else getattr(qsel,'concluded_at', None)
dt_arch = getattr(qsel,'archived_at', None) if hasattr(qsel,'archived_at') else getattr(qsel,'data_arquivado', None)
# Calcular dias até conclusão/arquivo
days_to_close = None
try:
    end_dt = dt_conc or dt_arch
    if dt_created and end_dt:
        days_to_close = (end_dt.date() - dt_created.date()).days
except Exception:
    days_to_close = None
# Estado de aprovação (se existir no modelo)
status_aprov = None
try:
    if hasattr(qsel,'aprovado'):
        status_aprov = 'Aprovado' if bool(getattr(qsel,'aprovado')) else 'Rejeitado'
    elif hasattr(qsel,'foi_aprovado'):
        status_aprov = 'Aprovado' if bool(getattr(qsel,'foi_aprovado')) else 'Rejeitado'
    elif hasattr(qsel,'status') and str(getattr(qsel,'status')).upper() in ('APROVADO','REJEITADO'):
        status_aprov = str(getattr(qsel,'status')).capitalize()
except Exception:
    status_aprov = None

m1, m2, m3 = st.columns(3)
m1.metric("Total final (€)", f"€ {final:.2f}")
m2.metric("Custo material (€)", f"€ {cmat:.2f}")
m3.metric("Custo serviços (€)", f"€ {csrv:.2f}")

m4, m5, m6 = st.columns(3)
m4.metric("Lucro (€)", f"€ {float(profit):.2f}")
m5.metric("% gastos", ("—" if exp_pct is None else f"{float(exp_pct):.1f}%"))
m6.metric("Custo total (€)", f"€ {tcost:.2f}")

# Descrição e Observações (se existirem)
if desc_txt:
    with st.expander("📝 Descrição", expanded=False):
        st.write(desc_txt)
if obs_txt:
    with st.expander("📌 Observações", expanded=False):
        st.write(obs_txt)

# Dias até conclusão/arquivo e aprovação
d1, d2 = st.columns(2)
d1.metric("Dias até conclusão/arquivo", ("—" if days_to_close is None else f"{int(days_to_close)}"))
d2.metric("Aprovação", (status_aprov or "—"))

# Ações
ac1, ac2, ac3 = st.columns([1,1,2])
if ac1.button("✏️ Abrir no Orçamentos"):
    st.session_state['current_quote_id'] = qsel.id
    try:
        st.switch_page("pages/3_Orcamentos.py")
    except Exception:
        st.info("Vai ao menu e abre a página 'Orçamentos' — o orçamento já está selecionado.")
        st.rerun()
if ac2.button("↩️ Reativar (voltar ao Planeamento)"):
    with get_session() as s:
        q = s.get(Quote, qsel.id)
        if q:
            q.estado = "PLANEAMENTO"
            s.add(q); s.commit()
    st.success("Orçamento reativado e devolvido ao Planeamento.")
    st.rerun()

# Versões disponíveis
with get_session() as s:
    vers = s.exec(select(QuoteVersion).where(QuoteVersion.quote_id == qsel.id).order_by(QuoteVersion.version_num.desc())).all()

st.subheader("Versões")
if not vers:
    st.info("Ainda não há versões guardadas para este orçamento.")
else:
    for v in vers:
        st.markdown(f"**Versão v{v.version_num}** — {v.created_at.date().isoformat()}")
        if v.pdf_cliente_path and os.path.exists(v.pdf_cliente_path):
            with open(v.pdf_cliente_path, "rb") as f:
                st.download_button("⬇️ PDF cliente", data=f.read(), file_name=os.path.basename(v.pdf_cliente_path), mime="application/pdf", key=f"c{v.id}")
        if getattr(v, 'pdf_interno_path', None) and os.path.exists(v.pdf_interno_path):
            with open(v.pdf_interno_path, "rb") as f:
                st.download_button("⬇️ PDF interno", data=f.read(), file_name=os.path.basename(v.pdf_interno_path), mime="application/pdf", key=f"i{v.id}")

# Itens do orçamento (consulta)
st.subheader("Itens do orçamento")
with get_session() as s:
    itens = s.exec(select(QuoteItem).where(QuoteItem.quote_id == qsel.id)).all()
    cfg = s.exec(select(Settings)).first()

if not itens:
    st.info("Este orçamento não tem itens guardados.")
else:
    rows = []
    uv_price = float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0) if cfg else 0.0
    lang = (getattr(qsel,'lingua','PT') or 'PT').upper()
    total_estimado = 0.0
    for it in itens:
        nome_item = getattr(it,'nome_pt','') or ''
        if lang == 'EN' and (getattr(it,'nome_en','') or ''):
            nome_item = getattr(it,'nome_en')
        elif lang == 'FR' and (getattr(it,'nome_fr','') or ''):
            nome_item = getattr(it,'nome_fr')
        if it.unidade == 'min':
            part = float(getattr(it,'preco_unitario_cliente',0.0) or 0.0) * float(getattr(it,'quantidade',0.0) or 0.0)
        else:
            part = float(getattr(it,'preco_unitario_cliente',0.0) or 0.0) * (float(getattr(it,'percent_uso',0.0) or 0.0)/100.0) * float(getattr(it,'quantidade',0.0) or 0.0)
        tl = max(0.0, part - float(getattr(it,'desconto_item',0.0) or 0.0))
        tinta_ml = float(getattr(it,'ink_ml',0.0) or 0.0)
        if tinta_ml > 0:
            tl += uv_price * tinta_ml
        total_estimado += tl
        rows.append({
            "Categoria": getattr(it,'categoria_item','') or '',
            "Código": getattr(it,'code','') or '',
            "Nome": nome_item or (getattr(it,'nome_pt','') or ''),
            "Qtd": float(getattr(it,'quantidade',0.0) or 0.0),
            "Un.": getattr(it,'unidade','') or '',
            "% uso": float(getattr(it,'percent_uso',0.0) or 0.0),
            "Preço un (cliente)": float(getattr(it,'preco_unitario_cliente',0.0) or 0.0),
            "Desc. (€)": float(getattr(it,'desconto_item',0.0) or 0.0),
            "Tinta UV (ml)": tinta_ml,
            "Subtotal (€)": tl,
        })
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Qtd": st.column_config.NumberColumn(format="%.0f"),
            "% uso": st.column_config.NumberColumn(format="%.1f%%"),
            "Preço un (cliente)": st.column_config.NumberColumn(format="€ %.4f"),
            "Desc. (€)": st.column_config.NumberColumn(format="€ %.2f"),
            "Tinta UV (ml)": st.column_config.NumberColumn(format="%.1f"),
            "Subtotal (€)": st.column_config.NumberColumn(format="€ %.2f"),
        }
    )
    st.caption(f"Total estimado (itens): € {total_estimado:,.2f}".replace(","," ").replace(".",",").replace(" ","."))

st.subheader("Todos os orçamentos arquivados")
rows_all = []
for q in qs:
    cli = client_map.get(q.cliente_id)
    mat_q = to_float0(getattr(q, 'total_material_cost_eur', None))
    srv_q = to_float0(getattr(q, 'total_service_internal_cost_eur', getattr(q, 'total_service_cost_eur', None)))
    final_q = to_float0(getattr(q, 'final_total_eur', None))
    tcost_q = mat_q + srv_q
    pct_q = (tcost_q / final_q * 100.0) if final_q > 0 else None

    dt_created_q = getattr(q,'data_criacao', None)
    dt_end_q = (getattr(q,'data_conclusao', None) if hasattr(q,'data_conclusao') else getattr(q,'concluded_at', None)) or (getattr(q,'archived_at', None) if hasattr(q,'archived_at') else getattr(q,'data_arquivado', None))
    days_q = None
    try:
        if dt_created_q and dt_end_q:
            days_q = (dt_end_q.date() - dt_created_q.date()).days
    except Exception:
        days_q = None
    status_ap_q = None
    try:
        if hasattr(q,'aprovado'):
            status_ap_q = 'Aprovado' if bool(getattr(q,'aprovado')) else 'Rejeitado'
        elif hasattr(q,'foi_aprovado'):
            status_ap_q = 'Aprovado' if bool(getattr(q,'foi_aprovado')) else 'Rejeitado'
        elif hasattr(q,'status') and str(getattr(q,'status')).upper() in ('APROVADO','REJEITADO'):
            status_ap_q = str(getattr(q,'status')).capitalize()
    except Exception:
        status_ap_q = None
    rows_all.append({
        "Nº": getattr(q,'numero', None) or '—',
        "Cliente": getattr(cli,'nome','—'),
        "Criado": (q.data_criacao.date().isoformat() if getattr(q,'data_criacao',None) else '—'),
        "Entrega": (q.data_entrega_prevista.date().isoformat() if getattr(q,'data_entrega_prevista',None) else '—'),
        "Final (€)": float(final_q),
        "Custo (€)": float(tcost_q),
        "% gastos": (None if pct_q is None else float(pct_q)),
        "Dias": (None if days_q is None else int(days_q)),
        "Aprovação": (status_ap_q or '—'),
    })
if rows_all:
    df_all = pd.DataFrame(rows_all)
    st.dataframe(
        df_all,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Final (€)": st.column_config.NumberColumn(format="€ %.2f"),
            "Custo (€)": st.column_config.NumberColumn(format="€ %.2f"),
            "% gastos": st.column_config.NumberColumn(format="%.1f%%"),
            "Dias": st.column_config.NumberColumn(format="%d"),
        }
    )
else:
    st.info("Sem orçamentos arquivados para listar.")

st.divider()
with st.expander("⚠️ Limpeza do ARQUIVO (TESTES)", expanded=False):
    st.warning("Isto vai apagar **TODOS** os orçamentos em ARQUIVADO (e versões/itens) e repor stock quando possível.")
    c1, c2 = st.columns([1,1])
    do_clean = c1.checkbox("Sim, quero apagar TODO o arquivo (ARQUIVADO)")
    confirm = c2.text_input("Escreve APAGAR para confirmar", value="")
    if st.button("🗑️ Limpar arquivo e repor stock", type="primary", disabled=not (do_clean and confirm.strip().upper() == "APAGAR")):
        STOCK_FIELDS = [
            'stock_qty','quantidade_stock','quantidade_em_stock','qtd_em_stock','qtd_stock','em_stock','stock','quantidade'
        ]
        with get_session() as s:
            qs_arch = s.exec(select(Quote).where(Quote.estado == "ARQUIVADO")).all()
            if not qs_arch:
                st.info("Não há orçamentos em ARQUIVADO para limpar.")
                st.stop()
            quote_ids = [q.id for q in qs_arch]
            movs = s.exec(select(StockMovement).where(StockMovement.quote_id.in_(quote_ids))).all()
            mats = {m.code: m for m in s.exec(select(Material)).all()}
            repostos = 0
            for mv in movs:
                code = getattr(mv, 'code', '')
                qty = float(getattr(mv, 'qty_delta', 0.0) or 0.0)
                if qty == 0:
                    continue
                restore = -qty
                if restore <= 0:
                    continue
                mat = mats.get(code)
                if not mat:
                    continue
                for fname in STOCK_FIELDS:
                    if hasattr(mat, fname):
                        try:
                            cur = getattr(mat, fname)
                            cur = 0.0 if cur is None else float(cur)
                            setattr(mat, fname, cur + restore)
                            s.add(mat)
                            repostos += 1
                            break
                        except Exception:
                            continue
            # apagar movimentos, versões, itens e orçamentos
            for mv in movs:
                try:
                    s.delete(mv)
                except Exception:
                    pass
            vers_del = s.exec(select(QuoteVersion).where(QuoteVersion.quote_id.in_(quote_ids))).all()
            for v in vers_del:
                try:
                    s.delete(v)
                except Exception:
                    pass
            itens_del = s.exec(select(QuoteItem).where(QuoteItem.quote_id.in_(quote_ids))).all()
            for it in itens_del:
                try:
                    s.delete(it)
                except Exception:
                    pass
            for q in qs_arch:
                try:
                    s.delete(q)
                except Exception:
                    pass
            s.commit()
        st.success("Arquivo limpo e stock reposto (quando possível).")
        st.rerun()
