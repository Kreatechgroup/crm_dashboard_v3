"""Acciones compartidas entre tableros: actividades, pérdidas y renovación de cotizaciones.

Todas respetan permisos: cargan el documento y llaman check_permission antes de
escribir; las inserciones y submits pasan por los permisos normales de Frappe.
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, getdate, nowdate

from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	ConfigModelo,
	config_de,
	motivo_valido,
)


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


def oportunidad_del_modelo(nombre: str, sales_model: str, permiso: str = "read"):
	doc = frappe.get_doc("Opportunity", nombre)
	doc.check_permission(permiso)
	if doc.get("sales_model") != sales_model:
		frappe.throw(_("La oportunidad {0} no es del modelo {1}.").format(nombre, sales_model))
	return doc


def registrar_actividad(oportunidad, activity_type: str, comment: str, next_contact_date: str):
	"""Crea una Opportunity Activity; su próximo contacto es el próximo paso de la tarjeta."""
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
	return actividad.name


def perder_oportunidad(doc, cfg: ConfigModelo, motivo: str, detalle: str | None = None):
	"""Lleva la oportunidad a la etapa de pérdida con un Lost Reason válido."""
	if not motivo_valido(motivo, cfg):
		frappe.throw(_("Elige un motivo de pérdida específico."), title=_("Motivo de pérdida"))
	perdida = cfg.por_status("Lost")
	doc.lost_reason = motivo
	if detalle:
		doc.order_lost_reason = detalle
	doc.set(CAMPO_ETAPA, perdida.titulo)
	doc.save()
	return doc


def _cotizacion_con_oportunidad(nombre: str, sales_model: str):
	cotizacion = frappe.get_doc("Quotation", nombre)
	cotizacion.check_permission("read")
	if cotizacion.docstatus != 1:
		frappe.throw(_("La cotización {0} no está enviada.").format(nombre))
	if not cotizacion.get("opportunity"):
		frappe.throw(_("La cotización {0} no está ligada a una oportunidad.").format(nombre))
	modelo = frappe.db.get_value("Opportunity", cotizacion.opportunity, "sales_model")
	if modelo != sales_model:
		frappe.throw(_("La cotización {0} no es del modelo {1}.").format(nombre, sales_model))
	return cotizacion


def renovar_cotizacion(nombre: str, sales_model: str, valid_till: str | None = None) -> str:
	"""Copia enviada de la cotización con nueva vigencia (por defecto, la misma duración que tenía)."""
	original = _cotizacion_con_oportunidad(nombre, sales_model)
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


def perder_cotizacion(nombre: str, sales_model: str, motivo: str, detalle: str | None = None) -> str:
	"""Declara perdida la cotización y, si no le quedan cotizaciones vivas, también la oportunidad."""
	cfg = config_de(sales_model)
	if not motivo_valido(motivo, cfg):
		frappe.throw(_("Elige un motivo de pérdida específico."), title=_("Motivo de pérdida"))
	if not (frappe.db.exists("Quotation Lost Reason", motivo) and frappe.db.exists("Lost Reason", motivo)):
		frappe.throw(
			_("El motivo «{0}» debe existir como motivo de cotización y de oportunidad.").format(motivo),
			title=_("Motivo de pérdida"),
		)
	cotizacion = _cotizacion_con_oportunidad(nombre, sales_model)
	cotizacion.check_permission("write")
	cotizacion.declare_enquiry_lost([{"lost_reason": motivo}], [], detalle)

	vivas = frappe.get_list(
		"Quotation",
		filters={
			"opportunity": cotizacion.opportunity,
			"docstatus": 1,
			"name": ["!=", cotizacion.name],
			"valid_till": [">=", nowdate()],
			"status": ["not in", ["Lost", "Cancelled", "Ordered"]],
		},
		pluck="name",
	)
	oportunidad = oportunidad_del_modelo(cotizacion.opportunity, sales_model, "write")
	# ERPNext puede haber dejado la oportunidad en Lost (db_set, sin validate):
	# en ese caso la etapa se alinea aunque queden otras cotizaciones.
	ya_perdida = oportunidad.get(CAMPO_ETAPA) == cfg.por_status("Lost").titulo
	if not ya_perdida and (not vivas or oportunidad.status == "Lost"):
		perder_oportunidad(oportunidad, cfg, motivo, detalle)
	return cotizacion.name
