import streamlit as st, os
from sqlmodel import select
from app.db import get_session, Settings, Service, Machine, machine_cost_per_min, upgrade_quoteitems_ink_ml, upgrade_machines_table, seed_default_machines_from_settings, upgrade_services_machine_fk
# Import opcional: histórico (tabela)
try:
    from app.db import ServiceCostHistory, upgrade_service_cost_history_table  # type: ignore
except Exception:
    ServiceCostHistory = None  # type: ignore
    def upgrade_service_cost_history_table():
        return None

# Import opcional: coluna machine_type em Service
try:
    from app.db import upgrade_services_machine_type  # type: ignore
except Exception:
    def upgrade_services_machine_type():
        return None

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

st.title("⚙️ Parâmetros")

assets_dir = "assets"

# Import opcional: migração leve da tabela Settings
try:
    from app.db import upgrade_settings_table  # type: ignore
except Exception:
    def upgrade_settings_table():
        return None

# Garantir que a tabela Settings tem as colunas novas
try:
    upgrade_settings_table()
except Exception:
    pass

# Garantir que a tabela de histórico existe
try:
    upgrade_service_cost_history_table()
except Exception:
    pass

# Garantir coluna machine_type em Service
try:
    upgrade_services_machine_type()
except Exception:
    pass

try:
    upgrade_quoteitems_ink_ml()
except Exception:
    pass

# Garantir que as tabelas de máquinas estão prontas
try:
    upgrade_machines_table(); seed_default_machines_from_settings(); upgrade_services_machine_fk()
except Exception:
    pass

with get_session() as s:
    cfg = s.exec(select(Settings)).first()
    if not cfg:
        cfg = Settings()
        s.add(cfg); s.commit(); s.refresh(cfg)

