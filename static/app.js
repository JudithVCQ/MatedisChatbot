"use strict";
/* TriajeLógico · front sin frameworks.
   - Todo el texto del servidor entra con textContent (nunca innerHTML): no hay inyección posible.
   - La ubicación solo se pide cuando el servidor la pide (opción «Compartir mi ubicación») y se envía redondeada a
     3 decimales. Las coordenadas exactas se quedan en esta pestaña, solo para dibujar «Estás aquí». */

const $ = (id) => document.getElementById(id);
const MIN_ESCRIBIENDO_MS = 400;
const ESCRITORIO = window.matchMedia("(min-width: 900px)");

let sesion = crypto.randomUUID();
let ocupado = false;                 // hay una petición en curso
let posicion = null;                 // {lat, lng, precision}: exacta, solo para el mapa
let historial = [];                  // razonamiento de cada respuesta
let contadorRespuestas = 0;

/** Crea un elemento: el([etiqueta], {className, text, attrs, on}, ...hijos). */
function el(etiqueta, props = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  if (props.className) nodo.className = props.className;
  if (props.text != null) nodo.textContent = props.text;
  for (const [k, v] of Object.entries(props.attrs || {})) nodo.setAttribute(k, v);
  for (const [k, v] of Object.entries(props.on || {})) nodo.addEventListener(k, v);
  hijos.flat().filter(Boolean).forEach((h) => nodo.append(h));
  return nodo;
}

const icono = (id) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  const uso = document.createElementNS("http://www.w3.org/2000/svg", "use");
  uso.setAttribute("href", `#${id}`);
  svg.append(uso);
  return svg;
};

const hora = () => new Date().toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit" });
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
const telefonoLimpio = (t) => String(t).replace(/[^\d+]/g, "");

// ---------- mapa (Leaflet) ----------
let mapa = null, capaRuta = null, capaUsuario = null, capaZona = null;

function iniciarMapa() {
  if (typeof L === "undefined") {          // sin internet no carga la librería: el resto sigue funcionando
    $("mapa").append(el("p", { className: "nota", text: "No se pudo cargar el mapa. Los datos de la ruta siguen en la conversación.", attrs: { style: "padding:12px" } }));
    return;
  }
  mapa = L.map("mapa");
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a> (ODbL)',
  }).addTo(mapa);
  capaZona = L.layerGroup().addTo(mapa);
  capaUsuario = L.layerGroup().addTo(mapa);
  capaRuta = L.layerGroup().addTo(mapa);
  mapa.setView([-12.07, -77.05], 12);
  fetch("/api/zona").then((r) => r.json()).then((z) => {     // la zona sale de data/zona.json: sin números fijos aquí
    L.circle([z.centro.lat, z.centro.lng], { radius: z.radio_m, color: "#64748b", weight: 1, dashArray: "6 6", fill: false }).addTo(capaZona);
    if (!posicion) mapa.setView([z.centro.lat, z.centro.lng], 12);
  }).catch(() => {});
}

function dibujarUsuario() {
  if (!mapa) return;
  capaUsuario.clearLayers();
  if (!posicion) return;
  const punto = [posicion.lat, posicion.lng];
  L.circle(punto, { radius: posicion.precision, color: "#1d4ed8", weight: 1, fillOpacity: 0.12 }).addTo(capaUsuario);
  L.circleMarker(punto, { radius: 8, color: "#fff", weight: 2, fillColor: "#1d4ed8", fillOpacity: 1 })
    .bindTooltip("Estás aquí", { permanent: true, direction: "top", offset: [0, -8] }).addTo(capaUsuario);
}

function dibujarRuta(ruta) {
  if (!mapa || !ruta) return;
  capaRuta.clearLayers();
  L.polyline(ruta.linea, { weight: 5, color: "#1d4ed8" }).addTo(capaRuta);
  const destino = ruta.puntos[ruta.puntos.length - 1];
  const popup = el("div", {}, el("b", { text: ruta.destino }),
    el("br"), document.createTextNode(`${ruta.minutos} min aprox.`),
    ruta.direccion ? [el("br"), document.createTextNode(ruta.direccion)] : null,
    ruta.telefono ? [el("br"), document.createTextNode(`Tel. ${ruta.telefono}`)] : null);
  L.marker([destino.lat, destino.lng]).bindPopup(popup).addTo(capaRuta);
  const limites = L.latLngBounds(ruta.linea);
  if (posicion) limites.extend([posicion.lat, posicion.lng]);      // que se vean el usuario y el destino
  mapa.fitBounds(limites, { padding: [30, 30] });
}

