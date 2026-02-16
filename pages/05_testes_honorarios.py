import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÕES DA PÁGINA ---
st.set_page_config(page_title="Processador de Honorários", page_icon="💰", layout="wide")

# Recuperar segredos e estado da sessão
master_api_key = st.secrets.get("GEMINI_API_KEY")
sheet_url = st.session_state.get('sheet_url')

if not master_api_key or not sheet_url:
    st.error("❌ Erro: API Key ou Link da Planilha em falta. Configure na página Home.")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE (MOTOR DE DATAS E IDs) ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data(data_str):
    """Normaliza datas para DD-MM-YYYY, corrigindo inversões de ano/dia."""
    if not data_str: return None
    data_str = str(data_str).strip()
    partes = re.findall(r'\d+', data_str)
    
    if len(partes) == 3:
        p1, p2, p3 = partes
        # Caso: 2020-01-14 -> p1 é o ano
        if len(p1) == 4:
            ano, mes, dia = p1, p2, p3
        # Caso: 14-01-2020 -> p3 é o ano
        elif len(p3) == 4:
            dia, mes, ano = p1, p2, p3
        # Caso: 14-01-20 -> p3 é o ano curto
        else:
            dia, mes, ano = p1, p2, p3
            if len(ano) == 2: ano = "20" + ano
            
        return f"{dia.zfill(2)}-{mes.zfill(2)}-{ano}"
    return None

def extrair_dados_ia(texto_pagina, model):
    """Solicita à IA a extração estruturada dos dados de honorários."""
    prompt = """
    Analisa este documento de honorários médicos e extrai os dados para JSON.
    Campos obrigatórios:
    - data: A data do ato médico (DD-MM-YYYY).
    - hcis: O número do processo ou ID do doente (apenas números).
    - nome: Nome completo do doente (MAIÚSCULAS).
    - valor: Valor líquido/honorário (ex: 45.50).
    - procedimento: Descrição da técnica (ex: CONSULTA, ECOGRAFIA, INFILTRAÇÃO).
    - entidade: Entidade pagadora (ex: ADSE, MÉDIS, MULTICARE, SNS, PARTICULAR).
    
    JSON: [{"data":"...", "hcis":"...", "nome":"...", "valor":0.0, "procedimento":"...", "entidade":"..."}]
    """
    try:
        response = model.generate_content(f"{prompt}\n\nTEXTO:\n{texto_pagina}", generation_config={"temperature": 0.0})
        # Limpar a resposta para garantir que temos apenas o JSON
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        return json.loads(match.group()) if match else []
    except:
        return []

# --- 3. CONEXÃO COM GOOGLE SHEETS E IA ---
try:
    genai.configure(api_key=master_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    
    # Abre a aba 'pagos' (ou a primeira aba da planilha)
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Erro de Autenticação/Conexão: {e}")
    st.stop()

# --- 4. INTERFACE E LÓGICA DE PROCESSAMENTO ---
st.title("💰 Extração de Honorários Médicos")
st.info("Gravação na Coluna B: [Data, HCIS, Nome, Valor, Procedimento, Entidade]")

uploads = st.file_uploader("Carregue os PDFs de Honorários", type=['pdf'], accept_multiple_files=True)

if uploads and st.button("🚀 Iniciar Processamento"):
    todas_as_linhas = []
    data_log = datetime.now().strftime("%d-%m-%Y %H:%M")
    termos_filtro = ["UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO", "PROENÇA ANTUNES"]

    progresso = st.progress(0)
    status = st.empty()
    
    # Obter dados para evitar escrever por cima (usado para calcular a proxima_linha)
    dados_atuais = worksheet.get_all_values()

    for idx, pdf_file in enumerate(uploads):
        status.info(f"📖 A ler ficheiro: {pdf_file.name}")
        ultima_data = datetime.now().strftime("%d-%m-%Y")

        with pdfplumber.open(pdf_file) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text()
                if not texto: continue
                
                itens_ia = extrair_dados_ia(texto, model)
                
                for item in itens_ia:
                    # Normalizar data
                    dt = formatar_data(item.get('data'))
                    if dt: ultima_data = dt
                    else: dt = ultima_data
                    
                    # Limpar dados
                    hcis = re.sub(r'\D', '', str(item.get('hcis', '')))
                    nome = str(item.get('nome', '')).strip().upper()
                    valor = item.get('valor', 0.0)
                    proc = str(item.get('procedimento', '')).strip().upper()
                    entidade = str(item.get('entidade', '')).strip().upper()
                    
                    # Filtro de segurança (Lixo e repetidos no cabeçalho)
                    e_lixo = any(termo in nome for termo in termos_filtro)

                    if hcis and len(nome) > 3 and not e_lixo:
                        # ORDEM EXATA PARA A PLANILHA (A partir da Coluna B)
                        todas_as_linhas.append([
                            dt,       # Coluna B: Data
                            hcis,     # Coluna C: HCIS
                            nome,     # Coluna D: Nome
                            valor,    # Coluna E: Valor
                            proc,     # Coluna F: Procedimento
                            entidade, # Coluna G: Entidade
                            data_log  # Coluna H: Data de Registo
                        ])
        
        progresso.progress((idx + 1) / len(uploads))

    status.empty()

    if todas_as_linhas:
        try:
            # Definir onde começa a escrita (após a última linha ocupada)
            proxima_fila = len(dados_atuais) + 1
            worksheet.update(
                range_name=f"B{proxima_fila}", 
                values=todas_as_linhas,
                value_input_option="USER_ENTERED"
            )
            st.success(f"✅ Sucesso! {len(todas_as_linhas)} registos gravados.")
            st.table(todas_as_linhas)
        except Exception as e:
            st.error(f"❌ Erro ao escrever na planilha: {e}")
    else:
        st.warning("⚠️ Nenhum dado válido foi extraído dos ficheiros carregados.")
