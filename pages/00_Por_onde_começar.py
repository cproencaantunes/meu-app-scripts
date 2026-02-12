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
    st.write("Para que o sistema funcione, deve utilizar o modelo oficial. Clique no botão abaixo e faça uma cópia para a sua conta Google.")
    st.link_button("Abrir Template do Excel ↗️", "https://docs.google.com/spreadsheets/d/1oyWViB-jafKCGKLTMCDcY5xShMNgtWVUjTqmZfzWQMM/edit?gid=0#gid=0")

with col_b:
    st.markdown("### 🔑 Passo 2: Dar acesso ao sistema")
    st.write("Abra a sua planilha, clique em **Partilhar** e adicione o e-mail abaixo como **Editor**:")
    st.code("pdf-extractor@gen-lang-client-0404678969.iam.gserviceaccount.com", language="text")
    st.warning("Sem este passo, o sistema receberá um erro de 'Permissão Negada' ao tentar gravar dados.")

st.markdown("---")

# --- SECÇÃO 2: CONFIGURAÇÃO NO APP ---
st.header("2️⃣ Configurar a Ligação")
st.markdown("""
Vá à página **🏠 Home** e insira:
1.  **Gemini API Key:** A sua chave pessoal da Google AI.
2.  **Link da Planilha:** O link da cópia que criou no passo anterior.
""")

# --- SECÇÃO 3: ONDE CARREGAR CADA RELATÓRIO ---
st.header("3️⃣ Onde carregar os seus relatórios?")
st.write("Cada página foi treinada para um tipo específico de documento:")



c1, c2, c3, c4 = st.columns(4)

with c1:
    st.info("### 💰 Honorários\nListagens de pagamentos. Ignora automaticamente a primeira página de cabeçalho.")

with c2:
    st.success("### 💉 Anestesiados\nAtos anestésicos. Faz a desduplicação (não repete doentes já existentes).")

with c3:
    st.warning("### 🧪 Especiais\nExames técnicos onde a data aparece no topo de grupos de doentes.")

with c4:
    st.error("### 👨‍⚕️ Consultas\nListagens diárias de consultas externas. Extrai Data, Processo e Nome.")

# --- SECÇÃO 4: DICAS DE OURO ---
st.markdown("---")
st.header("💡 Dicas de Ouro")

st.markdown("""
* **A e B Vazias:** Por design, os dados são inseridos a partir da **Coluna C**. Não apague as colunas vazias na planilha.
* **Erro 429 (Limite):** Se processar muitos PDFs, a Google pode pedir uma pausa. O sistema aguarda automaticamente, basta ter paciência.
* **Nomes Limpos:** O sistema remove automaticamente termos de cabeçalho (como o seu nome ou "Página 1") para manter a lista limpa.
""")

st.caption("Sistema de Apoio Clínico | v2.5 (2026)")