// ---------- panel: mapa y razonamiento ----------
const panel = $("panel");
let disparador = null;

function seleccionarPestana(cual) {
  const mapaActivo = cual === "mapa";
  $("tab-mapa").setAttribute("aria-selected", String(mapaActivo));
  $("tab-razon").setAttribute("aria-selected", String(!mapaActivo));
  $("tab-mapa").tabIndex = mapaActivo ? 0 : -1;
  $("tab-razon").tabIndex = mapaActivo ? -1 : 0;
  $("vista-mapa").hidden = !mapaActivo;
  $("vista-razon").hidden = mapaActivo;
  if (mapaActivo && mapa) setTimeout(() => mapa.invalidateSize(), 60);
}

function abrirPanel(pestana, origen) {
  seleccionarPestana(pestana);
  if (ESCRITORIO.matches) return;                      // en escritorio el panel siempre está a la vista
  disparador = origen || document.activeElement;
  panel.classList.add("abierto");
  $("fondo-panel").hidden = false;
  if (pestana === "mapa" && mapa) setTimeout(() => mapa.invalidateSize(), 280);
  $(pestana === "mapa" ? "tab-mapa" : "tab-razon").focus();
}

function cerrarPanel() {
  panel.classList.remove("abierto");
  $("fondo-panel").hidden = true;
  if (disparador && document.contains(disparador)) disparador.focus(); else $("entrada").focus();
}

$("tab-mapa").addEventListener("click", () => seleccionarPestana("mapa"));
$("tab-razon").addEventListener("click", () => seleccionarPestana("razon"));
document.querySelector(".pestanas").addEventListener("keydown", (e) => {   // flechas entre pestañas (patrón ARIA)
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const destino = $("tab-mapa").getAttribute("aria-selected") === "true" ? "razon" : "mapa";
  seleccionarPestana(destino);
  $(destino === "mapa" ? "tab-mapa" : "tab-razon").focus();
});
$("abrir-razonamiento").addEventListener("click", (e) => abrirPanel("razon", e.currentTarget));
$("cerrar-panel").addEventListener("click", cerrarPanel);
$("fondo-panel").addEventListener("click", cerrarPanel);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && panel.classList.contains("abierto")) cerrarPanel(); });
ESCRITORIO.addEventListener("change", () => { panel.classList.remove("abierto"); $("fondo-panel").hidden = true; if (mapa) mapa.invalidateSize(); });

// ---------- razonamiento: pasos numerados ----------
const sinGuiones = (s) => s.replace(/_/g, " ");

