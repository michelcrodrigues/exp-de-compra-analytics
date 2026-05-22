"""
Script de coleta de dados do Google Analytics 4 — v2
Gera o arquivo data.json com todas as métricas do dashboard.
"""

import json
import os
from datetime import datetime
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest, DateRange, Metric, Dimension, OrderBy,
    Filter, FilterExpression,
)

PROPERTY_ID   = os.environ["GA4_PROPERTY_ID"]
client        = BetaAnalyticsDataClient()
DATE_RANGE    = DateRange(start_date="30daysAgo", end_date="today")
DATE_RANGE_7D = DateRange(start_date="7daysAgo",  end_date="today")

def report(dimensions, metrics, date_range=None, order_bys=None, limit=20):
    req = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[date_range or DATE_RANGE],
        order_bys=order_bys or [],
        limit=limit,
    )
    return client.run_report(req)

def report_nodim(metrics, date_range=None):
    req = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[date_range or DATE_RANGE],
    )
    return client.run_report(req)

def dim(row, i): return row.dimension_values[i].value
def met(row, i): return row.metric_values[i].value
def intf(v):     return int(float(v))
def rnd(v):      return round(float(v), 2)

# ── 1. Totais ───────────────────────────────────────────────────────────────
print("1/11 Totais gerais...")
r = report_nodim(["sessions","totalUsers","newUsers","bounceRate",
                  "averageSessionDuration","conversions","screenPageViews"])
mv = r.rows[0].metric_values
totals = {
    "sessions": intf(mv[0].value), "total_users": intf(mv[1].value),
    "new_users": intf(mv[2].value), "bounce_rate": round(float(mv[3].value)*100,2),
    "avg_session_duration": rnd(mv[4].value),
    "conversions": intf(mv[5].value), "pageviews": intf(mv[6].value),
}
r7 = report_nodim(["sessions","totalUsers","conversions","newUsers"], DATE_RANGE_7D)
mv7 = r7.rows[0].metric_values
totals.update({
    "sessions_7d": intf(mv7[0].value), "users_7d": intf(mv7[1].value),
    "conversions_7d": intf(mv7[2].value), "new_users_7d": intf(mv7[3].value),
})

# ── 2. Sessões por dia ──────────────────────────────────────────────────────
print("2/11 Sessões por dia...")
r = report(["date"], ["sessions","totalUsers","conversions","newUsers"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))], limit=30)
daily = []
for row in r.rows:
    raw = dim(row,0)
    daily.append({
        "date": f"{raw[:4]}-{raw[4:6]}-{raw[6:]}",
        "sessions": intf(met(row,0)), "users": intf(met(row,1)),
        "conversions": intf(met(row,2)), "new_users": intf(met(row,3)),
    })

# ── 3. Páginas mais acessadas ───────────────────────────────────────────────
print("3/11 Páginas...")
r = report(["pagePath","pageTitle"],
           ["screenPageViews","totalUsers","averageSessionDuration"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)], limit=10)
pages = [{"path": dim(row,0), "title": dim(row,1),
          "pageviews": intf(met(row,0)), "users": intf(met(row,1)),
          "avg_duration": rnd(met(row,2)), "bounce_rate": 0,
          "exits": 0} for row in r.rows]

# ── 4. Páginas de entrada ───────────────────────────────────────────────────
print("4/11 Páginas de entrada...")
r = report(["landingPagePlusQueryString"],
           ["sessions","totalUsers","conversions","bounceRate"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)], limit=10)
landing_pages = [{"path": dim(row,0), "sessions": intf(met(row,0)),
                  "users": intf(met(row,1)), "conversions": intf(met(row,2)),
                  "bounce_rate": round(float(met(row,3))*100,2)} for row in r.rows]

# ── 5. Origens ──────────────────────────────────────────────────────────────
print("5/11 Origens...")
r = report(["sessionSource","sessionMedium"],
           ["sessions","totalUsers","conversions","bounceRate","averageSessionDuration"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)], limit=15)
sources = [{"source": dim(row,0), "medium": dim(row,1),
            "sessions": intf(met(row,0)), "users": intf(met(row,1)),
            "conversions": intf(met(row,2)),
            "conversion_rate": round(intf(met(row,2))/max(intf(met(row,0)),1)*100,2),
            "bounce_rate": round(float(met(row,3))*100,2),
            "avg_duration": rnd(met(row,4))} for row in r.rows]

# ── 6. Canais ───────────────────────────────────────────────────────────────
print("6/11 Canais...")
r = report(["sessionDefaultChannelGroup"],
           ["sessions","totalUsers","conversions","bounceRate","averageSessionDuration","newUsers"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)], limit=10)
channels = [{"channel": dim(row,0), "sessions": intf(met(row,0)),
             "users": intf(met(row,1)), "conversions": intf(met(row,2)),
             "conversion_rate": round(intf(met(row,2))/max(intf(met(row,0)),1)*100,2),
             "bounce_rate": round(float(met(row,3))*100,2),
             "avg_duration": rnd(met(row,4)), "new_users": intf(met(row,5))} for row in r.rows]

