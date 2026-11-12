"""Hooks de documentos: probabilidad y status coherentes con la etapa (embudo_state_v2).

El hook corre en todo guardado de la oportunidad —desde el tablero, el formulario o
los scripts existentes del ERP que escriben embudo_state_v2— y por eso no bloquea por
requisitos de etapa: esos se validan en el servidor cuando la etapa se cambia desde
el tablero (``proyectos/api.py · mover_etapa``). Aquí solo se asegura que:

- la probabilidad sea la de la etapa;
- Ganada ↔ Converted y Perdida ↔ Lost;
- un cambio de status hecho desde ERPNext (declarar perdida) arrastre la etapa;
- no se use un motivo de pérdida genérico.
"""

import frappe
from frappe import _

from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA, motivos_de
from crm_dashboard_v3.crm_tableros.common.tableros import tablero_de_oportunidad


def validar_oportunidad(doc, method=None):
	t = tablero_de_oportunidad(doc)
	if not t:
		return
	cfg = t.etapas
	anterior = None if doc.is_new() else doc.get_doc_before_save()

	if anterior is None or anterior.get("lost_reason") != doc.get("lost_reason"):
		for motivo in motivos_de(doc):
			if motivo in cfg.motivos_perdida_excluidos:
				frappe.throw(
					_("«{0}» no es un motivo de pérdida válido. Elige el motivo real.").format(motivo),
					title=_("Motivo de pérdida"),
				)

	etapa_cambio = anterior is None or anterior.get(CAMPO_ETAPA) != doc.get(CAMPO_ETAPA)
	status_cambio = anterior is not None and anterior.get("status") != doc.get("status")

	# Un cambio de status hecho desde ERPNext (p. ej. declarar perdida) arrastra la etapa.
	if status_cambio and not etapa_cambio and cfg.por_status(doc.status):
		doc.set(CAMPO_ETAPA, cfg.por_status(doc.status).valor)
		etapa_cambio = True

	etapa = cfg.por_valor(doc.get(CAMPO_ETAPA))
	if not etapa:
		# Sin etapa reconocible no se toca nada.
		return

	if etapa.probabilidad is not None:
		doc.probability = etapa.probabilidad
	if not etapa_cambio:
		return
	# Solo se ajusta el status cuando la etapa cambia, para no alterar el histórico
	# que nadie toca. Descartada no cambia el status: su migración está pendiente.
	if etapa.status and doc.get(CAMPO_ETAPA) == etapa.valor:
		doc.status = etapa.status
	elif not etapa.status and doc.status in ("Lost", "Converted"):
		# Reabrir una perdida: vuelve a estar abierta.
		doc.status = "Open"


def marcar_ganada(oportunidad: str):
	"""Pone la etapa Ganada (y Converted) a una oportunidad cuya orden de venta ya existe."""
	row = frappe.db.get_value(
		"Opportunity", oportunidad, ["sales_model", "establecimiento_lista"], as_dict=True
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
		{CAMPO_ETAPA: ganada.valor, "probability": ganada.probabilidad, "status": "Converted"},
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
