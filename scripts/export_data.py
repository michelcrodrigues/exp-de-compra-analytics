"""
export_data.py — Lê data/history.ndjson e gera data.json para o dashboard.

Roda no GitHub Actions após o fetch_ga4.py, ou pode rodar separado.
O data.json é commitado no repositório e servido pelo GitHub Pages.

Não depende de nenhuma API externa — lê apenas o arquivo local.

Deduplicação: como o fetch_ga4.py re-coleta os últimos 3 dias a cada execução
(para corrigir late-arriving data do GA4), o ndjson pode ter múltiplas linhas
para a mesma data. Este script mantém sempre o ÚLTIMO registro por data
(o mais recente, appended ao final do arquivo).
"""

import os
import json
import sys
import datetime

HISTORY_FILE = "data/history.ndjson"
OUTPUT_PATH  = "data.json"

def load_history():
    """
    Lê o history.ndjson e retorna lista de registros, um por data, ordenados.
    Se a mesma data aparecer mais de uma vez, mantém o ÚLTIMO registro
    (o fetch_ga4.py appenda novas coletas ao final — logo o último é o mais fresco).
    """
    if not os.path.exists(HISTORY_FILE):
        print(f"ERRO: {HISTORY_FILE} não encontrado.")
        sys.exit(1)

    # Dict data → record: sobrescreve ao iterar, então o último vence
    records_by_date = {}
    errors  = 0
    total_lines = 0

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            try:
                record = json.loads(line)
                date = record.get("data", "")
                if date:
                    records_by_date[date] = record  # último por data vence
            except json.JSONDecodeError as e:
                print(f"  AVISO: linha {i} inválida ignorada — {e}")
                errors += 1

    if errors:
        print(f"  {errors} linha(s) corrompida(s) ignorada(s).")

    duplicates = total_lines - len(records_by_date) - errors
    if duplicates > 0:
        print(f"  {duplicates} registro(s) duplicado(s) descartado(s) (mantido o mais recente por data).")

    # Ordenar por data crescente
    records = sorted(records_by_date.values(), key=lambda r: r.get("data", ""))
    return records

def safe_float(v, default=0.0):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return default

def safe_int(v, default=0):
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return default

