import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. RECUPERAÇÃO DE CONFIGURAÇÕES ---
user_api_key = st.session_state.get('user_api_key')
sheet_url = st.session_state.get('sheet_url')

st.set_page_config(page_title="Lista de Honorários", page_icon="💰", layout="wide")

if not user_api_key or not sheet_url:
    st.warning("⚠️ Configure a API Key e a Planilha na página **Home (🏠)**.")
    st.stop()

st.title("💰 Extração de Honorários (Precisão Total)")

# --- 2. FUNÇÕES TÉCNICAS ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data(data_str):
    """Força a data para o formato DD-MM-YYYY mesmo que a IA envie DD-MM-YY"""
    if not data_str or not isinstance(data_str, str):
        return data_str
    
    # Tenta encontrar o padrão dia-mes-ano
    partes = re.split(r'[-/]', data_str)
    if len(partes) == 3:
        dia, mes, ano = partes
        # Se o ano tiver 2 dígitos (ex: 22, 23, 24), transforma em 2022, 2023...
        if len(ano) == 2:
            ano = "20" + ano
        return f"{dia.zfill(2)}-{mes.zfill(2)}-{ano}"
    return data_str

def corrigir_texto_invertido(texto):
    linhas = texto.split('\n')
    texto_corrigido = []
    for linha in linhas:
        if "SOLRAC" in linha or "SENUTNA" in linha or "SEÕÇNETER" in linha:
            texto_corrigido.append(linha[::-1])
        else:
            texto_corrigido.append(linha)
    return "\n".join(texto_corrigido)

def extrair_dados_ia(texto_pagina, model):
    texto_limpo = corrigir_texto_invertido(texto_pagina)
    
    prompt = """
    Analise este relatório médico e extraia TODAS as linhas de honorários.
    Formato JSON: [{"data":"DD-MM-YYYY","id":"ID","nome":"NOME","valor":0.00}]
    
    REGRAS DE OURO:
    1. A DATA DEVE TER 4 DÍGITOS NO ANO (Ex: 2024 em vez de 24).
    2. Extraia cada doente individualmente.
    3. Ignore o nome do médico no cabeçalho.
    """
    
    try:
        response = model.generate_content(
            f"{prompt}\n\nTEXTO:\n{texto_limpo}",
            generation_config={"temperature": 0.0}
        )
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        if not match: return []
        
        dados = json.loads(match.group())
        
        dados_processados = []
        for d in dados:
            nome_upper = str(d.get('nome', '')).upper()
            # Filtro de segurança para o seu nome e lixo
            if "C PROENÇA" in nome_upper or "LISTAGEM" in nome_upper or not d.get('id'):
                continue
            
            # Força a formatação da data aqui
            d['data'] = formatar_data(d.get('data'))
            dados_processados.append(d)
            
        return dados_processados
    except Exception:
        return []

# --- 3. EXECUÇÃO ---

try:
    genai.configure(api_key=user_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    gc = gspread.authorize(creds)
    
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Erro: {e}")
    st.stop()

arquivos_pdf = st.file_uploader("Upload PDFs", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Processar e Corrigir"):
    todas_as_linhas = []
    data_exec = datetime.now().strftime("%d-%m-%Y %H:%M")
    
    progresso = st.progress(0)
    for i, pdf_file in enumerate(arquivos_pdf):
        with pdfplumber.open(pdf_file) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text(layout=True)
                if texto:
                    dados = extrair_dados_ia(texto, model)
                    for d in dados:
                        todas_as_linhas.append([
                            d.get('data'), 
                            d.get('id'), 
                            str(d.get('nome')).upper(), 
                            d.get('valor'), 
                            data_exec, 
                            pdf_file.name
                        ])
        progresso.progress((i + 1) / len(arquivos_pdf))
    
    if todas_as_linhas:
        worksheet.append_rows(todas_as_linhas)
        st.success(f"✅ Extraído e formatado: {len(todas_as_linhas)} linhas.")
        st.dataframe(todas_as_linhas)
