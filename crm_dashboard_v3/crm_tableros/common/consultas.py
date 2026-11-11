"""Consultas de oportunidades, actividades y cotizaciones (con permisos de ERPNext).

Todas usan frappe.get_list, así que respetan los permisos del usuario. No hay
límites silenciosos: ``limit_page_length=0`` trae todo lo que corresponde al
universo (que ya está acotado por asesor, modelo de venta y periodo).
"""

import frappe
from frappe.utils import flt, getdate

from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA, CAMPO_FECHA_RETOMAR, STATUS_CERRADOS

CAMPOS_OPORTUNIDAD = [
	"name",
	"title",
	"customer_name",
	"party_name",
	"opportunity_from",
	"status",
	"company",
	"tipo_de_oportunidad",
	"source",
	"opportunity_amount",
	"presupuesto_declarado_por_el_cliente",
	"fecha_estimada_aprobacion",
	"expected_closing",
	"probability",
	"modified",
	"owner",
	"asesor_comercial_user_id",
	"embudo_state_v2",
	"lost_reason",
	CAMPO_ETAPA,
	CAMPO_FECHA_RETOMAR,
]


def _filtro_usuarios(usuarios: list[str]) -> list:
	# Correo completo, nunca por prefijo.
	return [
		["Opportunity", "owner", "in", usuarios],
		["Opportunity", "asesor_comercial_user_id", "in", usuarios],
	]


def oportunidades_abiertas(usuarios: list[str], sales_model: str, company: str | None) -> list:
	"""Universo: oportunidades del modelo, del asesor, con status distinto de Lost/Converted/Closed."""
	if not usuarios:
		return []
	filtros = [
		["Opportunity", "sales_model", "=", sales_model],
		["Opportunity", "status", "not in", list(STATUS_CERRADOS)],
	]
	if company:
		filtros.append(["Opportunity", "company", "=", company])
	return frappe.get_list(
		"Opportunity",
		filters=filtros,
		or_filters=_filtro_usuarios(usuarios),
		fields=CAMPOS_OPORTUNIDAD,
		order_by="modified desc",
		limit_page_length=0,
	)


def oportunidades_cerradas(usuarios: list[str], sales_model: str, company: str | None, desde, hasta) -> list:
	"""Ganadas y perdidas cuyo último cambio cae dentro del periodo."""
	if not usuarios:
		return []
	filtros = [
		["Opportunity", "sales_model", "=", sales_model],
		["Opportunity", "status", "in", ["Converted", "Lost"]],
		["Opportunity", "modified", "between", [desde, hasta]],
	]
	if company:
		filtros.append(["Opportunity", "company", "=", company])
	return frappe.get_list(
		"Opportunity",
		filters=filtros,
		or_filters=_filtro_usuarios(usuarios),
		fields=CAMPOS_OPORTUNIDAD,
		order_by="modified desc",
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
