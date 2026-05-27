"""
fetch_ga4.py — Coleta métricas diárias do GA4 e grava no Google Sheets.

Modos de operação:
  HISTÓRICO — ativado por FORCE_HISTORICAL=true ou planilha vazia (0 linhas de dados)
              coleta de 01/01/2025 até ontem, dia a dia
  DIÁRIO    — padrão; coleta só o dia anterior

Secrets necessários no GitHub Actions:
  GA4_CREDENTIALS_JSON   → conteúdo do JSON da service account (já existe)
  SPREADSHEET_ID         → ID da planilha do Google Sheets

Variável opcional:
  FORCE_HISTORICAL=true  → força modo histórico independente do conteúdo da planilha

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
from googleapiclient.errors import HttpError

# ──────────────────────────────────────────────
# Configurações
# ──────────────────────────────────────────────

GA4_PROPERTY_ID    = "326912205"
HISTORY_START      = datetime.date(2025, 1, 1)
SHEET_TAB_NAME     = "analytics"
CHECKPOINT_EVERY   = 30    # gravar no Sheets a cada N linhas
PAUSE_BETWEEN_DAYS = 0.15  # segundos entre chamadas GA4 no modo histórico
MAX_RETRIES        = 3     # tentativas em caso de erro transitório da API

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

# Colunas de texto — usam "" como default, não 0
TEXT_COLUMNS = {
    "top_origem_1", "top_origem_2", "top_origem_3", "top_origem_4", "top_origem_5",
    "top_destino_1", "top_destino_2", "top_destino_3", "top_destino_4", "top_destino_5",
}

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
    # taxa_rejeicao_pct: gravado como percentual (ex: 62.5, não 0.625)
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
    meta      = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    tab_names = [s["properties"]["title"] for s in meta["sheets"]]

    if SHEET_TAB_NAME not in tab_names:
        print(f"  Aba '{SHEET_TAB_NAME}' não encontrada — criando...")
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": SHEET_TAB_NAME}}}]},
        ).execute()

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
# GA4 — helpers
# ──────────────────────────────────────────────

def get_ga4_service(creds):
    return build("analyticsdata", "v1beta", credentials=creds)


def run_report(service, date_str, dimensions, metrics, limit=10):
    """
    Executa um RunReport com retry automático em erros transitórios (429, 500, 503).
    Aguarda backoff exponencial entre tentativas.
    """
    body = {
        "dateRanges": [{"startDate": date_str, "endDate": date_str}],
        "dimensions": [{"name": d} for d in dimensions],
        "metrics":    [{"name": m} for m in metrics],
        "limit":      limit,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = (
                service.properties()
                .runReport(property=f"properties/{GA4_PROPERTY_ID}", body=body)
                .execute()
            )
            return resp.get("rows", [])
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < MAX_RETRIES:
                wait = 2 ** attempt  # 2s, 4s, 8s
                print(f"    API error {e.resp.status} — aguardando {wait}s (tentativa {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
            else:
                raise
    return []


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

# ──────────────────────────────────────────────
# GA4 — coleta de métricas por dia
# ──────────────────────────────────────────────

def collect_metrics(service, date_str):
    m = {}

    # ── Report 1: métricas gerais (sem dimensão) ─────────────────────────────
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
        # bounceRate vem como decimal (0–1) — converter para percentual
        m["taxa_rejeicao_pct"] = round(safe_float(v[4]["value"]) * 100, 2)
        m["duracao_media_seg"] = safe_float(v[5]["value"], 2)
        m["pageviews"]         = safe_int(v[6]["value"])
    else:
        for k in ["sessoes", "usuarios", "novos_usuarios", "compras",
                  "taxa_rejeicao_pct", "duracao_media_seg", "pageviews"]:
            m[k] = 0

    # CR calculado manualmente — não usar sessionConversionRate do GA4
    m["taxa_conversao_pct"] = calc_cr(m["compras"], m["sessoes"])

    # ── Report 2: sessões + compras por dispositivo ──────────────────────────
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

    # ── Report 3: sessões por canal ──────────────────────────────────────────
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

    # ── Report 4: funil de eventos ───────────────────────────────────────────
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

    # ── Report 5: top 5 origens ──────────────────────────────────────────────
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

    # ── Report 6: top 5 destinos ─────────────────────────────────────────────
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
    """Converte dict de métricas para lista na ordem de COLUMNS."""
    row = [date_str]
    for col in COLUMNS[1:]:
        default = "" if col in TEXT_COLUMNS else 0
        row.append(m.get(col, default))
    return row

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    spreadsheet_id   = os.environ.get("SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        print("ERRO: variável SPREADSHEET_ID não definida ou vazia.")
        sys.exit(1)

    force_historical = os.environ.get("FORCE_HISTORICAL", "").lower() == "true"
    yesterday        = datetime.date.today() - datetime.timedelta(days=1)

    print("Autenticando...")
    creds       = get_credentials()
    sheets      = get_sheets_service(creds)
    ga4_service = get_ga4_service(creds)

    print("Verificando planilha...")
    ensure_tab_and_header(sheets, spreadsheet_id)

    existing_dates = get_existing_dates(sheets, spreadsheet_id)
    print(f"Datas já na planilha: {len(existing_dates)}")

    # ── Modo de operação ─────────────────────────────────────────────────────
    # Histórico: forçado via env var OU planilha completamente vazia
    historical_mode = force_historical or len(existing_dates) == 0

    if historical_mode:
        if force_historical:
            print("MODO HISTÓRICO — forçado via FORCE_HISTORICAL=true")
        else:
            print("MODO HISTÓRICO — planilha vazia detectada")
        print(f"  Coletando de {HISTORY_START} até {yesterday}")

        dates_to_collect = []
        current = HISTORY_START
        while current <= yesterday:
            date_str = current.strftime("%Y-%m-%d")
            if date_str not in existing_dates:
                dates_to_collect.append(date_str)
            current += datetime.timedelta(days=1)

        total_days = len(dates_to_collect)
        # 6 chamadas à GA4 por dia × ~0.4s cada + pausa entre dias
        est_min    = round(total_days * (6 * 0.4 + PAUSE_BETWEEN_DAYS) / 60, 1)
        print(f"  {total_days} dias para coletar — estimativa: ~{est_min} min")

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

    # ── Coleta e gravação ────────────────────────────────────────────────────
    total      = len(dates_to_collect)
    batch      = []
    rows_added = 0
    errors     = []

    for i, date_str in enumerate(dates_to_collect, 1):
        print(f"  [{i}/{total}] {date_str}...", end=" ", flush=True)
        try:
            m = collect_metrics(ga4_service, date_str)
            batch.append(metrics_to_row(date_str, m))
            rows_added += 1
            print(
                f"sessoes={m['sessoes']:,} "
                f"compras={m['compras']:,} "
                f"CR={m['taxa_conversao_pct']}% "
                f"bounce={m['taxa_rejeicao_pct']}%"
            )
        except Exception as e:
            errors.append((date_str, str(e)))
            print(f"ERRO: {e}")

        # Checkpoint a cada CHECKPOINT_EVERY linhas (anti-timeout)
        if historical_mode and len(batch) >= CHECKPOINT_EVERY:
            print(f"  Gravando checkpoint ({rows_added} linhas acumuladas)...")
            append_rows(sheets, spreadsheet_id, batch)
            batch = []
            time.sleep(1)

        if historical_mode:
            time.sleep(PAUSE_BETWEEN_DAYS)

    # ── Gravar restante ──────────────────────────────────────────────────────
    if batch:
        print(f"\nGravando {len(batch)} linha(s) finais no Google Sheets...")
        append_rows(sheets, spreadsheet_id, batch)

    # ── Relatório final ──────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"Linhas adicionadas : {rows_added}")
    print(f"Erros              : {len(errors)}")
    if errors:
        print("Datas com erro:")
        for date_str, err in errors:
            print(f"  {date_str}: {err}")
    print("Concluído.")

    # Sair com erro se houver falhas, para o GitHub Actions reportar
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
