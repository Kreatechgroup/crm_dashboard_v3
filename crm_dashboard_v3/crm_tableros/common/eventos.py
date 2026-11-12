"""Hooks de documentos: etapa, probabilidad y status siempre coherentes (en servidor)."""

import frappe
from frappe import _

from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_PRESUPUESTO,
	DatosRelacionados,
	faltantes,
	motivos_de,
)
from crm_dashboard_v3.crm_tableros.common.tableros import tablero_de_oportunidad


def validar_oportunidad(doc, method=None):
	"""Hook validate de Opportunity: requisitos por etapa, probabilidad y status coherentes."""
	t = tablero_de_oportunidad(doc)
	if not t or not doc.meta.has_field(CAMPO_ETAPA):
		return
	cfg = t.etapas

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
			frappe.throw(_("La etapa {0} no existe en {1}.").format(doc.get(CAMPO_ETAPA), t.titulo))
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
			# El monto de la cotización reemplaza al estimado.
			doc.opportunity_amount = rel.monto_cotizacion
			doc.set(CAMPO_PRESUPUESTO, rel.monto_cotizacion)

	if etapa.probabilidad is not None:
		doc.probability = etapa.probabilidad
	if etapa.status:
		doc.status = etapa.status
	elif doc.status in ("Lost", "Converted"):
		# Reabrir una perdida: vuelve a estar abierta.
		doc.status = "Open"


def marcar_ganada(oportunidad: str):
	"""Pone la etapa Ganada (y Converted) a una oportunidad cuya orden de venta ya existe."""
	row = frappe.db.get_value(
		"Opportunity", oportunidad, ["sales_model", "establecimiento_lista", CAMPO_ETAPA], as_dict=True
	)
	t = tablero_de_oportunidad(row) if row else None
	ganada = t.etapas.por_status("Converted") if t else None
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
