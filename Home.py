import streamlit as st

st.set_page_config(page_title="Hub de Extração Pro", page_icon="🏥", layout="wide")

st.title("🏥 Central de Processamento de Documentos")

# Criar a barra lateral global
with st.sidebar:
    st.header("⚙️ Configuração")
    st.info("Insira o link da sua planilha pessoal para começar.")
    
    # Guardar apenas o URL da planilha no session_state
    # A API Key agora é carregada internamente via Secrets
    st.session_state['sheet_url'] = st.text_input(
        "Link da Planilha Google", 
        value=st.session_state.get('sheet_url', ''),
        placeholder="https://docs.google.com/spreadsheets/d/..."
    )

    if "gcp_service_account" in st.secrets:
        st.divider()
        st.markdown("### 🔑 Autorização")
        st.write("Partilhe a sua planilha como **'Editor'** com este e-mail:")
        st.code(st.secrets["gcp_service_account"]["client_email"], language="text")
        
    st.divider()
    st.caption("Versão Profissional v3.0 | 2026")

# Conteúdo Principal
st.markdown("---")
st.markdown("""
### 👋 Bem-vindo ao seu Assistente de Extração!
O sistema está pronto a utilizar. Utilize o menu lateral para aceder às ferramentas:

* **💰 Honorários**: Processamento de listagens de pagamentos.
* **💉 Anestesiados**: Extração de atos anestésicos com filtro de duplicados.
* **🧪 Especiais**: Processamento de exames e atos técnicos (ExamesEsp).
* **👨‍⚕️ Consultas**: Listagens diárias de consultas.

---
### 💡 Como funciona?
1.  Configure o link da sua planilha à esquerda.
2.  Escolha a página pretendida no menu lateral.
3.  Carregue os seus ficheiros PDF.
4.  O sistema extrai os dados e insere-os automaticamente na sua folha, **preservando as suas fórmulas nas Colunas A e B**.
""")

# Pequeno validador visual
if st.session_state.get('sheet_url'):
    st.success("✅ Link da planilha detetado. Pode avançar para as ferramentas!")
else:
    st.warning("👈 Por favor, introduza o link da sua planilha na barra lateral para ativar o sistema.")