# ── 7. Dispositivos ─────────────────────────────────────────────────────────
print("7/11 Dispositivos...")
r = report(["deviceCategory"], ["sessions","totalUsers","conversions","bounceRate"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)])
devices = [{"device": dim(row,0), "sessions": intf(met(row,0)),
            "users": intf(met(row,1)), "conversions": intf(met(row,2)),
            "bounce_rate": round(float(met(row,3))*100,2)} for row in r.rows]

# ── 8. Novos vs recorrentes ─────────────────────────────────────────────────
print("8/11 Novos vs recorrentes...")
r = report(["newVsReturning"], ["sessions","totalUsers","conversions","bounceRate"])
new_vs_returning = [{"type": dim(row,0), "sessions": intf(met(row,0)),
                     "users": intf(met(row,1)), "conversions": intf(met(row,2)),
                     "bounce_rate": round(float(met(row,3))*100,2)} for row in r.rows]

# ── 9. Funil por eventos ────────────────────────────────────────────────────
print("9/11 Funil de eventos...")
FUNNEL_EVENTS = [
    {"name": "Busca",                 "event": "search"},
    {"name": "Selecionou item",       "event": "select_item"},
    {"name": "Adicionou ao carrinho", "event": "add_to_cart"},
    {"name": "Iniciou checkout",      "event": "begin_checkout"},
    {"name": "Compra",                "event": "purchase"},
]
funnel = []
for step in FUNNEL_EVENTS:
    req = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount"), Metric(name="totalUsers")],
        date_ranges=[DATE_RANGE],
        dimension_filter=FilterExpression(
            filter=Filter(field_name="eventName",
                          string_filter=Filter.StringFilter(value=step["event"],
                          match_type=Filter.StringFilter.MatchType.EXACT))
        ),
    )
    resp = client.run_report(req)
    count = intf(resp.rows[0].metric_values[0].value) if resp.rows else 0
    users = intf(resp.rows[0].metric_values[1].value) if resp.rows else 0
    funnel.append({"step": step["name"], "event": step["event"],
                   "event_count": count, "users": users, "drop_rate": 0})

for i in range(1, len(funnel)):
    prev = funnel[i-1]["users"]
    curr = funnel[i]["users"]
    funnel[i]["drop_rate"] = round((1 - curr/prev)*100, 1) if prev > 0 else 0

# ── 10. Rotas ────────────────────────────────────────────────────────────────
print("10/11 Rotas...")

r = report(["customEvent:originCity","customEvent:destinationCity"],
           ["eventCount","totalUsers"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)],
           limit=20)
top_routes = []
for row in r.rows:
    o, d = dim(row,0), dim(row,1)
    if o and d and o != "(not set)" and d != "(not set)":
        top_routes.append({"origin": o, "destination": d,
                           "purchases": intf(met(row,0)), "users": intf(met(row,1))})

r = report(["customEvent:originCity"],
           ["eventCount","totalUsers","conversions"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)],
           limit=15)
top_origins = [{"city": dim(row,0), "searches": intf(met(row,0)),
                "users": intf(met(row,1)), "conversions": intf(met(row,2))}
               for row in r.rows if dim(row,0) != "(not set)"]

r = report(["customEvent:destinationCity"],
           ["eventCount","totalUsers","conversions"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)],
           limit=15)
top_destinations = [{"city": dim(row,0), "searches": intf(met(row,0)),
                     "users": intf(met(row,1)), "conversions": intf(met(row,2))}
                    for row in r.rows if dim(row,0) != "(not set)"]

r = report(["customEvent:originCity","customEvent:destinationCity"],
           ["eventCount","totalUsers"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalUsers"), desc=True)],
           limit=15)
route_conversion = []
for row in r.rows:
    o, d = dim(row,0), dim(row,1)
    if o and d and o != "(not set)" and d != "(not set)":
        route_conversion.append({
            "route": f"{o} → {d}", "origin": o, "destination": d,
            "searches": intf(met(row,0)), "users": intf(met(row,1)),
        })

routes = {
    "top_routes":       top_routes,
    "top_origins":      top_origins,
    "top_destinations": top_destinations,
    "route_conversion": route_conversion,
}

# ── 11. Saída ───────────────────────────────────────────────────────────────
print("11/11 Salvando...")
data = {
    "updated_at":       datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "period":           "últimos 30 dias",
    "totals":           totals,
    "daily":            daily,
    "pages":            pages,
    "landing_pages":    landing_pages,
    "sources":          sources,
    "channels":         channels,
    "devices":          devices,
    "new_vs_returning": new_vs_returning,
    "funnel":           funnel,
    "routes":           routes,
    "insights":         [],
}
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"✅ data.json gerado — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
