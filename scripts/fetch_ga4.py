"""
Script de coleta de dados do Google Analytics 4.
Gera o arquivo data.json com todas as métricas do dashboard.
"""

import json
import os
from datetime import datetime, timedelta
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Metric,
    Dimension,
    OrderBy,
    Filter,
    FilterExpression,
)

PROPERTY_ID = os.environ["GA4_PROPERTY_ID"]

client = BetaAnalyticsDataClient()

# ── Período: últimos 30 dias ────────────────────────────────────────────────
DATE_RANGE = DateRange(start_date="30daysAgo", end_date="today")
DATE_RANGE_7D = DateRange(start_date="7daysAgo", end_date="today")

def run_report(dimensions, metrics, date_range=None, order_bys=None, limit=10):
    """Helper para executar um relatório no GA4."""
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[date_range or DATE_RANGE],
        order_bys=order_bys or [],
        limit=limit,
    )
    return client.run_report(request)


def run_report_no_dim(metrics, date_range=None):
    """Helper para relatórios sem dimensão (totais)."""
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[date_range or DATE_RANGE],
    )
    return client.run_report(request)


def parse_rows(response, dim_count):
    """Converte linhas do response em lista de dicts."""
    rows = []
    for row in response.rows:
        item = {}
        for i, dim in enumerate(row.dimension_values):
            item[f"dim_{i}"] = dim.value
        for i, met in enumerate(row.metric_values):
            item[f"met_{i}"] = met.value
        rows.append(item)
    return rows


# ── 1. Totais gerais ────────────────────────────────────────────────────────
print("Buscando totais gerais...")
totals_resp = run_report_no_dim(
    ["sessions", "totalUsers", "newUsers", "bounceRate",
     "averageSessionDuration", "conversions", "screenPageViews"]
)
row = totals_resp.rows[0].metric_values
totals = {
    "sessions":               int(row[0].value),
    "total_users":            int(row[1].value),
    "new_users":              int(row[2].value),
    "bounce_rate":            round(float(row[3].value) * 100, 2),
    "avg_session_duration":   round(float(row[4].value), 1),
    "conversions":            int(row[5].value),
    "pageviews":              int(row[6].value),
}

# Totais da semana anterior para calcular variação
totals_7d_resp = run_report_no_dim(
    ["sessions", "totalUsers", "conversions"],
    date_range=DATE_RANGE_7D
)
row7 = totals_7d_resp.rows[0].metric_values
totals["sessions_7d"]     = int(row7[0].value)
totals["users_7d"]        = int(row7[1].value)
totals["conversions_7d"]  = int(row7[2].value)


# ── 2. Sessões por dia (últimos 30 dias) ────────────────────────────────────
print("Buscando sessões por dia...")
daily_resp = run_report(
    dimensions=["date"],
    metrics=["sessions", "totalUsers", "conversions"],
    order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
    limit=30,
)
daily = []
for row in daily_resp.rows:
    raw = row.dimension_values[0].value  # "20240115"
    date_fmt = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    daily.append({
        "date":        date_fmt,
        "sessions":    int(row.metric_values[0].value),
        "users":       int(row.metric_values[1].value),
        "conversions": int(row.metric_values[2].value),
    })


# ── 3. Páginas mais acessadas ───────────────────────────────────────────────
print("Buscando páginas mais acessadas...")
pages_resp = run_report(
    dimensions=["pagePath", "pageTitle"],
    metrics=["screenPageViews", "totalUsers", "averageSessionDuration", "bounceRate"],
    order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
    limit=10,
)
pages = []
for row in pages_resp.rows:
    pages.append({
        "path":         row.dimension_values[0].value,
        "title":        row.dimension_values[1].value,
        "pageviews":    int(row.metric_values[0].value),
        "users":        int(row.metric_values[1].value),
        "avg_duration": round(float(row.metric_values[2].value), 1),
        "bounce_rate":  round(float(row.metric_values[3].value) * 100, 2),
    })


