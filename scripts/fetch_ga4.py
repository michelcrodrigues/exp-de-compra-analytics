"""
Script de coleta de dados do Google Analytics 4 — v5
Gera o arquivo data.json com todas as métricas do dashboard.

Novidades v5 (vs v4):
- channels_daily garante bounceRate e averageSessionDuration por canal por dia
- devices_daily garante bounceRate e averageSessionDuration por dispositivo por dia
  (já estava no v4, mas confirmado explicitamente)
- Sem mudança estrutural no JSON — apenas garante que os campos existem
"""

import json
import os
from datetime import datetime, timedelta
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest, DateRange, Metric, Dimension, OrderBy,
    Filter, FilterExpression,
)

PROPERTY_ID    = os.environ["GA4_PROPERTY_ID"]
client         = BetaAnalyticsDataClient()
DATE_RANGE     = DateRange(start_date="90daysAgo", end_date="today")
DATE_RANGE_7D  = DateRange(start_date="7daysAgo",  end_date="today")
DATE_RANGE_30D = DateRange(start_date="30daysAgo", end_date="today")

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

def report_filtered(dimensions, metrics, filter_field, filter_value, date_range=None, limit=50):
    req = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[date_range or DATE_RANGE],
        dimension_filter=FilterExpression(
            filter=Filter(
                field_name=filter_field,
                string_filter=Filter.StringFilter(
                    value=filter_value,
                    match_type=Filter.StringFilter.MatchType.EXACT
                )
            )
        ),
        limit=limit,
    )
    return client.run_report(req)

def fmt_date(raw): return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
def dim(row, i):   return row.dimension_values[i].value
def met(row, i):   return row.metric_values[i].value
def intf(v):       return int(float(v))
def rnd(v):        return round(float(v), 2)

# ── 1. Totais ────────────────────────────────────────────────────────────────
print("1/14 Totais gerais...")
r = report_nodim(["sessions","totalUsers","newUsers","bounceRate",
                  "averageSessionDuration","ecommercePurchases","screenPageViews"])
mv = r.rows[0].metric_values
totals = {
    "sessions":             intf(mv[0].value),
    "total_users":          intf(mv[1].value),
    "new_users":            intf(mv[2].value),
    "bounce_rate":          round(float(mv[3].value)*100, 2),
    "avg_session_duration": rnd(mv[4].value),
    "conversions":          intf(mv[5].value),
    "pageviews":            intf(mv[6].value),
}
r7 = report_nodim(["sessions","totalUsers","ecommercePurchases","newUsers"], DATE_RANGE_7D)
mv7 = r7.rows[0].metric_values
totals.update({
    "sessions_7d":    intf(mv7[0].value),
    "users_7d":       intf(mv7[1].value),
    "conversions_7d": intf(mv7[2].value),
    "new_users_7d":   intf(mv7[3].value),
})

# ── 2. Sessões por dia ───────────────────────────────────────────────────────
print("2/14 Sessões por dia...")
r = report(["date"], ["sessions","totalUsers","ecommercePurchases","newUsers"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))], limit=91)
daily = []
for row in r.rows:
    daily.append({
        "date":        fmt_date(dim(row,0)),
        "sessions":    intf(met(row,0)),
        "users":       intf(met(row,1)),
        "conversions": intf(met(row,2)),
        "new_users":   intf(met(row,3)),
    })

# ── 3. Páginas mais acessadas ────────────────────────────────────────────────
print("3/14 Páginas...")
r = report(["pagePath","pageTitle"],
           ["screenPageViews","totalUsers","averageSessionDuration"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)], limit=10)
pages = [{"path": dim(row,0), "title": dim(row,1),
          "pageviews": intf(met(row,0)), "users": intf(met(row,1)),
          "avg_duration": rnd(met(row,2)), "bounce_rate": 0, "exits": 0} for row in r.rows]

# ── 4. Páginas de entrada ────────────────────────────────────────────────────
print("4/14 Páginas de entrada...")
r = report(["landingPagePlusQueryString"],
           ["sessions","totalUsers","ecommercePurchases","bounceRate"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)], limit=10)
landing_pages = [{"path": dim(row,0), "sessions": intf(met(row,0)),
                  "users": intf(met(row,1)), "conversions": intf(met(row,2)),
                  "bounce_rate": round(float(met(row,3))*100, 2)} for row in r.rows]

