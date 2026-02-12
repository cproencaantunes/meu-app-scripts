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

st.set_page_config(page_title="Lista de Honorários", page_icon="💰", layout="wide")

# Bloqueio de segurança
if not user_api_key or not sheet_url:
    st.warning("⚠️ Configuração em falta! Por favor, vá à página **Home (🏠)** e insira a sua API Key e o link da Planilha.")
    st.stop()

st.title("💰 Extração de Lista de Honorários")
st.markdown("---")

# --- 2. FUNÇÕES TÉCNICAS REFINADAS ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def corrigir_texto_invertido(texto):
    """Detecta e inverte linhas que o leitor de PDF baralhou (comum em PDFs da CUF)."""
    linhas = texto.split('\n')
    texto_corrigido = []
    for linha in linhas:
        # Se detetar termos chave invertidos
        if "SOLRAC" in linha or "SENUTNA" in linha or "SEÕÇNETER" in linha:
            texto_corrigido.append(linha[::-1])
        else:
            texto_corrigido.append(linha)
    return "\n".join(texto_corrigido)

def extrair_dados_ia(texto_pagina, model):
    texto_limpo = corrigir_texto_invertido(texto_pagina)
    
    prompt = """
    Analise este relatório de honorários médico.
    REGRAS CRÍTICAS:
    1. IGNORE o cabeçalho onde aparece o nome do médico (ex: C PROENÇA ANTUNES).
    2. Ignore linhas de totais ou sumários.
    3. Extraia apenas as linhas de atos médicos/doentes.
    4. Formato JSON estrito: [{"data":"DD-MM-YYYY","id":"ID_EPISODIO","nome":"NOME_DOENTE","valor":0.00}]
    5. Se o nome do doente parecer invertido, corrija-o.
    """
    
    try:
        response = model.generate_content(f"{prompt}\n\nTEXTO:\n{texto_limpo}")
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        if not match: return []
        
        dados = json.loads(match.group())
        
        # Filtro de Segurança adicional via Código
        dados_filtrados = [
            d for d in dados 
            if "PROENÇA" not in str(d.get('nome')).upper() 
            and "ANTUNES" not in str(d.get('nome')).upper()
            and len(str(d.get('id'))) > 4 # IDs de episódios são geralmente longos
        ]
        return dados_filtrados
    except Exception:
        return []

# --- 3. PROCESSO DE EXECUÇÃO ---

try:
    # Configurar IA
    genai.configure(api_key=user_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    
    # Configurar Google Sheets
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    gc = gspread.authorize(creds)
    
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Erro na ligação às APIs: {e}")
    st.stop()

# Interface de Upload
arquivos_pdf = st.file_uploader("Upload de PDFs de Honorários", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Processar e Gravar"):
    todas_as_linhas = []
    data_execucao = datetime.now().strftime("%d-%m-%Y %H:%M")
    
    progresso = st.progress(0)
    status_text = st.empty()
    
    for i, pdf_file in enumerate(arquivos_pdf):
        status_text.text(f"A ler ficheiro {i+1} de {len(arquivos_pdf)}: {pdf_file.name}")
        
        with pdfplumber.open(pdf_file) as pdf:
            for pagina in pdf.pages:
                # layout=True é essencial para manter a estrutura visual
                texto = pagina.extract_text(layout=True)
                if texto:
                    dados = extrair_dados_ia(texto, model)
                    for d in dados:
                        todas_as_linhas.append([
                            d.get('data'), 
                            d.get('id'), 
                            str(d.get('nome')).upper(), 
                            d.get('valor'), 
                            data_execucao, 
                            pdf_file.name
                        ])
        
        progresso.progress((i + 1) / len(arquivos_pdf))
        time.sleep(1) # Rate limiting para o Gemini

    # Gravação dos Resultados
    if todas_as_linhas:
        try:
            worksheet.append_rows(todas_as_linhas)
            st.balloons()
            st.success(f"✅ Sucesso! {len(todas_as_linhas)} linhas adicionadas à planilha.")
            
            with st.expander("Ver dados extraídos"):
                st.table(todas_as_linhas)
        except Exception as e:
            st.error(f"Erro ao escrever no Google Sheets: {e}")
    else:
        st.warning("Não foram encontrados dados de doentes válidos nestes ficheiros.")