with st.form("form_cfg"):
    c1, c2 = st.columns(2)
    cfg.company_name = c1.text_input("Nome da empresa", value=cfg.company_name)
    cfg.company_vat = c2.text_input("NIF/TVA", value=cfg.company_vat)
    cfg.company_address = c1.text_area("Morada", value=cfg.company_address)
    cfg.currency = c1.selectbox("Moeda", ["EUR","USD","GBP"], index=(["EUR","USD","GBP"].index(cfg.currency) if cfg.currency in ["EUR","USD","GBP"] else 0))
    cfg.vat_rate = c2.number_input("IVA padrão (%)", min_value=0.0, max_value=99.0, value=float(cfg.vat_rate), step=1.0)
    cfg.date_format = c1.selectbox("Formato de data", ["DD-MM-YYYY","YYYY-MM-DD"], index=0 if cfg.date_format!="YYYY-MM-DD" else 1)

    st.markdown("### Pagamento / Faturação")
    p1, p2 = st.columns(2)

    # IBAN: lê de company_bank_iban se existir, caso contrário usa company_iban
    iban_val = p1.text_input(
        "IBAN",
        value=(getattr(cfg, 'company_bank_iban', None) or getattr(cfg, 'company_iban', '') or '')
    )
    # guarda sempre no campo existente company_iban
    cfg.company_iban = iban_val
    # tenta também guardar no campo alternativo, se existir no modelo
    try:
        cfg.company_bank_iban = iban_val
    except Exception:
        pass

    # BIC (SWIFT): suporta dois nomes possíveis
    bic_val = p2.text_input(
        "BIC (SWIFT)",
        value=(getattr(cfg, 'company_bank_bic', None) or getattr(cfg, 'company_bic', '') or '')
    )
    if hasattr(cfg, 'company_bic'):
        cfg.company_bic = bic_val
    try:
        cfg.company_bank_bic = bic_val
    except Exception:
        pass

    # Instruções de pagamento (aparecem no PDF do cliente)
    pay_txt = st.text_area(
        "Instruções de pagamento (PDF cliente)",
        value=(getattr(cfg, 'payment_instructions', '') or ''),
        height=100
    )
    try:
        cfg.payment_instructions = pay_txt
    except Exception:
        pass

    # Validade padrão do orçamento
    qvd = st.number_input(
        "Validade padrão do orçamento (dias)",
        min_value=1,
        max_value=365,
        value=int(getattr(cfg, 'quote_valid_days', 30))
    )
    try:
        cfg.quote_valid_days = int(qvd)
    except Exception:
        pass


    # Helper: mostra em % ao utilizador, guarda como fração (0–1)
    def _percent_input(label: str, frac_value: float, **kwargs) -> float:
        perc_default = float(frac_value or 0.0) * 100.0
        perc = st.number_input(label, min_value=0.0, max_value=1000.0, value=perc_default, step=0.5, **kwargs)
        return float(perc) / 100.0

    # --- Margens ---
    # Se o modelo já tiver margens separadas, mostrar ambas; caso contrário, manter a secção única
    has_split_margins = all([
        hasattr(cfg, 'mat_margin_0_15'), hasattr(cfg, 'mat_margin_16_30'), hasattr(cfg, 'mat_margin_31_70'), hasattr(cfg, 'mat_margin_71_plus'),
        hasattr(cfg, 'srv_margin_0_15'), hasattr(cfg, 'srv_margin_16_30'), hasattr(cfg, 'srv_margin_31_70'), hasattr(cfg, 'srv_margin_71_plus'),
    ])

    if has_split_margins:
        st.markdown("### Margens — Materiais")
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            cfg.mat_margin_0_15 = _percent_input("Até 15% (+)", float(getattr(cfg, 'mat_margin_0_15', 0.0)), key="mat_m0_15")
        with m2:
            cfg.mat_margin_16_30 = _percent_input("16–30% (+)", float(getattr(cfg, 'mat_margin_16_30', 0.0)), key="mat_m16_30")
        with m3:
            cfg.mat_margin_31_70 = _percent_input("31–70% (+)", float(getattr(cfg, 'mat_margin_31_70', 0.0)), key="mat_m31_70")
        with m4:
            cfg.mat_margin_71_plus = _percent_input("71%+ (+)", float(getattr(cfg, 'mat_margin_71_plus', 0.0)), key="mat_m71_plus")

        st.markdown("### Margens — Serviços")
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            cfg.srv_margin_0_15 = _percent_input("Até 15% (+)", float(getattr(cfg, 'srv_margin_0_15', 0.0)), key="srv_m0_15")
        with s2:
            cfg.srv_margin_16_30 = _percent_input("16–30% (+)", float(getattr(cfg, 'srv_margin_16_30', 0.0)), key="srv_m16_30")
        with s3:
            cfg.srv_margin_31_70 = _percent_input("31–70% (+)", float(getattr(cfg, 'srv_margin_31_70', 0.0)), key="srv_m31_70")
        with s4:
            cfg.srv_margin_71_plus = _percent_input("71%+ (+)", float(getattr(cfg, 'srv_margin_71_plus', 0.0)), key="srv_m71_plus")
    else:
        st.markdown("### Margens padrão (Materiais/Serviços)")
        c3, c4, c5, c6 = st.columns(4)
        with c3:
            cfg.margin_0_15 = _percent_input("Até 15% (+)", float(getattr(cfg, 'margin_0_15', 0.0)))
        with c4:
            cfg.margin_16_30 = _percent_input("16–30% (+)", float(getattr(cfg, 'margin_16_30', 0.0)))
        with c5:
            cfg.margin_31_70 = _percent_input("31–70% (+)", float(getattr(cfg, 'margin_31_70', 0.0)))
        with c6:
            cfg.margin_71_plus = _percent_input("71%+ (+)", float(getattr(cfg, 'margin_71_plus', 0.0)))

    # --- Energia (GLOBAL) ---
    st.markdown("### Energia (global)")
    cfg.energy_cost_eur_kwh = st.number_input(
        "Custo energia (€/kWh) — usado por todas as máquinas",
        min_value=0.0,
        value=float(getattr(cfg, 'energy_cost_eur_kwh', 0.0)),
        step=0.01,
        format="%.4f",
        help="Valor único partilhado por todas as máquinas."
    )

    # Guardar valores anteriores para histórico
    prev_custo_total_min = float(getattr(cfg, 'service_cost_eur_per_min', 0.0) or 0.0)
    prev_uv_cost = float(getattr(cfg, 'uv_service_cost_eur_per_min', 0.0) or 0.0)
    submitted = st.form_submit_button("💾 Guardar")
    if submitted:
        new_cost_per_min = float(cfg.service_cost_eur_per_min or 0.0)
        updated = 0
        origin = "Parametros"
        new_cost_uv = float(getattr(cfg, 'uv_service_cost_eur_per_min', 0.0) or 0.0)
        with get_session() as s2:
            # Persistir Settings (merge para garantir persistência, mesmo vindo de outra sessão)
            cfg = s2.merge(cfg)
            s2.commit()
            # Atualizar serviços existentes com base nas máquinas definidas (sem defaults LASER/UV)
            try:
                # construir mapa {nome_maquina: custo_min}
                machine_costs = {}
                machines_all = s2.exec(select(Machine)).all()
                for m in machines_all:
                    try:
                        machine_costs[str(m.name)] = float(machine_cost_per_min(m, cfg))
                    except Exception:
                        continue
                all_svs = s2.exec(select(Service)).all()
                for sv in all_svs:
                    mtype = str(getattr(sv, 'machine_type', '') or '')
                    target = machine_costs.get(mtype)
                    if target is None:
                        continue
                    old = float(getattr(sv, 'custo_por_minuto', 0.0) or 0.0)
                    if target > 0.0 and abs(old - target) > 1e-6:
                        sv.custo_por_minuto = target
                        s2.add(sv)
                        updated += 1
                if updated:
                    s2.commit()
            except Exception:
                pass
            # Registar histórico (se houver alteração do custo total/min)
            try:
                if ServiceCostHistory and abs(prev_custo_total_min - new_cost_per_min) > 1e-9:
                    hist = ServiceCostHistory(
                        old_value=float(prev_custo_total_min),
                        new_value=float(new_cost_per_min),
                        origin=origin,
                        updated_services=int(updated),
                        changed_by=None
                    )
                    s2.add(hist); s2.commit()
            except Exception:
                pass
            try:
                # log também para a máquina UV, se mudou
                prev_uv = float(prev_uv_cost)
                if ServiceCostHistory and abs(prev_uv - new_cost_uv) > 1e-9:
                    hist2 = ServiceCostHistory(
                        old_value=float(prev_uv),
                        new_value=float(new_cost_uv),
                        origin=f"{origin}:UV",
                        updated_services=int(updated),
                        changed_by=None
                    )
                    s2.add(hist2); s2.commit()
            except Exception:
                pass
        msg = "Parâmetros guardados."
        if updated:
            msg += f" Custos por minuto atualizados em {updated} serviços."
        st.success(msg)
        if cfg.logo_path:
            st.image(cfg.logo_path, caption="Logo atual", width=160)

