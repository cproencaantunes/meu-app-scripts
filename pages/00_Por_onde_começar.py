import streamlit as st

# Configuração da página
st.set_page_config(page_title="Guia de Início", page_icon="📖", layout="wide")

st.title("📖 Guia de Início - Sistema de Extração CUF")
st.markdown("---")

# --- SECÇÃO 1: DOWNLOAD DO TEMPLATE E ACESSO ---
st.header("1️⃣ Preparar a Planilha")
col_a, col_b = st.columns(2)

with col_a:
    st.markdown("### 📑 Passo 1: Criar a sua cópia")
    st.write("Clique no botão abaixo para abrir o modelo e faça uma cópia para a sua conta Google.")
    st.link_button("Abrir Template do Excel ↗️", "https://docs.google.com/spreadsheets/d/1oyWViB-jafKCGKLTMCDcY5xShMNgtWVUjTqmZfzWQMM/edit?gid=0#gid=0")

with col_b:
    st.markdown("### 🔑 Passo 2: Dar acesso ao sistema")
    st.write("No botão **Partilhar** da sua planilha, adicione este e-mail como **Editor**:")
    st.code("pdf-extractor@gen-lang-client-0404678969.iam.gserviceaccount.com", language="text")

st.markdown("---")

# --- SECÇÃO 2: CONFIGURAÇÃO DE CHAVES ---
st.header("2️⃣ Configurar a Ligação")

col_c, col_d = st.columns(2)

with col_c:
    st.markdown("### 🗝️ Obter a Gemini API Key")
    st.write("A chave de inteligência deve ser gerada no Google AI Studio.")
    st.link_button("Gerar API Key no Google AI Studio ↗️", "https://aistudio.google.com/app/apikey")
    
    st.warning("""
    **⚠️ ATENÇÃO:** Deve utilizar um e-mail pessoal (@gmail.com). O sistema **não funcionará** com e-mails do domínio **jmellosaude.pt**, pois estes possuem restrições de segurança que bloqueiam a API.
    """)

with col_d:
    st.markdown("### 🔗 Vincular no App")
    st.write("Vá à página **🏠 Home** no menu lateral e introduza:")
    st.markdown("""
    * **Gemini API Key:** A chave que acabou de gerar.
    * **Link da Planilha:** O URL da cópia que criou no Passo 1.
    """)

# --- SECÇÃO 3: ONDE CARREGAR CADA RELATÓRIO ---
st.markdown("---")
st.header("3️⃣ Onde carregar os seus relatórios?")
st.write("Escolha a página correta no menu lateral de acordo com o tipo de PDF:")



c1, c2, c3, c4 = st.columns(4)

with c1:
    st.info("### 💰 Honorários\nListagens de pagamentos. Salta automaticamente a primeira página.")

with c2:
    st.success("### 💉 Anestesiados\nAtos anestésicos. Evita duplicados (Data + Processo + Nome).")

with c3:
    st.warning("### 🧪 Especiais\nExames onde a data serve para um grupo de doentes.")

with c4:
    st.error("### 👨‍⚕️ Consultas\nListagens diárias de consultas. Extrai Data, Processo e Nome.")

# --- SECÇÃO 4: REGRAS DE OURO ---
st.markdown("---")
st.header("💡 Regras de Ouro")

st.markdown("""
* **Colunas A e B:** Devem permanecer vazias. O sistema escreve propositadamente a partir da **Coluna C**.
* **Rate Limit:** Se aparecer um aviso de espera, não atualize a página. O sistema está a gerir o limite de tráfego da Google.
* **Formato:** Use apenas PDFs digitais (onde consegue selecionar o texto). Scans de papel podem falhar.
""")

st.caption("Sistema de Apoio Clínico | v2.6 (2026)")