# ── 5. Páginas top 10 com breakdown semanal ───────────────────────────────────
print("5/14 Páginas por semana...")
top_paths = [p["path"] for p in pages[:10]]

r = report(["yearWeek","pagePath"],
           ["screenPageViews","totalUsers"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="yearWeek"))],
           limit=1000)

pages_weekly_raw = {}
for row in r.rows:
    week = dim(row,0)
    path = dim(row,1)
    if path not in top_paths:
        continue
    if week not in pages_weekly_raw:
        pages_weekly_raw[week] = {}
    pages_weekly_raw[week][path] = {
        "pageviews": intf(met(row,0)),
        "users":     intf(met(row,1)),
    }

pages_weekly = {
    "weeks":  sorted(pages_weekly_raw.keys()),
    "paths":  top_paths,
    "data":   pages_weekly_raw,
}

# ── 6. Origens ───────────────────────────────────────────────────────────────
print("6/14 Origens...")
r = report(["sessionSource","sessionMedium"],
           ["sessions","totalUsers","ecommercePurchases","bounceRate","averageSessionDuration"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)], limit=50)
sources_all = [{"source": dim(row,0), "medium": dim(row,1),
            "source_medium": f"{dim(row,0)} / {dim(row,1)}",
            "sessions":        intf(met(row,0)),
            "users":           intf(met(row,1)),
            "conversions":     intf(met(row,2)),
            "conversion_rate": round(intf(met(row,2))/max(intf(met(row,0)),1)*100, 2),
            "bounce_rate":     round(float(met(row,3))*100, 2),
            "avg_duration":    rnd(met(row,4))} for row in r.rows]

TOP5_SOURCES = [r["source_medium"] for r in sources_all[:5]]
others = [r for r in sources_all[5:]]
others_agg = None
if others:
    others_sess  = sum(r["sessions"]    for r in others)
    others_users = sum(r["users"]       for r in others)
    others_conv  = sum(r["conversions"] for r in others)
    others_agg = {
        "source": "outros", "medium": "—",
        "source_medium": "outros / —",
        "sessions":        others_sess,
        "users":           others_users,
        "conversions":     others_conv,
        "conversion_rate": round(others_conv/max(others_sess,1)*100, 2),
        "bounce_rate":     round(sum(r["bounce_rate"]*r["sessions"] for r in others)/max(others_sess,1), 2),
        "avg_duration":    round(sum(r["avg_duration"]*r["sessions"] for r in others)/max(others_sess,1), 2),
    }
sources = sources_all[:5] + ([others_agg] if others_agg else [])

