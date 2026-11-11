"""Configuración de etapas por modelo de venta y reglas de servidor de la Opportunity.

Este módulo no contiene lógica de un tablero concreto: cada modelo de venta
(Proyectos hoy, Retail en la fase siguiente) declara sus etapas en
``crm_tableros/<modelo>/config.py`` y aquí solo se interpretan.
"""

import importlib
from dataclasses import dataclass, field
from functools import cached_property

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

CAMPO_ETAPA = "custom_etapa_crm"
CAMPO_FECHA_RETOMAR = "custom_fecha_retomar"
STATUS_CERRADOS = ("Lost", "Converted", "Closed")

# Modelos de venta que ya tienen configuración propia. Retail se agrega aquí
# cuando exista crm_tableros/retail/config.py.
MODELOS_CONFIGURADOS = ("Proyectos",)


@dataclass(frozen=True)
class Etapa:
	clave: str
	titulo: str
	probabilidad: float | None
	activa: bool
	requisitos: tuple[str, ...]
	texto_requisitos: str
	status: str | None = None
	cuenta_pronostico: bool = True
	actualiza_monto_con_cotizacion: bool = False


@dataclass(frozen=True)
class ConfigModelo:
	sales_model: str
	etapas: tuple[Etapa, ...]
	# Valor viejo de embudo_state_v2 -> clave de etapa nueva (lectura y migración).
	mapa_legado: dict[str, str]
	tipo_meta: str
	# Texto que distingue al Sales Person de este modelo (un usuario puede tener varios).
	texto_sales_person: str
	umbral_escalar: float
	dias_verde_max: int
	dias_amarillo_max: int
	motivos_perdida_excluidos: tuple[str, ...]
	roles_jefe: tuple[str, ...]
	campos_monto: tuple[str, ...] = ("opportunity_amount", "presupuesto_declarado_por_el_cliente")
	campos_fecha_cierre: tuple[str, ...] = ("fecha_estimada_aprobacion", "expected_closing")
	campo_etapa_legado: str = "embudo_state_v2"
	extras: dict = field(default_factory=dict)

	def etapa(self, clave: str | None) -> Etapa | None:
		return next((e for e in self.etapas if e.clave == clave), None)

	def por_titulo(self, titulo: str | None) -> Etapa | None:
		return next((e for e in self.etapas if e.titulo == titulo), None)

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


def config_de(sales_model: str | None) -> ConfigModelo | None:
	"""Configuración del modelo de venta, o None si el modelo no tiene tablero."""
	if sales_model not in MODELOS_CONFIGURADOS:
		return None
	modulo = importlib.import_module(f"crm_dashboard_v3.crm_tableros.{frappe.scrub(sales_model)}.config")
	return modulo.CONFIG


def titulos_de_todas_las_etapas() -> list[str]:
	titulos: list[str] = []
	for modelo in MODELOS_CONFIGURADOS:
		for etapa in config_de(modelo).etapas:
			if etapa.titulo not in titulos:
				titulos.append(etapa.titulo)
	return titulos


# ---------------------------------------------------------------------------
# Lectura de valores de una oportunidad (doc o fila de get_list)
# ---------------------------------------------------------------------------


def etapa_efectiva(row, cfg: ConfigModelo) -> Etapa:
	"""Etapa nueva si existe; si no, la equivalente del valor viejo; si no, por status."""
	etapa = cfg.por_titulo(row.get(CAMPO_ETAPA))
	if etapa:
		return etapa
	etapa = cfg.etapa(cfg.mapa_legado.get(row.get(cfg.campo_etapa_legado) or ""))
	if etapa:
		return etapa
	return cfg.por_status(row.get("status")) or cfg.activas[0]


def es_incoherente(row, cfg: ConfigModelo) -> bool:
	"""Etapa de cierre (Ganada/Perdida) con un status que no corresponde."""
	etapa = etapa_efectiva(row, cfg)
	return bool(etapa.status) and row.get("status") != etapa.status


def monto_de(row, cfg: ConfigModelo, monto_cotizacion: float = 0) -> float:
	"""Primer monto > 0 de los campos configurados; si no hay, la cotización ligada más alta."""
	for campo in cfg.campos_monto:
		if flt(row.get(campo)) > 0:
			return flt(row.get(campo))
	return flt(monto_cotizacion)


def fecha_cierre_de(row, cfg: ConfigModelo):
	for campo in cfg.campos_fecha_cierre:
		if row.get(campo):
			return getdate(row.get(campo))
	return None


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


def _proximo_paso_con_fecha(doc, rel: DatosRelacionados) -> bool:
	return bool(rel.ultima_actividad and rel.ultima_actividad.next_contact_date)


def _proximo_paso_vigente(doc, rel: DatosRelacionados) -> bool:
	return _proximo_paso_con_fecha(doc, rel) and getdate(rel.ultima_actividad.next_contact_date) >= getdate(
		nowdate()
	)


