import streamlit as st
import os, json, base64, io
from PIL import Image

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

HISTORICO_PATH = "data/historico_calculos.json"

st.title("📜 Histórico de Cálculos")

def carregar_historico():
    if os.path.exists(HISTORICO_PATH):
        with open(HISTORICO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

hist = carregar_historico()
if not hist:
    st.info("Nenhum cálculo guardado ainda.")
else:
    for reg in reversed(hist):
        st.markdown('---')
        col1, col2 = st.columns([1,2])
        with col1:
            try:
                img = Image.open(io.BytesIO(base64.b64decode(reg['imagem_base64'])))
                st.image(img, use_column_width=True)
                st.download_button('⬇️ PNG', data=base64.b64decode(reg['imagem_base64']), file_name=f"calculo_{reg['id']}.png", mime='image/png')
            except Exception as e:
                st.warning(f'Erro a mostrar miniatura: {e}')
        with col2:
            st.markdown(f"**ID:** {reg['id']}")
            st.markdown(f"**Data:** {reg['data']}")
            st.markdown(f"**Folga material:** {reg.get('folga_material',0)} cm")
            st.markdown(f"**Folga entre peças:** {reg.get('folga_peca',0)} cm")
            st.markdown(f"**Peças/chapa:** {reg.get('total_pecas',0)}")
            st.markdown(f"**Aproveitamento:** {reg.get('aproveitamento',0):.1f}%")
            if st.button('📌 Associar a Orçamento', key=f"assoc_{reg['id']}"):
                st.session_state['calculo_selecionado'] = reg
                st.success("Cálculo pronto para associar. Vá para 'Orçamentos'.")