function formatearPaso(linea) {
  let m = linea.match(/^([A-Z]+\d+): (.+?) → (\S+)\s+\(modus ponens\)(?: — (.+?))?(?: \[(.+)\])?$/);
  if (m) {
    const [, id, premisas, conclusion, explicacion, fuente] = m;
    const formula = el("div", { className: "regla-formula" },
      document.createTextNode(`si ${premisas.split(" ∧ ").map(sinGuiones).join(" ∧ ")} → `),
      el("span", { className: "concl", text: sinGuiones(conclusion) }));
    return [el("span", { className: "etq regla", text: `Regla ${id}` }), formula,
            explicacion ? el("div", { className: "paso-expl", text: explicacion + (fuente ? ` (fuente: ${fuente})` : "") }) : null];
  }
  m = linea.match(/^Mealy: δ\((\w+), (\w+)\) = (\w+)\s+\/\s+λ = (\w+)(?:\s+\((.+)\))?$/);
  if (m) {
    const [, de, simbolo, a, salida, nota] = m;
    return [el("span", { className: "etq mealy", text: "Estado" }),
            el("div", { className: "paso-texto", text: `${de} → ${a} al recibir «${sinGuiones(simbolo)}», acción: ${sinGuiones(salida)}` }),
            nota ? el("div", { className: "paso-expl", text: nota }) : null];
  }
  m = linea.match(/^Extractor \((.+?)\): presentes=\[(.*?)\] ausentes=\[(.*?)\]$/);
  if (m) {
    const lista = (t) => t.replace(/'/g, "").split(", ").filter(Boolean).map(sinGuiones).join(", ") || "ninguno";
    return [el("span", { className: "etq extractor", text: "Lo que entendí" }),
            el("div", { className: "paso-texto", text: `Síntomas presentes: ${lista(m[2])}. Ausentes: ${lista(m[3])}.` })];
  }
  const tipo = /^(Origen|Dijkstra|Ubicación|La calle|No hay camino)/.test(linea) ? ["ruta", "Ruta"]
             : /^Corregí/.test(linea) ? ["ortografia", "Ortografía"]
             : /^(Grupo de edad|Temperatura|Mensaje incompleto)/.test(linea) ? ["dato", "Lo que entendí"]
             : /^(Mealy\+pila|Se deshizo|El usuario pide deshacer)/.test(linea) ? ["mealy", "Deshacer"]
             : /^(Explicación|Corrección|Fin del interrogatorio|El usuario (confirma|quiere))/.test(linea) ? ["dato", "Diálogo"]
             : /^(Seguro|Intersección|Urgencia alta)/.test(linea) ? ["seguro", "Seguro"] : ["paso", "Paso"];
  const texto = tipo[0] === "seguro" ? linea.replace(/[\[\]']/g, "") : linea;        // sin corchetes ni comillas de Python
  return [el("span", { className: `etq ${tipo[0]}`, text: tipo[1] }), el("div", { className: "paso-texto", text: texto })];
}

function renderizarTraza() {
  const cont = $("traza");
  cont.replaceChildren();
  if (!historial.length) {
    cont.append(el("p", { className: "vacio", text: "Aún no hay razonamiento. Cuéntame tus síntomas para empezar." }));
    return;
  }
  [...historial].reverse().forEach((turno, i) => {          // lo más reciente primero y abierto: se ve sin desplazarse
    const ultimo = i === 0;
    const lista = el("ol", { className: "pasos" }, turno.lineas.map((l) => el("li", {}, el("div", { className: "paso-cuerpo" }, formatearPaso(l)))));
    const detalles = el("details", { className: "turno" }, el("summary", { text: `Respuesta ${turno.n} · ${turno.hora}` }), lista);
    if (ultimo) detalles.open = true;
    cont.append(detalles);
  });
  cont.parentElement.scrollTop = 0;
}

// ---------- chat ----------
const contMensajes = $("mensajes");

function bajar() { contMensajes.scrollTop = contMensajes.scrollHeight; }

function parrafos(texto) {
  return texto.split("\n").filter((l) => l.trim()).map((l) => el("p", { text: l }));
}

function agregarUsuario(texto) {
  contMensajes.append(el("div", { className: "fila usuario" },
    el("div", { className: "columna" }, el("div", { className: "burbuja" }, el("p", { text: texto })), el("span", { className: "hora", text: hora() }))));
  bajar();
}

function agregarBot(hijosColumna) {
  contMensajes.append(el("div", { className: "fila bot" }, avatar(), el("div", { className: "columna" }, hijosColumna, el("span", { className: "hora", text: hora() }))));
  bajar();
}

function avatar() {
  const svg = icono("i-bot");
  svg.setAttribute("class", "avatar");
  return svg;
}

function agregarError(texto, reintento) {
  agregarBot(el("div", { className: "burbuja error", attrs: { role: "alert" } }, el("p", { text: texto })));
  if (reintento) mostrarOpciones([{ etiqueta: "Reintentar", valor: "", accion: "reintentar", reintento }]);
}

let escribiendo = null;
function mostrarEscribiendo() {
  if (escribiendo) return;
  escribiendo = el("div", { className: "fila bot escribiendo", attrs: { role: "status", "aria-label": "TriajeLógico está escribiendo" } },
    avatar(), el("div", { className: "burbuja" }, el("i"), el("i"), el("i")));
  contMensajes.append(escribiendo);
  bajar();
}
function ocultarEscribiendo() { escribiendo?.remove(); escribiendo = null; }

function quitarOpciones() { contMensajes.querySelectorAll(".opciones").forEach((n) => n.remove()); }

const AUXILIARES = ["deshacer", "por_que"];   // botones pequeños: no son respuestas rápidas

function mostrarOpciones(opciones) {
  quitarOpciones();
  if (!opciones?.length) return;
  const rapidas = opciones.filter((o) => !AUXILIARES.includes(o.accion));
  const auxiliares = opciones.filter((o) => AUXILIARES.includes(o.accion));
  if (rapidas.length) agregarGrupo(rapidas, "opciones", "Respuestas rápidas", "opcion");
  if (auxiliares.length) agregarGrupo(auxiliares, "opciones aux", "Más opciones", "opcion-aux");
  bajar();
}

function agregarGrupo(opciones, clase, etiqueta, claseBoton) {
  const grupo = el("div", { className: clase, attrs: { role: "group", "aria-label": etiqueta } });
  opciones.forEach((o) => {
    const esUbicacion = o.accion === "ubicacion";
    const boton = el("button", { className: `${claseBoton}${esUbicacion ? " principal" : ""}`, attrs: { type: "button" } },
      esUbicacion ? icono("i-ubicacion") : null, document.createTextNode(o.etiqueta));
    boton.addEventListener("click", () => elegirOpcion(o));
    grupo.append(boton);
  });
  contMensajes.append(grupo);
}

function elegirOpcion(o) {
  if (ocupado) return;
  if (o.accion === "reintentar") { quitarOpciones(); o.reintento(); }
  else if (o.accion === "ubicacion") compartirUbicacion();
  else if (o.accion === "sin_ubicacion") enviarMensaje({ ubicacion_denegada: true }, "Prefiero no compartirla");
  else enviarMensaje({ mensaje: o.valor }, o.etiqueta);
  $("entrada").focus();
}

// ---------- tarjeta de resultado ----------
const NOMBRE_URGENCIA = { urgencia_alta: "Urgencia alta", urgencia_media: "Urgencia media", urgencia_baja: "Urgencia baja" };

function listaPlegable(titulo, items, clase) {
  return el("details", { className: `lista ${clase || ""}` }, el("summary", { text: titulo }), el("ul", {}, items.map((t) => el("li", { text: t }))));
}

function botonSamu(grande) {
  return el("a", { className: grande ? "btn-samu" : "btn secundario", attrs: { href: "tel:106" } }, icono("i-telefono"), document.createTextNode("Llamar al SAMU 106"));
}

function tarjetaEstablecimiento(est, urgencia, ruta) {
  const acciones = el("div", { className: "acciones" });
  if (ruta) acciones.append(el("button", { className: "btn", attrs: { type: "button" }, on: { click: (e) => { dibujarRuta(ruta); abrirPanel("mapa", e.currentTarget); } } }, icono("i-mapa"), document.createTextNode("Ver ruta")));
  if (est.telefono) acciones.append(el("a", { className: "btn secundario", attrs: { href: `tel:${telefonoLimpio(est.telefono)}` } }, icono("i-telefono"), document.createTextNode("Llamar")));
  if (urgencia === "urgencia_alta") acciones.append(botonSamu(false));
  return el("div", { className: "estab" },
    el("h3", { text: est.nombre }),
    el("span", { className: "min", text: `≈ ${est.minutos} min (estimado, sin tráfico)` }),
    el("span", { text: est.direccion || "Dirección: por confirmar", attrs: est.direccion ? {} : { style: "color:#475467" } }),
    est.telefono ? el("span", {}, document.createTextNode("Tel. "), el("a", { text: est.telefono, attrs: { href: `tel:${telefonoLimpio(est.telefono)}` } })) : el("span", { text: "Teléfono: por confirmar", attrs: { style: "color:#475467" } }),
    acciones);
}

function tarjetaResultado(res, ruta) {
  const alta = res.urgencia === "urgencia_alta";
  const tarjeta = el("div", { className: `tarjeta${alta ? " alta" : ""}`, attrs: { role: "group", "aria-label": "Resultado de la orientación" } });
  if (alta && !res.establecimiento) {
    tarjeta.append(el("div", { className: "tarjeta-alta-cab" }, el("span", { text: "⚠ Atención de emergencia ahora" }), botonSamu(true)));
  }
  const cuerpo = el("div", { className: "tarjeta-cuerpo" });
  const hayCuadro = Boolean(res.cuadro);
  if (res.urgencia && (hayCuadro || !res.establecimiento)) {
    cuerpo.append(el("div", { className: "fila-insignia" },
      el("span", { className: `insignia ${res.urgencia.replace("urgencia_", "")}`, text: NOMBRE_URGENCIA[res.urgencia] }),
      hayCuadro ? el("span", { className: "cuadro", text: res.cuadro }) : null,
      res.cie10 ? el("span", { className: "cie", text: `CIE-10 ${res.cie10}` }) : null));
  }
  if (res.cuidados?.length) cuerpo.append(listaPlegable("Qué hacer", res.cuidados));
  if (res.volver_si?.length) cuerpo.append(listaPlegable("Vuelve si…", res.volver_si, "sub-volver"));
  if (res.establecimiento) cuerpo.append(tarjetaEstablecimiento(res.establecimiento, res.urgencia, ruta));
  if (res.nota_seguro) cuerpo.append(el("p", { className: "nota", text: res.nota_seguro }));
  tarjeta.append(cuerpo);
  return tarjeta;
}

function mostrarRespuesta(d) {
  const piezas = [];
  if (d.resultado) piezas.push(tarjetaResultado(d.resultado, d.ruta));
  if (d.mensaje) piezas.push(el("div", { className: `burbuja${d.estado === "ERROR" ? " error" : ""}` }, parrafos(d.mensaje)));
  agregarBot(piezas);
  contadorRespuestas += 1;
  historial.push({ n: contadorRespuestas, hora: hora(), lineas: d.traza || [] });
  renderizarTraza();
  if (d.ruta) dibujarRuta(d.ruta);
  if (d.fuera_de_zona && posicion && mapa) mapa.setView([posicion.lat, posicion.lng], 12);   // el marcador sigue visible
  mostrarOpciones(d.opciones);
}

// ---------- envío ----------
async function enviarMensaje(extra = {}, burbujaUsuario = null) {
  if (ocupado) return;
  ocupado = true;
  $("enviar").disabled = true;
  contMensajes.setAttribute("aria-busy", "true");
  const miSesion = sesion;
  if (burbujaUsuario) agregarUsuario(burbujaUsuario);
  quitarOpciones();
  mostrarEscribiendo();
  const cuerpo = { sesion: miSesion, mensaje: "", ...extra };
  try {
    const [r] = await Promise.all([fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) }), dormir(MIN_ESCRIBIENDO_MS)]);
    const datos = await r.json();
    if (miSesion !== sesion) return;                              // se pidió una nueva consulta mientras esperábamos
    ocultarEscribiendo();
    if (r.status === 422 && datos.codigo === "ubicacion_invalida") {
      posicion = null; dibujarUsuario();
      ocupado = false;
      agregarError("No pude usar tu ubicación. Te doy la recomendación sin ruta.");
      return enviarMensaje({ ubicacion_denegada: true });
    }
    if (!datos.mensaje) throw new Error("respuesta vacía");
    mostrarRespuesta(datos);
  } catch (e) {
    if (miSesion !== sesion) return;
    ocultarEscribiendo();
    agregarError("No pude conectarme con el servidor. Revisa tu conexión e inténtalo de nuevo. Ante una emergencia llama al SAMU 106.",
                 () => enviarMensaje(extra));
  } finally {
    if (miSesion === sesion) {
      ocupado = false;
      $("enviar").disabled = false;
      contMensajes.removeAttribute("aria-busy");
    }
  }
}

