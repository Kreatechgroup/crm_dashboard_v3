"""Acciones compartidas entre tableros: actividades, pérdidas y renovación de cotizaciones.

Todas respetan permisos: cargan el documento y llaman check_permission antes de
escribir; las inserciones y submits pasan por los permisos normales de Frappe.
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, getdate, nowdate

from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_FECHA_PROXIMO_PASO,
	CAMPO_PRESUPUESTO,
	CAMPO_PROXIMO_PASO,
	ConfigModelo,
	DatosRelacionados,
	Etapa,
	etapa_efectiva,
	faltantes,
	motivo_valido,
	tasa_de,
	texto_paso_de_actividad,
)
from crm_dashboard_v3.crm_tableros.common import flujo
from crm_dashboard_v3.crm_tableros.common.eventos import FLAG_TABLERO
from crm_dashboard_v3.crm_tableros.common.tableros import ConfigTablero, tablero_de_oportunidad


def motivos_de_perdida(cfg: ConfigModelo, doctype: str = "Lost Reason") -> list[str]:
	"""Motivos disponibles en el catálogo, sin los genéricos excluidos por configuración.

	Opportunity.lost_reason usa «Lost Reason»; Quotation usa «Quotation Lost Reason».
	"""
	return [
		m
		for m in frappe.get_list(doctype, pluck="name", order_by="name asc", limit_page_length=0)
		if motivo_valido(m, cfg)
	]


def motivos_de_perdida_cotizacion(cfg: ConfigModelo) -> list[str]:
	"""Motivos que existen en ambos catálogos: al perder la cotización también puede perderse la oportunidad."""
	de_cotizacion = set(motivos_de_perdida(cfg, "Quotation Lost Reason"))
	return [m for m in motivos_de_perdida(cfg) if m in de_cotizacion]


def oportunidad_del_tablero(nombre: str, t: ConfigTablero, permiso: str = "read"):
	doc = frappe.get_doc("Opportunity", nombre)
	doc.check_permission(permiso)
	if tablero_de_oportunidad(doc) != t:
		frappe.throw(_("La oportunidad {0} no pertenece a {1}.").format(nombre, t.titulo))
	return doc


def registrar_actividad(oportunidad, activity_type: str, comment: str, next_contact_date: str):
	"""Crea una Opportunity Activity; su próximo contacto pasa a ser el próximo paso de la oportunidad."""
	falta = []
	if not activity_type:
		falta.append(_("tipo"))
	if not (comment or "").strip():
		falta.append(_("comentario"))
	if not next_contact_date:
		falta.append(_("próximo contacto"))
	if falta:
		frappe.throw(_("Falta: {0}.").format(", ".join(falta)), title=_("Opportunity Activity"))
	if getdate(next_contact_date) < getdate(nowdate()):
		frappe.throw(_("El próximo contacto debe ser hoy o una fecha futura."))
	actividad = frappe.get_doc(
		{
			"doctype": "Opportunity Activity",
			"opportunity": oportunidad.name,
			"company": oportunidad.company,
			"activity_type": activity_type,
			"comment": comment.strip(),
			"next_contact_date": next_contact_date,
		}
	)
	actividad.insert()
	if oportunidad.meta.has_field(CAMPO_FECHA_PROXIMO_PASO) and oportunidad.has_permission("write"):
		oportunidad.reload()
		oportunidad.set(CAMPO_PROXIMO_PASO, texto_paso_de_actividad(activity_type))
		oportunidad.set(CAMPO_FECHA_PROXIMO_PASO, next_contact_date)
		oportunidad.save()
	return actividad.name


def cambiar_etapa(doc, destino: Etapa, cfg: ConfigModelo):
	"""Cambia la etapa (embudo_state_v2) validando en el servidor los requisitos del destino.

	La probabilidad y el status los ajusta después el hook validate de Opportunity.
	"""
	actual = etapa_efectiva(doc, cfg)
	if actual.status == "Converted" and doc.status == "Converted" and destino.clave != actual.clave:
		frappe.throw(_("Una oportunidad ganada no puede cambiar de etapa."), title=_("Etapa"))
	rel = DatosRelacionados(doc.name)
	falta = faltantes(doc, destino, cfg, rel)
	# El workflow que controla embudo_state_v2 también debe permitir el cambio.
	bloqueo = flujo.bloqueo(doc, destino.valor)
	if bloqueo:
		frappe.throw(bloqueo, title=_("Workflow"))
	if falta:
		frappe.throw(
			_("Para pasar a {0} falta: {1}.").format(destino.titulo, ", ".join(falta)),
			title=_("Faltan datos"),
		)
	if destino.actualiza_monto_con_cotizacion and rel.monto_cotizacion:
		# El monto de la cotización (en moneda de la empresa) reemplaza al estimado,
		# guardado en la moneda de la oportunidad.
		monto = rel.monto_cotizacion / tasa_de(doc)
		doc.opportunity_amount = monto
		doc.set(CAMPO_PRESUPUESTO, monto)
	doc.set(CAMPO_ETAPA, destino.valor)
	# El hook validate no debe ignorar este cambio: ya se validó aquí.
	doc.flags[FLAG_TABLERO] = True
	doc.save()
	return doc


def perder_oportunidad(doc, cfg: ConfigModelo, motivo: str, detalle: str | None = None):
	"""Lleva la oportunidad a la etapa de pérdida con un Lost Reason válido."""
	if not motivo_valido(motivo, cfg):
		frappe.throw(_("Elige un motivo de pérdida específico."), title=_("Motivo de pérdida"))
	doc.lost_reason = motivo
	if detalle:
		doc.order_lost_reason = detalle
	return cambiar_etapa(doc, cfg.por_status("Lost"), cfg)


def _cotizacion_del_tablero(nombre: str, t: ConfigTablero):
	cotizacion = frappe.get_doc("Quotation", nombre)
	cotizacion.check_permission("read")
	if cotizacion.docstatus != 1:
		frappe.throw(_("La cotización {0} no está enviada.").format(nombre))
	if not cotizacion.get("opportunity"):
		frappe.throw(_("La cotización {0} no está ligada a una oportunidad.").format(nombre))
	op = frappe.db.get_value(
		"Opportunity", cotizacion.opportunity, ["sales_model", "establecimiento_lista"], as_dict=True
	)
	if not op or tablero_de_oportunidad(op) != t:
		frappe.throw(_("La cotización {0} no pertenece a {1}.").format(nombre, t.titulo))
	return cotizacion


def renovar_cotizacion(nombre: str, t: ConfigTablero, valid_till: str | None = None) -> str:
	"""Copia enviada de la cotización con nueva vigencia (por defecto, la misma duración que tenía)."""
	original = _cotizacion_del_tablero(nombre, t)
	frappe.has_permission("Quotation", "create", throw=True)
	hoy = getdate(nowdate())
	if not valid_till:
		duracion = max(1, date_diff(original.valid_till, original.transaction_date))
		valid_till = add_days(hoy, duracion)
	if getdate(valid_till) < hoy:
		frappe.throw(_("La nueva vigencia debe ser hoy o una fecha futura."))
	copia = frappe.copy_doc(original)
	copia.docstatus = 0
	copia.status = "Draft"
	copia.transaction_date = hoy
	copia.valid_till = valid_till
	copia.insert()
	copia.submit()
	return copia.name


def perder_cotizacion(nombre: str, t: ConfigTablero, motivo: str, detalle: str | None = None) -> str:
	"""Perder una cotización vencida = mismo flujo que «Dar por perdida» (especificación Retail).

	La cotización queda Lost con su motivo y la oportunidad en la etapa Perdida, aunque
	tenga otras cotizaciones: para seguir con otra cotización, el asesor renueva en lugar
	de perder.
	"""
	cfg = t.etapas
	if not motivo_valido(motivo, cfg):
		frappe.throw(_("Elige un motivo de pérdida específico."), title=_("Motivo de pérdida"))
	if not (frappe.db.exists("Quotation Lost Reason", motivo) and frappe.db.exists("Lost Reason", motivo)):
		frappe.throw(
			_("El motivo «{0}» debe existir como motivo de cotización y de oportunidad.").format(motivo),
			title=_("Motivo de pérdida"),
		)
	cotizacion = _cotizacion_del_tablero(nombre, t)
	cotizacion.check_permission("write")

	perdida = cfg.por_status("Lost")
	oportunidad = oportunidad_del_tablero(cotizacion.opportunity, t, "write")
	# Antes de tocar nada, el workflow debe permitir pasar la oportunidad a Perdida.
	if oportunidad.get(CAMPO_ETAPA) != perdida.valor:
		bloqueo = flujo.bloqueo(oportunidad, perdida.valor)
		if bloqueo:
			frappe.throw(bloqueo, title=_("Workflow"))

	cotizacion.declare_enquiry_lost([{"lost_reason": motivo}], [], detalle)
	# ERPNext pudo haber cambiado el status de la oportunidad (db_set, sin validate).
	oportunidad.reload()
	if oportunidad.get(CAMPO_ETAPA) != perdida.valor:
		perder_oportunidad(oportunidad, cfg, motivo, detalle)
	return cotizacion.name
