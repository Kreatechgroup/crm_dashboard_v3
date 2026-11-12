"""Etapas de la oportunidad, sus requisitos y la lectura de montos, fechas y próximo paso.

Este módulo no contiene lógica de un tablero concreto: cada tablero declara sus
etapas en ``crm_tableros/<tablero>/config.py`` y aquí solo se interpretan. Qué
etapas aplican a cada oportunidad lo decide ``common/tableros.py``.
"""

from dataclasses import dataclass
from functools import cached_property

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

# La etapa vive en el campo que ya usan scripts, reportes y notificaciones del ERP.
# Sus 17 valores se agrupan en las etapas nuevas (ConfigModelo.mapa_valores) y, al
# mover una etapa, se escribe el valor representativo de la etapa (Etapa.valor).
CAMPO_ETAPA = "embudo_state_v2"
CAMPO_FECHA_RETOMAR = "custom_fecha_retomar"
CAMPO_PROXIMO_PASO = "custom_proximo_paso"
CAMPO_FECHA_PROXIMO_PASO = "custom_fecha_proximo_paso"
CAMPO_PRESUPUESTO = "presupuesto_declarado_por_el_cliente"
# Orden de venta existente vinculada a mano al cerrar como ganada (si no viene de su cotización).
CAMPO_ORDEN_DE_VENTA = "custom_orden_de_venta"
STATUS_CERRADOS = ("Lost", "Converted", "Closed")


@dataclass(frozen=True)
class Etapa:
	clave: str
	titulo: str
	probabilidad: float | None
	activa: bool
	requisitos: tuple[str, ...]
	texto_requisitos: str
	# Valor de embudo_state_v2 que se escribe al mover a esta etapa.
	valor: str = ""
	status: str | None = None
	cuenta_pronostico: bool = True
	actualiza_monto_con_cotizacion: bool = False


@dataclass(frozen=True)
class ConfigModelo:
	"""Etapas y reglas del embudo de un tablero."""

	nombre: str
	etapas: tuple[Etapa, ...]
	# Valor de embudo_state_v2 -> clave de la etapa a la que pertenece.
	mapa_valores: dict[str, str]
	umbral_escalar: float
	dias_verde_max: int
	dias_amarillo_max: int
	motivos_perdida_excluidos: tuple[str, ...]
	# Orden de lectura del monto: el primero > 0 gana; si ninguno, la cotización más alta.
	campos_monto: tuple[str, ...] = (CAMPO_PRESUPUESTO, "opportunity_amount")
	campos_fecha_cierre: tuple[str, ...] = ("fecha_estimada_aprobacion", "expected_closing")

	def etapa(self, clave: str | None) -> Etapa | None:
		return next((e for e in self.etapas if e.clave == clave), None)

	def por_valor(self, valor: str | None) -> Etapa | None:
		"""Etapa a la que pertenece un valor de embudo_state_v2 (None si no se reconoce)."""
		return self.etapa(self.mapa_valores.get(valor or ""))

	def por_status(self, status: str) -> Etapa | None:
		return next((e for e in self.etapas if e.status == status), None)

	@property
	def activas(self) -> list[Etapa]:
		return [e for e in self.etapas if e.activa]

	def siguiente(self, clave: str) -> Etapa | None:
		activas = self.activas
		claves = [e.clave for e in activas]
		if clave not in claves:
			return None
		i = claves.index(clave)
		return activas[i + 1] if i + 1 < len(activas) else self.por_status("Converted")

	def anterior(self, clave: str) -> Etapa | None:
		claves = [e.clave for e in self.activas]
		if clave not in claves or claves.index(clave) == 0:
			return None
		return self.activas[claves.index(clave) - 1]


# ---------------------------------------------------------------------------
# Lectura de valores de una oportunidad (doc o fila de get_list)
# ---------------------------------------------------------------------------


def etapa_efectiva(row, cfg: ConfigModelo) -> Etapa:
	"""Etapa según embudo_state_v2; si está vacío o no se reconoce, según el status."""
	return cfg.por_valor(row.get(CAMPO_ETAPA)) or cfg.por_status(row.get("status")) or cfg.activas[0]


def es_incoherente(row, cfg: ConfigModelo) -> bool:
	"""Etapa de cierre (Ganada/Perdida) con un status que no corresponde."""
	etapa = etapa_efectiva(row, cfg)
	return bool(etapa.status) and row.get("status") != etapa.status


def tasa_de(row) -> float:
	"""Tasa de la oportunidad a la moneda de la empresa (``conversion_rate``); 1 si no tiene."""
	return flt(row.get("conversion_rate")) or 1


def monto_de(row, cfg: ConfigModelo, monto_cotizacion: float = 0) -> float:
	"""Monto en la moneda de la empresa.

	Primer monto > 0 de los campos configurados, convertido con la tasa de la propia
	oportunidad (igual que ERPNext convierte cotizaciones y facturas a sus campos base_*).
	Si no hay, la cotización ligada más alta, que ya viene en moneda de la empresa
	(``base_grand_total``).
	"""
	for campo in cfg.campos_monto:
		if flt(row.get(campo)) > 0:
			return flt(row.get(campo)) * tasa_de(row)
	return flt(monto_cotizacion)


def fecha_cierre_de(row, cfg: ConfigModelo):
	for campo in cfg.campos_fecha_cierre:
		if row.get(campo):
			return getdate(row.get(campo))
	return None