# ── 7. Canais com breakdown diário ───────────────────────────────────────────
# v5: garante bounce_rate e avg_duration por canal por dia (essencial para filtros)
print("7/14 Canais por dia...")
r = report(["date","sessionDefaultChannelGroup"],
           ["sessions","totalUsers","ecommercePurchases","bounceRate","averageSessionDuration","newUsers"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
           limit=910)

channels_daily_raw = {}
channels_agg = {}
for row in r.rows:
    date    = fmt_date(dim(row,0))
    channel = dim(row,1)
    sess    = intf(met(row,0))
    users   = intf(met(row,1))
    conv    = intf(met(row,2))
    bounce  = round(float(met(row,3))*100, 2)
    dur     = rnd(met(row,4))
    new_u   = intf(met(row,5))

    if date not in channels_daily_raw:
        channels_daily_raw[date] = {}
    # v5: inclui bounce_rate e avg_duration no breakdown diário
    channels_daily_raw[date][channel] = {
        "sessions":    sess,
        "users":       users,
        "conversions": conv,
        "bounce_rate": bounce,
        "avg_duration": dur,
    }

    if channel not in channels_agg:
        channels_agg[channel] = {"channel":channel,"sessions":0,"users":0,"conversions":0,
                                  "wBounce":0.0,"wDur":0.0,"new_users":0}
    channels_agg[channel]["sessions"]   += sess
    channels_agg[channel]["users"]      += users
    channels_agg[channel]["conversions"]+= conv
    channels_agg[channel]["new_users"]  += new_u
    channels_agg[channel]["wBounce"]    += bounce * sess
    channels_agg[channel]["wDur"]       += dur * sess

channels = []
for ch in channels_agg.values():
    s = max(ch["sessions"], 1)
    channels.append({
        "channel":         ch["channel"],
        "sessions":        ch["sessions"],
        "users":           ch["users"],
        "conversions":     ch["conversions"],
        "new_users":       ch["new_users"],
        "conversion_rate": round(ch["conversions"]/s*100, 2),
        "bounce_rate":     round(ch["wBounce"]/s, 2),
        "avg_duration":    round(ch["wDur"]/s, 2),
    })
channels.sort(key=lambda x: x["sessions"], reverse=True)

channels_daily = {
    "dates":    sorted(channels_daily_raw.keys()),
    "channels": list(channels_agg.keys()),
    "data":     channels_daily_raw,
}

# ── 7b. Source/medium daily breakdown ────────────────────────────────────────
print("7b/14 Origens por dia...")
r = report(["date","sessionSource","sessionMedium"],
           ["sessions","totalUsers","ecommercePurchases","bounceRate","averageSessionDuration"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
           limit=2000)

sources_daily_raw = {}
for row in r.rows:
    date   = fmt_date(dim(row,0))
    sm     = f"{dim(row,1)} / {dim(row,2)}"
    sess   = intf(met(row,0))
    users  = intf(met(row,1))
    conv   = intf(met(row,2))
    bounce = round(float(met(row,3))*100, 2)
    dur    = rnd(met(row,4))
    key    = sm if sm in TOP5_SOURCES else "outros / —"

    if date not in sources_daily_raw:
        sources_daily_raw[date] = {}
    if key not in sources_daily_raw[date]:
        sources_daily_raw[date][key] = {"sessions":0,"users":0,"conversions":0,"wBounce":0.0,"wDur":0.0}
    sources_daily_raw[date][key]["sessions"]   += sess
    sources_daily_raw[date][key]["users"]      += users
    sources_daily_raw[date][key]["conversions"]+= conv
    # v5: acumula bounce e dur ponderados para média ponderada posterior
    sources_daily_raw[date][key]["wBounce"]    += bounce * sess
    sources_daily_raw[date][key]["wDur"]       += dur * sess

sources_daily = {
    "dates":   sorted(sources_daily_raw.keys()),
    "sources": TOP5_SOURCES + ["outros / —"],
    "data":    sources_daily_raw,
}

# ── 7c. Dispositivo × Origem daily breakdown (para filtro combinado real) ─────
# Necessário para calcular conversão real quando ambos os filtros estão ativos.
# 90d × 3 devices × ~6 sources = ~1620 rows — dentro do limit.
print("7c/14 Dispositivo × Origem por dia...")
r = report(["date","deviceCategory","sessionSource","sessionMedium"],
           ["sessions","totalUsers","ecommercePurchases"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
           limit=3000)

device_source_daily_raw = {}  # date -> device -> source_medium -> {sessions, users, conversions}
for row in r.rows:
    date   = fmt_date(dim(row,0))
    device = dim(row,1)
    sm     = f"{dim(row,2)} / {dim(row,3)}"
    sess   = intf(met(row,0))
    users  = intf(met(row,1))
    conv   = intf(met(row,2))
    key    = sm if sm in TOP5_SOURCES else "outros / —"

    if date not in device_source_daily_raw:
        device_source_daily_raw[date] = {}
    if device not in device_source_daily_raw[date]:
        device_source_daily_raw[date][device] = {}
    if key not in device_source_daily_raw[date][device]:
        device_source_daily_raw[date][device][key] = {"sessions":0,"users":0,"conversions":0}
    device_source_daily_raw[date][device][key]["sessions"]   += sess
    device_source_daily_raw[date][device][key]["users"]      += users
    device_source_daily_raw[date][device][key]["conversions"]+= conv

device_source_daily = {
    "dates":   sorted(device_source_daily_raw.keys()),
    "devices": list(devices_agg.keys()) if 'devices_agg' in dir() else [],
    "sources": TOP5_SOURCES + ["outros / —"],
    "data":    device_source_daily_raw,
}

# ── 8. Dispositivos com breakdown diário ──────────────────────────────────────
# v5: bounce_rate e avg_duration já coletados — confirmado explicitamente
print("8/14 Dispositivos por dia...")
r = report(["date","deviceCategory"],
           ["sessions","totalUsers","ecommercePurchases","bounceRate","averageSessionDuration"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
           limit=300)

devices_daily_raw = {}
devices_agg = {}
for row in r.rows:
    date   = fmt_date(dim(row,0))
    device = dim(row,1)
    sess   = intf(met(row,0))
    users  = intf(met(row,1))
    conv   = intf(met(row,2))
    bounce = round(float(met(row,3))*100, 2)
    dur    = rnd(met(row,4))

    if date not in devices_daily_raw:
        devices_daily_raw[date] = {}
    devices_daily_raw[date][device] = {
        "sessions":    sess,
        "users":       users,
        "conversions": conv,
        "bounce_rate": bounce,
        "avg_duration": dur,
    }

    if device not in devices_agg:
        devices_agg[device] = {"device":device,"sessions":0,"users":0,"conversions":0,
                                "wBounce":0.0,"wDur":0.0}
    devices_agg[device]["sessions"]   += sess
    devices_agg[device]["users"]      += users
    devices_agg[device]["conversions"]+= conv
    devices_agg[device]["wBounce"]    += bounce * sess
    devices_agg[device]["wDur"]       += dur * sess

devices = []
for dv in devices_agg.values():
    s = max(dv["sessions"], 1)
    devices.append({
        "device":      dv["device"],
        "sessions":    dv["sessions"],
        "users":       dv["users"],
        "conversions": dv["conversions"],
        "bounce_rate": round(dv["wBounce"]/s, 2),
        "avg_duration": round(dv["wDur"]/s, 2),
    })
devices.sort(key=lambda x: x["sessions"], reverse=True)

devices_daily = {
    "dates":   sorted(devices_daily_raw.keys()),
    "devices": list(devices_agg.keys()),
    "data":    devices_daily_raw,
}

# ── 9. Novos vs Recorrentes com breakdown diário ──────────────────────────────
print("9/14 Novos vs recorrentes por dia...")
r = report(["date","newVsReturning"],
           ["sessions","totalUsers","ecommercePurchases","bounceRate"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
           limit=200)

nvr_daily_raw = {}
nvr_agg = {}
for row in r.rows:
    date  = fmt_date(dim(row,0))
    ntype = dim(row,1)
    sess  = intf(met(row,0))
    users = intf(met(row,1))
    conv  = intf(met(row,2))
    bounce= round(float(met(row,3))*100, 2)

    if date not in nvr_daily_raw:
        nvr_daily_raw[date] = {}
    nvr_daily_raw[date][ntype] = {"sessions":sess,"users":users,"conversions":conv}

    if ntype not in nvr_agg:
        nvr_agg[ntype] = {"type":ntype,"sessions":0,"users":0,"conversions":0,"bounce_rate":bounce}
    nvr_agg[ntype]["sessions"]   += sess
    nvr_agg[ntype]["users"]      += users
    nvr_agg[ntype]["conversions"]+= conv

new_vs_returning = list(nvr_agg.values())
nvr_daily = {
    "dates": sorted(nvr_daily_raw.keys()),
    "types": list(nvr_agg.keys()),
    "data":  nvr_daily_raw,
}

# ── 9b. NVR por dispositivo ───────────────────────────────────────────────────
print("9b/14 Novos vs recorrentes por dispositivo...")
r = report(["date","deviceCategory","newVsReturning"],
           ["sessions","totalUsers"],
           order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
           limit=600)

nvr_device_raw = {}
for row in r.rows:
    date   = fmt_date(dim(row,0))
    device = dim(row,1)
    ntype  = dim(row,2)
    sess   = intf(met(row,0))
    users  = intf(met(row,1))
    if date not in nvr_device_raw:
        nvr_device_raw[date] = {}
    if device not in nvr_device_raw[date]:
        nvr_device_raw[date][device] = {}
    if ntype not in nvr_device_raw[date][device]:
        nvr_device_raw[date][device][ntype] = {"sessions":0,"users":0}
    nvr_device_raw[date][device][ntype]["sessions"] += sess
    nvr_device_raw[date][device][ntype]["users"]    += users

nvr_by_device = {
    "dates":   sorted(nvr_device_raw.keys()),
    "devices": list(devices_agg.keys()),
    "data":    nvr_device_raw,
}

# ── 10. Funil com breakdown por data ──────────────────────────────────────────
print("10/14 Funil de eventos...")
FUNNEL_EVENTS = [
    {"name": "Busca",                 "event": "search"},
    {"name": "Selecionou item",       "event": "select_item"},
    {"name": "Adicionou ao carrinho", "event": "add_to_cart"},
    {"name": "Iniciou checkout",      "event": "begin_checkout"},
    {"name": "Compra",                "event": "purchase"},
]

funnel = []
funnel_daily_raw = {}

for step in FUNNEL_EVENTS:
    print(f"   funil: {step['event']}...")
    req_agg = RunReportRequest(
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
    resp_agg = client.run_report(req_agg)
    count = intf(resp_agg.rows[0].metric_values[0].value) if resp_agg.rows else 0
    users = intf(resp_agg.rows[0].metric_values[1].value) if resp_agg.rows else 0
    funnel.append({"step": step["name"], "event": step["event"],
                   "event_count": count, "users": users, "drop_rate": 0})

    req_daily = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name="date"), Dimension(name="eventName")],
        metrics=[Metric(name="eventCount"), Metric(name="totalUsers")],
        date_ranges=[DATE_RANGE],
        dimension_filter=FilterExpression(
            filter=Filter(field_name="eventName",
                          string_filter=Filter.StringFilter(value=step["event"],
                          match_type=Filter.StringFilter.MatchType.EXACT))
        ),
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
        limit=91,
    )
    resp_daily = client.run_report(req_daily)
    for row in resp_daily.rows:
        date = fmt_date(dim(row,0))
        if date not in funnel_daily_raw:
            funnel_daily_raw[date] = {}
        funnel_daily_raw[date][step["event"]] = {
            "event_count": intf(met(row,0)),
            "users":       intf(met(row,1)),
        }

for i in range(1, len(funnel)):
    prev = funnel[i-1]["users"]
    curr = funnel[i]["users"]
    funnel[i]["drop_rate"] = round((1 - curr/prev)*100, 1) if prev > 0 else 0

funnel_daily = {
    "dates":  sorted(funnel_daily_raw.keys()),
    "events": [s["event"] for s in FUNNEL_EVENTS],
    "data":   funnel_daily_raw,
}

# ── 11. Rotas (30d fixo) ──────────────────────────────────────────────────────
print("11/14 Rotas...")
r = report(["customEvent:originCity","customEvent:destinationCity"],
           ["eventCount","totalUsers"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)], limit=20)
top_routes = []
for row in r.rows:
    o, d = dim(row,0), dim(row,1)
    if o and d and o != "(not set)" and d != "(not set)":
        top_routes.append({"origin":o,"destination":d,"purchases":intf(met(row,0)),"users":intf(met(row,1))})

r = report(["customEvent:originCity"],["eventCount","totalUsers","ecommercePurchases"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)], limit=15)
top_origins = [{"city":dim(row,0),"searches":intf(met(row,0)),"users":intf(met(row,1)),"conversions":intf(met(row,2))}
               for row in r.rows if dim(row,0) != "(not set)"]

r = report(["customEvent:destinationCity"],["eventCount","totalUsers","ecommercePurchases"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)], limit=15)
top_destinations = [{"city":dim(row,0),"searches":intf(met(row,0)),"users":intf(met(row,1)),"conversions":intf(met(row,2))}
                    for row in r.rows if dim(row,0) != "(not set)"]

