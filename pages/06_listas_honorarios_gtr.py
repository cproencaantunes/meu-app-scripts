import streamlit as st
import gspread
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# CONFIGURAÇÕES INICIAIS
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Extração de Honorários", page_icon="💶", layout="wide")

sheet_url = st.session_state.get('sheet_url')
if not sheet_url:
    st.warning("⚠️ Configuração em falta na Home (Link da Planilha).")
    st.stop()

# ---------------------------------------------------------------------------
# PARSING DIRETO (sem IA)
#
# ESTRUTURA DO PDF (Mapa de Honorários - Detalhe):
#
# Pág. 1: sumário por grupo (ignorada)
# Págs. 2+: linhas de detalhe, uma por ato:
#   "DD-MM-YY <processo><nome> <Serviço> <cod_entidade> <entidade...> <cod_acto><acto...> [%] [NrK] <qtd> <valor>"
#
# Os nomes dos doentes ficam sempre antes do nome do serviço.
# O valor é sempre o último campo (formato 9.99 ou 9,999.99).
# O grupo (Anestesia, Cirurgias, Consultas, etc.) aparece como linha de secção.
# ---------------------------------------------------------------------------

# Serviços conhecidos — ordenados do mais longo para o mais curto para evitar
# matches parciais (ex: "Cirurgia Geral" antes de "Cirurgia")
_SERVICOS = [
    'Bloco Operatorio Tejo',
    'Cir. Plástica E Reconstru',
    'Ginecologia Obstetricia',
    'Otorrinolaringologia',
    'Neuro-Cirurgia',
    'Cirurgia Vascular',
    'Cirurgia Geral',
    'Gastroenterologia',
    'Anestesiologia',
    'Oftalmologia',
    'Ortopedia',
]
_SERVICOS.sort(key=len, reverse=True)

# Separador nome → serviço: serviço seguido imediatamente de dígitos (código da entidade)
RE_SERVICO = re.compile(
    r'\s*(' + '|'.join(re.escape(s) for s in _SERVICOS) + r')(?=\s*\d)'
)

# Linha de dados: começa com data DD-MM-YY, processo colado ao nome, termina em qtd + valor
RE_LINHA = re.compile(
    r'^(\d{2}-\d{2}-\d{2})\s+'   # data DD-MM-YY
    r'(\d+)'                       # processo (só dígitos, colado ao nome)
    r'(.+?)\s+'                    # nome + serviço + entidade + acto (tudo junto)
    r'\d+\s+'                      # quantidade
    r'([\d,]+\.\d{2})$'           # valor (ex: 50.00 ou 1,125.20)
)

# Cabeçalhos de secção de grupo
RE_GRUPO = re.compile(
    r'^(Anestesia|Cirurgias Oftalmologia|Cirurgias|Consultas|Endoscopia.*)$'
)

# Linhas de cabeçalho/rodapé a ignorar
RE_IGNORAR = re.compile(
    r'Hospital |Mapa de Honor|PS_PA_009|Utilizador:|Pág\.\s*(por|:)?\s*\d|'
    r'Data:\s*\d{4}|Hora:\s*\d|Ano:\s*\d|Prestador de Serviços|'
    r'Código fornecedor|1M - Processamento|Datas (Activ|Factur)|'
    r'Valores do Período|^Data\s+Doente|Total (do Período|Geral|Valor)'
)


def parsear_pagina(texto: str, grupo_atual: str) -> tuple[list, str]:
    """Parseia uma página e devolve (lista_registos, grupo_atual)."""
    registos = []
    for linha in texto.split('\n'):
        linha = linha.strip()
        if not linha or RE_IGNORAR.search(linha):
            continue

        # Detecta mudança de grupo
        mg = RE_GRUPO.match(linha)
        if mg:
            grupo_atual = mg.group(1).strip()
            continue

        # Linha de dados
        m = RE_LINHA.match(linha)
        if not m:
            continue

        data_raw = m.group(1)   # DD-MM-YY
        processo = m.group(2)   # só dígitos
        meio = m.group(3).strip()
        valor = m.group(4).replace(',', '')  # remove separador de milhar

        # Separa nome do serviço
        ms = RE_SERVICO.search(meio)
        nome = meio[:ms.start()].strip() if ms else meio.strip()
        servico = ms.group(1) if ms else ""

        # Converte DD-MM-YY → DD-MM-YYYY
        p = data_raw.split('-')
        data_fmt = f"{p[0]}-{p[1]}-20{p[2]}"

        registos.append({
            "data": data_fmt,
            "processo": processo,
            "nome": nome.upper(),
            "servico": servico,
            "grupo": grupo_atual,
            "valor": valor,
        })

    return registos, grupo_atual


