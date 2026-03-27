#!/usr/bin/env python3
"""
Rastreador de vuelos a Rio de Janeiro
Vuelo ida:    JetSmart  - 19 May 2026 - 15:55
Vuelo vuelta: Fly Bondi - 25 May 2026 - 15:50

Usa Playwright para simular un browser real y acceder a Turismo City.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright no instalado. Corré: pip install playwright && playwright install chromium")
    sys.exit(1)

# ── Configuración de vuelos ──────────────────────────────────────────────────
VUELOS = {
    "ida": {
        "origen": "EZE",          # Ezeiza (o AEP si JetSmart usa Aeroparque)
        "destino": "GIG",         # Rio de Janeiro - Galeão
        "fecha": "2026-05-19",
        "aerolinea": "JetSmart",
        "horario": "15:55",
    },
    "vuelta": {
        "origen": "GIG",
        "destino": "EZE",
        "fecha": "2026-05-25",
        "aerolinea": "Fly Bondi",
        "horario": "15:50",
    },
}

HISTORIAL_FILE = Path("historial_precios_rio.json")

# ── URL de Turismo City ──────────────────────────────────────────────────────
def build_url_turismocity():
    """Construye la URL de búsqueda en Turismo City (ida y vuelta)."""
    return (
        "https://www.turismocity.com.ar/vuelos/buscar"
        "?from=BUE&to=RIO"
        "&departureDate=2026-05-19"
        "&returnDate=2026-05-25"
        "&adults=1&type=roundtrip"
    )

# ── Scraping ─────────────────────────────────────────────────────────────────
def buscar_en_turismocity(playwright):
    """Abre Turismo City, espera que carguen los vuelos y extrae precios."""
    resultados = []
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    try:
        url = build_url_turismocity()
        print(f"\n🌐 Accediendo a Turismo City...")
        print(f"   {url}\n")
        page.goto(url, timeout=60_000)

        # Esperar a que aparezcan resultados (selector genérico, ajustar si cambia el sitio)
        try:
            page.wait_for_selector("[class*='flight'], [class*='vuelo'], [class*='result']", timeout=30_000)
        except PlaywrightTimeout:
            print("⚠️  Timeout esperando resultados. El sitio puede haber cambiado su estructura.")

        time.sleep(3)  # Dar tiempo extra a los datos dinámicos

        # Extraer texto completo de la página para buscar precios y horarios
        contenido = page.content()
        texto = page.inner_text("body")

        # Buscar el vuelo de ida (JetSmart 15:55)
        ida = extraer_precio_vuelo(texto, "JetSmart", "15:55")
        if ida:
            resultados.append({"tramo": "ida", **ida})

        # Buscar el vuelo de vuelta (Fly Bondi 15:50)
        vuelta = extraer_precio_vuelo(texto, "Fly Bondi", "15:50")
        if vuelta:
            resultados.append({"tramo": "vuelta", **vuelta})

        # Si no encontramos nada con los selectores específicos, guardar todos los precios visibles
        if not resultados:
            precios_todos = re.findall(r'\$[\s]?[\d.,]+', texto)
            print("   No se encontraron los vuelos exactos. Precios en pantalla:")
            for p in sorted(set(precios_todos))[:20]:
                print(f"   {p}")

        # Captura de pantalla para referencia
        screenshot_path = f"captura_turismocity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"\n📸 Captura guardada: {screenshot_path}")

    except Exception as e:
        print(f"❌ Error al acceder al sitio: {e}")
    finally:
        browser.close()

    return resultados


def extraer_precio_vuelo(texto, aerolinea, horario):
    """Busca precio de un vuelo específico en el texto extraído de la página."""
    lineas = texto.split("\n")
    for i, linea in enumerate(lineas):
        if aerolinea.lower() in linea.lower() and horario in linea:
            # Buscar precio en las líneas cercanas
            contexto = " ".join(lineas[max(0, i-3):i+5])
            precios = re.findall(r'\$\s?([\d.,]+)', contexto)
            if precios:
                precio_str = precios[0].replace(".", "").replace(",", ".")
                try:
                    return {
                        "aerolinea": aerolinea,
                        "horario": horario,
                        "precio": float(precio_str),
                        "precio_raw": f"${precios[0]}",
                        "contexto": linea.strip(),
                    }
                except ValueError:
                    pass
    return None


# ── Historial ────────────────────────────────────────────────────────────────
def cargar_historial():
    if HISTORIAL_FILE.exists():
        with open(HISTORIAL_FILE) as f:
            return json.load(f)
    return []


def guardar_historial(historial):
    with open(HISTORIAL_FILE, "w") as f:
        json.dump(historial, f, indent=2, ensure_ascii=False)


def agregar_al_historial(historial, resultados):
    entrada = {
        "timestamp": datetime.now().isoformat(),
        "fecha_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "vuelos": resultados,
    }
    historial.append(entrada)
    return historial


# ── Comparación con registro anterior ───────────────────────────────────────
def comparar_con_anterior(historial, resultados_nuevos):
    if len(historial) < 2:
        return
    anteriores = {v["tramo"]: v for v in historial[-2]["vuelos"]}
    for vuelo in resultados_nuevos:
        tramo = vuelo.get("tramo")
        if tramo in anteriores:
            prev = anteriores[tramo]["precio"]
            curr = vuelo["precio"]
            diff = curr - prev
            emoji = "📈" if diff > 0 else "📉" if diff < 0 else "➡️"
            print(f"  {emoji} {vuelo['aerolinea']} ({tramo}): "
                  f"${prev:,.0f} → ${curr:,.0f}  ({'+' if diff >= 0 else ''}{diff:,.0f})")


# ── Imprimir resumen ─────────────────────────────────────────────────────────
def imprimir_resumen(resultados):
    print("\n" + "="*55)
    print("  RESUMEN DE VUELOS - RIO DE JANEIRO")
    print("="*55)
    total = 0
    for v in resultados:
        print(f"\n  ✈️  {v['aerolinea']} — {v['horario']}")
        print(f"     Tramo  : {v['tramo'].upper()}")
        print(f"     Precio : {v['precio_raw']}")
        total += v.get("precio", 0)
    if len(resultados) == 2:
        print(f"\n  💰 TOTAL IDA Y VUELTA: ${total:,.0f}")
    print("="*55)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("━"*55)
    print("  RASTREADOR DE VUELOS - RIO DE JANEIRO")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("━"*55)
    print(f"\n  IDA    : JetSmart  BUE→RIO  19/05/2026  15:55")
    print(f"  VUELTA : Fly Bondi RIO→BUE  25/05/2026  15:50")

    historial = cargar_historial()

    with sync_playwright() as playwright:
        resultados = buscar_en_turismocity(playwright)

    if resultados:
        imprimir_resumen(resultados)
        historial = agregar_al_historial(historial, resultados)
        if len(historial) > 1:
            print("\n📊 Cambios respecto a la consulta anterior:")
            comparar_con_anterior(historial, resultados)
        guardar_historial(historial)
        print(f"\n✅ Historial guardado en: {HISTORIAL_FILE}")
    else:
        print("\n⚠️  No se encontraron los vuelos específicos.")
        print("   Revisá la captura de pantalla generada para ver qué cargó el sitio.")
        print("\n💡 Tip: También podés buscar manualmente en:")
        print("   https://www.turismocity.com.ar/vuelos/buscar?from=BUE&to=RIO&departureDate=2026-05-19&returnDate=2026-05-25&adults=1&type=roundtrip")

    # Mostrar historial completo si hay más de una entrada
    if len(historial) > 1:
        print(f"\n📋 Historial completo ({len(historial)} consultas):")
        for entrada in historial:
            precios = [f"{v['aerolinea']}: {v['precio_raw']}" for v in entrada["vuelos"]]
            print(f"  [{entrada['fecha_hora']}] {' | '.join(precios) if precios else 'sin datos'}")


if __name__ == "__main__":
    main()
