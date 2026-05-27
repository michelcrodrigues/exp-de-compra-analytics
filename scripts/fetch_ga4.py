"""
fetch_ga4.py — Coleta métricas diárias do GA4 e grava no Google Sheets.

Modos de operação:
  HISTÓRICO — primeira execução: coleta de 01/01/2025 até ontem, dia a dia
  DIÁRIO    — execuções seguintes: coleta só o dia anterior

Secrets necessários no GitHub Actions:
  GA4_CREDENTIALS_JSON   → conteúdo do JSON da service account (já existe)
  SPREADSHEET_ID         → ID da planilha do Google Sheets

A service account precisa ter acesso de Editor à planilha.
E-mail: ga4-dashboard-github@analytics-dashboard-497114.iam.gserviceaccount.com
"""

import os
import json
import datetime
import sys
import time

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ──────────────────────────────────────────────
# Configurações
# ──────────────────────────────────────────────

GA4_PROPERTY_ID = "326912205"
HISTORY_START   = datetime.date(2025, 1, 1)
SHEET_TAB_NAME  = "analytics"

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

# Colunas da planilha — ordem fixa, não alterar sem migrar o arquivo
COLUMNS = [
    "data",

    # ── Volume geral ─────────────────────────────────────────────
    "sessoes",
    "usuarios",
    "novos_usuarios",
    "pageviews",

    # ── Conversão geral ──────────────────────────────────────────
    # taxa_conversao_pct = compras / sessoes * 100 (calculado pelo script)
    "compras",
    "taxa_conversao_pct",

    # ── Engajamento ──────────────────────────────────────────────
    "taxa_rejeicao_pct",
    "duracao_media_seg",

    # ── Por dispositivo (sessões + compras) ──────────────────────
    # CR por device = compras_X / sessoes_X * 100 (calcular na planilha)
    "sessoes_mobile",
    "sessoes_desktop",
    "sessoes_tablet",
    "compras_mobile",
    "compras_desktop",
    "compras_tablet",

    # ── Por canal (sessões) ──────────────────────────────────────
    "sessoes_organico",
    "sessoes_direto",
    "sessoes_pago",
    "sessoes_social",
    "sessoes_email",
    "sessoes_referral",
    "sessoes_outros_canais",

    # ── Funil de eventos ─────────────────────────────────────────
    "funil_search",
    "funil_select_item",
    "funil_add_to_cart",
    "funil_begin_checkout",
    "funil_purchase",

    # ── Top 5 origens (cidade + sessões) ─────────────────────────
    "top_origem_1", "top_origem_1_sessoes",
    "top_origem_2", "top_origem_2_sessoes",
    "top_origem_3", "top_origem_3_sessoes",
    "top_origem_4", "top_origem_4_sessoes",
    "top_origem_5", "top_origem_5_sessoes",

    # ── Top 5 destinos (cidade + sessões) ────────────────────────
    "top_destino_1", "top_destino_1_sessoes",
    "top_destino_2", "top_destino_2_sessoes",
    "top_destino_3", "top_destino_3_sessoes",
    "top_destino_4", "top_destino_4_sessoes",
    "top_destino_5", "top_destino_5_sessoes",
]

# ──────────────────────────────────────────────
# Autenticação
# ──────────────────────────────────────────────

def get_credentials():
    creds_info = json.loads(os.environ["GA4_CREDENTIALS_JSON"])
    return service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )

# ──────────────────────────────────────────────
# Google Sheets
# ──────────────────────────────────────────────

def get_sheets_service(creds):
    return build("sheets", "v4", credentials=creds)


def ensure_tab_and_header(sheets, spreadsheet_id):
    meta     = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    tab_names = [s["properties"]["title"] for s in meta["sheets"]]

    if SHEET_TAB_NAME not in tab_names:
        print(f"  Aba '{SHEET_TAB_NAME}' não encontrada — criando...")
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": SHEET_TAB_NAME}}}]},
        ).execute()

    # Verificar se cabeçalho existe
    result = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{SHEET_TAB_NAME}!A1:A1",
    ).execute()

    if not result.get("values"):
        sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_TAB_NAME}!A1",
            valueInputOption="RAW",
            body={"values": [COLUMNS]},
        ).execute()
        print(f"  Cabeçalho criado ({len(COLUMNS)} colunas).")


