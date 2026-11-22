"""Validación en cada frontera (Pydantic)."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.datos import ids_extraibles

MAX_MENSAJE = 500


class Extraccion(BaseModel):
    """Salida de cualquier extractor (LLM o palabras clave)."""
    presentes: set[str] = Field(default_factory=set)
    ausentes: set[str] = Field(default_factory=set)
    alarma_incierta: bool = False
    correcciones: list[str] = Field(default_factory=list)   # ortografía corregida, para la traza

    @field_validator("presentes", "ausentes")
    @classmethod
    def solo_lista_cerrada(cls, v: set[str]) -> set[str]:
        desconocidos = v - ids_extraibles()
        if desconocidos:
            raise ValueError(f"síntomas o factores fuera de la lista cerrada: {desconocidos}")
        return v

    @model_validator(mode="after")
    def disjuntos(self):
        # presentes ∩ ausentes = ∅  (un síntoma no puede ser p y ~p a la vez)
        if self.presentes & self.ausentes:
            raise ValueError("un síntoma no puede estar presente y ausente a la vez")
        return self


class ChatRequest(BaseModel):
    sesion: str = Field(min_length=1, max_length=64)
    mensaje: str = Field(default="", max_length=MAX_MENSAJE)
    # Solo se valida que sean coordenadas geográficas posibles. Si caen fuera de la zona de cobertura
    # (data/zona.json) no es un error de formato: la respuesta dice "fuera de la zona cubierta".
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    # El usuario no compartió su ubicación (negó el permiso o falló): se recomienda sin ruta.
    ubicacion_denegada: bool = False

    @field_validator("lat", "lng")
    @classmethod
    def redondear(cls, v: float | None) -> float | None:
        # Privacidad (Ley 29733): ~100 m de precisión es suficiente para elegir el establecimiento.
        return None if v is None else round(v, 3)

    @model_validator(mode="after")
    def ubicacion_completa(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat y lng deben venir juntas")
        return self


class Punto(BaseModel):
    nombre: str
    lat: float
    lng: float


class Ruta(BaseModel):
    destino: str
    minutos: int
    linea: list[tuple[float, float]]    # [lat, lng] por las calles, de origen a destino
    puntos: list[Punto]                 # solo origen y destino, con nombre
    direccion: str | None = None
    telefono: str | None = None


class Establecimiento(BaseModel):
    nombre: str
    direccion: str | None = None
    telefono: str | None = None
    lat: float
    lng: float


class Opcion(BaseModel):
    """Botón de respuesta rápida. 'enviar' manda `valor` como mensaje; 'ubicacion' pide la ubicación al navegador
    y la envía; 'sin_ubicacion' avisa que el usuario prefiere no compartirla; 'deshacer' («Me equivoqué») y 'por_que' («¿Por qué?»)
    envían `valor` como mensaje pero el front los muestra como botones pequeños, aparte de las respuestas rápidas."""
    etiqueta: str
    valor: str = ""
    accion: Literal["enviar", "ubicacion", "sin_ubicacion", "deshacer", "por_que"] = "enviar"


class EstablecimientoResultado(BaseModel):
    nombre: str
    direccion: str | None = None
    telefono: str | None = None
    minutos: int


class Resultado(BaseModel):
    """Resultado estructurado: el front lo dibuja como tarjeta, sin interpretar texto plano."""
    cuadro: str | None = None
    cie10: str | None = None
    urgencia: str | None = None
    cuidados: list[str] = []
    volver_si: list[str] = []
    establecimiento: EstablecimientoResultado | None = None
    nota_seguro: str | None = None


class ChatResponse(BaseModel):
    estado: str
    mensaje: str
    urgencia: str | None = None
    cuadros: list[str] = []
    traza: list[str] = []
    ruta: Ruta | None = None
    fuera_de_zona: bool = False                   # la ubicación está fuera de la zona cubierta
    establecimientos: list[Establecimiento] = []  # sin ruta: la recomendación (los destinos adecuados)
    opciones: list[Opcion] = []                   # botones de respuesta rápida
    resultado: Resultado | None = None
