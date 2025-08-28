from __future__ import annotations
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "db.sqlite"
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

# Use expire_on_commit=False to keep objects usable after commit/close
# This avoids DetachedInstanceError in pages that read cfg after saving.
def get_session():
    return Session(engine, expire_on_commit=False)

class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_name: str = ""
    company_vat: str = ""
    company_address: str = ""
    company_iban: str = ""
    company_bank_iban: str | None = Field(default=None)
    company_bic: str | None = Field(default=None)
    company_bank_bic: str | None = Field(default=None)
    payment_instructions: str | None = Field(default=None)
    quote_valid_days: int = Field(default=30)
    terms_conditions: str = ""  # termos PDF cliente
    logo_path: str = ""
    currency: str = "EUR"
    vat_rate: float = 0.0
    date_format: str = "DD-MM-YYYY"
    margin_0_15: float = 0.50
    margin_16_30: float = 0.30
    margin_31_70: float = 0.25
    margin_71_plus: float = 0.0

    # --- Custos de máquina / energia ---
    machine_power_watts: float = 0.0                 # Potência da máquina (W)
    energy_cost_eur_kwh: float = 0.0                 # Custo energia (€/kWh)
    energy_markup_percent: float = 0.0               # Lucro aplicado sobre energia+desgaste (%)
    wear_cost_eur_per_min: float = 0.0               # Desgaste (€/min)
    service_cost_eur_per_min: float = 0.0            # Custo total por minuto calculado

    # --- Máquina UV ---
    uv_machine_power_watts: float = 0.0
    uv_wear_cost_eur_per_min: float = 0.0
    uv_markup_percent: float = 0.0
    uv_ink_price_eur_ml: float = 0.0
    uv_service_cost_eur_per_min: float = 0.0

    # --- Margens separadas (Materiais / Serviços) ---
    mat_margin_0_15: float = 0.0
    mat_margin_16_30: float = 0.0
    mat_margin_31_70: float = 0.0
    mat_margin_71_plus: float = 0.0

    srv_margin_0_15: float = 0.0
    srv_margin_16_30: float = 0.0
    srv_margin_31_70: float = 0.0
    srv_margin_71_plus: float = 0.0

    last_updated: datetime = Field(default_factory=datetime.utcnow)

class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    numero_cliente: int = Field(index=True)
    nome: str
    morada: str = ""
    pais: str = ""
    contacto: str = ""
    email: str = ""
    nif_tva: str = ""
    notas: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_modified_by: str = ""


class Material(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True)
    nome_pt: str = ""
    nome_en: str = ""
    nome_fr: str = ""
    categoria: str = ""
    tipo: str = "AREA"   # AREA | PC
    largura_cm: float = 0.0
    altura_cm: float = 0.0
    unidade: str = "cm²" # cm² | PC
    preco_compra_un: float = 0.0
    preco_cliente_un: float = 0.0
    use_param_margins: bool = Field(default=True)
    fornecedor: str = ""
    quantidade: float = 0.0
    qtd_minima: float = 0.0
    observacoes: str = ""
    margins_override: Optional[str] = None
    last_modified_by: str = ""

# --- Machine model ---
class Machine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)

    # Base inputs
    power_watts: float = 0.0                      # W
    wear_cost_eur_per_min: float = 0.0            # €/min (depreciação+manutenção+consumíveis)
    markup_percent: float = 0.0                    # % aplicado a (energia+desgaste)

    # Optional extras
    ink_price_eur_ml: float = 0.0                  # €/ml, se aplicável
    extra_label: Optional[str] = None              # rótulo livre (ex.: "Gás €/m³")
    extra_value: Optional[float] = None            # valor do extra

    active: bool = True

class Service(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True)
    nome_pt: str = ""
    nome_en: str = ""
    nome_fr: str = ""
    categoria: str = ""
    usa_area: bool = True
    usa_tempo: bool = True
    # Unidade de venda/medição do serviço ("min", "cm²", "PC")
    unidade: str = "min"
    largura_cm: float = 0.0
    altura_cm: float = 0.0
    unidade_area: str = "cm²"
    preco_cliente: float = 0.0  # preço base ao cliente (100%)
    custo_por_minuto: float = 0.0
    # Duração estimada para produzir 1 unidade (minutos)
    minutos_por_unidade: float | None = Field(default=0.0)
    machine_type: str = Field(default="")  # vazio = sem máquina
    custo_extra: float = 0.0
    custo_fornecedor: float = 0.0
    margins_override: Optional[str] = None
    machine_id: Optional[int] = Field(default=None, foreign_key="machine.id")
    observacoes: str = ""
    last_modified_by: str = ""

