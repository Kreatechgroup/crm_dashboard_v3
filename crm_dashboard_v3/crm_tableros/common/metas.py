"""Lectura de la Tabla de metas (reutilizable por Retail)."""

import frappe
from frappe.utils import flt


def metas_vigentes(sales_persons: list[str], tipo_de_meta: str, desde, hasta, company: str | None = None) -> list:
	"""Metas aprobadas y activas cuya vigencia se cruza con el periodo.

	Una meta que abarca varios meses aplica completa en cada mes.
	get_all: los asesores no tienen permiso de lectura sobre Tabla de metas y
	necesitan ver su propia meta; solo se consultan sus Sales Person.
	"""
	if not sales_persons:
		return []
	filtros = {
		"docstatus": 1,
		"disabled": 0,
		"asesor": ["in", sales_persons],
		"tipo_de_meta": tipo_de_meta,
		"date_from": ["<=", hasta],
	}
	if company:
		filtros["company"] = company
	metas = frappe.get_all(
		"Tabla de metas",
		filters=filtros,
		fields=["name", "asesor", "valor_deseado", "date_from", "date_to"],
	)
	# date_to vacío = vigente sin fecha de fin.
	return [m for m in metas if not m.date_to or m.date_to >= desde]


def meta_total(sales_persons: list[str], tipo_de_meta: str, desde, hasta, company: str | None = None) -> dict:
	metas = metas_vigentes(sales_persons, tipo_de_meta, desde, hasta, company)
	return {"monto": sum(flt(m.valor_deseado) for m in metas), "metas": [m.name for m in metas]}
