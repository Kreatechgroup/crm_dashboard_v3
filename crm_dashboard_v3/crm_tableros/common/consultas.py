"""Consultas de oportunidades, actividades, cotizaciones y órdenes (con permisos de ERPNext).

Usan frappe.get_list, así que respetan los permisos del usuario. No hay límites
silenciosos: ``limit_page_length=0`` trae todo lo que corresponde al universo,
que ya está acotado por asesor, tablero (modelos y establecimientos), empresa y periodo.
"""

import frappe
from frappe.utils import flt, getdate

from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_FECHA_PROXIMO_PASO,
	CAMPO_FECHA_RETOMAR,
	CAMPO_PROXIMO_PASO,
	STATUS_CERRADOS,
)
from crm_dashboard_v3.crm_tableros.common.tableros import ConfigTablero

CAMPOS_OPORTUNIDAD = [
	"name",
	"title",
	"customer_name",
	"party_name",
	"opportunity_from",
	"status",
	"company",
	"sales_model",
	"establecimiento_lista",
	"tipo_de_oportunidad",
	"source",
	"opportunity_amount",
	"presupuesto_declarado_por_el_cliente",
	"fecha_estimada_aprobacion",
	"expected_closing",
	"probability",
	"creation",
	"modified",
	"owner",
	"asesor_comercial_user_id",
	"lost_reason",
	CAMPO_ETAPA,
	CAMPO_FECHA_RETOMAR,
	CAMPO_PROXIMO_PASO,
	CAMPO_FECHA_PROXIMO_PASO,
]


def _filtro_usuarios(usuarios: list[str]) -> list:
	# Correo completo, nunca por prefijo.
	return [
		["Opportunity", "owner", "in", usuarios],
		["Opportunity", "asesor_comercial_user_id", "in", usuarios],
	]


def _filtros_tablero(t: ConfigTablero, company: str | None) -> list:
	filtros = [
		["Opportunity", "sales_model", "in", list(t.sales_models)],
		["Opportunity", "establecimiento_lista", "in", list(t.establecimientos)],
	]
	if company:
		filtros.append(["Opportunity", "company", "=", company])
	return filtros


def asesor_de(row, usuarios: list[str]) -> str:
	"""Usuario del asesor al que se atribuye la oportunidad."""
	if row.get("asesor_comercial_user_id") in usuarios:
		return row.asesor_comercial_user_id
	return row.owner


def oportunidades_abiertas(usuarios: list[str], t: ConfigTablero, company: str | None) -> list:
	"""Universo: oportunidades del tablero, del asesor, con status distinto de Lost/Converted/Closed."""
	if not usuarios:
		return []
	return frappe.get_list(
		"Opportunity",
		filters=_filtros_tablero(t, company) + [["Opportunity", "status", "not in", list(STATUS_CERRADOS)]],
		or_filters=_filtro_usuarios(usuarios),
		fields=CAMPOS_OPORTUNIDAD,
		order_by="modified desc",
		limit_page_length=0,
	)


def oportunidades_cerradas(usuarios: list[str], t: ConfigTablero, company: str | None, desde, hasta) -> list:
	"""Ganadas y perdidas cuyo último cambio cae dentro del periodo."""
	if not usuarios:
		return []
	return frappe.get_list(
		"Opportunity",
		filters=_filtros_tablero(t, company)
		+ [
			["Opportunity", "status", "in", ["Converted", "Lost"]],
			["Opportunity", "modified", "between", [desde, hasta]],
		],
		or_filters=_filtro_usuarios(usuarios),
		fields=CAMPOS_OPORTUNIDAD,
		order_by="modified desc",
		limit_page_length=0,
	)


def oportunidades_creadas(usuarios: list[str], t: ConfigTablero, company: str | None, desde, hasta) -> list:
	"""Oportunidades creadas en el rango (para conteos por mes y estado)."""
	if not usuarios:
		return []
	return frappe.get_list(
		"Opportunity",
		filters=_filtros_tablero(t, company) + [["Opportunity", "creation", "between", [desde, hasta]]],
		or_filters=_filtro_usuarios(usuarios),
		fields=["name", "status", "sales_model", "creation", "owner", "asesor_comercial_user_id"],
		order_by="creation asc",
		limit_page_length=0,
	)


def ultimas_actividades(oportunidades: list[str]) -> dict:
	"""Oportunidad -> su Opportunity Activity más reciente (tipo, fecha y próximo contacto)."""
	if not oportunidades:
		return {}
	filas = frappe.get_list(
		"Opportunity Activity",
		filters={"opportunity": ["in", oportunidades]},
		fields=["opportunity", "activity_type", "next_contact_date", "created_on"],
		order_by="created_on desc",
		limit_page_length=0,
	)
	ultimas = {}
	for fila in filas:
		ultimas.setdefault(fila.opportunity, fila)
	return ultimas


def montos_de_cotizacion(oportunidades: list[str]) -> dict:
	"""Oportunidad -> monto de su cotización enviada más alta (monto provisional)."""
	if not oportunidades:
		return {}
	filas = frappe.get_list(
		"Quotation",
		filters={
			"opportunity": ["in", oportunidades],
			"docstatus": 1,
			"status": ["not in", ["Lost", "Cancelled"]],
		},
		fields=["opportunity", "max(base_grand_total) as monto"],
		group_by="opportunity",
		limit_page_length=0,
	)
	return {f.opportunity: flt(f.monto) for f in filas}