# --- Lightweight migration to ensure Service.minutos_por_unidade exists (SQLite) ---

def upgrade_services_minutes():
    try:
        with engine.begin() as conn:  # type: ignore[name-defined]
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('service')")}
            if 'minutos_por_unidade' not in cols:
                conn.exec_driver_sql("ALTER TABLE service ADD COLUMN minutos_por_unidade REAL DEFAULT 0.0")
    except Exception:
        pass

# --- Lightweight migration: ensure Service.unidade exists and backfill from unidade_area ---

def upgrade_services_unidade():
    try:
        with engine.begin() as conn:  # type: ignore[name-defined]
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('service')")}
            if 'unidade' not in cols:
                conn.exec_driver_sql("ALTER TABLE service ADD COLUMN unidade TEXT DEFAULT 'min'")
                try:
                    conn.exec_driver_sql("UPDATE service SET unidade = unidade_area WHERE unidade_area IS NOT NULL AND unidade_area != ''")
                except Exception:
                    pass
    except Exception:
        pass

# --- Lightweight migration: ensure Service.observacoes exists ---

def upgrade_services_observacoes():
    try:
        with engine.begin() as conn:  # type: ignore[name-defined]
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('service')")}
            if 'observacoes' not in cols:
                conn.exec_driver_sql("ALTER TABLE service ADD COLUMN observacoes TEXT DEFAULT ''")
    except Exception:
        pass

class Quote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    numero: Optional[str] = Field(default=None, index=True)
    cliente_id: int = Field(foreign_key="client.id")
    lingua: str = "PT"
    estado: str = "RASCUNHO"
    validade_dias: int = 30
    data_criacao: datetime = Field(default_factory=datetime.utcnow)
    data_entrega_prevista: Optional[datetime] = None
    descricao: str = ""
    desconto_total: float = 0.0
    desconto_percent: Optional[float] = Field(default=None)
    iva_percent: float = 0.0
    imagem_descricao_path: str = ""
    observacoes: str = ""
    maquete_feita: bool = False
    maquete_aprovada: bool = False
    trabalho_realizado: bool = False
    trabalho_entregue: bool = False
    pago_total: bool = False
    pago_valor: float = 0.0
    metodo_pagamento: str = ""
    data_entrega_real: Optional[datetime] = None
    last_modified_by: str = ""

    # --- Campos adicionais para alinhamento com Planeamento/Arquivo ---
    # Alias usados na UI (mantemos os antigos para compatibilidade)
    realizado: bool = False            # usado na UI; mantemos trabalho_realizado para retro-compat
    entregue: bool = False             # usado na UI; mantemos trabalho_entregue para retro-compat
    pago_metodo: str = ""              # usado na UI; mantemos metodo_pagamento para retro-compat

    # Métricas de arquivo / datas de estado
    archived_at: Optional[datetime] = Field(default=None)
    approved_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)

    # Totais e métricas
    final_total_eur: Optional[float] = Field(default=None)
    total_material_cost_eur: Optional[float] = Field(default=None)
    total_service_internal_cost_eur: Optional[float] = Field(default=None)
    total_cost_eur: Optional[float] = Field(default=None)
    profit_eur: Optional[float] = Field(default=None)
    expense_percent: Optional[float] = Field(default=None)
    days_approval_to_completion: Optional[int] = Field(default=None)

    # Controle de baixa de stock (evita aplicar duas vezes)
    stock_discount_done: bool = False

class QuoteItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    quote_id: int = Field(foreign_key="quote.id", index=True)
    categoria_item: str = ""
    tipo_item: str = "MATERIAL"
    ref_id: Optional[int] = None
    code: str = ""
    nome_pt: str = ""
    nome_en: str = ""
    nome_fr: str = ""
    unidade: str = ""
    largura_cm: float = 0.0
    altura_cm: float = 0.0
    quantidade: float = 1.0
    ink_ml: float = 0.0  # consumo de tinta UV em mililitros (só para serviços UV)
    preco_unitario_cliente: float = 0.0
    percent_uso: float = 100.0
    desconto_item: float = 0.0
    subtotal_cliente: Optional[float] = Field(default=None)

    # Snapshot de custos/parametrizações no momento da adição (para histórico)
    preco_compra_unitario: Optional[float] = Field(default=None)
    snapshot_json: Optional[str] = Field(default=None)

class QuoteVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    quote_id: int = Field(foreign_key="quote.id", index=True)
    version_num: int
    pdf_cliente_path: str = ""
    pdf_interno_path: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

class StockMovement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow)
    quote_id: int
    code: str
    qty_delta: float  # negativo ao consumir
    unidade: Optional[str] = None
    note: Optional[str] = None

class NestLayout(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    input_filename: str = ""
    sheet_w_cm: float = 0.0
    sheet_h_cm: float = 0.0
    piece_w_cm: float = 0.0
    piece_h_cm: float = 0.0
    gap_cm: float = 0.5
    border_cm: float = 0.5
    dpi: int = 30
    angle_step_deg: int = 10
    pieces_placed: int = 0
    utilization_percent: float = 0.0
    png_path: str = ""
    svg_path: str = ""
    placements_json: str = ""   # lista de dicts {x_px, y_px, angle}
    linked_quote_id: Optional[int] = None


# --- ServiceCostHistory model ---
class ServiceCostHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    changed_at: datetime = Field(default_factory=datetime.utcnow)
    old_value: float = 0.0
    new_value: float = 0.0
    origin: str = "Parametros"  # "MiniCalculador" ou "Parametros"
    updated_services: int = 0
    changed_by: Optional[str] = None

def init_db():
    SQLModel.metadata.create_all(engine)

def automate_statuses():
    from datetime import datetime
    with get_session() as s:
        qs = s.exec(select(Quote)).all()
        changed = 0
        now = datetime.utcnow()
        for q in qs:
            if q.estado in ["ENVIADO"]:
                if (now - q.data_criacao).days > (q.validade_dias or 30):
                    q.estado = "EXPIRADO"; s.add(q); changed += 1
            if q.trabalho_entregue and q.pago_total and q.estado not in ["ARQUIVADO"]:
                q.estado = "ARQUIVADO"; s.add(q); changed += 1
        if changed:
            s.commit()
    return True

# --- Lightweight migration to ensure new Settings columns exist (SQLite) ---

def upgrade_settings_table():
    """Add missing columns to the `settings` table if they do not exist.
    Safe to call on every app start; no-op if columns already exist.
    """
    try:
        with engine.begin() as conn:  # uses module-level engine
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('settings')")}
            if 'company_bank_iban' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN company_bank_iban TEXT")
            if 'company_bank_bic' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN company_bank_bic TEXT")
            if 'company_bic' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN company_bic TEXT")
            if 'payment_instructions' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN payment_instructions TEXT")
            if 'quote_valid_days' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN quote_valid_days INTEGER DEFAULT 30")
            # Machine / energy cost columns
            if 'machine_power_watts' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN machine_power_watts REAL DEFAULT 0.0")
            if 'energy_cost_eur_kwh' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN energy_cost_eur_kwh REAL DEFAULT 0.0")
            if 'energy_markup_percent' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN energy_markup_percent REAL DEFAULT 0.0")
            if 'wear_cost_eur_per_min' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN wear_cost_eur_per_min REAL DEFAULT 0.0")
            if 'service_cost_eur_per_min' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN service_cost_eur_per_min REAL DEFAULT 0.0")
            if 'uv_machine_power_watts' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN uv_machine_power_watts REAL DEFAULT 0.0")
            if 'uv_wear_cost_eur_per_min' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN uv_wear_cost_eur_per_min REAL DEFAULT 0.0")
            if 'uv_markup_percent' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN uv_markup_percent REAL DEFAULT 0.0")
            if 'uv_ink_price_eur_ml' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN uv_ink_price_eur_ml REAL DEFAULT 0.0")
            if 'uv_service_cost_eur_per_min' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN uv_service_cost_eur_per_min REAL DEFAULT 0.0")
            # Split margins: materials and services
            if 'mat_margin_0_15' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN mat_margin_0_15 REAL DEFAULT 0.0")
            if 'mat_margin_16_30' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN mat_margin_16_30 REAL DEFAULT 0.0")
            if 'mat_margin_31_70' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN mat_margin_31_70 REAL DEFAULT 0.0")
            if 'mat_margin_71_plus' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN mat_margin_71_plus REAL DEFAULT 0.0")
            if 'srv_margin_0_15' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN srv_margin_0_15 REAL DEFAULT 0.0")
            if 'srv_margin_16_30' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN srv_margin_16_30 REAL DEFAULT 0.0")
            if 'srv_margin_31_70' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN srv_margin_31_70 REAL DEFAULT 0.0")
            if 'srv_margin_71_plus' not in cols:
                conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN srv_margin_71_plus REAL DEFAULT 0.0")
    except Exception:
        # Ignore errors to avoid breaking the UI
        pass

# --- Lightweight migration to ensure new Material columns exist (SQLite) ---

def upgrade_materials_table():
    """Add missing columns to the `material` table if they do not exist."""
    try:
        with engine.begin() as conn:
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('material')")}
            if 'use_param_margins' not in cols:
                conn.exec_driver_sql("ALTER TABLE material ADD COLUMN use_param_margins INTEGER DEFAULT 1")
    except Exception:
        # Do not crash UI if migration fails
        pass


# --- Lightweight migration to ensure ServiceCostHistory table exists (SQLite) ---

def upgrade_service_cost_history_table():
    """Create the servicecosthistory table if it doesn't exist."""
    try:
        with engine.begin() as conn:  # type: ignore[name-defined]
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS servicecosthistory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    changed_at TIMESTAMP NOT NULL,
                    old_value REAL NOT NULL DEFAULT 0.0,
                    new_value REAL NOT NULL DEFAULT 0.0,
                    origin TEXT NOT NULL,
                    updated_services INTEGER NOT NULL DEFAULT 0,
                    changed_by TEXT NULL
                )
                """
            )
    except Exception:
        # Do not crash UI if migration fails
        pass

# --- Lightweight migration to ensure Service.machine_type exists (SQLite) ---

def upgrade_services_machine_type():
    try:
        with engine.begin() as conn:  # type: ignore[name-defined]
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('service')")}
            if 'machine_type' not in cols:
                conn.exec_driver_sql("ALTER TABLE service ADD COLUMN machine_type TEXT DEFAULT 'LASER'")
    except Exception:
        pass

# --- upgrades for machines ---

def upgrade_machines_table():
    try:
        with engine.begin() as conn:  # create table if not exists
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS machine (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    power_watts REAL NOT NULL DEFAULT 0.0,
                    wear_cost_eur_per_min REAL NOT NULL DEFAULT 0.0,
                    markup_percent REAL NOT NULL DEFAULT 0.0,
                    ink_price_eur_ml REAL NOT NULL DEFAULT 0.0,
                    extra_label TEXT NULL,
                    extra_value REAL NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
    except Exception:
        pass


def seed_default_machines_from_settings():
    """If there are no machines yet, seed Laser and UV from Settings values."""
    try:
        with get_session() as s:
            have_any = s.exec(select(Machine)).first()
            if have_any:
                return
            stg = s.exec(select(Settings)).first()
            if not stg:
                stg = Settings(); s.add(stg); s.commit(); s.refresh(stg)
            # Laser
            laser = Machine(
                name="Máquina Laser",
                power_watts=float(getattr(stg, 'machine_power_watts', 0.0) or 0.0),
                wear_cost_eur_per_min=float(getattr(stg, 'wear_cost_eur_per_min', 0.0) or 0.0),
                markup_percent=float(getattr(stg, 'energy_markup_percent', 0.0) or 0.0),
                ink_price_eur_ml=0.0,
            )
            # UV
            uv = Machine(
                name="Máquina UV",
                power_watts=float(getattr(stg, 'uv_machine_power_watts', 0.0) or 0.0),
                wear_cost_eur_per_min=float(getattr(stg, 'uv_wear_cost_eur_per_min', 0.0) or 0.0),
                markup_percent=float(getattr(stg, 'uv_markup_percent', 0.0) or 0.0),
                ink_price_eur_ml=float(getattr(stg, 'uv_ink_price_eur_ml', 0.0) or 0.0),
            )
            s.add(laser); s.add(uv); s.commit()
    except Exception:
        pass


def upgrade_services_machine_fk():
    """Ensure Service has machine_id and try to backfill from legacy machine_type if present."""
    try:
        with engine.begin() as conn:
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('service')")}
            if 'machine_id' not in cols:
                conn.exec_driver_sql("ALTER TABLE service ADD COLUMN machine_id INTEGER NULL")
    except Exception:
        pass
    # Backfill using a session
    try:
        with get_session() as s:
            machines = {m.name.upper(): m for m in s.exec(select(Machine)).all()}
            for sv in s.exec(select(Service)).all():
                if getattr(sv, 'machine_id', None):
                    continue
                mtype = str(getattr(sv, 'machine_type', '') or '').upper()
                chosen = None
                if mtype == 'LASER':
                    chosen = machines.get('MÁQUINA LASER') or machines.get('MAQUINA LASER')
                elif mtype == 'UV':
                    chosen = machines.get('MÁQUINA UV') or machines.get('MAQUINA UV')
                if chosen:
                    sv.machine_id = chosen.id
                    s.add(sv)
            s.commit()
    except Exception:
        pass


def machine_cost_per_min(machine: Machine, settings: Settings) -> float:
    """Compute (energia + desgaste) + lucro for a machine, using global energy cost from settings."""
    try:
        energia_min = (float(machine.power_watts or 0.0) / 1000.0) * (1.0/60.0) * float(getattr(settings, 'energy_cost_eur_kwh', 0.0) or 0.0)
        base_min = energia_min + float(machine.wear_cost_eur_per_min or 0.0)
        lucro = base_min * (float(machine.markup_percent or 0.0) / 100.0)
        return max(0.0, base_min + lucro)
    except Exception:
        return 0.0

# --- Lightweight migration to ensure QuoteItem.ink_ml exists (SQLite) ---

def upgrade_quoteitems_ink_ml():
    try:
        with engine.begin() as conn:  # type: ignore[name-defined]
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('quoteitem')")}
            if 'ink_ml' not in cols:
                conn.exec_driver_sql("ALTER TABLE quoteitem ADD COLUMN ink_ml REAL DEFAULT 0.0")
    except Exception:
        pass

# --- Data migration: normalize unit strings from 'cm2' to 'cm²' ---

def upgrade_units_cm2_to_cm2_unicode():
    try:
        with engine.begin() as conn:  # type: ignore[name-defined]
            conn.exec_driver_sql("UPDATE material SET unidade='cm²' WHERE unidade='cm2'")
            conn.exec_driver_sql("UPDATE service SET unidade_area='cm²' WHERE unidade_area='cm2'")
            conn.exec_driver_sql("UPDATE quoteitem SET unidade='cm²' WHERE unidade='cm2'")
    except Exception:
        pass

# --- Lightweight migration to add archive/metrics columns to Quote (SQLite) ---

def upgrade_quotes_metrics():
    try:
        with engine.begin() as conn:
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('quote')")}
            if 'archived_at' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN archived_at TIMESTAMP")
            if 'approved_at' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN approved_at TIMESTAMP")
            if 'completed_at' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN completed_at TIMESTAMP")
            if 'final_total_eur' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN final_total_eur REAL")
            if 'total_material_cost_eur' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN total_material_cost_eur REAL")
            if 'total_service_internal_cost_eur' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN total_service_internal_cost_eur REAL")
            if 'total_cost_eur' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN total_cost_eur REAL")
            if 'profit_eur' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN profit_eur REAL")
            if 'expense_percent' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN expense_percent REAL")
            if 'days_approval_to_completion' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN days_approval_to_completion INTEGER")
            if 'desconto_percent' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN desconto_percent REAL")
            # Alinhar campos usados na UI
            if 'pago_metodo' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN pago_metodo TEXT")
            if 'realizado' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN realizado INTEGER DEFAULT 0")
            if 'entregue' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN entregue INTEGER DEFAULT 0")
    except Exception:
        pass

# --- Lightweight migration to add snapshot columns to QuoteItem (SQLite) ---

def upgrade_quoteitem_snapshot():
    try:
        with engine.begin() as conn:
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('quoteitem')")}
            if 'preco_compra_unitario' not in cols:
                conn.exec_driver_sql("ALTER TABLE quoteitem ADD COLUMN preco_compra_unitario REAL")
            if 'snapshot_json' not in cols:
                conn.exec_driver_sql("ALTER TABLE quoteitem ADD COLUMN snapshot_json TEXT")
            if 'subtotal_cliente' not in cols:
                conn.exec_driver_sql("ALTER TABLE quoteitem ADD COLUMN subtotal_cliente REAL")
    except Exception:
        pass


# --- Lightweight migration to add stock discount flag on Quote (SQLite) ---

def upgrade_quote_stock_flag():
    try:
        with engine.begin() as conn:
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info('quote')")}
            if 'stock_discount_done' not in cols:
                conn.exec_driver_sql("ALTER TABLE quote ADD COLUMN stock_discount_done INTEGER DEFAULT 0")
    except Exception:
        pass

# --- Lightweight migration to ensure StockMovement table exists (SQLite) ---

def upgrade_stock_movements_table():
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS stockmovement (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TIMESTAMP NOT NULL,
                    quote_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    qty_delta REAL NOT NULL,
                    unidade TEXT NULL,
                    note TEXT NULL
                )
                """
            )
    except Exception:
        pass