# clave -> (texto que ve el usuario, función(doc, relacionados, cfg) -> bool)
REQUISITOS = {
	"cliente": (_("cliente o lead"), lambda d, r, c: bool(d.get("party_name"))),
	"tipo": (_("tipo de oportunidad"), lambda d, r, c: bool(d.get("tipo_de_oportunidad"))),
	"origen": (_("origen"), lambda d, r, c: bool(d.get("source"))),
	"monto": (_("presupuesto o monto estimado"), lambda d, r, c: monto_de(d, c) > 0),
	"fecha_cierre": (_("fecha estimada de aprobación"), lambda d, r, c: bool(fecha_cierre_de(d, c))),
	"proximo_paso": (
		_("próximo paso con fecha (registra una Opportunity Activity con próximo contacto)"),
		lambda d, r, c: _proximo_paso_con_fecha(d, r),
	),
	"proximo_paso_vigente": (
		_("próximo paso con fecha de hoy en adelante"),
		lambda d, r, c: _proximo_paso_vigente(d, r),
	),
	"cotizacion_enviada": (
		_("cotización enviada (submit) ligada"),
		lambda d, r, c: bool(r.cotizaciones_enviadas),
	),
	"orden_de_venta": (_("orden de venta creada"), lambda d, r, c: bool(r.ordenes_de_venta)),
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


# ---------------------------------------------------------------------------
# Hooks de documentos
# ---------------------------------------------------------------------------


def validar_oportunidad(doc, method=None):
	"""Hook validate de Opportunity: requisitos por etapa, probabilidad y status coherentes."""
	cfg = config_de(doc.get("sales_model"))
	if not cfg or not doc.meta.has_field(CAMPO_ETAPA):
		return

	anterior = None if doc.is_new() else doc.get_doc_before_save()
	etapa_cambio = anterior is None or anterior.get(CAMPO_ETAPA) != doc.get(CAMPO_ETAPA)
	status_cambio = anterior is not None and anterior.get("status") != doc.get("status")

	# Un cambio de status hecho desde ERPNext (p. ej. declarar perdida) arrastra la etapa.
	if status_cambio and not etapa_cambio and cfg.por_status(doc.status):
		doc.set(CAMPO_ETAPA, cfg.por_status(doc.status).titulo)
		etapa_cambio = True

	for motivo in motivos_de(doc):
		if motivo in cfg.motivos_perdida_excluidos:
			frappe.throw(
				_("«{0}» no es un motivo de pérdida válido. Elige el motivo real.").format(motivo),
				title=_("Motivo de pérdida"),
			)

	etapa = cfg.por_titulo(doc.get(CAMPO_ETAPA))
	if not etapa:
		if doc.get(CAMPO_ETAPA):
			frappe.throw(_("La etapa {0} no existe para el modelo {1}.").format(doc.get(CAMPO_ETAPA), cfg.sales_model))
		return

	if etapa_cambio:
		etapa_previa = cfg.por_titulo(anterior.get(CAMPO_ETAPA)) if anterior else None
		if etapa_previa and etapa_previa.status == "Converted" and etapa != etapa_previa:
			frappe.throw(_("Una oportunidad ganada no puede cambiar de etapa."), title=_("Etapa"))

		rel = DatosRelacionados(None if doc.is_new() else doc.name)
		falta = faltantes(doc, etapa, cfg, rel)
		if falta:
			frappe.throw(
				_("Para pasar a {0} falta: {1}.").format(etapa.titulo, ", ".join(falta)),
				title=_("Faltan datos"),
			)
		if etapa.actualiza_monto_con_cotizacion and rel.monto_cotizacion:
			doc.opportunity_amount = rel.monto_cotizacion

	if etapa.probabilidad is not None:
		doc.probability = etapa.probabilidad
	if etapa.status:
		doc.status = etapa.status
	elif doc.status in ("Lost", "Converted"):
		# Reabrir una perdida: vuelve a estar abierta.
		doc.status = "Open"


def marcar_ganada(oportunidad: str):
	"""Pone la etapa Ganada (y Converted) a una oportunidad cuya orden de venta ya existe."""
	row = frappe.db.get_value("Opportunity", oportunidad, ["sales_model", CAMPO_ETAPA], as_dict=True)
	cfg = config_de(row.sales_model) if row else None
	ganada = cfg.por_status("Converted") if cfg else None
	if not ganada:
		return
	# set_value: la orden de venta ya cumplió el requisito; replicamos lo que ERPNext
	# hace con el status (db_set) para que etapa y status no queden desalineados.
	frappe.db.set_value(
		"Opportunity",
		oportunidad,
		{CAMPO_ETAPA: ganada.titulo, "probability": ganada.probabilidad, "status": "Converted"},
	)


def sincronizar_ganadas_desde_orden(doc, method=None):
	"""Hook on_submit de Sales Order: sus oportunidades pasan a Ganada."""
	cotizaciones = list({i.prevdoc_docname for i in doc.items if i.get("prevdoc_docname")})
	if not cotizaciones:
		return
	oportunidades = frappe.get_all(
		"Quotation",
		filters={"name": ["in", cotizaciones], "opportunity": ["is", "set"]},
		pluck="opportunity",
	)
	for oportunidad in set(oportunidades):
		marcar_ganada(oportunidad)
