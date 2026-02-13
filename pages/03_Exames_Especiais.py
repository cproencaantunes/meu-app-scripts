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
st.set_page_config(page_title="Exames Especiais", page_icon="🧪", layout="wide")

user_api_key = st.session_state.get('user_api_key')
sheet_url = st.session_state.get('sheet_url')

if not user_api_key or not sheet_url:
    st.warning("⚠️ Configuração em falta! Vá à página **Home (🏠)**.")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data_universal(data_str):
    if not data_str: return None
    s = str(data_str).strip()
    if "DD-MM-YYYY" in s.upper(): return None
    match_iso = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if match_iso:
        return f"{match_iso.group(3)}-{match_iso.group(2)}-{match_iso.group(1)}"
    match_pt = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', s)
    if match_pt:
        d, m, a = match_pt.groups()
        if len(a) == 2: a = "20" + a
        return f"{d.zfill(2)}-{m.zfill(2)}-{a}"
    return None

def extrair_dados_ia_com_retry(texto_pagina, model, max_retries=3):
    prompt_sistema = """
    Analisa este relatório médico CUF. Extrai os pacientes.
    JSON: [{"data": "DD-MM-YYYY", "processo": "123", "nome": "NOME", "procedimento": "PROC"}]
    """
    for i in range(max_retries):
        try:
            response = model.generate_content(prompt_sistema + "\n\nTEXTO:\n" + texto_pagina, 
                                            generation_config={"temperature": 0.0})
            match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
            return json.loads(match.group()) if match else []
        except Exception as e:
            if "429" in str(e):
                time.sleep((i + 1) * 6)
            else:
                return []
    return []

# --- 3. CONEXÃO ---
try:
    genai.configure(api_key=user_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    
    # NOME DA FOLHA ALTERADO CONFORME PEDIDO
    NOME_FOLHA = 'ExamesEsp'
    
    try:
        worksheet = sh.worksheet(NOME_FOLHA)
    except:
        worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="2000", cols="10")
        # Cabeçalho inicia logo na Coluna C para evitar conflitos com fórmulas em A e B
        worksheet.update(range_name="C1", values=[["Data", "Processo", "Nome Completo", "Procedimento", "Data Execução"]])
except Exception as e:
    st.error(f"❌ Erro de Ligação: {e}")
    st.stop()

# --- 4. INTERFACE ---
st.title("🧪 Exames Especiais")
st.info(f"Escrita direta na Coluna C da aba '{NOME_FOLHA}' (Preserva fórmulas em A e B).")

arquivos_pdf = st.file_uploader("Upload PDFs", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Processar Especiais"):
    novas_linhas = []
    data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
    termos_lixo = ["PROENÇA", "CPANTUNES", "PÁGINA", "UTILIZADOR", "GHCE9050"]

    progresso = st.progress(0)
    status = st.empty()

    # Obter dados atuais para saber onde começar a escrever
    dados_atuais = worksheet.get_all_values()

    for idx, pdf_file in enumerate(arquivos_pdf):
        status.text(f"📖 A ler: {pdf_file.name}")
        data_corrente = ""

        with pdfplumber.open(pdf_file) as pdf:
            for i, pagina in enumerate(pdf.pages):
                texto = pagina.extract_text()
                if not texto: continue

                dados_ia = extrair_dados_ia_com_retry(texto, model)

                for d in dados_ia:
                    nova_dt = formatar_data_universal(d.get('data', ''))
                    if nova_dt: data_corrente = nova_dt
                    
                    if not data_corrente: continue

                    nome = str(d.get('nome', '')).strip().upper()
                    if any(t in nome for t in termos_lixo) or len(nome) < 4:
                        continue

                    processo = re.sub(r'\D', '', str(d.get('processo', '')))
                    proc = str(d.get('procedimento', '')).strip()

                    # REMOVIDO O AVANÇO MANUAL "", ""
                    novas_linhas.append([
                        data_corrente, # Coluna C
                        processo,      # Coluna D
                        nome,          # Coluna E
                        proc,          # Coluna F
                        data_hoje      # Coluna G
                    ])
                
                time.sleep(2) 
        progresso.progress((idx + 1) / len(arquivos_pdf))

    status.empty()

    if novas_linhas:
        # Lógica de escrita forçada na Coluna C
        proxima_linha = len(dados_atuais) + 1
        worksheet.update(
            range_name=f"C{proxima_linha}", 
            values=novas_linhas
        )
        st.balloons()
        st.success(f"✅ {len(novas_linhas)} linhas gravadas na aba '{NOME_FOLHA}' (Coluna C).")
        st.dataframe(novas_linhas)
    else:
        st.warning("Nada extraído.")
