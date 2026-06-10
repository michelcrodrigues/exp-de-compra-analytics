"""
export_data_app.py — Lê data/history_app.ndjson e gera data_app.json para o dashboard.

Análogo ao export_data.py do site. Preserva insights_app, experimentos_app
e resumo_mensal_app se já existirem no data_app.json.

Não depende de nenhuma API externa — lê apenas o arquivo local.
"""

import os
import json
import sys
import datetime

HISTORY_FILE = "data/history_app.ndjson"
OUTPUT_PATH  = "data_app.json"


def load_history():
    """
    Lê o history_app.ndjson e retorna lista de registros, um por data, ordenados.
    Último registro por data vence (mesmo padrão do export_data.py do site).
    """
    if not os.path.exists(HISTORY_FILE):
        print(f"ERRO: {HISTORY_FILE} não encontrado.")
        sys.exit(1)

    records_by_date = {}
    errors      = 0
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
                    records_by_date[date] = record
            except json.JSONDecodeError as e:
                print(f"  AVISO: linha {i} inválida ignorada — {e}")
                errors += 1

    if errors:
        print(f"  {errors} linha(s) corrompida(s) ignorada(s).")

    duplicates = total_lines - len(records_by_date) - errors
    if duplicates > 0:
        print(f"  {duplicates} registro(s) duplicado(s) descartado(s) (mantido o mais recente por data).")

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
    Converte registros brutos para o formato esperado pelo dashboard.
    Schema idêntico ao do site — paridade total de colunas.
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
            # Dispositivo (android=mobile, ios=desktop, outros=tablet)
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
            # Rotas — vazias no app
            "top_origem_1":          r.get("top_origem_1") or "",
            "top_origem_1_sessoes":  safe_int(r.get("top_origem_1_sessoes")),
            "top_origem_2":          r.get("top_origem_2") or "",
            "top_origem_2_sessoes":  safe_int(r.get("top_origem_2_sessoes")),
            "top_origem_3":          r.get("top_origem_3") or "",
            "top_origem_3_sessoes":  safe_int(r.get("top_origem_3_sessoes")),
            "top_origem_4":          r.get("top_origem_4") or "",
            "top_origem_4_sessoes":  safe_int(r.get("top_origem_4_sessoes")),
            "top_origem_5":          r.get("top_origem_5") or "",
            "top_origem_5_sessoes":  safe_int(r.get("top_origem_5_sessoes")),
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
        }
        daily.append(entry)
    return daily


def load_existing_data():
    """Preserva insights_app, experimentos_app e resumo_mensal_app do data_app.json anterior."""
    if not os.path.exists(OUTPUT_PATH):
        return [], [], []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        insights      = existing.get("insights", [])
        experimentos  = existing.get("experimentos", [])
        resumo_mensal = existing.get("resumo_mensal", [])
        if insights:
            print(f"  Preservando {len(insights)} insight(s) existentes.")
        if experimentos:
            print(f"  Preservando {len(experimentos)} experimento(s) existentes.")
        if resumo_mensal:
            print(f"  Preservando {len(resumo_mensal)} entrada(s) de resumo_mensal.")
        return insights, experimentos, resumo_mensal
    except Exception:
        return [], [], []


def main():
    print(f"Lendo {HISTORY_FILE}...")
    records = load_history()
    print(f"  {len(records)} datas únicas carregadas.")

    existing_insights, existing_experimentos, existing_resumo_mensal = load_existing_data()

    print("Gerando data_app.json...")
    daily = build_daily(records)

    data = {
        "gerado_em":    datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_dias":   len(daily),
        "daily":        daily,
        "insights":     existing_insights,
        "experimentos": existing_experimentos,
        "resumo_mensal": existing_resumo_mensal,
    }

    try:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"ERRO: falha ao serializar data_app.json — {e}")
        sys.exit(1)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(payload)

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"  data_app.json gerado: {size_kb:.1f} KB, {data['total_dias']} dias.")
    print("Concluído.")


if __name__ == "__main__":
    main()