r = report(["customEvent:originCity","customEvent:destinationCity"],["eventCount","totalUsers"],
           order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalUsers"), desc=True)], limit=15)
route_conversion = []
for row in r.rows:
    o, d = dim(row,0), dim(row,1)
    if o and d and o != "(not set)" and d != "(not set)":
        route_conversion.append({"route":f"{o} → {d}","origin":o,"destination":d,
                                  "searches":intf(met(row,0)),"users":intf(met(row,1))})

routes = {
    "top_routes":       top_routes,
    "top_origins":      top_origins,
    "top_destinations": top_destinations,
    "route_conversion": route_conversion,
}

# ── 12. Saída ─────────────────────────────────────────────────────────────────
print("12/14 Montando JSON...")
data = {
    "updated_at":         datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "period":             "últimos 90 dias",
    "totals":             totals,
    "daily":              daily,
    "pages":              pages,
    "pages_weekly":       pages_weekly,
    "landing_pages":      landing_pages,
    "sources":            sources,
    "sources_daily":      sources_daily,
    "top5_sources":       TOP5_SOURCES,
    "channels":           channels,
    "channels_daily":     channels_daily,
    "devices":            devices,
    "devices_daily":      devices_daily,
    "new_vs_returning":   new_vs_returning,
    "nvr_daily":          nvr_daily,
    "nvr_by_device":      nvr_by_device,
    "funnel":             funnel,
    "funnel_daily":       funnel_daily,
    "device_source_daily": device_source_daily,
    "routes":             routes,
    "insights":           [],
}

print("13/14 Salvando data.json...")
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"14/14 ✅ data.json gerado — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
