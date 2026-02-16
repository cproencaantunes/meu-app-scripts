import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="Lista de Honorários", page_icon="💰", layout="wide")

master_api_key = st.secrets.get("GEMINI_API_KEY")
sheet_url = st.session_state.get('sheet_url')

if not master_api_key or not sheet_url:
    st.warning("⚠️ Configuração em falta! Verifique a API Key nos Secrets ou o link da planilha na Home.")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data(data_str):
    if not data_str: return None
    data_str = str(data_str).strip()
    # Captura números para evitar confusão entre YYYY-MM-DD e DD-MM-YYYY
    partes = re.findall(r'\d+', data_str)
    if len(partes) == 3:
        p1, p2, p3 = partes
        if len(p1) == 4: # ISO
            ano, mes, dia = p1, p2, p3
        else: # PT/BR
            dia, mes, ano = p1, p2, p3
            if len(ano) == 2: ano = "20" + ano
        return f"{dia.zfill(2)}-{mes.zfill(2)}-{ano}"
    return None

def extrair_dados_ia(texto_pagina, model):
    # PROMPT ATUALIZADO PARA INCLUIR ENTIDADE E PROCEDIMENTO
    prompt = """
    Analisa este documento de honorários médicos e extrai os dados para JSON.
    Campos necessários:
    - data: A data do ato (DD-MM-YYYY).
    - hcis: O número do processo ou ID do doente.
    - nome: Nome completo do doente.
    - valor: Valor líquido/honorário (numérico).
    - procedimento: Descrição breve do ato médico (ex: Consulta, Ecografia, Biópsia).
    - entidade: Entidade pagadora (ex: ADSE, Médis, Multicare, SNS, Particular).
    
    JSON: [{"data":"...", "hcis":"...", "nome":"...", "valor":0.00, "procedimento":"...", "entidade":"..."}]
    """
    try:
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
    # Abre a folha 'pagos' (ou a primeira folha se preferir)
    worksheet = sh.get_worksheet(0) 
except Exception as e:
    st.error(f"❌ Erro de Conexão: {e}")
    st.stop()

# --- 4. INTERFACE ---
st.title("💰 Processador de Honorários Avançado")
st.info("Extração detalhada: Data, HCIS, Nome, Valor, Procedimento e Entidade.")

arquivos_pdf = st.file_uploader("Carregue os PDFs", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Iniciar Processamento"):
    todas_as_linhas_final = []
    data_exec = datetime.now().strftime("%d-%m-%Y %H:%M")
    termos_ignorar = ["PROENÇA ANTUNES", "UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO"]

    progresso = st.progress(0)
    status_info = st.empty()
    dados_atuais = worksheet.get_all_values()

    for idx, pdf_file in enumerate(arquivos_pdf):
        status_info.info(f"📖 A processar: {pdf_file.name}")
        ultima_data_valida = ""

        with pdfplumber.open(pdf_file) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text()
                if not texto: continue
                
                dados_ia = extrair_dados_ia(texto, model)

                for d in dados_ia:
                    dt = formatar_data(d.get('data', ''))
                    if dt: ultima_data_valida = dt
                    else: dt = ultima_data_valida

                    hcis = re.sub(r'\D', '', str(d.get('hcis', '')))
                    nome = str(d.get('nome', '')).strip().upper()
                    procedimento = str(d.get('procedimento', '')).strip().upper()
                    entidade = str(d.get('entidade', '')).strip().upper()
                    
                    e_lixo = any(termo in nome for termo in termos_ignorar)

                    if hcis and not e_lixo and len(nome) > 3:
                        # ORGANIZAÇÃO DAS COLUNAS (A partir da Coluna B)
                        todas_as_linhas_final.append([
                            dt,             # Coluna B: Data
                            hcis,           # Coluna C: HCIS
                            nome,           # Coluna D: Nome
                            procedimento,   # Coluna E: Procedimento (NOVO)
                            entidade,       # Coluna F: Entidade (NOVO)
                            d.get('valor', 0.0), # Coluna G: Valor
                            data_exec       # Coluna H: Registo
                        ])
        
        progresso.progress((idx + 1) / len(arquivos_pdf))

    status_info.empty()

    if todas_as_linhas_final:
        try:
            proxima_linha = len(dados_atuais) + 1
            worksheet.update(
                range_name=f"B{proxima_linha}", 
                values=todas_as_linhas_final
            )
            st.success(f"✅ {len(todas_as_linhas_final)} registos extraídos com Entidade e Procedimento!")
            st.table(todas_as_linhas_final)
        except Exception as e:
            st.error(f"❌ Erro ao gravar: {e}")
    else:
        st.warning("Nenhum dado encontrado.")