# =====================
# Máquinas (dinâmicas)
# =====================
st.markdown("---")
st.header("🛠️ Máquinas")

with get_session() as s_curr:
    cfg_live = s_curr.exec(select(Settings)).first() or cfg

# Mini-calc helper with unique keys

def mini_calc_wear(prefix_key: str):
    with st.expander("Mini‑calculador de desgaste (€/min)"):
        d1, d2, d3 = st.columns(3)
        preco_compra = d1.number_input("Preço de compra (€)", min_value=0.0, value=0.0, step=100.0, key=f"{prefix_key}_pc")
        valor_residual = d2.number_input("Valor residual (€)", min_value=0.0, value=0.0, step=50.0, key=f"{prefix_key}_res")
        vida_anos = d3.number_input("Vida útil (anos)", min_value=1.0, value=4.0, step=1.0, key=f"{prefix_key}_anos")
        e1, e2 = st.columns(2)
        dias_ano = e1.number_input("Dias de operação/ano", min_value=1, value=220, step=1, key=f"{prefix_key}_dias")
        horas_dia = e2.number_input("Horas de operação/dia", min_value=0.1, value=5.0, step=0.5, key=f"{prefix_key}_horas")
        f1, f2 = st.columns(2)
        manut = f1.number_input("Manutenção anual (€)", min_value=0.0, value=0.0, step=50.0, key=f"{prefix_key}_manut")
        cons = f2.number_input("Consumíveis anuais (€)", min_value=0.0, value=0.0, step=50.0, key=f"{prefix_key}_cons")
        mins_year = float(dias_ano) * float(horas_dia) * 60.0
        if mins_year > 0 and float(vida_anos) > 0:
            depreciacao_min = max(0.0, float(preco_compra) - float(valor_residual)) / (float(vida_anos) * mins_year)
        else:
            depreciacao_min = 0.0
        manut_min = (float(manut) / mins_year) if mins_year > 0 else 0.0
        cons_min = (float(cons) / mins_year) if mins_year > 0 else 0.0
        wear_calc = depreciacao_min + manut_min + cons_min
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Depreciação/min", f"{depreciacao_min:.4f} €")
        mc2.metric("Manutenção/min", f"{manut_min:.4f} €")
        mc3.metric("Consumíveis/min", f"{cons_min:.4f} €")
        mc4.metric("Desgaste calculado", f"{wear_calc:.4f} €")
        return wear_calc

