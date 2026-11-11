"""Custom Fields que necesitan los tableros CRM (se crean en after_install / after_migrate)."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_FECHA_RETOMAR,
	titulos_de_todas_las_etapas,
)


def definicion_campos() -> dict:
	return {
		"Opportunity": [
			{
				"fieldname": CAMPO_ETAPA,
				"label": "Etapa CRM",
				"fieldtype": "Select",
				"options": "\n" + "\n".join(titulos_de_todas_las_etapas()),
				"insert_after": "embudo_state_v2",
				"in_standard_filter": 1,
				"in_list_view": 1,
				"description": "La probabilidad y el status se ajustan solos según la etapa.",
			},
			{
				"fieldname": CAMPO_FECHA_RETOMAR,
				"label": "Fecha para retomar",
				"fieldtype": "Date",
				"insert_after": CAMPO_ETAPA,
				"depends_on": f"eval:doc.{CAMPO_ETAPA}=='En pausa'",
			},
		],
	}


def crear_campos():
	"""Idempotente: create_custom_fields actualiza si el campo ya existe."""
	create_custom_fields(definicion_campos(), update=True)
