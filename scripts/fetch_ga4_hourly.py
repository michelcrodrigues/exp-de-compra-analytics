"""
fetch_ga4_hourly.py — Coleta métricas do GA4 por HORA e grava em data/history_hourly.ndjson.

Adaptado de scripts/fetch_ga4.py, usando a dimensão nativa "dateHour" do GA4
(formato AAAAMMDDHH), que traz o intervalo inteiro numa única chamada por
relatório — não precisa fazer loop dia a dia.

Uso:
    GA4_CREDENTIALS_JSON='<json da service account>' \
    python scripts/fetch_ga4_hourly.py --property-id 326912205 \
        --start 2026-06-17 --end 2026-07-07 --output data/history_hourly_site.ndjson

Property IDs do projeto (ver scripts/fetch_ga4.py e fetch_ga4_app.py):
    Site -> 326912205
    App  -> 256859064

Cada linha do ndjson de saída é uma hora:
    {"hora": "2026-07-01T00:00", "sessoes": ..., "taxa_rejeicao_pct": ...,
     "duracao_media_seg": ..., "compras": ..., "funil_search": ...,
     "sessoes_mobile": ..., "taxa_rejeicao_mobile": ..., ...}

Observação sobre fuso horário: o GA4 retorna dateHour no fuso configurado na
propriedade (Admin > Configurações da propriedade > Fuso horário de relatórios).
Confirme esse fuso antes de cruzar com timestamps do Grafana.
"""

import os
import json
import argparse
import datetime
import time

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

MAX_RETRIES = 3

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

FUNNEL_EVENTS = ["search", "select_item", "add_to_cart", "begin_checkout", "purchase"]


def get_credentials():
    creds_info = json.loads(os.environ["GA4_CREDENTIALS_JSON"])
    return service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)


def get_service(creds):
    return build("analyticsdata", "v1beta", credentials=creds)


def safe_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def safe_float(v, decimals=4):
    try:
        return round(float(v), decimals)
    except (TypeError, ValueError):
        return 0.0


def run_report(service, property_id, start_date, end_date, dimensions, metrics, limit=100000, dimension_filter=None):
    body = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": d} for d in dimensions],
        "metrics": [{"name": m} for m in metrics],
        "limit": limit,
    }
    if dimension_filter:
        body["dimensionFilter"] = dimension_filter
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = (
                service.properties()
                .runReport(property=f"properties/{property_id}", body=body)
                .execute()
            )
            return resp.get("rows", [])
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                print(f"  API error {e.resp.status} — aguardando {wait}s (tentativa {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
            else:
                raise
    return []


def format_hora(date_hour_str):
    """Converte 'AAAAMMDDHH' -> 'AAAA-MM-DDTHH:00'."""
    dt = datetime.datetime.strptime(date_hour_str, "%Y%m%d%H")
    return dt.strftime("%Y-%m-%dT%H:00")


def is_valid_date_hour(date_hour_str):
    """
    O GA4 pode devolver um bucket agregado '(other)' quando a combinação de
    dimensões tem cardinalidade muito alta (ex.: dateHour x eventName com
    muitos tipos de evento). Essa linha não é uma data/hora real e deve ser
    descartada, senão quebra o parse.
    """
    return bool(date_hour_str) and len(date_hour_str) == 10 and date_hour_str.isdigit()


def collect_hourly(service, property_id, start_date, end_date):
    """Retorna dict {dateHour_str: {...metricas...}} já mesclado."""
    data = {}

    def ensure(dh):
        if dh not in data:
            data[dh] = {"hora": format_hora(dh)}
        return data[dh]

    # ── Relatório 1: métricas gerais por hora ────────────────────────────
    rows = run_report(
        service, property_id, start_date, end_date, ["dateHour"],
        ["sessions", "transactions", "bounceRate", "averageSessionDuration"],
    )
    for row in rows:
        dh = row["dimensionValues"][0]["value"]
        if not is_valid_date_hour(dh):
            continue
        v = row["metricValues"]
        rec = ensure(dh)
        sessoes = safe_int(v[0]["value"])
        compras = safe_int(v[1]["value"])
        rec["sessoes"] = sessoes
        rec["compras"] = compras
        rec["taxa_conversao_pct"] = round(compras / sessoes * 100, 4) if sessoes else 0.0
        rec["taxa_rejeicao_pct"] = round(safe_float(v[2]["value"]) * 100, 2)
        rec["duracao_media_seg"] = safe_float(v[3]["value"], 2)

    # ── Relatório 2: por dispositivo ──────────────────────────────────────
    rows = run_report(
        service, property_id, start_date, end_date, ["dateHour", "deviceCategory"],
        ["sessions", "transactions", "bounceRate", "averageSessionDuration"],
    )
    for row in rows:
        dh = row["dimensionValues"][0]["value"]
        dev = row["dimensionValues"][1]["value"].lower()
        if not is_valid_date_hour(dh) or dev not in ("mobile", "desktop", "tablet"):
            continue
        v = row["metricValues"]
        rec = ensure(dh)
        rec[f"sessoes_{dev}"] = safe_int(v[0]["value"])
        rec[f"compras_{dev}"] = safe_int(v[1]["value"])
        rec[f"taxa_rejeicao_{dev}"] = round(safe_float(v[2]["value"]) * 100, 2)
        rec[f"duracao_media_{dev}"] = safe_float(v[3]["value"], 2)

    # ── Relatório 3: funil por hora (eventos-chave) ────────────────────────
    # Filtra eventName já na query (inListFilter) — sem isso, a combinação
    # dateHour x eventName inclui TODOS os eventos do site/app e o GA4 pode
    # agregar o excesso num bucket "(other)" que não é uma hora válida.
    funil_filter = {
        "filter": {
            "fieldName": "eventName",
            "inListFilter": {"values": FUNNEL_EVENTS},
        }
    }
    rows = run_report(
        service, property_id, start_date, end_date, ["dateHour", "eventName"],
        ["eventCount"],
        dimension_filter=funil_filter,
    )
    for row in rows:
        dh = row["dimensionValues"][0]["value"]
        event = row["dimensionValues"][1]["value"]
        if is_valid_date_hour(dh) and event in FUNNEL_EVENTS:
            rec = ensure(dh)
            rec[f"funil_{event}"] = safe_int(row["metricValues"][0]["value"])

    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--property-id", required=True, help="GA4 property ID (site: 326912205 / app: 256859064)")
    parser.add_argument("--start", required=True, help="AAAA-MM-DD")
    parser.add_argument("--end", required=True, help="AAAA-MM-DD")
    parser.add_argument("--output", required=True, help="Caminho do ndjson de saída")
    args = parser.parse_args()

    creds = get_credentials()
    service = get_service(creds)

    print(f"Property {args.property_id}: buscando dados por hora de {args.start} a {args.end}...")
    data = collect_hourly(service, args.property_id, args.start, args.end)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for dh in sorted(data.keys()):
            f.write(json.dumps(data[dh], ensure_ascii=False, separators=(",", ":")) + "\n")

    print(f"OK — {len(data)} horas gravadas em {args.output}")


if __name__ == "__main__":
    main()
