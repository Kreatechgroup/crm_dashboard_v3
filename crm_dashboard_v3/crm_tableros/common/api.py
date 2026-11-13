"""Métodos whitelisted comunes a todos los tableros CRM."""

import frappe
from frappe import _

from crm_dashboard_v3.crm_tableros.common import acciones, alcance, tableros


def tablero_o_error(clave: str) -> tableros.ConfigTablero:
	try:
		return tableros.tablero(clave)
	except KeyError:
		frappe.throw(_("No existe el tablero {0}.").format(clave))


@frappe.whitelist()
def get_contexto(
	tablero: str, mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None
):
	"""Contexto de sesión del tablero: usuario → empleado → Sales Person, empresa, rol de jefe y mes.

	Devuelve lo mismo que el encabezado de cualquier tablero: periodo, meses
	seleccionables, empresa, establecimiento, Sales Person del asesor, si es jefe
	(con los asesores de la tienda) y el título. Si el usuario no entra al
	tablero, ``mensaje`` explica por qué.
	"""
	return alcance.obtener(tablero_o_error(tablero), mes, asesor, establecimiento).base


# ---------------------------------------------------------------------------
# Botón «Descartar» del formulario de Opportunity (Client Script Opportunity-Client)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def como_descartar(nombre: str) -> dict:
	"""Cómo debe comportarse «Descartar» para esta oportunidad.

	En las oportunidades de un tablero «Descartada» no es una etapa: el botón pide un
	motivo y da la oportunidad por perdida. En las demás, el botón hace lo de siempre.
	"""
	doc = frappe.get_doc("Opportunity", nombre)
	doc.check_permission("read")
	t = tableros.tablero_de_oportunidad(doc)
	if not t:
		return {"pedir_motivo": False}
	return {"pedir_motivo": True, "motivos": acciones.motivos_de_perdida(t.etapas)}


@frappe.whitelist(methods=["POST"])
def descartar_oportunidad(nombre: str, motivo: str, detalle: str | None = None) -> dict:
	"""«Descartar» en una oportunidad de tablero: la da por perdida con un motivo válido."""
	doc = frappe.get_doc("Opportunity", nombre)
	doc.check_permission("write")
	t = tableros.tablero_de_oportunidad(doc)
	if not t:
		frappe.throw(_("La oportunidad {0} no pertenece a ningún tablero.").format(nombre))
	acciones.perder_oportunidad(doc, t.etapas, motivo, detalle)
	return {"name": doc.name, "status": doc.status}
