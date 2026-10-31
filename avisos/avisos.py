"""Avisos a Telegram aunque la PC esté apagada (corre en GitHub Actions).

  python avisos.py agenda          → agenda del día (sale 1 h antes de la apertura de NY): datos de EE.UU., hora de México
  python avisos.py agenda ya       → la agenda ahorita, sin esperar la hora (para probar)
  python avisos.py recordatorios   → "En N min: CPI…" antes de cada dato de impacto alto (una sola vez)
  PRUEBA=1 python avisos.py …      → imprime en vez de mandar

Variables: TELEGRAM_TOKEN y TELEGRAM_CHAT (secrets del repo); HORARIO="09:30-11:00" en hora de NY (opcional).
Solo usa la biblioteca estándar de Python."""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MX = ZoneInfo("America/Chihuahua")  # misma hora que la Ciudad de México todo el año
NY = ZoneInfo("America/New_York")
ESTADO = Path(__file__).with_name("estado.json")
SEMANA = Path(__file__).with_name("semana.json")
FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
VENTANA_MIN = 20  # el recordatorio sale cuando faltan 20 min o menos (GitHub a veces corre unos minutos tarde)
AGENDA_MIN = (15, 75)  # la agenda sale si faltan entre 15 y 75 min para la apertura de NY (la idea: 1 h antes)
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

NOMBRES = {  # Forex Factory los da en inglés
    "CPI m/m": "Inflación mensual (CPI)",
    "CPI y/y": "Inflación anual (CPI)",
    "Core CPI m/m": "Inflación subyacente mensual (Core CPI)",
    "PPI m/m": "Precios al productor (PPI)",
    "Core PPI m/m": "Precios al productor subyacente (Core PPI)",
    "Non-Farm Employment Change": "Nóminas no agrícolas (NFP)",
    "Unemployment Rate": "Tasa de desempleo",
    "Average Hourly Earnings m/m": "Salarios por hora",
    "Unemployment Claims": "Solicitudes de desempleo",
    "Federal Funds Rate": "Decisión de tasas de la Fed",
    "FOMC Statement": "Comunicado de la Fed",
    "FOMC Press Conference": "Conferencia de prensa de la Fed",
    "FOMC Meeting Minutes": "Minutas de la Fed",
    "Core PCE Price Index m/m": "PCE subyacente mensual",
    "Advance GDP q/q": "PIB preliminar",
    "Prelim GDP q/q": "PIB (segunda estimación)",
    "Final GDP q/q": "PIB (final)",
    "Retail Sales m/m": "Ventas minoristas",
    "Core Retail Sales m/m": "Ventas minoristas subyacentes",
    "ISM Manufacturing PMI": "ISM manufacturero",
    "ISM Services PMI": "ISM de servicios",
    "JOLTS Job Openings": "Vacantes de empleo (JOLTS)",
    "ADP Non-Farm Employment Change": "Empleo privado ADP",
    "Prelim UoM Consumer Sentiment": "Sentimiento del consumidor (U. de Michigan)",
    "CB Consumer Confidence": "Confianza del consumidor (Conference Board)",
}


def nombre(t):
    es = NOMBRES.get(t)
    return f"{es} ({t})" if es else t


def _bajar():
    req = urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0 (avisos de Arnoldo JH)"})
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 429 si se pide seguido: se reintenta
            print(f"calendario: {e}")
            time.sleep(10 * (intento + 1))
    return None


def calendario(fresco=False):
    """Datos de EE.UU. de la semana. Forex Factory bloquea si se le pide seguido: se baja con la agenda
    (una vez al día) y se guarda en el repo; los recordatorios usan esa copia mientras tenga menos de 12 h."""
    guardado = json.loads(SEMANA.read_text(encoding="utf-8")) if SEMANA.exists() else {}
    edad = time.time() - guardado.get("bajado", 0)
    datos = guardado.get("datos") if not fresco and edad < 12 * 3600 else None
    if datos is None:
        datos = _bajar()
        if datos is not None:
            SEMANA.write_text(json.dumps({"bajado": int(time.time()), "datos": datos}, ensure_ascii=False) + "\n",
                              encoding="utf-8")
        else:
            datos = guardado.get("datos", [])  # sin red: lo último que se tenga
    vistos, out = set(), []
    for e in datos:
        clave = (e.get("title"), e.get("country"), e.get("date"))
        if clave in vistos or e.get("country") != "USD":
            continue
        vistos.add(clave)
        try:
            e["hora"] = datetime.fromisoformat(e["date"]).astimezone(MX)
        except (KeyError, ValueError):
            continue
        out.append(e)
    return sorted(out, key=lambda e: e["hora"])


