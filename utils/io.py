import json, re
from pathlib import Path
from .fields import FIELD_MAP, QUOTE_DEFAULTS, PLAN_DEFAULTS, ARCHIVE_DEFAULTS

def load_json(path: Path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        try:
            data = json.load(f)
        except Exception:
            return []
    if isinstance(data, dict):
        # normalizar para lista
        return [data]
    if isinstance(data, list):
        return data
    return []

def save_json(path: Path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def strip_safe(v):
    # Evita 'float' object has no attribute 'strip'
    if isinstance(v, str):
        return v.strip()
    return v

def to_float(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    # remover símbolos como € e converter vírgulas
    s = re.sub(r'[^0-9,.\-]', '', s)
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return 0.0

def normalize_record(rec: dict, defaults: dict):
    out = dict(defaults)
    # aplicar mapeamento de campos
    for k, v in rec.items():
        key_norm = FIELD_MAP.get(k, k)
        val = strip_safe(v)
        out[key_norm] = val
    # garantir tipos em valores comuns
    if "valor_final" in out:
        out["valor_final"] = to_float(out["valor_final"])
    if "custo_total" in out:
        out["custo_total"] = to_float(out["custo_total"])
    if "desconto" in out:
        out["desconto"] = to_float(out["desconto"])
    return out

def append_unique(data: list, rec: dict, key: str):
    if key and rec.get(key) is not None:
        for i, r in enumerate(data):
            if r.get(key) == rec.get(key):
                data[i] = rec
                return data
    data.append(rec)
    return data

def transfer_quote_to_plan(quote: dict):
    # Normaliza e constrói um registo de planeamento a partir do orçamento
    q = normalize_record(quote, QUOTE_DEFAULTS)
    plan = dict(PLAN_DEFAULTS)
    plan.update({
        "id_orcamento": q.get("id_orcamento"),
        "cliente": q.get("cliente"),
        "numero_cliente": q.get("numero_cliente"),
        "descricao": q.get("descricao") or "",
        "observacoes": q.get("observacoes") or "",
    })
    return plan

def archive_from_plan(plan: dict, quote_lookup: dict):
    # Cria um registo de arquivo a partir do planeamento + dados do orçamento
    p = normalize_record(plan, PLAN_DEFAULTS)
    q = normalize_record(quote_lookup or {}, QUOTE_DEFAULTS)
    arq = dict(ARCHIVE_DEFAULTS)
    arq.update({
        "id_orcamento": p.get("id_orcamento") or q.get("id_orcamento"),
        "cliente": p.get("cliente") or q.get("cliente"),
        "numero_cliente": p.get("numero_cliente") or q.get("numero_cliente"),
        "valor_final": q.get("valor_final", 0.0),
        "custo_total": q.get("custo_total", 0.0),
        "aprovado": q.get("aprovado"),
        "descricao": (p.get("descricao") or q.get("descricao") or ""),
        "observacoes": (p.get("observacoes") or q.get("observacoes") or ""),
    })
    # calcular percentagem de gastos se possível
    vf = to_float(arq.get("valor_final"))
    ct = to_float(arq.get("custo_total"))
    arq["percent_gastos"] = round((ct / vf) * 100, 2) if vf > 0 else None
    return arq
