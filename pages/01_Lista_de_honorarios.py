import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="Lista de Honorários", page_icon="💰", layout="wide")

# Lemos a TUA chave mestra e o link do cliente
master_api_key = st.secrets.get("GEMINI_API_KEY")
sheet_url = st.session_state.get('sheet_url')

if not master_api_key:
    st.error("❌ Erro Crítico: GEMINI_API_KEY não configurada nos Secrets.")
    st.stop()

if not sheet_url:
    st.warning("⚠️ Configuração em falta! Por favor, insira o link da sua planilha na página Home (🏠).")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data(data_str):
    data_str = str(data_str).strip()
    if not data_str or "DD-MM-YYYY" in data_str.upper():
        return None
    match = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', data_str)
    if match:
        d, m, a = match.groups()
        if len(a) == 2: a = "20" + a
        return f"{d.zfill(2)}-{m.zfill(2)}-{a}"
    return None

def extrair_dados_ia(texto_pagina, model):
    prompt = "Extraia dados deste PDF CUF para este JSON: [{\"data\":\"DD-MM-YYYY\",\"id\":\"ID\",\"nome\":\"NOME\",\"valor\":0.00}]"
    try:
        # Usamos a API Key mestra (Tier 1) para processamento rápido
        response = model.generate_content(f"{prompt}\n\nTEXTO:\n{texto_pagina}", generation_config={"temperature": 0.0})
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        return json.loads(match.group()) if match else []
    except:
        return []

# --- 3. CONEXÃO ---
try:
    genai.configure(api_key=master_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    
    # Abre a primeira folha (Honorários)
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Erro de Conexão: {e}")
    st.stop()

# --- 4. INTERFACE ---
st.title("💰 Processador de Honorários (Escrita na Coluna B)")
st.info("O sistema escreve a partir da Coluna B, preservando fórmulas na Coluna A.")

arquivos_pdf = st.file_uploader("Carregue os PDFs de Honorários", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Iniciar Processamento"):
    todas_as_linhas_final = []
    data_exec = datetime.now().strftime("%d-%m-%Y %H:%M")
    termos_ignorar = ["PROENÇA ANTUNES", "UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO", "FIM DA LISTAGEM"]

    progresso = st.progress(0)
    status_info = st.empty()

    # Obtemos os dados atuais para saber a próxima linha livre
    dados_atuais = worksheet.get_all_values()

    for idx, pdf_file in enumerate(arquivos_pdf):
        status_info.info(f"📖 A ler: {pdf_file.name}")
        ultima_data_valida = ""

        with pdfplumber.open(pdf_file) as pdf:
            for i, pagina in enumerate(pdf.pages):
                if i == 0: continue # Pula capa/cabeçalho se necessário

                texto = pagina.extract_text(layout=True)
                if not texto: continue
                dados_ia = extrair_dados_ia(texto, model)

                for d in dados_ia:
                    dt = formatar_data(d.get('data', ''))
                    if dt: ultima_data_valida = dt
                    else: dt = ultima_data_valida

                    id_limpo = re.sub(r'\D', '', str(d.get('id', '')))
                    nome_raw = str(d.get('nome', '')).strip().upper()
                    
                    e_lixo = any(termo in nome_raw for termo in termos_ignorar)

                    if id_limpo and not e_lixo and len(nome_raw) > 3:
                        # LISTA SEM O ESPAÇO VAZIO INICIAL (O update tratará da coluna B)
                        todas_as_linhas_final.append([
                            dt,          # Coluna B
                            id_limpo,    # Coluna C
                            nome_raw,    # Coluna D
                            d.get('valor', 0.0), # Coluna E
                            data_exec,   # Coluna F
                            pdf_file.name # Coluna G
                        ])
        
        progresso.progress((idx + 1) / len(arquivos_pdf))

    status_info.empty()

    if todas_as_linhas_final:
        try:
            # ESCRITA FORÇADA NA COLUNA B
            # proxima_linha é o total de linhas + 1
            proxima_linha = len(dados_atuais) + 1
            
            # Atualiza a partir da Coluna 2 (B)
            worksheet.update(
                range_name=f"B{proxima_linha}", 
                values=todas_as_linhas_final
            )
            
            st.success(f"✅ {len(todas_as_linhas_final)} linhas gravadas com sucesso na Coluna B.")
            st.dataframe(todas_as_linhas_final)
        except Exception as e:
            st.error(f"❌ Erro ao gravar na planilha: {e}")
    else:
        st.warning("Nenhum dado válido encontrado nos PDFs.")
