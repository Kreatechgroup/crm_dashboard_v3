"""Métodos whitelisted comunes a todos los tableros CRM."""

import frappe
from frappe import _

from crm_dashboard_v3.crm_tableros.common import alcance, tableros


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
