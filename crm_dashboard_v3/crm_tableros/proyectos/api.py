"""Métodos whitelisted del tablero CRM Proyectos (asesores de Plus).

Todo el cálculo se hace en el servidor; la página solo pinta lo que devuelven
estos métodos y llama a las acciones.

- Un asesor ve solo lo suyo (sus dos Sales Person, Proyectos y Retail).
- Un jefe de Plus ve la tienda completa o a un asesor elegido.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate

from crm_dashboard_v3.crm_tableros.common import acciones, alcance, entregables, etapas, flujo
from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_FECHA_PROXIMO_PASO,
	CAMPO_FECHA_RETOMAR,
	CAMPO_ORDEN_DE_VENTA,
	CAMPO_PROXIMO_PASO,
)
from crm_dashboard_v3.crm_tableros.common.formato import nombres_de_usuarios
from crm_dashboard_v3.crm_tableros.proyectos import consolidado, embudo, historico
from crm_dashboard_v3.crm_tableros.proyectos.config import TABLERO

HISTORIAL_POR_PAGINA = 50
# Órdenes de venta del cliente que se ofrecen para vincular al cerrar como ganada.
MESES_ORDENES_PARA_VINCULAR = 6
CAMPOS_EDITABLES = (
	"presupuesto_declarado_por_el_cliente",
	"fecha_estimada_aprobacion",
	"source",
	"tipo_de_oportunidad",
	CAMPO_PROXIMO_PASO,
	CAMPO_FECHA_PROXIMO_PASO,
)


# ---------------------------------------------------------------------------
# Tablero (el alcance —quién mira y a quién— lo resuelve common/alcance.py)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_tablero(mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None):
	a = alcance.obtener(TABLERO, mes, asesor, establecimiento)
	if a.mensaje:
		return a.base
	return {**a.base, **embudo.construir(a.tablero, a.ctx, a.seleccion, con_resumen=a.vista_tienda)}


@frappe.whitelist()
def get_consolidado(mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None):
	a = alcance.obtener(TABLERO, mes, asesor, establecimiento)
	if a.mensaje:
		return a.base
	return {**a.base, **consolidado.construir(a.tablero, a.ctx, a.seleccion, a.vista_tienda)}


@frappe.whitelist()
def get_historico(mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None):
	a = alcance.obtener(TABLERO, mes, asesor, establecimiento)
	if a.mensaje:
		return a.base
	return {**a.base, **historico.construir(a.tablero, a.ctx, a.seleccion)}


# ---------------------------------------------------------------------------
# Detalle de una oportunidad
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_oportunidad(nombre: str, pagina_historial: int = 0):
	t = TABLERO
	cfg = t.etapas
	doc = acciones.oportunidad_del_tablero(nombre, t)
	rel = etapas.DatosRelacionados(doc.name)
	etapa = etapas.etapa_efectiva(doc, cfg)
	hoy = getdate()

	cerrada = bool(etapa.status) and doc.status == etapa.status
	if cerrada:
		siguiente = anterior = None
	elif etapa.clave == "pausa":
		siguiente, anterior = _etapa_para_retomar(doc, cfg, rel), None
	else:
		siguiente, anterior = cfg.siguiente(etapa.clave), cfg.anterior(etapa.clave)

	pagina = max(0, int(pagina_historial or 0))
	total_historial = frappe.db.count("Opportunity Activity", {"opportunity": doc.name})
	historial = frappe.get_list(
		"Opportunity Activity",
		filters={"opportunity": doc.name},
		fields=["name", "created_on", "activity_type", "comment", "next_contact_date", "owner"],
		order_by="created_on desc",
		start=pagina * HISTORIAL_POR_PAGINA,
		page_length=HISTORIAL_POR_PAGINA,
	)
	autores = nombres_de_usuarios([h.owner for h in historial] + [doc.owner, doc.get("asesor_comercial_user_id")])
	paso = etapas.proximo_paso_de(doc, rel.ultima_actividad)
	cotizacion_para_orden = next(
		(q.name for q in rel.cotizaciones_enviadas if q.status != "Ordered" and getdate(q.valid_till) >= hoy),
		None,
	)
	asesor_usuario = doc.get("asesor_comercial_user_id") or doc.owner
	ultima = getdate(doc.modified)
	if rel.ultima_actividad and rel.ultima_actividad.created_on:
		ultima = max(ultima, getdate(rel.ultima_actividad.created_on))
	cotizacion_vigente = next((q for q in rel.cotizaciones_enviadas if q.name == cotizacion_para_orden), None)

	meta_op = frappe.get_meta("Opportunity")
	meta_act = frappe.get_meta("Opportunity Activity")
	return {
		"name": doc.name,
		"cliente": doc.customer_name or doc.title or doc.party_name,
		"modelo": doc.get("sales_model"),
		"status": doc.status,
		"etapa": {"clave": etapa.clave, "titulo": etapa.titulo, "probabilidad": etapa.probabilidad},
		"cerrada": cerrada,
		"incoherente": etapas.es_incoherente(doc, cfg),
		"asesor": autores.get(asesor_usuario, ""),
		"dias": max(0, (hoy - ultima).days),
		"tipo_de_oportunidad": doc.get("tipo_de_oportunidad"),
		"source": doc.get("source"),
		"presupuesto_declarado_por_el_cliente": flt(doc.get("presupuesto_declarado_por_el_cliente")),
		"opportunity_amount": flt(doc.opportunity_amount),
		"monto": etapas.monto_de(doc, cfg, rel.monto_cotizacion),
		"fecha_estimada_aprobacion": doc.get("fecha_estimada_aprobacion"),
		"fecha_retomar": doc.get(CAMPO_FECHA_RETOMAR),
		"lost_reason": doc.get("lost_reason"),
		"proximo_paso": {
			"texto": paso.texto,
			"fecha": str(paso.fecha) if paso.fecha else None,
			"vencido": bool(paso.fecha and paso.fecha < hoy),
			# Si los campos propios están vacíos, el paso viene de la última actividad.
			"de_actividad": not (doc.get(CAMPO_PROXIMO_PASO) or doc.get(CAMPO_FECHA_PROXIMO_PASO)),
		},
		"cotizaciones": [
			{"name": q.name, "monto": flt(q.base_grand_total), "valid_till": q.valid_till, "status": q.status}
			for q in rel.cotizaciones
		],
		"ordenes_de_venta": rel.ordenes_de_venta + ([doc.get(CAMPO_ORDEN_DE_VENTA)] if etapas.orden_vinculada(doc) else []),
		"cotizacion_para_orden": cotizacion_para_orden,
		"monto_cotizacion_para_orden": flt(cotizacion_vigente.base_grand_total) if cotizacion_vigente else 0,
		"ordenes_del_cliente": _ordenes_del_cliente(doc) if not cerrada else [],
		"entregables": entregables.de_documento("Opportunity", doc.name, hoy),
		"siguiente": _etapa_con_faltantes(doc, siguiente, cfg, rel),
		"anterior": _etapa_con_faltantes(doc, anterior, cfg, rel),
		"puede_pausar": not cerrada and etapa.clave != "pausa",
		# Mensaje si el workflow de embudo_state_v2 no permite pausar o perder desde la etapa actual.
		"bloqueos": {
			clave: flujo.bloqueo(doc, cfg.etapa(clave).valor) if not cerrada else None for clave in ("pausa", "perdida")
		},
		"historial": [
			{
				"fecha": h.created_on,
				"tipo": h.activity_type,
				"comentario": h.comment,
				"proximo": h.next_contact_date,
				"autor": autores.get(h.owner, ""),
			}
			for h in historial
		],
		"historial_total": total_historial,
		"historial_pagina": pagina,
		"historial_por_pagina": HISTORIAL_POR_PAGINA,
		"opciones": {
			"tipos": _opciones_select(meta_op, "tipo_de_oportunidad"),
			"origenes": frappe.get_list("Lead Source", pluck="name", order_by="name asc", limit_page_length=0),
			"tipos_actividad": _opciones_select(meta_act, "activity_type"),
			"motivos": acciones.motivos_de_perdida(cfg),
			"tipos_entregable": entregables.tipos(),
		},
	}


def _cliente_de(doc) -> str | None:
	"""Customer de la oportunidad (directo, o el creado desde su Lead)."""
	if doc.opportunity_from == "Customer":
		return doc.party_name
	if doc.opportunity_from == "Lead":
		return frappe.db.get_value("Customer", {"lead_name": doc.party_name}, "name")
	return None


def _ordenes_del_cliente(doc) -> list[dict]:
	"""Órdenes de venta enviadas del cliente en los últimos meses, con la oportunidad a la que ya están ligadas."""
	cliente = _cliente_de(doc)
	if not cliente:
		return []
	ordenes = frappe.get_list(
		"Sales Order",
		filters={
			"customer": cliente,
			"company": doc.company,
			"docstatus": 1,
			"transaction_date": [">=", add_months(getdate(), -MESES_ORDENES_PARA_VINCULAR)],
		},
		fields=["name", "transaction_date", "base_grand_total", "status"],
		order_by="transaction_date desc",
		limit_page_length=0,
	)
	if not ordenes:
		return []
	nombres = [o.name for o in ordenes]
	ligadas = _oportunidades_de_ordenes(nombres)
	return [
		{
			"name": o.name,
			"fecha": str(o.transaction_date),
			"monto": flt(o.base_grand_total),
			"status": o.status,
			"ligada_a": ligadas.get(o.name) if ligadas.get(o.name) != doc.name else None,
		}
		for o in ordenes
	]


def _oportunidades_de_ordenes(ordenes: list[str]) -> dict[str, str]:
	"""Orden de venta -> oportunidad a la que ya pertenece (por su cotización o vinculada a mano).

	get_all: solo se leen nombres de documentos ligados a órdenes que el usuario ya pudo listar.
	"""
	ligadas = dict(
		frappe.get_all(
			"Opportunity",
			filters={CAMPO_ORDEN_DE_VENTA: ["in", ordenes]},
			fields=[CAMPO_ORDEN_DE_VENTA, "name"],
			as_list=True,
		)
	)
	items = frappe.get_all(
		"Sales Order Item",
		filters={"parent": ["in", ordenes], "prevdoc_docname": ["is", "set"]},
		fields=["parent", "prevdoc_docname"],
	)
	oportunidad_de = dict(
		frappe.get_all(
			"Quotation",
			filters={"name": ["in", list({i.prevdoc_docname for i in items}) or [""]], "opportunity": ["is", "set"]},
			fields=["name", "opportunity"],
			as_list=True,
		)
	)
	for i in items:
		if oportunidad_de.get(i.prevdoc_docname):
			ligadas.setdefault(i.parent, oportunidad_de[i.prevdoc_docname])
	return ligadas


def _etapa_para_retomar(doc, cfg, rel):
	"""Al salir de pausa: la etapa activa más avanzada cuyos requisitos ya se cumplen."""
	cumplidas = [e for e in cfg.activas if not etapas.faltantes(doc, e, cfg, rel)]
	return cumplidas[-1] if cumplidas else cfg.activas[0]


def _opciones_select(meta, fieldname: str) -> list[str]:
	campo = meta.get_field(fieldname)
	return [o for o in (campo.options or "").split("\n") if o] if campo else []


def _etapa_con_faltantes(doc, etapa, cfg, rel):
	if not etapa:
		return None
	return {
		"clave": etapa.clave,
		"titulo": etapa.titulo,
		"probabilidad": etapa.probabilidad,
		"faltantes": etapas.faltantes(doc, etapa, cfg, rel) + list(filter(None, [flujo.bloqueo(doc, etapa.valor)])),
	}


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def mover_etapa(
	nombre: str,
	etapa: str,
	fecha_retomar: str | None = None,
	motivo: str | None = None,
	detalle: str | None = None,
):
	"""Cambia la etapa validando en el servidor los requisitos de la etapa destino."""
	cfg = TABLERO.etapas
	destino = cfg.etapa(etapa)
	if not destino:
		frappe.throw(_("Etapa desconocida: {0}").format(etapa))
	doc = acciones.oportunidad_del_tablero(nombre, TABLERO, "write")
	if destino.status == "Lost":
		acciones.perder_oportunidad(doc, cfg, motivo, detalle)
	else:
		if destino.clave == "pausa":
			doc.set(CAMPO_FECHA_RETOMAR, fecha_retomar)
		acciones.cambiar_etapa(doc, destino, cfg)
	return {"name": doc.name, "etapa": destino.titulo, "probability": doc.probability, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def guardar_datos(nombre: str, datos: str | dict):
	datos = frappe.parse_json(datos) or {}
	doc = acciones.oportunidad_del_tablero(nombre, TABLERO, "write")
	for campo in CAMPOS_EDITABLES:
		if campo in datos:
			doc.set(campo, datos[campo] or None)
	doc.save()
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def registrar_actividad(nombre: str, activity_type: str, comment: str, next_contact_date: str):
	doc = acciones.oportunidad_del_tablero(nombre, TABLERO)
	return acciones.registrar_actividad(doc, activity_type, comment, next_contact_date)


@frappe.whitelist(methods=["POST"])
def renovar_cotizacion(cotizacion: str, valid_till: str | None = None):
	return acciones.renovar_cotizacion(cotizacion, TABLERO, valid_till)


@frappe.whitelist(methods=["POST"])
def perder_cotizacion(cotizacion: str, motivo: str, detalle: str | None = None):
	return acciones.perder_cotizacion(cotizacion, TABLERO, motivo, detalle)


@frappe.whitelist(methods=["POST"])
def crear_orden_de_venta(nombre: str, delivery_date: str):
	"""Crea en borrador la orden de venta desde la cotización vigente; al enviarla, la oportunidad queda Ganada."""
	from erpnext.selling.doctype.quotation.quotation import make_sales_order

	if not delivery_date:
		frappe.throw(_("Falta la fecha de entrega."))
	if getdate(delivery_date) < getdate():
		frappe.throw(_("La fecha de entrega debe ser hoy o una fecha futura."))
	doc = acciones.oportunidad_del_tablero(nombre, TABLERO, "write")
	rel = etapas.DatosRelacionados(doc.name)
	cotizacion = next(
		(q.name for q in rel.cotizaciones_enviadas if q.status != "Ordered" and getdate(q.valid_till) >= getdate()),
		None,
	)
	if not cotizacion:
		frappe.throw(_("La oportunidad no tiene una cotización enviada y vigente para crear la orden de venta."))
	frappe.get_doc("Quotation", cotizacion).check_permission("read")
	frappe.has_permission("Sales Order", "create", throw=True)
	orden = make_sales_order(cotizacion)
	orden.delivery_date = delivery_date
	for item in orden.items:
		item.delivery_date = delivery_date
	orden.insert()
	return orden.name


@frappe.whitelist(methods=["POST"])
def vincular_orden_de_venta(nombre: str, sales_order: str):
	"""Cierra como ganada con una orden de venta existente del mismo cliente que no esté ligada a otra oportunidad."""
	doc = acciones.oportunidad_del_tablero(nombre, TABLERO, "write")
	orden = frappe.get_doc("Sales Order", sales_order)
	orden.check_permission("read")
	if orden.docstatus != 1:
		frappe.throw(_("La orden de venta {0} no está enviada.").format(sales_order))
	if orden.customer != _cliente_de(doc):
		frappe.throw(_("La orden de venta {0} es de otro cliente.").format(sales_order))
	ligada = _oportunidades_de_ordenes([sales_order]).get(sales_order)
	if ligada and ligada != doc.name:
		frappe.throw(_("La orden de venta {0} ya está ligada a {1}.").format(sales_order, ligada))
	doc.set(CAMPO_ORDEN_DE_VENTA, sales_order)
	ganada = TABLERO.etapas.por_status("Converted")
	acciones.cambiar_etapa(doc, ganada, TABLERO.etapas)
	return {"name": doc.name, "status": doc.status, "etapa": ganada.titulo}


@frappe.whitelist(methods=["POST"])
def solicitar_entregable(nombre: str, tipo_entregable: str, fecha: str, descripcion: str):
	doc = acciones.oportunidad_del_tablero(nombre, TABLERO)
	return entregables.solicitar("Opportunity", doc.name, tipo_entregable, fecha, descripcion)