def cotizaciones_vencidas(oportunidades: list[str], hoy) -> list:
	"""Cotizaciones enviadas, vencidas y sin orden de venta, de oportunidades activas.

	Una vencida deja de contar cuando se renueva (existe una cotización enviada
	posterior y vigente para la misma oportunidad) o cuando se da por perdida.
	"""
	if not oportunidades:
		return []
	vencidas = frappe.get_list(
		"Quotation",
		filters={
			"opportunity": ["in", oportunidades],
			"docstatus": 1,
			"valid_till": ["<", hoy],
			"status": ["not in", ["Ordered", "Partially Ordered", "Lost", "Cancelled"]],
		},
		fields=[
			"name",
			"opportunity",
			"customer_name",
			"party_name",
			"base_grand_total",
			"valid_till",
			"transaction_date",
			"creation",
		],
		order_by="base_grand_total desc",
		limit_page_length=0,
	)
	if not vencidas:
		return []
	vigentes = frappe.get_list(
		"Quotation",
		filters={
			"opportunity": ["in", list({v.opportunity for v in vencidas})],
			"docstatus": 1,
			"valid_till": [">=", hoy],
			"status": ["not in", ["Lost", "Cancelled"]],
		},
		fields=["opportunity", "creation"],
		limit_page_length=0,
	)
	renovada = {}
	for v in vigentes:
		renovada[v.opportunity] = max(renovada.get(v.opportunity, v.creation), v.creation)
	return [
		v
		for v in vencidas
		if not (v.opportunity in renovada and renovada[v.opportunity] > v.creation)
		and getdate(v.valid_till) < getdate(hoy)
	]


# ---------------------------------------------------------------------------
# Documentos del consolidado (cotizaciones y órdenes de venta)
# ---------------------------------------------------------------------------

CAMPOS_COTIZACION = [
	"name",
	"owner",
	"transaction_date",
	"valid_till",
	"customer_name",
	"party_name",
	"sales_model",
	"status",
	"opportunity",
	"base_net_total",
]


def cotizaciones_del_periodo(usuarios: list[str], t: ConfigTablero, company: str | None, desde, hasta) -> list:
	"""Cotizaciones enviadas en el rango, hechas por los asesores, de los modelos del tablero."""
	if not usuarios:
		return []
	filtros = {
		"docstatus": 1,
		"owner": ["in", usuarios],
		"sales_model": ["in", list(t.sales_models)],
		"transaction_date": ["between", [desde, hasta]],
	}
	if company:
		filtros["company"] = company
	return frappe.get_list(
		"Quotation", filters=filtros, fields=CAMPOS_COTIZACION, order_by="transaction_date asc", limit_page_length=0
	)


def cotizaciones_vigentes(usuarios: list[str], t: ConfigTablero, company: str | None, hoy) -> list:
	"""Cotizaciones enviadas, abiertas y vigentes hoy."""
	if not usuarios:
		return []
	filtros = {
		"docstatus": 1,
		"owner": ["in", usuarios],
		"sales_model": ["in", list(t.sales_models)],
		"valid_till": [">=", hoy],
		"status": ["not in", ["Ordered", "Lost", "Cancelled", "Expired"]],
	}
	if company:
		filtros["company"] = company
	return frappe.get_list(
		"Quotation", filters=filtros, fields=CAMPOS_COTIZACION, order_by="transaction_date asc", limit_page_length=0
	)


def ordenes_del_periodo(sales_persons: list[str], company: str | None, desde, hasta) -> list:
	"""Órdenes de venta del rango atribuidas por la tabla Comisiones Asesor (una fila por Sales Person)."""
	if not sales_persons:
		return []
	filtros = [
		["Sales Order", "docstatus", "=", 1],
		["Sales Order", "transaction_date", "between", [desde, hasta]],
		["Comisiones Asesores", "asesor", "in", sales_persons],
	]
	if company:
		filtros.append(["Sales Order", "company", "=", company])
	return frappe.get_list(
		"Sales Order",
		filters=filtros,
		fields=[
			"name",
			"transaction_date",
			"customer_name",
			"sales_model_1",
			"base_net_total",
			"per_billed",
			"`tabComisiones Asesores`.asesor as asesor",
			"`tabComisiones Asesores`.distribucion as distribucion",
		],
		order_by="transaction_date asc",
		limit_page_length=0,
	)


def cadena_de_ordenes(ordenes: list[str]) -> dict[str, dict]:
	"""Orden de venta -> cotización y oportunidad de las que viene, y facturas que la cobran.

	get_all sobre las tablas hijas: solo se leen nombres de documentos ligados a
	órdenes que el usuario ya pudo listar con permisos.
	"""
	if not ordenes:
		return {}
	cadena = {o: {"cotizacion": None, "oportunidad": None, "facturas": []} for o in ordenes}
	items = frappe.get_all(
		"Sales Order Item",
		filters={"parent": ["in", ordenes], "prevdoc_docname": ["is", "set"]},
		fields=["parent", "prevdoc_docname"],
	)
	for i in items:
		cadena[i.parent]["cotizacion"] = cadena[i.parent]["cotizacion"] or i.prevdoc_docname
	cotizaciones = list({c["cotizacion"] for c in cadena.values() if c["cotizacion"]})
	oportunidad_de = dict(
		frappe.get_all(
			"Quotation", filters={"name": ["in", cotizaciones or [""]]}, fields=["name", "opportunity"], as_list=True
		)
	)
	for c in cadena.values():
		c["oportunidad"] = oportunidad_de.get(c["cotizacion"])
	facturas = frappe.get_all(
		"Sales Invoice Item",
		filters={"sales_order": ["in", ordenes], "docstatus": 1},
		fields=["sales_order", "parent"],
		distinct=True,
	)
	for f in facturas:
		if f.parent not in cadena[f.sales_order]["facturas"]:
			cadena[f.sales_order]["facturas"].append(f.parent)
	return cadena
