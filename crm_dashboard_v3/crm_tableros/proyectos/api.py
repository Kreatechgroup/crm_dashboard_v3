"""Métodos whitelisted del tablero CRM Proyectos (asesores de Plus).

Todo el cálculo se hace en el servidor; la página solo pinta lo que devuelven
estos métodos y llama a las acciones.

- Un asesor ve solo lo suyo (sus dos Sales Person, Proyectos y Retail).
- Un jefe de Plus ve la tienda completa o a un asesor elegido.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from crm_dashboard_v3.crm_tableros.common import acciones, contexto, etapas
from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_FECHA_PROXIMO_PASO,
	CAMPO_FECHA_RETOMAR,
	CAMPO_PROXIMO_PASO,
)
from crm_dashboard_v3.crm_tableros.common.formato import etiqueta_mes, nombres_de_usuarios
from crm_dashboard_v3.crm_tableros.proyectos import consolidado, embudo, historico
from crm_dashboard_v3.crm_tableros.proyectos.config import TABLERO

HISTORIAL_POR_PAGINA = 50
CAMPOS_EDITABLES = (
	"presupuesto_declarado_por_el_cliente",
	"fecha_estimada_aprobacion",
	"source",
	"tipo_de_oportunidad",
	CAMPO_PROXIMO_PASO,
	CAMPO_FECHA_PROXIMO_PASO,
)


# ---------------------------------------------------------------------------
# Alcance: quién mira y a quién
# ---------------------------------------------------------------------------


def _alcance(mes, asesor, establecimiento):
	"""Contexto, datos base de la respuesta y asesores a mostrar (o un mensaje)."""
	t = TABLERO
	ctx = contexto.obtener(t, mes, establecimiento)
	base = {
		"tablero": t.titulo,
		"meses": contexto.meses_disponibles(),
		"mes": ctx.desde.strftime("%Y-%m"),
		"etiqueta_mes": etiqueta_mes(ctx.desde),
		"hoy": str(ctx.hoy),
		"dia_de_corte": str(ctx.dia_de_corte),
		"es_jefe": ctx.es_jefe,
		"establecimientos": ctx.establecimientos,
		"establecimiento": ctx.establecimiento,
		"moneda": ctx.moneda,
		"asesores": [],
		"asesor": None,
		"nombre_usuario": ctx.nombre,
	}
	if ctx.mensaje:
		return t, ctx, {**base, "titulo": t.titulo, "mensaje": ctx.mensaje}, []

	if ctx.es_jefe:
		asesores = contexto.asesores_de_tienda(t, ctx.establecimiento)
		base["asesores"] = [{"empleado": a.empleado, "nombre": a.nombre} for a in asesores]
		seleccion = asesores
		if asesor:
			seleccion = [a for a in asesores if a.empleado == asesor]
			if not seleccion:
				frappe.throw(_("El asesor elegido no pertenece a este establecimiento."))
			base["asesor"] = asesor
		titulo = _("Proyectos de {0}").format(seleccion[0].nombre) if asesor else _("Proyectos · toda la tienda")
		if not asesores:
			return t, ctx, {**base, "titulo": titulo, "mensaje": _("No hay asesores activos en {0}.").format(ctx.establecimiento)}, []
	else:
		# Un asesor nunca ve a otro: el parámetro ``asesor`` se ignora.
		seleccion = [ctx.como_asesor()]
		titulo = _("Mis proyectos · {0}").format(ctx.nombre)

	base["titulo"] = titulo
	base["subtitulo"] = " · ".join(filter(None, [ctx.establecimiento, ctx.company, etiqueta_mes(ctx.desde)]))
	return t, ctx, base, seleccion


@frappe.whitelist()
def get_tablero(mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None):
	t, ctx, base, seleccion = _alcance(mes, asesor, establecimiento)
	if base.get("mensaje"):
		return base
	vista_tienda = ctx.es_jefe and not base["asesor"]
	return {**base, **embudo.construir(t, ctx, seleccion, con_resumen=vista_tienda)}


@frappe.whitelist()
def get_consolidado(mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None):
	t, ctx, base, seleccion = _alcance(mes, asesor, establecimiento)
	if base.get("mensaje"):
		return base
	vista_tienda = ctx.es_jefe and not base["asesor"]
	return {**base, **consolidado.construir(t, ctx, seleccion, vista_tienda)}


@frappe.whitelist()
def get_historico(mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None):
	t, ctx, base, seleccion = _alcance(mes, asesor, establecimiento)
	if base.get("mensaje"):
		return base
	return {**base, **historico.construir(t, ctx, seleccion)}


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
		"ordenes_de_venta": rel.ordenes_de_venta,
		"cotizacion_para_orden": cotizacion_para_orden,
		"siguiente": _etapa_con_faltantes(doc, siguiente, cfg, rel),
		"anterior": _etapa_con_faltantes(doc, anterior, cfg, rel),
		"puede_pausar": not cerrada and etapa.clave != "pausa",
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
		},
	}


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
		"faltantes": etapas.faltantes(doc, etapa, cfg, rel),
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
	"""Cambia la etapa. Los requisitos los valida el hook validate de Opportunity."""
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
		doc.set(CAMPO_ETAPA, destino.titulo)
		doc.save()
	return {"name": doc.name, "etapa": doc.get(CAMPO_ETAPA), "probability": doc.probability, "status": doc.status}


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
