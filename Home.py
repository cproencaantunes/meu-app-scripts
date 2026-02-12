import streamlit as st

st.set_page_config(page_title="Hub de Extração CUF", layout="wide")

st.title("🏥 Central de Processamento de Documentos")

# Criar a barra lateral global
with st.sidebar:
    st.header("⚙️ Configuração")
    st.info("Estes dados são necessários para todas as ferramentas.")
    
    # Guardar inputs no session_state para as outras páginas lerem
    st.session_state['user_api_key'] = st.text_input("Gemini API Key", type="password", value=st.session_state.get('user_api_key', ''))
    st.session_state['sheet_url'] = st.text_input("Link da Planilha Google", value=st.session_state.get('sheet_url', ''))

    if "gcp_service_account" in st.secrets:
        st.divider()
        st.warning("⚠️ Partilhe a sua planilha como 'Editor' com:")
        st.code(st.secrets["gcp_service_account"]["client_email"])

st.markdown("""
### Bem-vindo!
Selecione a ferramenta pretendida no menu à esquerda:
1. **Lista de Honorários**
2. **Doentes Anestesiados** (Em breve)
3. **Exames** (Em breve)
4. **Consultas** (Em breve)
""")
