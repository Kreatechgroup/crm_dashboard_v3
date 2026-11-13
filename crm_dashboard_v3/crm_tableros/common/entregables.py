"""Entregables (DocType «Documento Entregable») ligados a un documento: renders, planos, fichas…

Se usan en la pestaña Entregables de la oportunidad; Retail puede reutilizarlos.
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, strip_html

DOCTYPE = "Documento Entregable"


def disponible() -> bool:
	return bool(frappe.db.exists("DocType", DOCTYPE))


def tipos() -> list[str]:
	if not disponible():
		return []
	return frappe.get_list("Tipo Entregable", pluck="name", order_by="name asc", limit_page_length=0)


def de_documento(doctype: str, nombre: str, hoy) -> list[dict]:
	"""Entregables pedidos para el documento, del más reciente al más antiguo."""
	if not disponible():
		return []
	filas = frappe.get_list(
		DOCTYPE,
		filters={"tipo_documento": doctype, "documento": nombre},
		fields=["name", "tipo_entregable", "fecha_solicitada_entrega", "due_date", "descripcion_solicitud", "creation"],
		order_by="creation desc",
		limit_page_length=0,
	)
	resultado = []
	for f in filas:
		solicitada = getdate(f.fecha_solicitada_entrega) if f.fecha_solicitada_entrega else None
		if f.due_date:
			estado, clave = _("Entregado el {0}").format(f.due_date), "verde"
		elif solicitada and solicitada < getdate(hoy):
			estado, clave = _("Atrasado · pedido para el {0}").format(solicitada), "rojo"
		else:
			estado, clave = _("Solicitado · para el {0}").format(solicitada or "—"), "gris"
		resultado.append(
			{
				"name": f.name,
				"tipo": f.tipo_entregable,
				"descripcion": strip_html(f.descripcion_solicitud or ""),
				"estado": estado,
				"clave": clave,
			}
		)
	return resultado


def solicitar(doctype: str, nombre: str, tipo_entregable: str, fecha: str, descripcion: str) -> str:
	if not disponible():
		frappe.throw(_("El DocType {0} no existe en este sitio.").format(DOCTYPE))
	falta = []
	if not tipo_entregable:
		falta.append(_("tipo"))
	if not fecha:
		falta.append(_("fecha solicitada"))
	if not (descripcion or "").strip():
		falta.append(_("descripción"))
	if falta:
		frappe.throw(_("Falta: {0}.").format(", ".join(falta)), title=_("Entregable"))
	if getdate(fecha) < getdate(nowdate()):
		frappe.throw(_("La fecha solicitada debe ser hoy o una fecha futura."))
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"tipo_documento": doctype,
			"documento": nombre,
			"tipo_entregable": tipo_entregable,
			"fecha_solicitada_entrega": fecha,
			"descripcion_solicitud": frappe.utils.escape_html(descripcion.strip()),
		}
	)
	doc.insert()
	return doc.name
