"""Workflow de la oportunidad («Embudo de ventas 2019» controla embudo_state_v2).

Frappe valida en cada guardado que un cambio del campo de estado del workflow sea
una transición permitida para los roles del usuario; si no lo es, el guardado
falla. Aquí se consulta eso antes de escribir la etapa, para:

- que el hook validate nunca rompa un guardado por cambiar la etapa;
- que la page explique qué transición falta en lugar del error genérico.
"""

import frappe
from frappe import _
from frappe.model.workflow import get_workflow_name, is_transition_condition_satisfied

from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA


def _workflow_de_etapa(doctype: str):
	"""Workflow activo del doctype si su campo de estado es el de la etapa; si no, None."""
	nombre = get_workflow_name(doctype)
	if not nombre:
		return None
	workflow = frappe.get_cached_doc("Workflow", nombre)
	return workflow if workflow.workflow_state_field == CAMPO_ETAPA else None


def estado_existe(valor: str, doctype: str = "Opportunity") -> bool:
	"""True si ``valor`` es un estado del workflow activo (o si ningún workflow controla la etapa)."""
	workflow = _workflow_de_etapa(doctype)
	return not workflow or any(s.state == valor for s in workflow.states)


def bloqueo(doc, destino: str, actual: str | None = None) -> str | None:
	"""Mensaje si el workflow no permite pasar de ``actual`` a ``destino``.

	Si no se da ``actual``, se toma el valor de la etapa que tiene ``doc`` (debe ser
	todavía el guardado en la base). Devuelve None si la transición está permitida o
	si ningún workflow controla la etapa.
	"""
	workflow = _workflow_de_etapa(doc.doctype)
	actual = doc.get(CAMPO_ETAPA) if actual is None else actual
	if not workflow or not destino or actual == destino or doc.is_new():
		return None
	if not actual:
		# Sin estado actual Frappe toma el primero del workflow y solo permite ese.
		return None if destino == workflow.states[0].state else _mensaje(workflow.name, actual, destino)
	# Mismo criterio que frappe.model.workflow.get_transitions (estado, rol y condición),
	# sin su chequeo de lectura: el hook también corre en guardados con ignore_permissions.
	roles = set(frappe.get_roles())
	for t in workflow.transitions:
		if t.state == actual and t.next_state == destino and t.allowed in roles:
			if is_transition_condition_satisfied(t, doc):
				return None
	return _mensaje(workflow.name, actual, destino)


def _mensaje(workflow: str, actual: str | None, destino: str) -> str:
	return _("El workflow «{0}» no permite pasar de «{1}» a «{2}» con tu rol. Pide que se agregue esa transición.").format(
		workflow, actual or _("sin estado"), destino
	)