def get_existing_dates(sheets, spreadsheet_id):
    result = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{SHEET_TAB_NAME}!A2:A",
    ).execute()
    return {row[0] for row in result.get("values", []) if row}


def append_rows(sheets, spreadsheet_id, rows):
    sheets.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{SHEET_TAB_NAME}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()

# ──────────────────────────────────────────────
# GA4
# ──────────────────────────────────────────────

def get_ga4_service(creds):
    return build("analyticsdata", "v1beta", credentials=creds)


def run_report(service, date_str, dimensions, metrics, limit=10):
    body = {
        "dateRanges": [{"startDate": date_str, "endDate": date_str}],
        "dimensions": [{"name": d} for d in dimensions],
        "metrics":    [{"name": m} for m in metrics],
        "limit":      limit,
    }
    resp = (
        service.properties()
        .runReport(property=f"properties/{GA4_PROPERTY_ID}", body=body)
        .execute()
    )
    return resp.get("rows", [])


def safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def safe_float(value, decimals=4):
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return 0.0


def calc_cr(compras, sessoes):
    """Taxa de conversão real: compras / sessoes * 100."""
    if sessoes > 0:
        return round(compras / sessoes * 100, 4)
    return 0.0


def collect_metrics(service, date_str):
    m = {}

    # ── Métricas gerais ──────────────────────────────────────────────────────
    rows = run_report(
        service, date_str, [],
        ["sessions", "totalUsers", "newUsers", "transactions",
         "bounceRate", "averageSessionDuration", "screenPageViews"],
    )
    if rows:
        v = rows[0]["metricValues"]
        m["sessoes"]           = safe_int(v[0]["value"])
        m["usuarios"]          = safe_int(v[1]["value"])
        m["novos_usuarios"]    = safe_int(v[2]["value"])
        m["compras"]           = safe_int(v[3]["value"])
        m["taxa_rejeicao_pct"] = safe_float(v[4]["value"])
        m["duracao_media_seg"] = safe_float(v[5]["value"], 2)
        m["pageviews"]         = safe_int(v[6]["value"])
    else:
        for k in ["sessoes", "usuarios", "novos_usuarios", "compras",
                  "taxa_rejeicao_pct", "duracao_media_seg", "pageviews"]:
            m[k] = 0

    # CR calculado manualmente — não usar sessionConversionRate do GA4
    m["taxa_conversao_pct"] = calc_cr(m["compras"], m["sessoes"])

    # ── Sessões + compras por dispositivo ────────────────────────────────────
    for dev in ["mobile", "desktop", "tablet"]:
        m[f"sessoes_{dev}"] = 0
        m[f"compras_{dev}"] = 0

    rows = run_report(
        service, date_str,
        ["deviceCategory"],
        ["sessions", "transactions"],
    )
    for row in rows:
        dev = row["dimensionValues"][0]["value"].lower()
        if dev in ("mobile", "desktop", "tablet"):
            m[f"sessoes_{dev}"] = safe_int(row["metricValues"][0]["value"])
            m[f"compras_{dev}"] = safe_int(row["metricValues"][1]["value"])

    # ── Sessões por canal ────────────────────────────────────────────────────
    channel_map = {
        "organic search": "sessoes_organico",
        "direct":         "sessoes_direto",
        "paid search":    "sessoes_pago",
        "organic social": "sessoes_social",
        "email":          "sessoes_email",
        "referral":       "sessoes_referral",
    }
    for k in channel_map.values():
        m[k] = 0
    m["sessoes_outros_canais"] = 0

    rows = run_report(
        service, date_str,
        ["sessionDefaultChannelGroup"],
        ["sessions"],
        limit=20,
    )
    for row in rows:
        channel = row["dimensionValues"][0]["value"].lower()
        val     = safe_int(row["metricValues"][0]["value"])
        if channel in channel_map:
            m[channel_map[channel]] = val
        else:
            m["sessoes_outros_canais"] += val

    # ── Funil de eventos ─────────────────────────────────────────────────────
    funil_map = {
        "search":         "funil_search",
        "select_item":    "funil_select_item",
        "add_to_cart":    "funil_add_to_cart",
        "begin_checkout": "funil_begin_checkout",
        "purchase":       "funil_purchase",
    }
    for k in funil_map.values():
        m[k] = 0

    rows = run_report(
        service, date_str,
        ["eventName"],
        ["eventCount"],
        limit=50,
    )
    for row in rows:
        event = row["dimensionValues"][0]["value"]
        if event in funil_map:
            m[funil_map[event]] = safe_int(row["metricValues"][0]["value"])

    # ── Top 5 origens ────────────────────────────────────────────────────────
    for i in range(1, 6):
        m[f"top_origem_{i}"]         = ""
        m[f"top_origem_{i}_sessoes"] = 0

    rows = run_report(
        service, date_str,
        ["customEvent:originCity"],
        ["sessions"],
        limit=5,
    )
    for i, row in enumerate(rows, 1):
        city = row["dimensionValues"][0]["value"]
        if city and city != "(not set)":
            m[f"top_origem_{i}"]         = city
            m[f"top_origem_{i}_sessoes"] = safe_int(row["metricValues"][0]["value"])

    # ── Top 5 destinos ───────────────────────────────────────────────────────
    for i in range(1, 6):
        m[f"top_destino_{i}"]         = ""
        m[f"top_destino_{i}_sessoes"] = 0

    rows = run_report(
        service, date_str,
        ["customEvent:destinationCity"],
        ["sessions"],
        limit=5,
    )
    for i, row in enumerate(rows, 1):
        city = row["dimensionValues"][0]["value"]
        if city and city != "(not set)":
            m[f"top_destino_{i}"]         = city
            m[f"top_destino_{i}_sessoes"] = safe_int(row["metricValues"][0]["value"])

    return m