def build_daily(records):
    """
    Converte registros brutos do ndjson para o formato esperado pelo dashboard.
    Como os dados já vêm tipados do fetch_ga4.py, a conversão é principalmente
    uma garantia de tipos — não há risco de formatação regional.
    """
    daily = []
    for r in records:
        entry = {
            "data":               r.get("data", ""),
            # Volume
            "sessoes":            safe_int(r.get("sessoes")),
            "usuarios":           safe_int(r.get("usuarios")),
            "novos_usuarios":     safe_int(r.get("novos_usuarios")),
            "pageviews":          safe_int(r.get("pageviews")),
            # Conversão
            "compras":            safe_int(r.get("compras")),
            "taxa_conversao_pct": safe_float(r.get("taxa_conversao_pct")),
            # Engajamento
            "taxa_rejeicao_pct":  safe_float(r.get("taxa_rejeicao_pct")),
            "duracao_media_seg":  safe_float(r.get("duracao_media_seg")),
            # Dispositivo
            "sessoes_mobile":          safe_int(r.get("sessoes_mobile")),
            "sessoes_desktop":         safe_int(r.get("sessoes_desktop")),
            "sessoes_tablet":          safe_int(r.get("sessoes_tablet")),
            "compras_mobile":          safe_int(r.get("compras_mobile")),
            "compras_desktop":         safe_int(r.get("compras_desktop")),
            "compras_tablet":          safe_int(r.get("compras_tablet")),
            "usuarios_mobile":         safe_int(r.get("usuarios_mobile")),
            "usuarios_desktop":        safe_int(r.get("usuarios_desktop")),
            "usuarios_tablet":         safe_int(r.get("usuarios_tablet")),
            "novos_usuarios_mobile":   safe_int(r.get("novos_usuarios_mobile")),
            "novos_usuarios_desktop":  safe_int(r.get("novos_usuarios_desktop")),
            "novos_usuarios_tablet":   safe_int(r.get("novos_usuarios_tablet")),
            "taxa_rejeicao_mobile":    safe_float(r.get("taxa_rejeicao_mobile")),
            "taxa_rejeicao_desktop":   safe_float(r.get("taxa_rejeicao_desktop")),
            "taxa_rejeicao_tablet":    safe_float(r.get("taxa_rejeicao_tablet")),
            "duracao_media_mobile":    safe_float(r.get("duracao_media_mobile")),
            "duracao_media_desktop":   safe_float(r.get("duracao_media_desktop")),
            "duracao_media_tablet":    safe_float(r.get("duracao_media_tablet")),
            # Canal
            "sessoes_organico":      safe_int(r.get("sessoes_organico")),
            "sessoes_direto":        safe_int(r.get("sessoes_direto")),
            "sessoes_pago":          safe_int(r.get("sessoes_pago")),
            "sessoes_social":        safe_int(r.get("sessoes_social")),
            "sessoes_email":         safe_int(r.get("sessoes_email")),
            "sessoes_referral":      safe_int(r.get("sessoes_referral")),
            "sessoes_outros_canais": safe_int(r.get("sessoes_outros_canais")),
            # Funil total
            "funil_search":         safe_int(r.get("funil_search")),
            "funil_select_item":    safe_int(r.get("funil_select_item")),
            "funil_add_to_cart":    safe_int(r.get("funil_add_to_cart")),
            "funil_begin_checkout": safe_int(r.get("funil_begin_checkout")),
            "funil_purchase":       safe_int(r.get("funil_purchase")),
            # Funil por dispositivo
            **{
                f"funil_{e}_{dev}": safe_int(r.get(f"funil_{e}_{dev}"))
                for e in ["search", "select_item", "add_to_cart", "begin_checkout", "purchase"]
                for dev in ["mobile", "desktop", "tablet"]
            },
            # Rotas
            "top_origem_1":         r.get("top_origem_1") or "",
            "top_origem_1_sessoes": safe_int(r.get("top_origem_1_sessoes")),
            "top_origem_2":         r.get("top_origem_2") or "",
            "top_origem_2_sessoes": safe_int(r.get("top_origem_2_sessoes")),
            "top_origem_3":         r.get("top_origem_3") or "",
            "top_origem_3_sessoes": safe_int(r.get("top_origem_3_sessoes")),
            "top_origem_4":         r.get("top_origem_4") or "",
            "top_origem_4_sessoes": safe_int(r.get("top_origem_4_sessoes")),
            "top_origem_5":         r.get("top_origem_5") or "",
            "top_origem_5_sessoes": safe_int(r.get("top_origem_5_sessoes")),
            "top_destino_1":         r.get("top_destino_1") or "",
            "top_destino_1_sessoes": safe_int(r.get("top_destino_1_sessoes")),
            "top_destino_2":         r.get("top_destino_2") or "",
            "top_destino_2_sessoes": safe_int(r.get("top_destino_2_sessoes")),
            "top_destino_3":         r.get("top_destino_3") or "",
            "top_destino_3_sessoes": safe_int(r.get("top_destino_3_sessoes")),
            "top_destino_4":         r.get("top_destino_4") or "",
            "top_destino_4_sessoes": safe_int(r.get("top_destino_4_sessoes")),
            "top_destino_5":         r.get("top_destino_5") or "",
            "top_destino_5_sessoes": safe_int(r.get("top_destino_5_sessoes")),
            # NPS — total (default 0 para registros históricos sem NPS)
            "nps_respostas":          safe_int(r.get("nps_respostas")),
            "nps_promotores":         safe_int(r.get("nps_promotores")),
            "nps_neutros":            safe_int(r.get("nps_neutros")),
            "nps_detratores":         safe_int(r.get("nps_detratores")),
            "nps_score":              safe_float(r.get("nps_score")),
            "nps_nota_media":         safe_float(r.get("nps_nota_media")),
            # NPS mobile
            "nps_respostas_mobile":   safe_int(r.get("nps_respostas_mobile")),
            "nps_promotores_mobile":  safe_int(r.get("nps_promotores_mobile")),
            "nps_neutros_mobile":     safe_int(r.get("nps_neutros_mobile")),
            "nps_detratores_mobile":  safe_int(r.get("nps_detratores_mobile")),
            "nps_score_mobile":       safe_float(r.get("nps_score_mobile")),
            "nps_nota_media_mobile":  safe_float(r.get("nps_nota_media_mobile")),
            # NPS desktop
            "nps_respostas_desktop":  safe_int(r.get("nps_respostas_desktop")),
            "nps_promotores_desktop": safe_int(r.get("nps_promotores_desktop")),
            "nps_neutros_desktop":    safe_int(r.get("nps_neutros_desktop")),
            "nps_detratores_desktop": safe_int(r.get("nps_detratores_desktop")),
            "nps_score_desktop":      safe_float(r.get("nps_score_desktop")),
            "nps_nota_media_desktop": safe_float(r.get("nps_nota_media_desktop")),
        }
        daily.append(entry)
    return daily

def load_existing_insights():
    """Lê os insights já gravados no data.json para não apagá-los."""
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        insights = existing.get("insights", [])
        if insights:
            print(f"  Preservando {len(insights)} insight(s) existentes.")
        return insights
    except Exception:
        return []

def load_existing_loop_data():
    """Lê experimentos e resumo_mensal já gravados no data.json para não apagá-los."""
    if not os.path.exists(OUTPUT_PATH):
        return [], []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        experimentos = existing.get("experimentos", [])
        resumo_mensal = existing.get("resumo_mensal", [])
        if experimentos:
            print(f"  Preservando {len(experimentos)} experimento(s) existentes.")
        if resumo_mensal:
            print(f"  Preservando {len(resumo_mensal)} entrada(s) de resumo_mensal.")
        return experimentos, resumo_mensal
    except Exception:
        return [], []

def load_nps_comentarios():
    """Lê data/nps_comentarios.json gerado pelo fetch_ga4.py. Retorna lista ou []."""
    path = "data/nps_comentarios.json"
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        comentarios = obj.get("comentarios", [])
        if comentarios:
            print(f"  Incluindo {len(comentarios)} comentário(s) NPS de {path}.")
        return comentarios
    except Exception:
        return []

def main():
    print(f"Lendo {HISTORY_FILE}...")
    records = load_history()
    print(f"  {len(records)} datas únicas carregadas.")

    existing_insights = load_existing_insights()
    existing_experimentos, existing_resumo_mensal = load_existing_loop_data()
    nps_comentarios = load_nps_comentarios()

    print("Gerando data.json...")
    daily = build_daily(records)

    data = {
        "gerado_em":    datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_dias":   len(daily),
        "daily":        daily,
        "insights":     existing_insights,
        "experimentos": existing_experimentos,
        "resumo_mensal": existing_resumo_mensal,
        "nps_top_comentarios": nps_co
