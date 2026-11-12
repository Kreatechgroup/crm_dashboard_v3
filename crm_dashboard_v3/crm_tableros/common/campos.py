"""Custom Fields que necesitan los tableros CRM (se crean en after_install / after_migrate)."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_FECHA_PROXIMO_PASO,
	CAMPO_FECHA_RETOMAR,
	CAMPO_ORDEN_DE_VENTA,
	CAMPO_PROXIMO_PASO,
)
from crm_dashboard_v3.crm_tableros.common.tableros import valores_de_etapa


def definicion_campos() -> dict:
	# La etapa es embudo_state_v2 (campo existente); aquí solo los campos nuevos.
	return {
		"Opportunity": [
			{
				"fieldname": CAMPO_FECHA_RETOMAR,
				"label": "Fecha para retomar",
				"fieldtype": "Date",
				"insert_after": CAMPO_ETAPA,
				"depends_on": f"eval:in_list({valores_de_etapa('pausa')!r}, doc.{CAMPO_ETAPA})",
			},
			{
				"fieldname": CAMPO_PROXIMO_PASO,
				"label": "Próximo paso",
				"fieldtype": "Data",
				"insert_after": CAMPO_FECHA_RETOMAR,
				"description": "Si está vacío, el tablero usa la última Opportunity Activity.",
			},
			{
				"fieldname": CAMPO_FECHA_PROXIMO_PASO,
				"label": "Fecha del próximo paso",
				"fieldtype": "Date",
				"insert_after": CAMPO_PROXIMO_PASO,
			},
			{
				"fieldname": CAMPO_ORDEN_DE_VENTA,
				"label": "Orden de venta vinculada",
				"fieldtype": "Link",
				"options": "Sales Order",
				"insert_after": CAMPO_FECHA_PROXIMO_PASO,
				"read_only": 1,
				"description": "Orden existente con la que se cerró como ganada (si no se creó desde su cotización).",
			},
		],
	}


def crear_campos():
	"""Idempotente: create_custom_fields actualiza si el campo ya existe."""
	create_custom_fields(definicion_campos(), update=True)
