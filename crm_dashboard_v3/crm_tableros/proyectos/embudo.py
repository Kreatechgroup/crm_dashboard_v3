"""Vista Embudo de CRM Proyectos: indicadores, columnas por etapa, Mi día y resumen por asesor.

Junta las oportunidades de los dos modelos de venta del asesor de Plus
(Proyectos y Retail); cada tarjeta lleva su modelo para filtrar en la página.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from crm_dashboard_v3.crm_tableros.common import acciones, consultas, etapas, metas, venta_pos, ventas
from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_FECHA_RETOMAR
from crm_dashboard_v3.crm_tableros.common.formato import ritmo, semaforo_dias
from crm_dashboard_v3.crm_tableros.proyectos.config import PROYECTOS


def construir(t, ctx, asesores: list, con_resumen: bool = False) -> dict:
	cfg = t.etapas
	usuarios = [a.usuario for a in asesores]
	abiertas = consultas.oportunidades_abiertas(usuarios, t, ctx.company)
	cerradas = consultas.oportunidades_cerradas(usuarios, t, ctx.company, ctx.desde, ctx.hasta)
	nombres = [o.name for o in abiertas + cerradas]
	actividades = consultas.ultimas_actividades(nombres)
	montos_q = consultas.montos_de_cotizacion(nombres)
	nombre_de = {a.usuario: a.nombre for a in asesores}

	def preparar(o):
		return _preparar(o, cfg, ctx, actividades.get(o.name), montos_q.get(o.name, 0), usuarios, nombre_de)

	ops = [preparar(o) for o in abiertas]
	cer = [preparar(o) for o in cerradas]
	revision_pos = _revision_pos(usuarios, t, ctx)
	for o in cer:
		o.revision_pos = revision_pos.get(o.name)
	vencidas = consultas.cotizaciones_vencidas([o.name for o in ops if not o.incoherente], ctx.hoy)
	op_de = {o.name: o for o in ops}
	for v in vencidas:
		v.asesor_usuario = op_de[v.opportunity].asesor_usuario
		v.modelo = op_de[v.opportunity].modelo

	mostrar_asesor = len(asesores) > 1
	grupo = _agrupar(ops, cer, vencidas)
	ventas_por_asesor = {a.usuario: meta_y_facturado(a, t, ctx) for a in asesores}
	avance = {usuario: avance_de_metas(v) for usuario, v in ventas_por_asesor.items()}

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
		"mi_dia": _mi_dia(grupo, cfg, ctx, mostrar_asesor, avance),
		"vencidas": [_vencida(v, nombre_de, mostrar_asesor, ctx) for v in vencidas],
		"incoherentes": {
			"cantidad": len(grupo["incoherentes"]),
			"nombres": [o.name for o in grupo["incoherentes"]],
		},
		# Ganadas con una venta POS que después se canceló o devolvió (no se modifican).
		"revision_pos": {"cantidad": len(revision_pos), "nombres": sorted(revision_pos)},
		"motivos": acciones.motivos_de_perdida_cotizacion(cfg),
		"umbral_escalar": cfg.umbral_escalar,
		"dias_verde_max": cfg.dias_verde_max,
		"dias_amarillo_max": cfg.dias_amarillo_max,
		"mostrar_asesor": mostrar_asesor,
		"resumen": None,
	}
	if con_resumen:
		resultado["resumen"] = _resumen(asesores, ops, vencidas, ventas_por_asesor, ctx, cfg)
	return resultado


def _revision_pos(usuarios, t, ctx) -> dict[str, str]:
	"""Oportunidad ganada -> motivo de revisión, si su venta POS se canceló o se devolvió."""
	ganadas = consultas.ganadas_con_venta_pos(usuarios, t, ctx.company)
	motivos = venta_pos.para_revision(list(set(ganadas.values())))
	return {op: motivos[f] for op, f in ganadas.items() if f in motivos}


def meta_y_facturado(asesor, t, ctx) -> dict:
	"""Meta y facturado del mes del asesor: Σ de todos sus Sales Person, y separado por modelo."""
	meta = metas.meta_por_modelo(asesor.sales_persons, t.tipo_meta, ctx.desde, ctx.hasta, ctx.company)
	fact = ventas.facturado(
		asesor.sales_persons_de_ventas, asesor.usuario, ctx.company, ctx.desde, ctx.hasta, t.modelo_por_defecto
	)
	return {
		"asesor": asesor.nombre,
		"meta": sum(meta.values()),
		"facturado": fact["monto"],
		"facturas": fact["facturas"],
		"filas": fact["filas"],
		"meta_por_modelo": meta,
	}


def avance_de_metas(ventas_asesor: dict) -> dict[str, dict]:
	"""Modelo -> meta, facturado y lo que falta, de la meta de cada Sales Person del asesor."""
	avance = {m: {"meta": monto, "facturado": 0.0} for m, monto in ventas_asesor["meta_por_modelo"].items()}
	for f in ventas_asesor["filas"]:
		avance.setdefault(f.modelo, {"meta": 0.0, "facturado": 0.0})["facturado"] += f.monto
	for a in avance.values():
		a["falta"] = max(0.0, a["meta"] - a["facturado"])
	return avance


def completa_la_meta(o, avance: dict) -> dict | None:
	"""Si la oportunidad, al ganarse, completa la meta de su modelo (la de su Sales Person).

	Solo cuenta cuando la meta existe y aún falta algo: el monto de la oportunidad
	cubre lo que le falta al asesor en ese modelo.
	"""
	a = (avance.get(o.asesor_usuario) or {}).get(o.modelo)
	if not a or a["meta"] <= 0 or a["falta"] <= 0 or o.monto < a["falta"]:
		return None
	return {"modelo": o.modelo, "falta": a["falta"]}


def _preparar(o, cfg, ctx, actividad, monto_cotizacion, usuarios, nombre_de):
	etapa = etapas.etapa_efectiva(o, cfg)
	ultima = getdate(o.modified)
	if actividad and actividad.created_on:
		ultima = max(ultima, getdate(actividad.created_on))
	dias = max(0, (ctx.hoy - ultima).days)

	paso = etapas.proximo_paso_de(o, actividad)
	if paso.texto and paso.fecha:
		proximo = {"texto": paso.texto, "fecha": str(paso.fecha), "estado": "vencido" if paso.fecha < ctx.hoy else "ok"}
	else:
		proximo = {"texto": paso.texto, "fecha": str(paso.fecha) if paso.fecha else None, "estado": "vacio"}

	asesor_usuario = consultas.asesor_de(o, usuarios)
	return frappe._dict(
		name=o.name,
		cliente=o.customer_name or o.title or o.party_name,
		modelo=o.sales_model,
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


def _agrupar(ops, cer, vencidas) -> dict:
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


def _indicadores(grupo, ventas_asesores, ctx) -> dict:
	ventas_asesores = list(ventas_asesores)
	meta = sum(v["meta"] for v in ventas_asesores)
	facturado = sum(v["facturado"] for v in ventas_asesores)
	facturas = sorted({f for v in ventas_asesores for f in v["facturas"]})
	por_modelo = {}
	for v in ventas_asesores:
		for modelo, monto in v["meta_por_modelo"].items():
			por_modelo.setdefault(modelo, {"meta": 0, "facturado": 0})["meta"] += monto
		for f in v["filas"]:
			por_modelo.setdefault(f.modelo, {"meta": 0, "facturado": 0})["facturado"] += f.monto

	en_pronostico = [o for o in grupo["activas"] if _en_pronostico(o)]
	del_mes = [o for o in en_pronostico if o.fecha_cierre and ctx.desde <= o.fecha_cierre <= ctx.hasta]
	sin_fecha = [o for o in en_pronostico if not o.fecha_cierre]
	vigentes = [o for o in grupo["activas"] if o.etapa.clave in ("prop", "neg")]
	vencidas = grupo["vencidas"]
	filas = [
		{
			"name": f.name,
			"cliente": f.cliente,
			"empresa": f.empresa,
			"fecha": str(f.fecha),
			"modelo": f.modelo,
			"monto": f.monto,
			"distribucion": f.distribucion,
			"propia": f.propia,
			"nota_de_credito": f.nota_de_credito,
			"asesor": v.get("asesor", ""),
		}
		for v in ventas_asesores
		for f in v["filas"]
	]
	return {
		"meta": {
			"meta": meta,
			"facturado": facturado,
			"porcentaje": round(facturado / meta * 100) if meta else 0,
			"facturas": facturas,
			"filas": sorted(filas, key=lambda x: -x["monto"]),
			"por_modelo": por_modelo,
			"ritmo": ritmo(facturado, meta, ctx.fraccion_del_mes),
			"ritmo_esperado": round(ctx.fraccion_del_mes * 100),
		},
		"pronostico": {
			# Se calcula con las oportunidades abiertas hoy: para un mes ya cerrado no pronostica nada.
			"mes_cerrado": ctx.hasta < ctx.hoy,
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
	elif o.get("revision_pos"):
		extra = _("Para revisión: {0}").format(o.revision_pos)
	return {
		"name": o.name,
		"cliente": o.cliente,
		"modelo": o.modelo,
		"monto": o.monto,
		"ponderado": _ponderado(o) if _en_pronostico(o) else 0,
		"cierre": str(o.fecha_cierre) if o.fecha_cierre else None,
		"dias": o.dias,
		"semaforo": o.semaforo,
		"tipo": o.tipo,
		"etapa": o.etapa.titulo,
		"etapa_clave": o.etapa.clave,
		"asesor": o.asesor if mostrar_asesor else "",
		"proximo": o.proximo,
		"extra": extra,
		"revision": bool(o.get("revision_pos")),
	}


def _columna(lista, mostrar_asesor: bool) -> dict:
	lista = sorted(lista, key=lambda o: o.monto, reverse=True)
	return {
		"cantidad": len(lista),
		"total": sum(o.monto for o in lista),
		"nombres": [o.name for o in lista],
		"tarjetas": [_tarjeta(o, mostrar_asesor) for o in lista],
	}


def _faltan_datos(o, ctx) -> list[str]:
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


def _mi_dia(grupo, cfg, ctx, mostrar_asesor: bool, avance: dict) -> list[dict]:
	activas = grupo["activas"]
	sin_mover = [o for o in activas if o.dias > cfg.dias_verde_max]
	# Primero las que completan la meta de su modelo; después, por monto.
	escalar = [o for o in sin_mover if o.monto >= cfg.umbral_escalar]
	for o in escalar:
		o.completa_meta = completa_la_meta(o, avance)
	escalar.sort(key=lambda o: (o.completa_meta is None, -o.monto))
	atrasadas = sorted([o for o in sin_mover if o.monto < cfg.umbral_escalar], key=lambda o: -o.dias)
	incompletas = sorted(
		[o for o in activas if o.dias <= cfg.dias_verde_max and _faltan_datos(o, ctx)],
		key=lambda o: -o.monto,
	)
	retomar = [o for o in grupo["pausa"] if o.fecha_retomar and o.fecha_retomar <= ctx.hoy]

	def item(o, sub, valor=None, tab="datos"):
		prefijos = [o.asesor if mostrar_asesor else "", o.modelo if o.modelo != PROYECTOS else ""]
		prefijo = "".join(f"{p} · " for p in prefijos if p)
		return {
			"name": o.name,
			"cliente": o.cliente,
			"sub": prefijo + sub,
			"valor": valor,
			"dias": o.dias,
			"tab": tab,
			"completa_meta": o.get("completa_meta"),
		}

	grupos = [
		{
			"clave": "escalar",
			"titulo": _("Escalar al jefe"),
			"ayuda": _("Monto de {0} o más y más de {1} días sin actividad"),
			"ayuda_args": [cfg.umbral_escalar, cfg.dias_verde_max],
			"tono": "rojo",
			"items": [item(o, o.etapa.titulo, o.monto, "actividad") for o in escalar],
			"completan_meta": sum(1 for o in escalar if o.completa_meta),
			# Cuánto le falta de cada meta (solo con un asesor: en la tienda cada uno tiene la suya).
			"metas": None if mostrar_asesor else _resumen_metas(next(iter(avance.values()), {})),
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
			"ayuda": _("Les falta presupuesto, fecha estimada de aprobación (o está vencida) o próximo paso vigente"),
			"tono": "gris",
			"items": [item(o, _("Falta: {0}").format(", ".join(_faltan_datos(o, ctx))), o.monto) for o in incompletas],
		},
	]
	for g in grupos:
		g.setdefault("cantidad", len(g["items"]))
		g["nombres"] = [i["name"] for i in g["items"]]
	# "Retomar hoy" solo aparece cuando hay algo que retomar.
	return [g for g in grupos if g["clave"] != "retomar" or g["cantidad"]]


def _resumen_metas(avance_asesor: dict) -> list[dict]:
	return [
		{"modelo": modelo, **a, "porcentaje": round(a["facturado"] / a["meta"] * 100) if a["meta"] else 0}
		for modelo, a in avance_asesor.items()
		if a["meta"] > 0
	]


def _vencida(v, nombre_de, mostrar_asesor: bool, ctx) -> dict:
	return {
		"name": v.name,
		"oportunidad": v.opportunity,
		"cliente": v.customer_name or v.party_name,
		"modelo": v.modelo,
		"monto": flt(v.base_grand_total),
		"valid_till": str(v.valid_till),
		"dias_cotizada": (ctx.hoy - getdate(v.transaction_date)).days,
		"asesor": nombre_de.get(v.asesor_usuario, "") if mostrar_asesor else "",
	}


def _resumen(asesores, ops, vencidas, ventas_por_asesor, ctx, cfg) -> dict:
	filas = []
	for a in asesores:
		propias = [o for o in ops if o.asesor_usuario == a.usuario]
		grupo = _agrupar(propias, [], [v for v in vencidas if v.asesor_usuario == a.usuario])
		filas.append(_fila_resumen(a.empleado, a.nombre, grupo, [ventas_por_asesor[a.usuario]], ctx, cfg))
	total = _fila_resumen(None, _("Tienda"), _agrupar(ops, [], vencidas), list(ventas_por_asesor.values()), ctx, cfg)
	return {"filas": filas, "total": total}


def _fila_resumen(empleado, nombre, grupo, ventas_asesores, ctx, cfg) -> dict:
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