function compartirUbicacion() {
  if (ocupado) return;
  agregarUsuario("📍 Compartir mi ubicación");
  quitarOpciones();
  if (!navigator.geolocation) {
    enviarMensaje({ ubicacion_denegada: true });
    return;
  }
  ocupado = true;
  mostrarEscribiendo();
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      posicion = { lat: pos.coords.latitude, lng: pos.coords.longitude, precision: pos.coords.accuracy };
      dibujarUsuario();
      ocupado = false;
      ocultarEscribiendo();
      // al servidor solo viajan coordenadas redondeadas a 3 decimales (~100 m)
      enviarMensaje({ lat: +pos.coords.latitude.toFixed(3), lng: +pos.coords.longitude.toFixed(3) });
    },
    () => {                                                       // permiso negado o falla: recomendación sin ruta
      posicion = null; dibujarUsuario();
      ocupado = false;
      ocultarEscribiendo();
      enviarMensaje({ ubicacion_denegada: true });
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

$("form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const texto = $("entrada").value.trim();
  if (!texto || ocupado) return;
  $("entrada").value = "";
  enviarMensaje({ mensaje: texto }, texto);
  $("entrada").focus();
});

$("nueva").addEventListener("click", () => {
  sesion = crypto.randomUUID();           // sesión nueva: se olvida todo lo anterior, incluido el seguro
  ocupado = false;
  $("enviar").disabled = false;
  posicion = null;
  historial = []; contadorRespuestas = 0;
  contMensajes.replaceChildren();
  escribiendo = null;
  capaRuta?.clearLayers(); capaUsuario?.clearLayers();
  renderizarTraza();
  if (panel.classList.contains("abierto")) cerrarPanel();
  enviarMensaje({});
  $("entrada").focus();
});

iniciarMapa();
seleccionarPestana("mapa");
enviarMensaje({});
$("entrada").focus();