# ── 4. Por origem/mídia ────────────────────────────────────────────────────
print("Buscando dados por origem...")
source_resp = run_report(
    dimensions=["sessionSource", "sessionMedium"],
    metrics=["sessions", "totalUsers", "conversions", "bounceRate", "averageSessionDuration"],
    order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
    limit=15,
)
sources = []
for row in source_resp.rows:
    sources.append({
        "source":       row.dimension_values[0].value,
        "medium":       row.dimension_values[1].value,
        "sessions":     int(row.metric_values[0].value),
        "users":        int(row.metric_values[1].value),
        "conversions":  int(row.metric_values[2].value),
        "bounce_rate":  round(float(row.metric_values[3].value) * 100, 2),
        "avg_duration": round(float(row.metric_values[4].value), 1),
    })


# ── 5. Por canal agrupado ──────────────────────────────────────────────────
print("Buscando dados por canal...")
channel_resp = run_report(
    dimensions=["sessionDefaultChannelGroup"],
    metrics=["sessions", "totalUsers", "conversions"],
    order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
    limit=10,
)
channels = []
for row in channel_resp.rows:
    channels.append({
        "channel":     row.dimension_values[0].value,
        "sessions":    int(row.metric_values[0].value),
        "users":       int(row.metric_values[1].value),
        "conversions": int(row.metric_values[2].value),
    })


# ── 6. Funil de abandono (por etapa de página) ─────────────────────────────
# Reconstrói o funil a partir de pageviews das etapas principais.
# Ajuste os paths abaixo para os caminhos reais do seu funil.
print("Buscando dados de funil...")

FUNNEL_STEPS = [
    {"name": "Página Inicial",  "path": "/"},
    {"name": "Produto / Lista", "path": "/produtos"},
    {"name": "Carrinho",        "path": "/carrinho"},
    {"name": "Checkout",        "path": "/checkout"},
    {"name": "Confirmação",     "path": "/obrigado"},
]

funnel = []
for step in FUNNEL_STEPS:
    req = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name="pagePath")],
        metrics=[Metric(name="screenPageViews"), Metric(name="totalUsers")],
        date_ranges=[DATE_RANGE],
        dimension_filter=FilterExpression(
            filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(
                    value=step["path"],
                    match_type=Filter.StringFilter.MatchType.BEGINS_WITH,
                ),
            )
        ),
    )
    resp = client.run_report(req)
    views = int(resp.rows[0].metric_values[0].value) if resp.rows else 0
    users = int(resp.rows[0].metric_values[1].value) if resp.rows else 0
    funnel.append({"step": step["name"], "path": step["path"], "pageviews": views, "users": users})

# Calcula taxa de abandono entre etapas
for i in range(1, len(funnel)):
    prev = funnel[i - 1]["users"]
    curr = funnel[i]["users"]
    drop = round((1 - curr / prev) * 100, 1) if prev > 0 else 0
    funnel[i]["drop_rate"] = drop
funnel[0]["drop_rate"] = 0


# ── 7. Por dispositivo ─────────────────────────────────────────────────────
print("Buscando dados por dispositivo...")
device_resp = run_report(
    dimensions=["deviceCategory"],
    metrics=["sessions", "totalUsers", "conversions"],
    order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
    limit=5,
)
devices = []
for row in device_resp.rows:
    devices.append({
        "device":      row.dimension_values[0].value,
        "sessions":    int(row.metric_values[0].value),
        "users":       int(row.metric_values[1].value),
        "conversions": int(row.metric_values[2].value),
    })


# ── Monta e salva o JSON final ─────────────────────────────────────────────
data = {
    "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "period":     "últimos 30 dias",
    "totals":     totals,
    "daily":      daily,
    "pages":      pages,
    "sources":    sources,
    "channels":   channels,
    "funnel":     funnel,
    "devices":    devices,
    "insights":   []   # Preenchido manualmente via Claude.ai
}

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ data.json gerado com sucesso — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