def metrics_to_row(date_str, m):
    return [date_str] + [m.get(col, 0) for col in COLUMNS[1:]]


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    yesterday      = datetime.date.today() - datetime.timedelta(days=1)

    print("Autenticando...")
    creds       = get_credentials()
    sheets      = get_sheets_service(creds)
    ga4_service = get_ga4_service(creds)

    print("Verificando planilha...")
    ensure_tab_and_header(sheets, spreadsheet_id)

    existing_dates = get_existing_dates(sheets, spreadsheet_id)
    print(f"Datas já na planilha: {len(existing_dates)}")

    # ── Modo de operação ─────────────────────────────────────────────────────
    historical_mode = len(existing_dates) < 5

    if historical_mode:
        print(f"MODO HISTÓRICO — coletando de {HISTORY_START} até {yesterday}")
        dates_to_collect = []
        current = HISTORY_START
        while current <= yesterday:
            date_str = current.strftime("%Y-%m-%d")
            if date_str not in existing_dates:
                dates_to_collect.append(date_str)
            current += datetime.timedelta(days=1)
    else:
        date_str = yesterday.strftime("%Y-%m-%d")
        if date_str in existing_dates:
            print(f"MODO DIÁRIO — {date_str} já existe. Nada a fazer.")
            sys.exit(0)
        print(f"MODO DIÁRIO — coletando {date_str}")
        dates_to_collect = [date_str]

    if not dates_to_collect:
        print("Nenhuma data nova para coletar.")
        sys.exit(0)

    # ── Coleta ───────────────────────────────────────────────────────────────
    total = len(dates_to_collect)
    batch = []
    rows_added = 0

    for i, date_str in enumerate(dates_to_collect, 1):
        print(f"  [{i}/{total}] {date_str}...", end=" ", flush=True)
        try:
            m = collect_metrics(ga4_service, date_str)
            batch.append(metrics_to_row(date_str, m))
            rows_added += 1
            print(
                f"sessoes={m['sessoes']} "
                f"compras={m['compras']} "
                f"CR={m['taxa_conversao_pct']}%"
            )
        except Exception as e:
            print(f"ERRO: {e}")

        # Checkpoint a cada 30 linhas no modo histórico
        if historical_mode and len(batch) >= 30:
            print(f"  Gravando checkpoint ({rows_added} linhas acumuladas)...")
            append_rows(sheets, spreadsheet_id, batch)
            batch = []
            time.sleep(1)

        if historical_mode:
            time.sleep(0.3)

    # ── Gravar restante ──────────────────────────────────────────────────────
    if batch:
        print(f"\nGravando {len(batch)} linha(s) finais no Google Sheets...")
        append_rows(sheets, spreadsheet_id, batch)

    print(f"Total de linhas adicionadas: {rows_added}")
    print("Concluído.")


if __name__ == "__main__":
    main()