# Nova máquina
with st.expander("➕ Nova máquina"):
    with st.form("new_machine_form"):
        cm1, cm2 = st.columns(2)
        with cm1:
            n_name = st.text_input("Nome da máquina", key="new_name")
            n_power = st.number_input("Potência (W)", min_value=0.0, value=0.0, step=50.0, key="new_power")
            n_wear  = st.number_input("Desgaste (€/min)", min_value=0.0, value=0.0, step=0.01, format="%.4f", key="new_wear")
            n_markup = st.number_input("Lucro (%)", min_value=0.0, max_value=1000.0, value=0.0, step=1.0, key="new_markup")
            n_active = st.checkbox("Ativa", value=True, key="new_active")
        with cm2:
            n_ink   = st.number_input("Tinta (€/ml) — opcional", min_value=0.0, value=0.0, step=0.001, format="%.4f", key="new_ink")
            n_xlab  = st.text_input("Campo extra — rótulo", key="new_xlab")
            n_xval  = st.number_input("Campo extra — valor", min_value=0.0, value=0.0, step=0.01, format="%.4f", key="new_xval")
            preview_new = machine_cost_per_min(Machine(power_watts=n_power, wear_cost_eur_per_min=n_wear, markup_percent=n_markup), cfg_live)
            st.metric("Pré-visualização custo/min (energia global)", f"{preview_new:.4f} €")
        wc_new = mini_calc_wear("newmc")
        cbtn1, cbtn2 = st.columns(2)
        if cbtn1.form_submit_button("💾 Criar máquina"):
            with get_session() as s_new:
                m = Machine(
                    name=n_name,
                    power_watts=float(n_power),
                    wear_cost_eur_per_min=float(n_wear or wc_new or 0.0),
                    markup_percent=float(n_markup),
                    ink_price_eur_ml=float(n_ink),
                    extra_label=(n_xlab or None),
                    extra_value=(n_xval if n_xval else None),
                    active=bool(n_active),
                )
                s_new.add(m); s_new.commit()
                # Recalcular custo/min de todos os serviços após alteração de máquinas
                try:
                    machine_costs_by_id = {}
                    machine_costs_by_name = {}
                    all_m = s_new.exec(select(Machine)).all()
                    for _m in all_m:
                        try:
                            cpm_calc = float(machine_cost_per_min(_m, cfg_live))
                        except Exception:
                            cpm_calc = float(getattr(_m, 'wear_cost_eur_per_min', 0.0) or 0.0)
                        machine_costs_by_id[_m.id] = cpm_calc
                        machine_costs_by_name[str(_m.name)] = cpm_calc
                    svs_all = s_new.exec(select(Service)).all()
                    upd = 0
                    for sv in svs_all:
                        target = None
                        mid = getattr(sv, 'machine_id', None)
                        mtype = str(getattr(sv, 'machine_type', '') or '')
                        if mid in machine_costs_by_id:
                            target = machine_costs_by_id[mid]
                        elif mtype in machine_costs_by_name:
                            target = machine_costs_by_name[mtype]
                        if target is not None and target > 0.0:
                            old = float(getattr(sv, 'custo_por_minuto', 0.0) or 0.0)
                            if abs(old - float(target)) > 1e-6:
                                sv.custo_por_minuto = float(target)
                                s_new.add(sv)
                                upd += 1
                    if upd:
                        s_new.commit()
                        st.info(f"Serviços atualizados: {upd}")
                except Exception:
                    pass
                st.success("Máquina criada.")
                st.rerun()

# Listagem + edição por máquina
with get_session() as s_list:
    machines = s_list.exec(select(Machine)).all()

if not machines:
    st.info("Ainda não há máquinas. Cria a primeira acima.")
