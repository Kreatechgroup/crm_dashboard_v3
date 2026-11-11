"""Métodos whitelisted del tablero CRM Proyectos.

Todo el cálculo se hace aquí; la página solo pinta lo que devuelve get_tablero
y llama a las acciones.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from crm_dashboard_v3.crm_tableros.common import acciones, consultas, contexto, etapas, metas, ventas
from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA, CAMPO_FECHA_RETOMAR
from crm_dashboard_v3.crm_tableros.common.formato import (
	etiqueta_mes,
	nombres_de_usuarios,
	ritmo,
	semaforo_dias,
)
from crm_dashboard_v3.crm_tableros.proyectos.config import SALES_MODEL

HISTORIAL_POR_PAGINA = 50
CAMPOS_EDITABLES = (
	"presupuesto_declarado_por_el_cliente",
	"fecha_estimada_aprobacion",
	"source",
	"tipo_de_oportunidad",
)


def _cfg():
	return etapas.config_de(SALES_MODEL)


# ---------------------------------------------------------------------------
# Tablero
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_tablero(mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None):
	cfg = _cfg()
	ctx = contexto.obtener(cfg, mes, establecimiento)
	base = {
		"meses": contexto.meses_disponibles(),
		"mes": ctx.desde.strftime("%Y-%m"),
		"etiqueta_mes": etiqueta_mes(ctx.desde),
		"hoy": str(ctx.hoy),
		"es_jefe": ctx.es_jefe,
		"establecimientos": ctx.establecimientos,
		"establecimiento": ctx.establecimiento,
		"moneda": ctx.moneda,
		"asesores": [],
		"asesor": None,
	}
	if ctx.mensaje:
		return {**base, "titulo": _("CRM Proyectos"), "mensaje": ctx.mensaje}

	if ctx.es_jefe:
		asesores = contexto.asesores_de_tienda(cfg, ctx.company, ctx.establecimiento)
		base["asesores"] = [{"empleado": a.empleado, "nombre": a.nombre} for a in asesores]
		seleccion = asesores
		if asesor:
			seleccion = [a for a in asesores if a.empleado == asesor]
			if not seleccion:
				frappe.throw(_("El asesor elegido no pertenece a este establecimiento."))
			base["asesor"] = asesor
		titulo = _("Proyectos de {0}").format(seleccion[0].nombre) if asesor else _("Proyectos · toda la tienda")
		if not asesores:
			return {**base, "titulo": titulo, "mensaje": _("No hay asesores activos en {0}.").format(ctx.establecimiento)}
	else:
		seleccion = [ctx.como_asesor()]
		titulo = _("Mis proyectos · {0}").format(ctx.nombre)

	subtitulo = " · ".join(filter(None, [ctx.establecimiento, ctx.company, etiqueta_mes(ctx.desde)]))
	datos = construir_tablero(cfg, ctx, seleccion, con_resumen=ctx.es_jefe and not asesor)
	return {**base, "titulo": titulo, "subtitulo": subtitulo, **datos}


def construir_tablero(cfg, ctx, asesores: list, con_resumen: bool = False) -> dict:
	usuarios = [a.usuario for a in asesores]
	abiertas = consultas.oportunidades_abiertas(usuarios, cfg.sales_model, ctx.company)
	cerradas = consultas.oportunidades_cerradas(usuarios, cfg.sales_model, ctx.company, ctx.desde, ctx.hasta)
	nombres = [o.name for o in abiertas + cerradas]
	actividades = consultas.ultimas_actividades(nombres)
	montos_q = consultas.montos_de_cotizacion(nombres)
	nombre_de = {a.usuario: a.nombre for a in asesores}

	def preparar(o):
		return _preparar(o, cfg, ctx, actividades.get(o.name), montos_q.get(o.name, 0), usuarios, nombre_de)

	ops = [preparar(o) for o in abiertas]
	cer = [preparar(o) for o in cerradas]
	vencidas = consultas.cotizaciones_vencidas([o.name for o in ops if not o.incoherente], ctx.hoy)
	asesor_de_op = {o.name: o.asesor_usuario for o in ops}
	for v in vencidas:
		v.asesor_usuario = asesor_de_op.get(v.opportunity)

	mostrar_asesor = len(asesores) > 1
	grupo = _agrupar(ops, cer, vencidas, cfg, ctx)
	ventas_por_asesor = {a.usuario: _meta_y_facturado(a, cfg, ctx) for a in asesores}

	resultado = {
		"kpis": _indicadores(grupo, ventas_por_asesor.values(), ctx),
		"columnas": [
			{
				"clave": e.clave,
				"titulo": e.titulo,
				"probabilidad": e.probabilidad,
				"requisitos": e.texto_requisitos,
				**_columna([o for o in grupo["activas"] if o.etapa.clave == e.clave], mostrar_asesor),
			}
			for e in cfg.activas
		],
		"cerradas": [
			{"clave": "pausa", "titulo": cfg.etapa("pausa").titulo, **_columna(grupo["pausa"], mostrar_asesor)},
			{"clave": "ganada", "titulo": _("Ganadas del mes"), **_columna(grupo["ganadas"], mostrar_asesor)},
			{"clave": "perdida", "titulo": _("Perdidas del mes"), **_columna(grupo["perdidas"], mostrar_asesor)},
		],
		"tipos": sorted({o.tipo for o in grupo["activas"] if o.tipo}),
		"mi_dia": _mi_dia(grupo, cfg, ctx, mostrar_asesor),
		"vencidas": [_vencida(v, nombre_de, mostrar_asesor) for v in vencidas],
		"incoherentes": {
			"cantidad": len(grupo["incoherentes"]),
			"nombres": [o.name for o in grupo["incoherentes"]],
		},
		"motivos": acciones.motivos_de_perdida_cotizacion(cfg),
		"umbral_escalar": cfg.umbral_escalar,
		"dias_verde_max": cfg.dias_verde_max,
		"dias_amarillo_max": cfg.dias_amarillo_max,
		"mostrar_asesor": mostrar_asesor,
		"resumen": None,
	}
	if con_resumen:
		resultado["resumen"] = _resumen(asesores, ops, vencidas, ventas_por_asesor, cfg, ctx)
	return resultado


def _preparar(o, cfg, ctx, actividad, monto_cotizacion, usuarios, nombre_de):
	etapa = etapas.etapa_efectiva(o, cfg)
	ultima = getdate(o.modified)
	if actividad and actividad.created_on:
		ultima = max(ultima, getdate(actividad.created_on))
	dias = max(0, (ctx.hoy - ultima).days)

	proximo = {"texto": _("Sin próximo paso"), "fecha": None, "estado": "vacio"}
	if actividad and actividad.next_contact_date:
		fecha = getdate(actividad.next_contact_date)
		vencido = fecha < ctx.hoy
		proximo = {
			"texto": _("Contactar · {0}").format(actividad.activity_type or _("seguimiento")),
			"fecha": str(fecha),
			"estado": "vencido" if vencido else "ok",
		}

	asesor_usuario = o.asesor_comercial_user_id if o.asesor_comercial_user_id in usuarios else o.owner
	return frappe._dict(
		name=o.name,
		cliente=o.customer_name or o.title or o.party_name,
		etapa=etapa,
		status=o.status,
		monto=etapas.monto_de(o, cfg, monto_cotizacion),
		fecha_cierre=etapas.fecha_cierre_de(o, cfg),
		dias=dias,
		semaforo=semaforo_dias(dias, cfg.dias_verde_max, cfg.dias_amarillo_max),
		tipo=o.tipo_de_oportunidad,
		asesor_usuario=asesor_usuario,
		asesor=nombre_de.get(asesor_usuario, ""),
		proximo=proximo,
		incoherente=etapas.es_incoherente(o, cfg),
		fecha_retomar=getdate(o.get(CAMPO_FECHA_RETOMAR)) if o.get(CAMPO_FECHA_RETOMAR) else None,
		lost_reason=o.lost_reason,
	)


def _agrupar(ops, cer, vencidas, cfg, ctx) -> dict:
	validas = [o for o in ops if not o.incoherente]
	activas = [o for o in validas if o.etapa.activa]
	return {
		"activas": activas,
		"pausa": [o for o in validas if not o.etapa.activa and not o.etapa.status],
		"incoherentes": [o for o in ops if o.incoherente],
		"ganadas": [o for o in cer if o.status == "Converted"],
		"perdidas": [o for o in cer if o.status == "Lost"],
		"vencidas": vencidas,
	}


def _ponderado(o) -> float:
	return o.monto * flt(o.etapa.probabilidad) / 100


def _en_pronostico(o) -> bool:
	return o.etapa.activa and o.etapa.cuenta_pronostico and o.etapa.probabilidad is not None


def _meta_y_facturado(asesor, cfg, ctx) -> dict:
	meta = metas.meta_total(asesor.sales_persons, cfg.tipo_meta, ctx.desde, ctx.hasta, ctx.company)
	fact = ventas.facturado(asesor.sales_persons, asesor.usuario, ctx.company, ctx.desde, ctx.hasta)
	return {"meta": meta["monto"], "facturado": fact["monto"], "facturas": fact["facturas"]}


def _indicadores(grupo, ventas_asesores, ctx) -> dict:
	ventas_asesores = list(ventas_asesores)
	meta = sum(v["meta"] for v in ventas_asesores)
	facturado = sum(v["facturado"] for v in ventas_asesores)
	facturas = sorted({f for v in ventas_asesores for f in v["facturas"]})

	en_pronostico = [o for o in grupo["activas"] if _en_pronostico(o)]
	del_mes = [o for o in en_pronostico if o.fecha_cierre and ctx.desde <= o.fecha_cierre <= ctx.hasta]
	sin_fecha = [o for o in en_pronostico if not o.fecha_cierre]
	vigentes = [o for o in grupo["activas"] if o.etapa.clave in ("prop", "neg")]
	vencidas = grupo["vencidas"]
	return {
		"meta": {
			"meta": meta,
			"facturado": facturado,
			"porcentaje": round(facturado / meta * 100) if meta else 0,
			"facturas": facturas,
			"ritmo": ritmo(facturado, meta, ctx.fraccion_del_mes),
			"ritmo_esperado": round(ctx.fraccion_del_mes * 100),
		},
		"pronostico": {
			"mes": sum(_ponderado(o) for o in del_mes),
			"total": sum(_ponderado(o) for o in en_pronostico),
			"nombres_mes": [o.name for o in del_mes],
			"nombres_total": [o.name for o in en_pronostico],
			"activas": len(en_pronostico),
			"con_fecha": len(en_pronostico) - len(sin_fecha),
			"sin_fecha": len(sin_fecha),
			"nombres_sin_fecha": [o.name for o in sin_fecha],
		},
		"vigentes": {
			"monto": sum(o.monto for o in vigentes),
			"cantidad": len(vigentes),
			"nombres": [o.name for o in vigentes],
		},
		"vencidas": {
			"monto": sum(flt(v.base_grand_total) for v in vencidas),
			"cantidad": len(vencidas),
			"nombres": [v.name for v in vencidas],
		},
	}


def _tarjeta(o, mostrar_asesor: bool) -> dict:
	extra = ""
	if o.etapa.clave == "pausa":
		extra = _("Retomar el {0}").format(o.fecha_retomar) if o.fecha_retomar else _("Sin fecha para retomar")
	elif o.status == "Lost":
		extra = _("Motivo: {0}").format(o.lost_reason or _("sin motivo"))
	return {
		"name": o.name,
		"cliente": o.cliente,
		"monto": o.monto,
		"dias": o.dias,
		"semaforo": o.semaforo,
		"tipo": o.tipo,
		"etapa": o.etapa.titulo,
		"asesor": o.asesor if mostrar_asesor else "",
		"proximo": o.proximo,
		"extra": extra,
	}


def _columna(lista, mostrar_asesor: bool) -> dict:
	lista = sorted(lista, key=lambda o: o.monto, reverse=True)
	return {
		"cantidad": len(lista),
		"total": sum(o.monto for o in lista),
		"nombres": [o.name for o in lista],
		"tarjetas": [_tarjeta(o, mostrar_asesor) for o in lista],
	}


def _faltan_datos(o, cfg, ctx) -> list[str]:
	falta = []
	if o.monto <= 0:
		falta.append(_("presupuesto"))
	if not o.fecha_cierre:
		falta.append(_("fecha estimada"))
	elif o.fecha_cierre < ctx.hoy:
		falta.append(_("fecha estimada vencida"))
	if o.proximo["estado"] != "ok":
		falta.append(_("próximo paso"))
	return falta


def _mi_dia(grupo, cfg, ctx, mostrar_asesor: bool) -> list[dict]:
	activas = grupo["activas"]
	sin_mover = [o for o in activas if o.dias > cfg.dias_verde_max]
	escalar = sorted([o for o in sin_mover if o.monto >= cfg.umbral_escalar], key=lambda o: -o.monto)
	atrasadas = sorted([o for o in sin_mover if o.monto < cfg.umbral_escalar], key=lambda o: -o.dias)
	incompletas = sorted(
		[o for o in activas if o.dias <= cfg.dias_verde_max and _faltan_datos(o, cfg, ctx)],
		key=lambda o: -o.monto,
	)
	retomar = [o for o in grupo["pausa"] if o.fecha_retomar and o.fecha_retomar <= ctx.hoy]

	def item(o, sub, valor=None, tab="datos"):
		prefijo = f"{o.asesor} · " if mostrar_asesor and o.asesor else ""
		return {"name": o.name, "cliente": o.cliente, "sub": prefijo + sub, "valor": valor, "dias": o.dias, "tab": tab}

	grupos = [
		{
			"clave": "escalar",
			"titulo": _("Escalar al jefe"),
			"ayuda": _("Monto de {0} o más y más de {1} días sin actividad"),
			"ayuda_args": [cfg.umbral_escalar, cfg.dias_verde_max],
			"tono": "rojo",
			"items": [item(o, o.etapa.titulo, o.monto, "actividad") for o in escalar],
		},
		{
			"clave": "vencidas",
			"titulo": _("Propuestas vencidas"),
			"ayuda": _("Renovar con nueva vigencia o darla por perdida"),
			"tono": "rojo",
			"items": [],
			"cantidad": len(grupo["vencidas"]),
		},
		{
			"clave": "retomar",
			"titulo": _("Retomar hoy"),
			"ayuda": _("Oportunidades en pausa cuya fecha ya llegó"),
			"tono": "amarillo",
			"items": [item(o, _("Tocaba retomar el {0}").format(o.fecha_retomar)) for o in retomar],
		},
		{
			"clave": "atrasadas",
			"titulo": _("Sin actividad reciente"),
			"ayuda": _("Más de {0} días sin moverse · registra un contacto").format(cfg.dias_verde_max),
			"tono": "amarillo",
			"items": [item(o, o.etapa.titulo, None, "actividad") for o in atrasadas],
		},
		{
			"clave": "incompletas",
			"titulo": _("Datos incompletos"),
			"ayuda": _("Les falta presupuesto, fecha estimada (o está vencida) o próximo paso vigente"),
			"tono": "gris",
			"items": [item(o, _("Falta: {0}").format(", ".join(_faltan_datos(o, cfg, ctx))), o.monto) for o in incompletas],
		},
	]
	for g in grupos:
		g.setdefault("cantidad", len(g["items"]))
		g["nombres"] = [i["name"] for i in g["items"]]
	# "Retomar hoy" solo aparece cuando hay algo que retomar.
	return [g for g in grupos if g["clave"] != "retomar" or g["cantidad"]]


def _vencida(v, nombre_de, mostrar_asesor: bool) -> dict:
	asesor = nombre_de.get(v.asesor_usuario, "") if mostrar_asesor else ""
	return {
		"name": v.name,
		"oportunidad": v.opportunity,
		"cliente": v.customer_name or v.party_name,
		"monto": flt(v.base_grand_total),
		"valid_till": str(v.valid_till),
		"dias_cotizada": (getdate() - getdate(v.transaction_date)).days,
		"asesor": asesor,
	}


def _resumen(asesores, ops, vencidas, ventas_por_asesor, cfg, ctx) -> dict:
	filas = []
	for a in asesores:
		propias = [o for o in ops if o.asesor_usuario == a.usuario]
		grupo = _agrupar(propias, [], [v for v in vencidas if v.asesor_usuario == a.usuario], cfg, ctx)
		filas.append(_fila_resumen(a.empleado, a.nombre, grupo, [ventas_por_asesor[a.usuario]], cfg, ctx))
	total = _fila_resumen(
		None, _("Tienda"), _agrupar(ops, [], vencidas, cfg, ctx), list(ventas_por_asesor.values()), cfg, ctx
	)
	return {"filas": filas, "total": total}


def _fila_resumen(empleado, nombre, grupo, ventas_asesores, cfg, ctx) -> dict:
	kpis = _indicadores(grupo, ventas_asesores, ctx)
	activas = grupo["activas"]
	sin_mover = [o for o in activas if o.dias > cfg.dias_verde_max]
	escalar = [o for o in sin_mover if o.monto >= cfg.umbral_escalar]
	return {
		"empleado": empleado,
		"nombre": nombre,
		"meta": kpis["meta"],
		"activas": {"cantidad": len(activas), "monto": sum(o.monto for o in activas), "nombres": [o.name for o in activas]},
		"pronostico": kpis["pronostico"]["total"],
		"vencidas": kpis["vencidas"],
		"sin_actividad": {"cantidad": len(sin_mover), "nombres": [o.name for o in sin_mover]},
		"escalar": {"cantidad": len(escalar), "nombres": [o.name for o in escalar]},
		"incoherentes": {
			"cantidad": len(grupo["incoherentes"]),
			"nombres": [o.name for o in grupo["incoherentes"]],
		},
	}


# ---------------------------------------------------------------------------
# Detalle de una oportunidad
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_oportunidad(nombre: str, pagina_historial: int = 0):
	cfg = _cfg()
	doc = acciones.oportunidad_del_modelo(nombre, cfg.sales_model)
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
	ultima = rel.ultima_actividad
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
			"tipo": ultima.activity_type if ultima else None,
			"fecha": ultima.next_contact_date if ultima else None,
			"vencido": bool(ultima and ultima.next_contact_date and getdate(ultima.next_contact_date) < hoy),
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
	cfg = _cfg()
	destino = cfg.etapa(etapa)
	if not destino:
		frappe.throw(_("Etapa desconocida: {0}").format(etapa))
	doc = acciones.oportunidad_del_modelo(nombre, cfg.sales_model, "write")
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
	cfg = _cfg()
	datos = frappe.parse_json(datos) or {}
	doc = acciones.oportunidad_del_modelo(nombre, cfg.sales_model, "write")
	for campo in CAMPOS_EDITABLES:
		if campo in datos:
			doc.set(campo, datos[campo] or None)
	doc.save()
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def registrar_actividad(nombre: str, activity_type: str, comment: str, next_contact_date: str):
	cfg = _cfg()
	doc = acciones.oportunidad_del_modelo(nombre, cfg.sales_model)
	return acciones.registrar_actividad(doc, activity_type, comment, next_contact_date)


@frappe.whitelist(methods=["POST"])
def renovar_cotizacion(cotizacion: str, valid_till: str | None = None):
	return acciones.renovar_cotizacion(cotizacion, SALES_MODEL, valid_till)


@frappe.whitelist(methods=["POST"])
def perder_cotizacion(cotizacion: str, motivo: str, detalle: str | None = None):
	return acciones.perder_cotizacion(cotizacion, SALES_MODEL, motivo, detalle)
