"""Venta facturada atribuida a asesores y su comisión (agregada en servidor).

Atribución (igual que el reporte de comisiones de Plus):
- Por la tabla Comisiones Asesor (``comisiones_asesor``) de la orden de venta de
  cada línea de la factura: Σ base_net_amount × distribución.
- Más las facturas que el asesor creó sin orden de venta (100%).
Las notas de crédito (montos negativos) restan.

El modelo de venta de cada factura es el «Modelo de Venta» de su orden
(``sales_model_1``); si la orden no lo tiene, el del Sales Person. Las facturas
sin orden toman el modelo por defecto del tablero.

SQL directo: es una agregación sobre las ventas del propio asesor (o de los
asesores de la tienda, para un jefe ya validado por la API). Solo se devuelven
los datos de esas facturas, que se abren luego en ERPNext con sus permisos normales.
"""

from collections import defaultdict

import frappe
from frappe.utils import flt, getdate


def facturas_atribuidas(
	sales_persons: dict[str, str], usuario: str, company: str, desde, hasta, modelo_por_defecto: str
) -> list[frappe._dict]:
	"""Una fila por factura y Sales Person (o por factura propia sin orden)."""
	if not company or not (sales_persons or usuario):
		return []
	params = {
		"company": company,
		"desde": desde,
		"hasta": hasta,
		"sps": tuple(sales_persons) or ("",),
		"usuario": usuario or "",
	}
	por_orden = frappe.db.sql(
		"""
		select si.name, si.posting_date, si.customer_name, si.is_return,
			si.base_grand_total, si.outstanding_amount,
			so.name as sales_order, so.sales_model_1 as modelo_orden,
			ca.asesor, ca.distribucion,
			sum(sii.base_net_amount) as neto
		from `tabSales Invoice` si
		join `tabSales Invoice Item` sii on sii.parent = si.name
		join `tabSales Order` so on so.name = sii.sales_order
		join `tabComisiones Asesores` ca
			on ca.parent = so.name and ca.parenttype = 'Sales Order'
		where si.docstatus = 1 and si.company = %(company)s
			and si.posting_date between %(desde)s and %(hasta)s
			and ca.asesor in %(sps)s
		group by si.name, so.name, ca.name
		""",
		params,
		as_dict=True,
	)
	propias = frappe.db.sql(
		"""
		select si.name, si.posting_date, si.customer_name, si.is_return,
			si.base_grand_total, si.outstanding_amount, si.base_net_total as neto
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
	tasas = _tasas_de_comision(list(sales_persons))
	sp_por_modelo = {}
	for sp, modelo in sales_persons.items():
		sp_por_modelo.setdefault(modelo, sp)

	filas = []
	for f in por_orden:
		modelo = f.modelo_orden or sales_persons.get(f.asesor) or modelo_por_defecto
		filas.append(_fila(f, modelo, f.asesor, flt(f.distribucion), tasas.get(f.asesor, 0)))
	for f in propias:
		sp = sp_por_modelo.get(modelo_por_defecto)
		filas.append(_fila(f, modelo_por_defecto, sp, 100, tasas.get(sp, 0), propia=True))
	return sorted(filas, key=lambda x: (x.fecha, x.name))


def _fila(f, modelo, sales_person, distribucion, tasa, propia=False) -> frappe._dict:
	neto = flt(f.neto)
	atribuido = neto * distribucion / 100
	gran_total = flt(f.base_grand_total)
	# Parte cobrada sin IVA: neto × (total − saldo) ÷ total.
	cobrado = neto * (gran_total - flt(f.outstanding_amount)) / gran_total if gran_total else 0
	base = cobrado * distribucion / 100
	return frappe._dict(
		name=f.name,
		fecha=getdate(f.posting_date),
		cliente=f.customer_name,
		modelo=modelo,
		sales_order=f.get("sales_order"),
		sales_person=sales_person,
		propia=propia,
		nota_de_credito=bool(f.is_return),
		distribucion=distribucion,
		neto=neto,
		gran_total=gran_total,
		saldo=flt(f.outstanding_amount),
		monto=atribuido,
		cobrado=cobrado,
		tasa=flt(tasa),
		comision=base * flt(tasa) / 100,
		comision_futura=(atribuido - base) * flt(tasa) / 100,
		por_cobrar=atribuido - base,
	)


def _tasas_de_comision(sales_persons: list[str]) -> dict[str, float]:
	if not sales_persons:
		return {}
	# get_all: solo la tasa de los Sales Person del propio asesor (o de su tienda, para un jefe).
	return {
		s.name: flt(s.commission_rate)
		for s in frappe.get_all(
			"Sales Person", filters={"name": ["in", sales_persons]}, fields=["name", "commission_rate"]
		)
	}


def facturado(sales_persons: dict[str, str], usuario: str, company: str, desde, hasta, modelo_por_defecto: str) -> dict:
	"""Total facturado del periodo y las facturas que lo forman."""
	filas = facturas_atribuidas(sales_persons, usuario, company, desde, hasta, modelo_por_defecto)
	return {"monto": sum(f.monto for f in filas), "facturas": sorted({f.name for f in filas}), "filas": filas}


def por_mes(filas: list) -> dict[tuple[str, str], float]:
	"""(YYYY-MM, modelo) -> monto atribuido."""
	totales = defaultdict(float)
	for f in filas:
		totales[(f.fecha.strftime("%Y-%m"), f.modelo)] += f.monto
	return totales