else:
    import pandas as pd
    rows = []
    for m in machines:
        preview = machine_cost_per_min(m, cfg_live)
        rows.append({
            "ID": m.id,
            "Nome": m.name,
            "Potência (W)": m.power_watts,
            "Desgaste €/min": m.wear_cost_eur_per_min,
            "Lucro %": m.markup_percent,
            "Custo/min (prev)": round(preview, 4),
            "Ativa": "✔" if m.active else "✖",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    for m in machines:
        with st.expander(f"✏️ Editar #{m.id} — {m.name}"):
            with st.form(f"edit_machine_{m.id}"):
                em1, em2 = st.columns(2)
                with em1:
                    e_name = st.text_input("Nome da máquina", value=m.name, key=f"nm_{m.id}")
                    e_power = st.number_input("Potência (W)", min_value=0.0, value=float(m.power_watts), step=50.0, key=f"pw_{m.id}")
                    e_wear  = st.number_input("Desgaste (€/min)", min_value=0.0, value=float(m.wear_cost_eur_per_min), step=0.01, format="%.4f", key=f"wr_{m.id}")
                    e_markup = st.number_input("Lucro (%)", min_value=0.0, max_value=1000.0, value=float(m.markup_percent), step=1.0, key=f"mk_{m.id}")
                    e_active = st.checkbox("Ativa", value=bool(m.active), key=f"ac_{m.id}")
                with em2:
                    e_ink   = st.number_input("Tinta (€/ml) — opcional", min_value=0.0, value=float(m.ink_price_eur_ml or 0.0), step=0.001, format="%.4f", key=f"ik_{m.id}")
                    e_xlab  = st.text_input("Campo extra — rótulo", value=(m.extra_label or ""), key=f"xl_{m.id}")
                    e_xval  = st.number_input("Campo extra — valor", min_value=0.0, value=float(m.extra_value or 0.0), step=0.01, format="%.4f", key=f"xv_{m.id}")
                    preview_e = machine_cost_per_min(Machine(power_watts=e_power, wear_cost_eur_per_min=e_wear, markup_percent=e_markup), cfg_live)
                    st.metric("Pré-visualização custo/min", f"{preview_e:.4f} €")
                wc_edit = mini_calc_wear(f"mc_{m.id}")
                eb1, eb2, eb3 = st.columns(3)
                if eb1.form_submit_button("💾 Guardar alterações"):
                    with get_session() as s_up:
                        mm = s_up.get(Machine, m.id)
                        mm.name = e_name
                        mm.power_watts = float(e_power)
                        mm.wear_cost_eur_per_min = float(e_wear or wc_edit or 0.0)
                        mm.markup_percent = float(e_markup)
                        mm.ink_price_eur_ml = float(e_ink or 0.0)
                        mm.extra_label = (e_xlab or None)
                        mm.extra_value = (e_xval if e_xval else None)
                        mm.active = bool(e_active)
                        s_up.add(mm); s_up.commit()
                        # Atualizar custos de todos os serviços após alteração desta máquina
                        try:
                            machine_costs_by_id = {}
                            machine_costs_by_name = {}
                            all_m = s_up.exec(select(Machine)).all()
                            for _m in all_m:
                                try:
                                    cpm_calc = float(machine_cost_per_min(_m, cfg_live))
                                except Exception:
                                    cpm_calc = float(getattr(_m, 'wear_cost_eur_per_min', 0.0) or 0.0)
                                machine_costs_by_id[_m.id] = cpm_calc
                                machine_costs_by_name[str(_m.name)] = cpm_calc
                            svs_all = s_up.exec(select(Service)).all()
                            upd = 0
                            for sv in svs_all:
                                target = None
                                mid = getattr(sv, 'machine_id', None)
                                mtype = str(getattr(sv, 'machine_type', '') or '')
                                if mid in machine_costs_by_id:
                                    target = machine_costs_by_id[mid]
                                elif mtype in machine_costs_by_name:
                                    target = machine_costs_by_name[mtype]
                                if target is not None and target > 0.0:
                                    old = float(getattr(sv, 'custo_por_minuto', 0.0) or 0.0)
                                    if abs(old - float(target)) > 1e-6:
                                        sv.custo_por_minuto = float(target)
                                        s_up.add(sv)
                                        upd += 1
                            if upd:
                                s_up.commit()
                                st.info(f"Serviços atualizados: {upd}")
                        except Exception:
                            pass
                        st.success("Máquina atualizada.")
                        st.rerun()
                if eb2.form_submit_button("🗑 Apagar"):
                    with get_session() as s_del:
                        mm = s_del.get(Machine, m.id)
                        if mm:
                            s_del.delete(mm); s_del.commit()
                            # Após apagar a máquina, zerar custo/min dos serviços ligados a ela (por id ou nome)
                            try:
                                svs_all = s_del.exec(select(Service)).all()
                                upd = 0
                                for sv in svs_all:
                                    if getattr(sv, 'machine_id', None) == m.id or str(getattr(sv, 'machine_type', '') or '') == str(m.name):
                                        if float(getattr(sv, 'custo_por_minuto', 0.0) or 0.0) != 0.0:
                                            sv.custo_por_minuto = 0.0
                                            s_del.add(sv)
                                            upd += 1
                                if upd:
                                    s_del.commit()
                                    st.info(f"Serviços reajustados: {upd}")
                            except Exception:
                                pass
                            st.warning("Máquina apagada.")
                            st.rerun()