# --- Helpers: baixa de stock ao arquivar ---

_DEF_STOCK_FIELDS = [
    'stock_qty', 'quantidade_stock', 'quantidade_em_stock', 'qtd_em_stock', 'qtd_stock', 'em_stock', 'stock', 'quantidade'
]

def _decrement_material_stock(session: Session, material_obj, used_amount: float):
    """Tenta encontrar um campo de stock no objeto e subtrair `used_amount`.
    Retorna (ok: bool, field_or_msg: str|None).
    """
    for fname in _DEF_STOCK_FIELDS:
        if hasattr(material_obj, fname):
            try:
                cur = getattr(material_obj, fname)
                cur = 0.0 if cur is None else float(cur)
                newv = cur - float(used_amount)
                if newv < 0:
                    newv = 0.0
                setattr(material_obj, fname, newv)
                session.add(material_obj)
                return True, fname
            except Exception as e:
                return False, f"erro a atualizar {fname}: {e}"
    return False, "sem_campo_stock"


def apply_stock_on_archive(session: Session, quote_id: int):
    """Percorre os itens do orçamento e lança baixas de stock para materiais.
    Regista sempre um StockMovement. Ignora serviços/minutos.
    """
    # evitar import circular
    from app.db import QuoteItem, Material
    items = session.exec(select(QuoteItem).where(QuoteItem.quote_id == quote_id)).all()
    for it in items:
        if getattr(it, 'tipo_item', '') != 'MATERIAL':
            continue
        if getattr(it, 'unidade', '') == 'min':
            continue
        perc = float(getattr(it, 'percent_uso', 0.0) or 0.0) / 100.0
        qty  = float(getattr(it, 'quantidade', 0.0) or 0.0)
        used = perc * qty if perc > 0 else qty
        mat = session.exec(select(Material).where(Material.code == getattr(it,'code',''))).first()
        note = None
        if mat is not None:
            ok, note = _decrement_material_stock(session, mat, used)
            if not ok and note:
                session.add(StockMovement(quote_id=quote_id, code=getattr(it,'code',''), qty_delta=-used, unidade=getattr(it,'unidade',''), note=note))
        else:
            note = 'material_nao_encontrado'
            session.add(StockMovement(quote_id=quote_id, code=getattr(it,'code',''), qty_delta=-used, unidade=getattr(it,'unidade',''), note=note))
    session.commit()


# --- Convenience: run all safe upgrades for app startup ---

def upgrade_all_safe():
    upgrade_settings_table()
    upgrade_materials_table()
    upgrade_service_cost_history_table()
    upgrade_services_machine_type()
    upgrade_services_minutes()
    upgrade_services_unidade()
    upgrade_services_observacoes()
    upgrade_quoteitems_ink_ml()
    upgrade_units_cm2_to_cm2_unicode()
    upgrade_quotes_metrics()
    upgrade_quoteitem_snapshot()
    upgrade_quote_stock_flag()
    upgrade_stock_movements_table()
    upgrade_machines_table()
    seed_default_machines_from_settings()
    upgrade_services_machine_fk()
