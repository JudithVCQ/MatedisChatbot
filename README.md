# TriajeLógico

Asistente de orientación médica con razonamiento explicable (proyecto de Matemática Discreta).
**Orientación, no diagnóstico.** Ante una emergencia: SAMU 106.

## Correr en local (Windows)

```powershell
cd "C:\CHATBOT MATEDIS"
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # opcional: completar si usan LLM
uvicorn app.main:app --reload
```

- App: http://127.0.0.1:8000
- Documentación automática de la API: http://127.0.0.1:8000/docs
- Pruebas: `pytest -v`
- Verificar la base de conocimiento (restricciones I1–I12): `python -m app.motor.verificacion`

Sin `.env`, el sistema funciona solo con el extractor por palabras clave (plan B).

## Estructura

| Archivo | Tema del curso |
|---|---|
| `app/motor/inferencia.py` | Lógica proposicional, modus ponens, terminación por inducción |
| `app/motor/verificacion.py` | Tablas de verdad acotadas, contradicciones |
| `app/motor/fsm.py` | Máquina de Mealy con función de transición total |
| `app/motor/arbol.py` | Árbol binario, recursión, preorden |
| `app/motor/relaciones.py` | Matrices booleanas, composición de relaciones |
| `app/motor/red_vial.py` | Grafo dirigido de calles reales (OpenStreetMap), Dijkstra con parada temprana, haversine |
| `app/motor/ruteo.py` | Destino según el nivel de urgencia y el seguro, zona de cobertura y ruta desde la ubicación |
| `app/motor/seguros.py` | Reconoce el seguro del usuario y detecta que pide un establecimiento |
| `app/motor/grafo.py` | Grafo de distritos y Dijkstra (respaldo si no existe `data/red_lima.json`) |
| `app/motor/extractor_keywords.py` | Autómata finito de negación |
| `app/motor/extractor_llm.py` | LLM: solo traduce texto a la lista cerrada |
| `app/schemas.py` | Validación en cada frontera (Pydantic) |
| `data/*.json` | Reglas, síntomas, cuadros, niveles, seguros, árbol, grafo, zona y red vial (datos versionados) |
| `static/` | Front sin frameworks (HTML, CSS y JS), mobile-first |

## Cómo conversa el chat

Todo el diálogo es **determinista** (el LLM solo traduce texto a síntomas; no participa aquí):

- **Atajos y aclaraciones:** el saludo ofrece síntomas comunes; "tengo dolor" pregunta dónde, "me siento mal" pregunta qué sientes.
- **Una sola pregunta de edad** (bebé, niño, persona de 5 a 59 años, persona de 60 o más); si el mensaje ya trae la edad ("mi hijo de 3 años"), no se vuelve a preguntar.
- **Errores de ortografía:** "fievre", "diarea" o "me duele el peho" se entienden (distancia de Levenshtein); el razonamiento muestra cada corrección.
- **Duración e intensidad:** con fiebre pregunta desde cuándo (o lo toma de "hace 4 días" y "39 de fiebre"); con dolor de barriga, qué tan fuerte es.
- **Confirmación:** antes de concluir resume lo que entendió y deja corregirlo. Con un signo de alarma **no** se pide confirmación.
- **«Me equivoqué»:** deshace el último paso (hasta 20). **«¿Por qué?»:** explica por qué se hace esa pregunta, sin avanzar.

## Red vial real (OpenStreetMap)

La ruta al establecimiento sigue las **calles reales** de Lima, desde la ubicación del usuario. La red está en
`data/red_lima.json` (unos 2,5 MB, ya incluida en el repo) y la zona que cubre se define en `data/zona.json`
(centro, radio de 9000 m y umbral de "fuera de zona"). Si ese archivo no existe, el sistema usa el grafo de
distritos sin errores.

### Regenerar la red (solo en la PC, una sola vez; nunca en Render)

Hace falta solo si cambias `data/zona.json`. `osmnx` va en `requirements-dev.txt` y **no** en `requirements.txt`.

```powershell
.venv\Scripts\activate
pip install -r requirements-dev.txt
python scripts/descargar_red.py
```

Tarda unos 3 minutos y necesita internet. El script descarga la red, se queda con la parte conexa más grande,
guarda `data/red_lima.json`, asigna a cada establecimiento de `data/grafo.json` su calle más cercana (`nodo`) y
guarda los hospitales y clínicas de OSM en `data/establecimientos_osm_candidatos.json` (sin validar:
todos con `revisar: true`, y **no** entran a `grafo.json` hasta contrastarlos con RENIPRESS). Al final imprime un
resumen. Si el servidor de OpenStreetMap está saturado, el script reintenta; también puedes probar otro con
`--overpass https://overpass.private.coffee/api`.

Si solo agregaste o corregiste establecimientos en `data/grafo.json`, no hace falta descargar de nuevo:

```powershell
python scripts/descargar_red.py --solo-asignar
```

(`python -m app.motor.verificacion` y el arranque del servidor avisan si a un establecimiento le falta su `nodo`.)
Si `red_lima.json` pesara más de 40 MB, reduce `radio_m` en `data/zona.json` antes de subirlo a GitHub.

### Probar la ubicación sin moverte (Chrome DevTools)

1. Abre la app en Chrome y pulsa **F12**.
2. Menú **⋮** de DevTools → **More tools** → **Sensors**.
3. En **Location** elige una ciudad o **Other…** y escribe latitud y longitud, por ejemplo:
   - Ciudad Universitaria de la UNMSM: `-12.056`, `-77.084`
   - Parque Kennedy (Miraflores): `-12.1211`, `-77.0297`
   - Fuera de la zona (Arequipa): `-16.40`, `-71.53`
4. En la app, escribe un síntoma de alarma (por ejemplo "me duele el pecho"). El chat pide la ubicación con el botón
   **Compartir mi ubicación**; al tocarlo, el navegador usa la de Sensors. Si cambias la ubicación en Sensors, usa
   **Intentar de nuevo** (o «Nueva consulta»). Para una urgencia media, el chat pregunta antes el seguro
   (botones: SIS, EsSalud, EPS, Sanidad FFAA/PNP, No tengo seguro, No sé).
   Para probar el permiso denegado: en Chrome, clic en el candado de la barra → Ubicación → Bloquear.

### Atribución

Los datos de calles y los mosaicos del mapa son © colaboradores de OpenStreetMap, licencia ODbL
(https://www.openstreetmap.org/copyright). Los tiempos de viaje son **estimados, sin tráfico**.

## Pendientes de datos (antes de la demo)

- [ ] Contrastar `data/reglas.json` con fuentes MINSA/OMS.
- [ ] Reemplazar los centros de salud marcados "EJEMPLO" por establecimientos reales (hay candidatos en
      `data/establecimientos_osm_candidatos.json` para validar contra RENIPRESS) y correr
      `python scripts/descargar_red.py --solo-asignar`.
- [ ] Ampliar a 15–25 establecimientos, con categoría, emergencia 24 h, dirección y teléfono.

## Despliegue en Render

1. Subir el repo a GitHub.
2. En Render: **New → Blueprint** y elegir el repo (usa `render.yaml`).
3. Si usan LLM: en **Environment**, cargar `LLM_API_KEY`, `LLM_BASE_URL` y `LLM_MODEL`.
4. Abrir la URL unos minutos antes de la demo (el plan gratuito se duerme).
