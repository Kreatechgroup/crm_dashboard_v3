"""Venta facturada atribuida a asesores (agregada en servidor)."""

import frappe
from frappe.utils import flt


def facturado(sales_persons: list[str], usuario: str, company: str, desde, hasta) -> dict:
	"""Facturas del periodo atribuidas al asesor.

	- Por la tabla Comisiones Asesor (``comisiones_asesor``) de la orden de venta de
	  cada línea: Σ base_net_amount × distribución.
	- Más las facturas que el asesor creó sin orden de venta.
	Las notas de crédito (montos negativos) restan.

	SQL directo: es una agregación sobre las ventas del propio asesor (o de los
	asesores de la tienda, para un jefe ya validado por la API). Solo se devuelve
	el total y los nombres de las facturas, que se abren luego en la lista de
	ERPNext con sus permisos normales.
	"""
	if not company or not (sales_persons or usuario):
		return {"monto": 0, "facturas": []}
	params = {
		"company": company,
		"desde": desde,
		"hasta": hasta,
		"sps": tuple(sales_persons) or ("",),
		"usuario": usuario or "",
	}
	filas = frappe.db.sql(
		"""
		select si.name, sum(sii.base_net_amount * ca.distribucion / 100) as monto
		from `tabSales Invoice` si
		join `tabSales Invoice Item` sii on sii.parent = si.name
		join `tabComisiones Asesores` ca
			on ca.parent = sii.sales_order and ca.parenttype = 'Sales Order'
		where si.docstatus = 1 and si.company = %(company)s
			and si.posting_date between %(desde)s and %(hasta)s
			and ca.asesor in %(sps)s
		group by si.name

		union all

		select si.name, si.base_net_total as monto
		from `tabSales Invoice` si
		where si.docstatus = 1 and si.company = %(company)s
			and si.posting_date between %(desde)s and %(hasta)s
			and si.owner = %(usuario)s
			and not exists (
				select 1 from `tabSales Invoice Item` x
				where x.parent = si.name and ifnull(x.sales_order, '') != ''
			)
		""",
		params,
		as_dict=True,
	)
	return {"monto": sum(flt(f.monto) for f in filas), "facturas": sorted({f.name for f in filas})}
