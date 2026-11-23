"""Venta POS (factura de caja, sin orden de venta) con la que se gana una oportunidad.

Una sola regla para la lista que ve el asesor, el vínculo desde el tablero y
cualquier otro guardado (formulario, API, scripts): ``candidatas`` y
``validar_vinculo``. Así no hay atajo: poner a mano una factura en el campo
«Venta POS vinculada» pasa por las mismas condiciones.

Condiciones de la factura:
- POS, enviada, no es devolución y no tiene una devolución (nota de crédito) enviada;
- sin orden de venta en ninguna línea;
- del asesor de la oportunidad o de su cliente, en una empresa con la moneda de la
  oportunidad;
- con fecha desde la creación de la oportunidad (menos ``DIAS_ANTES_DE_LA_OPORTUNIDAD``)
  y de los últimos ``MESES_ATRAS`` meses;
- no ligada a otra oportunidad (además, el campo es único en la base).

Condiciones de la oportunidad: abierta (no Converted, Lost ni Closed), sin otra venta
POS y sin órdenes de venta.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, format_date, getdate

from crm_dashboard_v3.crm_tableros.common import consultas, ventas
from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_FACTURA_POS,
	CAMPO_ORDEN_DE_VENTA,
	STATUS_CERRADOS,
	DatosRelacionados,
)

MESES_ATRAS = 6
# Margen antes de la creación de la oportunidad: el asesor a veces la registra unos días
# después de que el cliente pagó en caja. Una semana cubre ese atraso sin dejar ligar
# ventas viejas que no tienen relación con la oportunidad.
DIAS_ANTES_DE_LA_OPORTUNIDAD = 7
MAX_CANDIDATAS = 50
TITULO = "Venta POS"  # se traduce al usarlo: _(TITULO)


def cliente_de(doc) -> str | None:
	"""Customer de la oportunidad (directo, o el creado desde su Lead)."""
	if doc.get("opportunity_from") == "Customer":
		return doc.get("party_name")
	if doc.get("opportunity_from") == "Lead":
		return frappe.db.get_value("Customer", {"lead_name": doc.get("party_name")}, "name")
	return None


def usuario_asesor(doc) -> str:
	return doc.get("asesor_comercial_user_id") or doc.get("owner")


def fecha_minima(doc):
	"""Fecha más antigua que puede tener la venta POS: la más reciente de los dos límites."""
	hoy = getdate()
	creada = getdate(doc.get("creation")) if doc.get("creation") else hoy
	return max(add_months(hoy, -MESES_ATRAS), add_days(creada, -DIAS_ANTES_DE_LA_OPORTUNIDAD))


def candidatas(doc, factura: str | None = None) -> list:
	"""Facturas POS que pueden cerrar la oportunidad como ganada (o solo ``factura``, si cumple).

	SQL directo: los asesores no siempre pueden leer Sales Invoice (solo las que crearon),
	y la venta pudo capturarla otro usuario a nombre del cliente. Solo se devuelven las
	del asesor de la oportunidad o las de su cliente, en las empresas con su moneda.
	"""
	params = {
		"companias": tuple(ventas.empresas_de_la_moneda(doc.company)),
		"usuario": usuario_asesor(doc),
		"cliente": cliente_de(doc) or "",
		"desde": fecha_minima(doc),
		"factura": factura or "",
	}
	solo = "and si.name = %(factura)s" if factura else ""
	return frappe.db.sql(
		f"""
		select si.name, si.company, si.posting_date, si.customer, si.customer_name, si.owner,
			si.base_net_total, si.pos_profile,
			(select sii.item_name from `tabSales Invoice Item` sii where sii.parent = si.name order by sii.idx limit 1) as producto,
			(select count(*) from `tabSales Invoice Item` sii where sii.parent = si.name) as lineas
		from `tabSales Invoice` si
		where si.docstatus = 1 and si.is_pos = 1 and si.is_return = 0
			and si.company in %(companias)s
			and (si.owner = %(usuario)s or si.customer = %(cliente)s)
			and si.posting_date >= %(desde)s
			and not exists (
				select 1 from `tabSales Invoice Item` x
				where x.parent = si.name and ifnull(x.sales_order, '') != ''
			)
			and not exists (
				select 1 from `tabSales Invoice` dev
				where dev.return_against = si.name and dev.is_return = 1 and dev.docstatus = 1
			)
			{solo}
		order by (si.customer = %(cliente)s) desc, si.posting_date desc, si.name desc
		limit {MAX_CANDIDATAS}
		""",
		params,
		as_dict=True,
	)


def motivo_oportunidad_cerrada(estado) -> str | None:
	"""Por qué la oportunidad (en su estado guardado) ya no acepta una venta POS; None si la acepta."""
	if estado.get("status") in STATUS_CERRADOS:
		return _("La oportunidad {0} ya está cerrada (status {1}).").format(estado.name, estado.status)
	if estado.get(CAMPO_FACTURA_POS):
		return _("La oportunidad {0} ya tiene la venta POS {1}.").format(estado.name, estado.get(CAMPO_FACTURA_POS))
	ordenes = [estado.get(CAMPO_ORDEN_DE_VENTA)] if estado.get(CAMPO_ORDEN_DE_VENTA) else []
	if not estado.is_new():
		ordenes += DatosRelacionados(estado.name).ordenes_de_venta
	if ordenes:
		return _("La oportunidad {0} ya tiene orden de venta ({1}).").format(estado.name, ", ".join(ordenes))
	return None


def validar_vinculo(doc, anterior=None):
	"""Valida en el servidor la venta POS que se está poniendo en ``doc`` (hook validate).

	``anterior`` es la oportunidad guardada (None si es nueva): sus datos deciden si
	todavía acepta una venta POS. Lanza ValidationError con el motivo.
	"""
	factura = doc.get(CAMPO_FACTURA_POS)
	if not factura:
		return
	motivo = motivo_oportunidad_cerrada(anterior if anterior is not None else doc)
	if motivo:
		frappe.throw(motivo, title=_(TITULO))
	if not candidatas(doc, factura):
		frappe.throw(
			_(
				"{0} no es una venta POS enviada, sin orden de venta ni devolución, del asesor o del cliente "
				"de la oportunidad y con fecha desde el {1}."
			).format(factura, format_date(fecha_minima(doc))),
			title=_(TITULO),
		)
	ligada = consultas.oportunidades_de_facturas_pos([factura]).get(factura)
	if ligada and ligada != doc.name:
		frappe.throw(_("La venta POS {0} ya está vinculada a {1}.").format(factura, ligada), title=_(TITULO))


def mensaje_de_duplicado(factura: str) -> str:
	"""Texto claro cuando el índice único rechaza la venta (otra petición la ligó al mismo tiempo)."""
	ligada = consultas.oportunidades_de_facturas_pos([factura]).get(factura)
	if ligada:
		return _("La venta POS {0} ya está vinculada a {1}.").format(factura, ligada)
	return _("La venta POS {0} se acaba de vincular a otra oportunidad.").format(factura)