def mandar(texto):
    if os.environ.get("PRUEBA"):
        print("---- (prueba, no se manda) ----\n" + texto)
        return True
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT")
    if not token or not chat:
        sys.exit("Faltan los secrets TELEGRAM_TOKEN y TELEGRAM_CHAT del repo.")
    datos = urllib.parse.urlencode({"chat_id": chat, "text": texto, "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=datos, timeout=20) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"telegram: {e}")
        return False


def detalle(e):
    partes = []
    if e.get("forecast"):
        partes.append(f"prev. {e['forecast']}")
    if e.get("previous"):
        partes.append(f"ant. {e['previous']}")
    return " · ".join(partes)


def horario(hoy):
    """Tu ventana (hora de NY) traducida a hora de México para ese día."""
    ini, fin = os.environ.get("HORARIO", "09:30-11:00").split("-")
    a = datetime.combine(hoy, datetime.strptime(ini, "%H:%M").time(), NY).astimezone(MX)
    b = datetime.combine(hoy, datetime.strptime(fin, "%H:%M").time(), NY).astimezone(MX)
    apertura = datetime.combine(hoy, datetime.strptime("09:30", "%H:%M").time(), NY).astimezone(MX)
    return apertura, a, b


def agenda(ya=False):
    """Hay dos horarios en el workflow (12:30 y 13:30 UTC) porque NY cambia de horario y México no:
    sale el que cae 1 h antes de la apertura (6:30 México en verano de EE.UU., 7:30 en invierno)."""
    ahora = datetime.now(MX)
    hoy = ahora.date()
    apertura, a, b = horario(hoy)
    faltan = (apertura - ahora).total_seconds() / 60
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    clave = f"agenda|{hoy}"
    if not ya and (not AGENDA_MIN[0] <= faltan <= AGENDA_MIN[1] or clave in estado):
        print(f"Agenda: faltan {faltan:.0f} min para la apertura; no toca ahora.")
        return False
    eventos = [e for e in calendario(fresco=True) if e["hora"].date() == hoy]
    altos = [e for e in eventos if e.get("impact") == "High"]
    medios = [e for e in eventos if e.get("impact") == "Medium"]
    lineas = [f"Agenda de hoy · {DIAS[hoy.weekday()]} {hoy:%d/%m}", ""]
    if altos:
        lineas.append("Datos fuertes de EE.UU. (hora de México):")
        lineas += [f"• {e['hora']:%H:%M} · {nombre(e['title'])}" + (f" · {detalle(e)}" if detalle(e) else "") for e in altos]
    else:
        lineas.append("Hoy no hay datos de impacto alto de EE.UU.")
    if medios:
        lineas.append("")
        lineas.append("Impacto medio: " + "; ".join(f"{e['hora']:%H:%M} {nombre(e['title'])}" for e in medios))
    lineas += ["", f"Apertura de NY: {apertura:%H:%M} · tu horario: {a:%H:%M}–{b:%H:%M}",
               "Antes de abrir: relee tu plan de anoche. Un solo trade."]
    ok = mandar("\n".join(lineas))
    if ok and not ya:
        estado[clave] = ahora.isoformat(timespec="minutes")
        ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return ok


def recordatorios():
    ahora = datetime.now(MX)
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    limite = (ahora - timedelta(days=7)).isoformat()
    estado = {k: v for k, v in estado.items() if v >= limite}
    por_hora = {}  # los datos que salen a la misma hora (CPI, Core CPI…) van en un solo mensaje
    for e in calendario():
        if e.get("impact") == "High":
            por_hora.setdefault(e["date"], []).append(e)
    for fecha, grupo in por_hora.items():
        faltan = (grupo[0]["hora"] - ahora).total_seconds() / 60
        clave = f"{fecha}|{grupo[0]['title']}"
        if 0 < faltan <= VENTANA_MIN and clave not in estado:
            texto = (f"En {int(faltan)} min ({grupo[0]['hora']:%H:%M} México):\n"
                     + "\n".join(f"• {nombre(e['title'])}" + (f" · {detalle(e)}" if detalle(e) else "") for e in grupo)
                     + "\n\nNo operes la noticia: espera a que el precio te muestre la dirección.")
            if mandar(texto):
                estado[clave] = ahora.isoformat(timespec="minutes")
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    modo = (sys.argv[1] if len(sys.argv) > 1 else "recordatorios").strip().lower()
    if modo.startswith("agenda"):
        agenda(ya="ya" in sys.argv[2:] or modo == "agenda ya")
    else:
        recordatorios()
