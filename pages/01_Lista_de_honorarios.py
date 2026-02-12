import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. RECUPERAÇÃO DE CONFIGURAÇÕES DA SESSÃO ---
user_api_key = st.session_state.get('user_api_key')
sheet_url = st.session_state.get('sheet_url')

st.set_page_config(page_title="Lista de Honorários", page_icon="💰")

# Bloqueio de segurança: Se não houver chaves, não corre
if not user_api_key or not sheet_url:
    st.warning("⚠️ Configuração em falta! Por favor, vá à página **Home (🏠)** e insira a sua API Key e o link da Planilha.")
    st.stop()

st.title("💰 Processamento de Lista de Honorários")
st.info("Esta ferramenta extrai Data, ID (Episódio), Nome do Paciente e Valor dos honorários.")

# --- 2. FUNÇÕES TÉCNICAS ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def corrigir_texto_invertido(texto):
    """Corrige o erro de leitura reversa (ex: SOLRAC -> CARLOS)"""
    linhas = texto.split('\n')
    texto_corrigido = []
    for linha in linhas:
        # Detetores comuns de inversão no PDF da CUF
        if "SOLRAC" in linha or "SENUTNA" in linha or "SEÕÇNETER" in linha:
            texto_corrigido.append(linha[::-1])
        else:
            texto_corrigido.append(linha)
    return "\n".join(texto_corrigido)

def extrair_dados_ia(texto_pagina, model):
    """Envia o texto para o Gemini e extrai o JSON estruturado"""
    texto_limpo = corrigir_texto_invertido(texto_pagina)
    
    prompt = """
    Analise este texto de um relatório de honorários médico CUF.
    Extraia todas as transações individuais para este formato JSON:
    [{"data":"DD-MM-YYYY","id":"ID_NUMERICO","nome":"NOME_COMPLETO","valor":0.00}]
    
    Regras:
    1. A data deve ser DD-MM-YYYY.
    2. O ID deve conter apenas números.
    3. O nome deve ser limpo de ruído e corrigido se estiver invertido.
    4. Retorne APENAS o JSON, sem explicações.
    """
    try:
        response = model.generate_content(f"{prompt}\n\nTEXTO:\n{texto_limpo}")
        # Encontra o JSON dentro da resposta da IA
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        return json.loads(match.group()) if match else []
    except Exception:
        return []

# --- 3. EXECUÇÃO ---

# Configuração da IA e Google Sheets
try:
    genai.configure(api_key=user_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    
    # Autenticação Google Sheets via Service Account (Robô do App)
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    gc = gspread.authorize(creds)
    
    sheet_id = extrair_id_planilha(sheet_url)
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.get_worksheet(0) # Usa a primeira aba
except Exception as e:
    st.error(f"❌ Erro de Autenticação: {e}")
    st.stop()

# Upload de Ficheiros
arquivos_pdf = st.file_uploader("Arraste os PDFs de Honorários aqui", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Iniciar Extração"):
    todas_as_linhas = []
    data_proc = datetime.now().strftime("%d-%m-%Y %H:%M")
    
    progresso = st.progress(0)
    for i, pdf_file in enumerate(arquivos_pdf):
        st.write(f"Analisando: `{pdf_file.name}`...")
        
        with pdfplumber.open(pdf_file) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text(layout=True)
                if texto:
                    dados = extrair_dados_ia(texto, model)
                    for d in dados:
                        # Monta a linha para a planilha (Data, ID, Nome, Valor, Data Proc, Origem)
                        todas_as_linhas.append([
                            d.get('data'), 
                            d.get('id'), 
                            d.get('nome', '').upper(), 
                            d.get('valor'), 
                            data_proc, 
                            pdf_file.name
                        ])
        
        progresso.progress((i + 1) / len(arquivos_pdf))
        time.sleep(1) # Evitar bloqueio de taxa da API

    # Gravação Final
    if todas_as_linhas:
        try:
            worksheet.append_rows(todas_as_linhas)
            st.balloons()
            st.success(f"✅ Concluído! {len(todas_as_linhas)} linhas adicionadas à planilha.")
            st.table(todas_as_linhas[:10]) # Mostra as primeiras 10 linhas como amostra
        except Exception as e:
            st.error(f"Erro ao gravar na planilha: {e}")
    else:
        st.warning("Nenhum dado válido foi encontrado nos PDFs.")
