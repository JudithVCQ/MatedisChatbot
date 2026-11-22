"""Front (static/): comprobaciones estáticas. La verificación en un navegador real a 360 y 1280 px se hizo a mano
con Chrome (ver el resumen de la tarea); aquí quedan las garantías que no necesitan navegador."""
import re
import shutil
import subprocess

import pytest

from tests.ayudas import cliente, media, nueva
from app.main import STATIC

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "estilos.css").read_text(encoding="utf-8")


def test_estructura_accesible_y_movil():
    assert '<html lang="es">' in HTML and 'name="viewport"' in HTML
    assert re.search(r'id="mensajes"[^>]*role="log"[^>]*aria-live="polite"', HTML)       # área de mensajes anunciada
    assert 'id="entrada"' in HTML and "autofocus" in HTML and 'maxlength="500"' in HTML
    assert re.search(r'<label for="entrada"', HTML)                                        # el input tiene etiqueta
    assert 'aria-label="Enviar mensaje"' in HTML and 'aria-label="Nueva consulta"' in HTML  # botones solo-ícono con nombre
    assert 'role="tablist"' in HTML and HTML.count('role="tab"') == 2 and HTML.count('role="tabpanel"') == 2
    assert 'href="tel:106"' in HTML and "Orientación, no diagnóstico" in HTML               # el aviso siempre visible
    assert "En línea" in HTML and "TriajeLógico" in HTML


def test_no_hay_selector_de_distrito_ni_boton_fijo_de_ubicacion():
    assert "<select" not in HTML and "distrito" not in HTML.lower()
    assert "distrito" not in JS.lower() and "api/distritos" not in JS
    assert "Usar mi ubicación" not in HTML and 'id="ubicacion"' not in HTML        # solo como respuesta rápida del chat
    assert "Compartir mi ubicación" not in HTML


def test_el_js_es_seguro_y_amable():
    assert "alert(" not in JS and "confirm(" not in JS and "prompt(" not in JS     # errores dentro del chat
    assert "innerHTML" not in re.sub(r"/\*.*?\*/", "", JS, flags=re.S)             # el texto del servidor entra con textContent
    assert "MIN_ESCRIBIENDO_MS = 400" in JS                                        # «escribiendo…» dura al menos 400 ms
    assert "opciones" in JS and "resultado" in JS and "tel:106" in JS
    assert "toFixed(3)" in JS                                                      # solo viajan coordenadas redondeadas
    assert JS.count("Ubicación activada") == 0                                      # sin avisos repetidos de ubicación


def test_el_css_cuida_accesibilidad_y_responsive():
    assert ":focus-visible" in CSS and "prefers-reduced-motion" in CSS and "min-width: 900px" in CSS
    assert "env(safe-area-inset-bottom)" in CSS and "100dvh" in CSS


def test_regresion_los_iconos_no_encogen_la_capa_svg_de_leaflet():
    """La regla global 'svg {width: 1.25em}' encogía la capa SVG de Leaflet y la ruta no se veía."""
    regla = re.search(r"^(svg[^{]*)\{\s*width: 1\.25em", CSS, flags=re.M)
    assert regla and "leaflet-zoom-animated" in regla.group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_la_sintaxis_del_js_es_valida():
    r = subprocess.run(["node", "--check", str(STATIC / "app.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_el_servidor_entrega_los_archivos_del_front():
    for ruta in ("/", "/static/app.js", "/static/estilos.css"):
        assert cliente.get(ruta).status_code == 200
    assert "estilos.css" in cliente.get("/").text


def test_el_contrato_publica_opciones_y_resultado():
    esquema = cliente.get("/openapi.json").json()["components"]["schemas"]
    assert {"opciones", "resultado", "fuera_de_zona", "establecimientos"} <= set(esquema["ChatResponse"]["properties"])
    assert set(esquema["Resultado"]["properties"]) == {"cuadro", "cie10", "urgencia", "cuidados", "volver_si",
                                                       "establecimiento", "nota_seguro"}
    assert set(esquema["Opcion"]["properties"]) == {"etiqueta", "valor", "accion"}
    assert "distrito" not in esquema["ChatRequest"]["properties"] and "ubicacion_denegada" in esquema["ChatRequest"]["properties"]


def test_la_respuesta_trae_todo_lo_que_la_tarjeta_necesita():
    """Lo que dibuja el front sale de campos estructurados, no de texto plano."""
    r = media(nueva())
    res = r["resultado"]
    assert {"cuadro", "cie10", "urgencia", "cuidados", "volver_si", "establecimiento", "nota_seguro"} == set(res)
    assert all(isinstance(o["etiqueta"], str) and o["accion"] in ("enviar", "ubicacion", "sin_ubicacion", "deshacer", "por_que") for o in r["opciones"])