def proximo_paso_de(row, ultima_actividad=None) -> frappe._dict:
	"""Próximo paso de la oportunidad: sus campos propios o, si están vacíos, la última actividad.

	Devuelve ``texto`` y ``fecha`` (date o None).
	"""
	texto = (row.get(CAMPO_PROXIMO_PASO) or "").strip()
	fecha = row.get(CAMPO_FECHA_PROXIMO_PASO)
	if texto or fecha:
		return frappe._dict(texto=texto, fecha=getdate(fecha) if fecha else None)
	if ultima_actividad and ultima_actividad.get("next_contact_date"):
		return frappe._dict(
			texto=texto_paso_de_actividad(ultima_actividad.get("activity_type")),
			fecha=getdate(ultima_actividad.get("next_contact_date")),
		)
	return frappe._dict(texto="", fecha=None)


def texto_paso_de_actividad(tipo: str | None) -> str:
	return _("Contactar · {0}").format(tipo or _("seguimiento"))


def motivo_valido(motivo: str | None, cfg: ConfigModelo) -> bool:
	return bool(motivo) and motivo not in cfg.motivos_perdida_excluidos


def motivos_de(doc) -> list[str]:
	motivos = [r.lost_reason for r in (doc.get("lost_reasons") or []) if r.get("lost_reason")]
	if doc.get("lost_reason"):
		motivos.append(doc.get("lost_reason"))
	return motivos


# ---------------------------------------------------------------------------
# Requisitos para entrar a una etapa
# ---------------------------------------------------------------------------


class DatosRelacionados:
	"""Documentos ligados que se necesitan para validar requisitos.

	Usa frappe.get_all a propósito: la validación de integridad debe ver todas las
	cotizaciones/órdenes ligadas aunque el usuario no tenga permiso de lectura sobre
	ellas; no se devuelve ningún dato al usuario, solo si cumple o no.
	"""

	def __init__(self, oportunidad: str | None):
		self.oportunidad = oportunidad

	@cached_property
	def ultima_actividad(self):
		if not self.oportunidad:
			return None
		filas = frappe.get_all(
			"Opportunity Activity",
			filters={"opportunity": self.oportunidad},
			fields=["activity_type", "next_contact_date", "created_on"],
			order_by="created_on desc",
			limit=1,
		)
		return filas[0] if filas else None

	@cached_property
	def cotizaciones(self) -> list:
		if not self.oportunidad:
			return []
		return frappe.get_all(
			"Quotation",
			filters={"opportunity": self.oportunidad, "docstatus": 1},
			fields=["name", "status", "base_grand_total", "valid_till", "creation"],
			order_by="creation desc",
		)

	@property
	def cotizaciones_enviadas(self) -> list:
		return [q for q in self.cotizaciones if q.status not in ("Lost", "Cancelled")]

	@property
	def monto_cotizacion(self) -> float:
		return max((flt(q.base_grand_total) for q in self.cotizaciones_enviadas), default=0)

	@cached_property
	def ordenes_de_venta(self) -> list[str]:
		nombres = [q.name for q in self.cotizaciones]
		if not nombres:
			return []
		return frappe.get_all(
			"Sales Order Item",
			filters={"prevdoc_docname": ["in", nombres], "docstatus": 1},
			pluck="parent",
			distinct=True,
		)


def orden_vinculada(doc) -> str | None:
	"""Orden de venta enviada que se vinculó a mano a la oportunidad."""
	orden = doc.get(CAMPO_ORDEN_DE_VENTA)
	if orden and frappe.db.get_value("Sales Order", orden, "docstatus") == 1:
		return orden
	return None


def _proximo_paso_con_fecha(doc, rel: DatosRelacionados) -> bool:
	paso = proximo_paso_de(doc, rel.ultima_actividad)
	return bool(paso.texto and paso.fecha)


def _proximo_paso_vigente(doc, rel: DatosRelacionados) -> bool:
	paso = proximo_paso_de(doc, rel.ultima_actividad)
	return bool(paso.texto and paso.fecha and paso.fecha >= getdate(nowdate()))


# clave -> (texto que ve el usuario, función(doc, relacionados, cfg) -> bool)
REQUISITOS = {
	"cliente": (_("cliente o lead"), lambda d, r, c: bool(d.get("party_name"))),
	"tipo": (_("tipo de oportunidad"), lambda d, r, c: bool(d.get("tipo_de_oportunidad"))),
	"origen": (_("origen"), lambda d, r, c: bool(d.get("source"))),
	"monto": (_("presupuesto declarado"), lambda d, r, c: monto_de(d, c) > 0),
	"fecha_cierre": (_("fecha estimada de aprobación"), lambda d, r, c: bool(fecha_cierre_de(d, c))),
	"proximo_paso": (
		_("próximo paso con fecha"),
		lambda d, r, c: _proximo_paso_con_fecha(d, r),
	),
	"proximo_paso_vigente": (
		_("fecha del próximo paso (hoy o después)"),
		lambda d, r, c: _proximo_paso_vigente(d, r),
	),
	"cotizacion_enviada": (
		_("cotización enviada (submit) ligada"),
		lambda d, r, c: bool(r.cotizaciones_enviadas),
	),
	"orden_de_venta": (
		_("orden de venta creada o vinculada"),
		lambda d, r, c: bool(r.ordenes_de_venta or orden_vinculada(d)),
	),
	"motivo_perdida": (
		_("motivo de pérdida específico"),
		lambda d, r, c: any(motivo_valido(m, c) for m in motivos_de(d)),
	),
	"fecha_retomar": (_("fecha para retomar"), lambda d, r, c: bool(d.get(CAMPO_FECHA_RETOMAR))),
}


def faltantes(doc, etapa: Etapa, cfg: ConfigModelo, rel: DatosRelacionados | None = None) -> list[str]:
	"""Textos de los requisitos que la oportunidad no cumple para entrar a ``etapa``."""
	rel = rel or DatosRelacionados(None if doc.get("__islocal") else doc.get("name"))
	return [REQUISITOS[k][0] for k in etapa.requisitos if not REQUISITOS[k][1](doc, rel, cfg)]