# ---------------------------------------------------------------------------
# CONEXÃO GOOGLE SHEETS
# ---------------------------------------------------------------------------
try:
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scope
    )
    gc = gspread.authorize(creds)
    sheet_id = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url).group(1)
    sh = gc.open_by_key(sheet_id)

    NOME_FOLHA = 'Honorários'
    try:
        worksheet = sh.worksheet(NOME_FOLHA)
    except Exception:
        worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="10000", cols="10")
        worksheet.update(
            range_name="A1",
            values=[["Data", "Processo", "Nome do Doente", "Serviço", "Grupo", "Valor (€)", "Gravado Em", "Origem PDF"]]
        )
except Exception as e:
    st.error(f"❌ Erro de ligação ao Google Sheets: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# INTERFACE E PROCESSAMENTO
# ---------------------------------------------------------------------------
st.title("💶 Extração de Honorários")
st.info(
    "Extrai todas as linhas dos PDFs **Mapa de Honorários - Detalhe** para o Google Sheets.  \n"
    "**Sem deduplicação** — todas as linhas são gravadas, incluindo repetidas."
)

uploads = st.file_uploader(
    "Carregue os PDFs de Honorários", type=['pdf', 'PDF'], accept_multiple_files=True
)

if uploads and st.button("🚀 Iniciar Processamento"):
    data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
    status_msg = st.empty()
    progresso = st.progress(0)

    for idx_pdf, pdf_file in enumerate(uploads):
        todas_linhas = []
        grupo_atual = ""

        with pdfplumber.open(pdf_file) as pdf:
            total_pags = len(pdf.pages)

            for p_idx, pagina in enumerate(pdf.pages):
                status_msg.info(
                    f"📄 PDF {idx_pdf+1}/{len(uploads)} | "
                    f"Página {p_idx+1}/{total_pags} — {pdf_file.name}"
                )
                texto = pagina.extract_text()
                if not texto:
                    continue

                registos, grupo_atual = parsear_pagina(texto, grupo_atual)

                for r in registos:
                    todas_linhas.append([
                        r["data"], r["processo"], r["nome"],
                        r["servico"], r["grupo"], r["valor"],
                        data_hoje, pdf_file.name
                    ])

        # Diagnóstico
        st.write(f"**{pdf_file.name}** — {len(todas_linhas)} linhas extraídas")

        if todas_linhas:
            # Pág. 1 é só sumário — não tem linhas de dados, ok
            # Gravação em lotes de 500
            for i in range(0, len(todas_linhas), 500):
                lote = todas_linhas[i:i+500]
                worksheet.append_rows(
                    lote,
                    value_input_option="USER_ENTERED",
                    table_range="A1"
                )
                if len(todas_linhas) > 500:
                    time.sleep(1)
            st.toast(f"✅ {len(todas_linhas)} linhas gravadas de {pdf_file.name}")
        else:
            # Mostra diagnóstico se nada extraído
            with pdfplumber.open(pdf_file) as pdf:
                txt_p2 = pdf.pages[1].extract_text() if len(pdf.pages) > 1 else ""
            st.warning("⚠️ Nenhum registo encontrado. Primeiras linhas da pág. 2:")
            st.code(txt_p2[:1500] if txt_p2 else "(vazio)")

        progresso.progress((idx_pdf + 1) / len(uploads))

    status_msg.success("✨ Processamento concluído!")
    st.balloons()
