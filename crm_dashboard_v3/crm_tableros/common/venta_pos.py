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
POS, sin órdenes de venta y en una etapa que acepte venta POS (``Etapa.acepta_venta_pos``
de su tablero; en Proyectos: 1 · Calificar, 2 · Requerimiento y diseño y En pausa).

Si la venta se cancela o se devuelve después de ganar, la oportunidad **no** se toca
(decisión del negocio): se deja un comentario y el tablero la marca para revisión.
Quien cancela o devuelve queda como autor del comentario (Frappe lo muestra con su nombre).
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
	etapa_efectiva,
)
from crm_dashboard_v3.crm_tableros.common.tableros import tablero_de_oportunidad

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


def acepta_venta_pos(estado) -> bool:
	"""La etapa de la oportunidad (en su estado guardado) permite ganar con una venta POS.

	Las oportunidades fuera de un tablero no tienen etapas propias: no se restringen.
	"""
	t = tablero_de_oportunidad(estado)
	return not t or etapa_efectiva(estado, t.etapas).acepta_venta_pos


def motivo_etapa_sin_venta_pos(estado) -> str | None:
	"""Por qué la etapa de la oportunidad no acepta una venta POS; None si la acepta."""
	if acepta_venta_pos(estado):
		return None
	cfg = tablero_de_oportunidad(estado).etapas
	return _(
		"La oportunidad {0} está en «{1}», donde no se puede ganar con una venta POS: ciérrala como "
		"ganada con una orden de venta. La venta POS solo se vincula en: {2}."
	).format(
		estado.name,
		etapa_efectiva(estado, cfg).titulo,
		", ".join(e.titulo for e in cfg.etapas_con_venta_pos),
	)


def validar_vinculo(doc, anterior=None):
	"""Valida en el servidor la venta POS que se está poniendo en ``doc`` (hook validate).

	``anterior`` es la oportunidad guardada (None si es nueva): sus datos deciden si
	todavía acepta una venta POS. Lanza ValidationError con el motivo.
	"""
	factura = doc.get(CAMPO_FACTURA_POS)
	if not factura:
		return
	estado = anterior if anterior is not None else doc
	motivo = motivo_oportunidad_cerrada(estado) or motivo_etapa_sin_venta_pos(estado)
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


# ---------------------------------------------------------------------------
# Venta cancelada o devuelta después de ganar: comentario y marca para revisión
# ---------------------------------------------------------------------------


def para_revision(facturas: list[str]) -> dict[str, str]:
	"""Factura POS -> por qué su oportunidad está para revisión (cancelada o con devolución).

	SQL directo: solo se consultan las facturas ya ligadas a oportunidades que el
	usuario puede ver; se devuelve el motivo, no datos de la factura.
	"""
	if not facturas:
		return {}
	filas = frappe.db.sql(
		"""
		select si.name, si.docstatus,
			(select dev.name from `tabSales Invoice` dev
				where dev.return_against = si.name and dev.is_return = 1 and dev.docstatus = 1
				order by dev.posting_date, dev.name limit 1) as devolucion
		from `tabSales Invoice` si
		where si.name in %(facturas)s
		""",
		{"facturas": tuple(facturas)},
		as_dict=True,
	)
	motivos = {}
	for f in filas:
		if f.docstatus == 2:
			motivos[f.name] = _("Venta POS {0} cancelada").format(f.name)
		elif f.devolucion:
			motivos[f.name] = _("Venta POS {0} devuelta (nota de crédito {1})").format(f.name, f.devolucion)
	return motivos


# Savepoint del aviso: si el comentario falla se deshace solo lo suyo, no la operación de caja.
_SAVEPOINT_AVISO = "crm_aviso_venta_pos"


def _comentar(factura: str, texto: str):
	"""Comentario en cada oportunidad ganada con ``factura``.

	ignore_permissions: quien cancela o devuelve en caja no suele tener permiso sobre la
	oportunidad, y el comentario es solo un registro para el asesor y su jefe.

	Corre dentro de on_cancel / on_submit de Sales Invoice en todas las empresas: la
	cancelación o la nota de crédito nunca dependen de este aviso. Si falla, se deshace
	lo que el aviso alcanzó a escribir, se quitan sus mensajes y se registra en Error Log.
	"""
	mensajes = len(frappe.message_log)
	oportunidad = None
	frappe.db.savepoint(_SAVEPOINT_AVISO)
	try:
		for oportunidad in consultas.oportunidades_de_facturas_pos([factura]).values():
			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Comment",
					"reference_doctype": "Opportunity",
					"reference_name": oportunidad,
					"content": texto,
				}
			).insert(ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point=_SAVEPOINT_AVISO)
		del frappe.message_log[mensajes:]
		titulo = (
			_("CRM: no se pudo comentar la venta POS {0} en la oportunidad {1}").format(factura, oportunidad)
			if oportunidad
			else _("CRM: no se pudo comentar la venta POS {0} en su oportunidad").format(factura)
		)
		frappe.log_error(
			title=titulo,
			reference_doctype="Sales Invoice",
			reference_name=factura,
		)


def avisar_cancelacion(doc, method=None):
	"""Hook on_cancel de Sales Invoice: la venta POS (o su devolución) se canceló."""
	if doc.get("is_return") and doc.get("return_against"):
		_comentar(
			doc.return_against,
			_("Se canceló la devolución {0} de la venta POS {1}. La oportunidad no se modificó.").format(
				doc.name, doc.return_against
			),
		)
		return
	_comentar(
		doc.name,
		_(
			"La venta POS {0} con la que se ganó esta oportunidad se canceló. La oportunidad no se "
			"modificó: queda para revisión en el tablero."
		).format(doc.name),
	)


def avisar_devolucion(doc, method=None):
	"""Hook on_submit de Sales Invoice: devolución (nota de crédito) contra una venta POS ligada."""
	if not (doc.get("is_return") and doc.get("return_against")):
		return
	_comentar(
		doc.return_against,
		_(
			"Se registró la devolución {0} contra la venta POS {1} con la que se ganó esta oportunidad. "
			"La oportunidad no se modificó: queda para revisión en el tablero."
		).format(doc.name, doc.return_against),
	)
