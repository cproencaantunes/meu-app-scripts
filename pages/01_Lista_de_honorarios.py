import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÕES E SEGURANÇA ---
st.set_page_config(page_title="Lista de Honorários", page_icon="💰", layout="wide")

user_api_key = st.session_state.get('user_api_key')
sheet_url = st.session_state.get('sheet_url')

if not user_api_key or not sheet_url:
    st.warning("⚠️ Configuração em falta! Por favor, vá à página **Home (🏠)** e insira os dados.")
    st.stop()

# --- 2. FUNÇÕES DE TRATAMENTO DE DADOS ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data_robusta(data_str):
    """
    Extrai a data e força o formato DD-MM-YYYY.
    Resolve o erro de datas coladas com IDs (ex: 2022-09-2001 -> 20-09-2022).
    """
    if not data_str or not isinstance(data_str, str):
        return data_str
    
    # Procura apenas o padrão de data (DD-MM-YY ou DD-MM-YYYY) no início
    # Aceita separadores - / ou .
    match = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', data_str)
    
    if match:
        dia, mes, ano = match.groups()
        
        # Se o ano tiver 2 dígitos, converte para 4
        if len(ano) == 2:
            prefixo = "19" if int(ano) > 80 else "20"
            ano = prefixo + ano
        
        # Retorna sempre com 4 dígitos no ano e zeros à esquerda
        return f"{dia.zfill(2)}-{mes.zfill(2)}-{ano}"
    
    return data_str

def corrigir_texto_invertido(texto):
    """Inverte linhas que o PDF da CUF por vezes baralha."""
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
    Analise este relatório de honorários CUF.
    Extraia as transações para este formato JSON:
    [{"data":"DD-MM-YYYY","id":"ID","nome":"NOME","valor":0.00}]
    
    REGRAS:
    1. A data deve ter 4 dígitos no ano.
    2. NÃO junte a data com o número do ID que vem a seguir.
    3. Ignore o nome do médico (C PROENÇA ANTUNES).
    """
    
    try:
        response = model.generate_content(
            f"{prompt}\n\nTEXTO:\n{texto_limpo}",
            generation_config={"temperature": 0.0}
        )
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        if not match: return []
        
        dados = json.loads(match.group())
        
        dados_finais = []
        for d in dados:
            nome = str(d.get('nome', '')).upper()
            # Filtro para evitar lixo e o seu nome de médico
            if "PROENÇA" in nome or "ANTUNES" in nome or not d.get('id'):
                continue
            
            # Aplica a formatação de data que separa os números grudados
            d['data'] = formatar_data_robusta(d.get('data'))
            dados_finais.append(d)
            
        return dados_finais
    except:
        return []

# --- 3. INTERFACE E PROCESSAMENTO ---

st.title("💰 Processador de Honorários")
st.info("Extração com correção automática de datas e IDs.")

try:
    genai.configure(api_key=user_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    
    # Conectar ao Google Sheets
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Erro de conexão: {e}")
    st.stop()

arquivos = st.file_uploader("Carregue os PDFs", type=['pdf'], accept_multiple_files=True)

if arquivos and st.button("🚀 Processar PDFs"):
    todas_as_linhas = []
    data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
    
    barra = st.progress(0)
    for idx, arq in enumerate(arquivos):
        with pdfplumber.open(arq) as pdf:
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
                            data_hoje, 
                            arq.name
                        ])
        barra.progress((idx + 1) / len(arquivos))

    if todas_as_linhas:
        worksheet.append_rows(todas_as_linhas)
        st.balloons()
        st.success(f"✅ Sucesso! {len(todas_as_linhas)} linhas gravadas.")
        st.dataframe(todas_as_linhas)
    else:
        st.warning("Nenhum dado válido extraído.")
