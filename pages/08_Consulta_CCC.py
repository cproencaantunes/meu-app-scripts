import streamlit as st
import pdfplumber
import re
import io
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from datetime import datetime

# ─── Autenticação ─────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    st.warning("🔐 Por favor autentique-se na página principal.")
    st.stop()

# ─── Constantes de layout e RegEx ─────────────────────────────────────────────
NAME_X_MIN  = 150   
NAME_X_MAX  = 400   

# Regex para Data e Hora
DATE_TIME_RE = re.compile(r'(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})?')

# Regex para capturar o prefixo no grupo 1 e os NÚMEROS no grupo 2
PROC_RE = re.compile(r'(CCC|CCO|HCIS)/(\d+)')

# Filtro para ignorar lixo
JUNK_RE = re.compile(r'\d{5,}|^[A-Z0-9]{6,}$|Anestesiologi|Consultas|Consulta De')

# ─── Parser PDF ───────────────────────────────────────────────────────────────

def cluster_rows(words, gap=5):
    if not words: return []
    sw = sorted(words, key=lambda w: w['top'])
    clusters = [[sw[0]]]
    for w in sw[1:]:
        if w['top'] - clusters[-1][-1]['top'] <= gap:
            clusters[-1].append(w)
        else:
            clusters.append([w])
    return clusters

def limpar_nome(parts):
    limpos = [p for p in parts if not JUNK_RE.search(p)]
    return ' '.join(limpos).strip()

def parse_consultas_pdf(pdf_bytes):
    records = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(keep_blank_chars=False, x_tolerance=3, y_tolerance=3)
            clusters = cluster_rows(words, gap=5)

            i = 0
            while i < len(clusters):
                row = clusters[i]
                row_text = " ".join([w['text'] for w in row])

                date_val = None
                proc_val = None
                name_parts = []

                date_match = DATE_TIME_RE.search(row_text)
                proc_match = PROC_RE.search(row_text)

                if date_match:
                    date_val = date_match.group(1)
                
                if proc_match:
                    # ALTERAÇÃO: Captura apenas o grupo(2), que são os números
                    proc_val = proc_match.group(2)

                if date_val and proc_val:
                    for w in sorted(row, key=lambda x: x['x0']):
                        if NAME_X_MIN <= w['x0'] <= NAME_X_MAX:
                            if re.match(r'^[A-ZÁÉÍÓÚÀÃÕÂÊÔÇÜ]', w['text']):
                                name_parts.append(w['text'])

                    j = i + 1
                    while j < len(clusters):
                        next_row = clusters[j]
                        next_text = " ".join([w['text'] for w in next_row])
                        if DATE_TIME_RE.search(next_text) or "nascimento" in next_text.lower():
                            break
                        for w in sorted(next_row, key=lambda x: x['x0']):
                            if NAME_X_MIN <= w['x0'] <= NAME_X_MAX:
                                if re.match(r'^[A-ZÁÉÍÓÚÀÃÕÂÊÔÇÜ]', w['text']):
                                    name_parts.append(w['text'])
                        j += 1

                    pts = date_val.split('-')
                    date_fmt = f"{pts[2]}-{pts[1]}-{pts[0]}"

                    records.append({
                        "data":     date_fmt,
                        "processo": proc_val,
                        "nome":     limpar_nome(name_parts),
                    })
                    i = j
                else:
                    i += 1
    return records

# ─── Google Sheets ────────────────────────────────────────────────────────────

def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
    return gspread.authorize(creds)

def append_to_sheets(records, sheet_url, pdf_name):
    gc = get_gspread_client()
    sh = gc.open_by_url(sheet_url)

    try:
        ws = sh.worksheet("Consulta")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Consulta", rows=2000, cols=20)
        ws.update(range_name="C1:F1", values=[["Data", "Nº Processo", "Nome", "Origem PDF"]])
        ws.format("C1:F1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.1, "green": 0.2, "blue": 0.4}})

    col_c = ws.col_values(3)
    first_free_row = len(col_c) + 1

    rows_to_write = [[r["data"], r["processo"], r["nome"], pdf_name] for r in records]
    last_row = first_free_row + len(rows_to_write) - 1
    
    ws.update(range_name=f"C{first_free_row}:F{last_row}", values=rows_to_write)
    return first_free_row, len(rows_to_write)

# ─── Interface Streamlit ──────────────────────────────────────────────────────

st.title("🗓️ Extração de Consultas — GHCE4025R")
st.markdown("Extração de dados sem prefixos (apenas números de processo).")

sheet_url = st.session_state.get("sheet_url", "").strip()

uploaded_file = st.file_uploader("📂 Selecionar PDF", type=["pdf"])

if uploaded_file:
    pdf_bytes = uploaded_file.read()
    with st.spinner("🔍 A processar PDF..."):
        try:
            records = parse_consultas_pdf(pdf_bytes)
        except Exception as e:
            st.error(f"Erro: {e}")
            st.stop()

    if not records:
        st.error("Nenhum dado extraído. Verifique o PDF.")
    else:
        df = pd.DataFrame(records)
        st.dataframe(df, use_container_width=True, hide_index=True)

        if sheet_url:
            if st.button("📤 Enviar para Google Sheets"):
                with st.spinner("A enviar..."):
                    row, count = append_to_sheets(records, sheet_url, uploaded_file.name)
                    st.success(f"Sucesso! {count} registos enviados.")
        else:
            st.warning("🔗 Por favor, configure o link da planilha.")
