import streamlit as st
import pdfplumber
import re
import io
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# ─── Autenticação ─────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    st.warning("🔐 Por favor autentique-se na página principal.")
    st.stop()

# ─── Constantes de layout ─────────────────────────────────────────────────────
NAME_X_MIN  = 155   # coluna do nome começa aqui
NAME_X_MAX  = 225   # coluna do nome termina aqui (N.Benef começa depois)

DATE_TIME_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})\d{2}:\d{2}$')
HCIS_RE      = re.compile(r'^HCIS/(\d+)$')
# Remove tokens que não fazem parte do nome (N.Benef colados, códigos alfanum.)
JUNK_RE      = re.compile(r'\d{5,}|^[A-Z0-9]{6,}$|Anestesiologi')


# ─── Parser PDF ───────────────────────────────────────────────────────────────

def cluster_rows(words, gap=5):
    """Agrupa palavras em linhas por proximidade vertical."""
    if not words:
        return []
    sw = sorted(words, key=lambda w: w['top'])
    clusters = [[sw[0]]]
    for w in sw[1:]:
        if w['top'] - clusters[-1][-1]['top'] <= gap:
            clusters[-1].append(w)
        else:
            clusters.append([w])
    return clusters


def limpar_nome(parts):
    """Remove tokens de N.Benef que ficam colados na coluna do nome."""
    limpos = []
    for p in parts:
        if JUNK_RE.search(p):
            continue
        limpos.append(p)
    return ' '.join(limpos)


def parse_consultas_pdf(pdf_bytes):
    """
    Extrai registos de consulta do PDF GHCE4025R.
    Devolve lista de dicts: data, processo, nome.
    """
    records = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(
                keep_blank_chars=False, x_tolerance=3, y_tolerance=3
            )
            clusters = cluster_rows(words, gap=5)

            i = 0
            while i < len(clusters):
                row = clusters[i]

                date_val = None
                proc_val = None
                name_parts = []

                for w in sorted(row, key=lambda x: x['x0']):
                    dm = DATE_TIME_RE.match(w['text'])
                    if dm:
                        date_val = dm.group(1)
                    hm = HCIS_RE.match(w['text'])
                    if hm:
                        proc_val = hm.group(1)
                    if NAME_X_MIN <= w['x0'] <= NAME_X_MAX:
                        if re.match(r'^[A-ZÁÉÍÓÚÀÃÕÂÊÔÇÜ]', w['text']):
                            name_parts.append(w['text'])

                if date_val and proc_val:
                    # Recolher continuação do nome nas linhas seguintes
                    j = i + 1
                    while j < len(clusters):
                        next_row = clusters[j]
                        # Parar no próximo registo ou em "Data de nascimento"
                        has_date = any(DATE_TIME_RE.match(w['text']) for w in next_row)
                        has_nasc = any(
                            w['text'] == 'Data' and w['x0'] < 35 for w in next_row
                        )
                        if has_date or has_nasc:
                            break
                        for w in sorted(next_row, key=lambda x: x['x0']):
                            if NAME_X_MIN <= w['x0'] <= NAME_X_MAX:
                                if re.match(r'^[A-ZÁÉÍÓÚÀÃÕÂÊÔÇÜ]', w['text']):
                                    name_parts.append(w['text'])
                        j += 1

                    # Formatar data dd-mm-yyyy
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
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=scopes
    )
    return gspread.authorize(creds)


def append_to_sheets(records, sheet_url, pdf_name):
    """
    Abre (ou cria) a aba 'Consulta', encontra a primeira linha livre
    na coluna C e acrescenta os registos sem apagar dados existentes.
    Colunas: C=Data  D=Processo  E=Nome  F=Origem PDF
    """
    gc = get_gspread_client()
    sh = gc.open_by_url(sheet_url)

    try:
        ws = sh.worksheet("Consulta")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Consulta", rows=2000, cols=20)
        ws.update(
            range_name="C1:F1",
            values=[["Data", "Nº Processo", "Nome", "Origem PDF"]]
        )
        ws.format("C1:F1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.122, "green": 0.220, "blue": 0.392},
        })

    # Primeira linha livre na coluna C
    first_free_row = len(ws.col_values(3)) + 1

    rows_to_write = [
        [rec["data"], rec["processo"], rec["nome"], pdf_name]
        for rec in records
    ]

    last_row = first_free_row + len(rows_to_write) - 1
    ws.update(
        range_name=f"C{first_free_row}:F{last_row}",
        values=rows_to_write
    )

    return first_free_row, len(rows_to_write)


# ─── Interface ────────────────────────────────────────────────────────────────

st.title("🗓️ Extração de Consultas — GHCE4025R")
st.markdown(
    "Carregue o PDF de **Actos Médicos** (consultas). "
    "Os dados são extraídos e escritos automaticamente na aba **Consulta** "
    "da planilha configurada, a partir da primeira linha livre na coluna **C**."
)

st.divider()

sheet_url = st.session_state.get("sheet_url", "").strip()

if not sheet_url:
    st.warning(
        "⚠️ Nenhuma planilha configurada. "
        "Cole o link na barra lateral (⚙️ Configuração) antes de carregar o PDF."
    )

uploaded_file = st.file_uploader(
    "📂 Selecionar PDF",
    type=["pdf"],
    help="Relatório GHCE4025R — Actos Médicos por Estado"
)

if uploaded_file:
    pdf_bytes = uploaded_file.read()

    # ── Parsing ───────────────────────────────────────────────────────────────
    with st.spinner("🔍 A processar PDF..."):
        try:
            records = parse_consultas_pdf(pdf_bytes)
        except Exception as e:
            st.error(f"Erro ao processar PDF: {e}")
            st.stop()

    if not records:
        st.error("Não foi possível extrair registos. Confirme que é um relatório GHCE4025R válido.")
        st.stop()

    # ── Pré-visualização ──────────────────────────────────────────────────────
    import pandas as pd
    df = pd.DataFrame(records)
    df.columns = ["Data", "Nº Processo", "Nome"]

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Nome": st.column_config.TextColumn(width="large"),
        }
    )

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Consultas", len(records))
    with col2:
        st.metric("Dias com Consultas", len({r["data"] for r in records}))

    st.divider()

    # ── Escrita automática na planilha ────────────────────────────────────────
    if not sheet_url:
        st.info("Configure o link da planilha na barra lateral para exportar os dados.")
    else:
        st.caption(f"🔗 Planilha: `{sheet_url}`")
        with st.spinner("📤 A escrever na planilha..."):
            try:
                first_row, n = append_to_sheets(records, sheet_url, uploaded_file.name)
                st.success(
                    f"✅ **{n} registos** escritos na aba **Consulta** "
                    f"a partir da linha **{first_row}** (coluna C)."
                )
                st.markdown(f"[🔗 Abrir Planilha]({sheet_url})")
                st.session_state["last_consultas_write"] = {
                    "rows": n,
                    "time": datetime.now().strftime("%d-%m-%Y %H:%M"),
                    "file": uploaded_file.name,
                }
            except gspread.exceptions.SpreadsheetNotFound:
                st.error("❌ Planilha não encontrada. Verifique o URL na configuração.")
            except gspread.exceptions.APIError as e:
                st.error(f"❌ Erro de API Google: {e}")
            except Exception as e:
                st.error(f"❌ Erro inesperado: {e}")
                st.exception(e)

    last = st.session_state.get("last_consultas_write")
    if last:
        st.caption(
            f"📝 Última exportação: **{last['rows']} registos** "
            f"de `{last['file']}` → {last['time']}"
        )

else:
    st.info("👆 Carregue um ficheiro PDF para começar.")
