"""Vista Consolidado por asesor: Proyectos, Retail y Total de cada asesor de Plus.

Por asesor: meta, facturado, órdenes de venta, cotizado, cotizaciones vigentes y
oportunidades; las barras de facturado de los últimos meses; la comisión factura
por factura y los documentos vinculados (oportunidad → cotización → orden → factura).
"""

from collections import defaultdict

from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate

from crm_dashboard_v3.crm_tableros.common import consultas, metas, ventas
from crm_dashboard_v3.crm_tableros.common.formato import etiqueta_mes_corta, ritmo

TOTAL = "Total"


def construir(t, ctx, asesores: list, vista_tienda: bool) -> dict:
	"""``vista_tienda``: jefe sin asesor elegido → tarjeta completa de la tienda (como la de
	un asesor, con los datos de todos) y debajo las tarjetas resumen de cada asesor."""
	modelos = list(t.sales_models)
	inicio_hist = get_first_day(add_months(ctx.desde, -(t.meses_historico - 1)))
	meses = [add_months(inicio_hist, i) for i in range(t.meses_historico)]
	datos = {a.usuario: _datos_asesor(a, t, ctx, inicio_hist) for a in asesores}

	tarjetas = []
	if vista_tienda:
		tarjetas.append(_tarjeta(_("Toda la tienda"), None, list(datos.values()), modelos, meses, ctx, detalle=True))
	for a in asesores:
		tarjetas.append(
			_tarjeta(a.nombre, a.empleado, [datos[a.usuario]], modelos, meses, ctx, detalle=not vista_tienda)
		)
	return {"modelos": modelos, "total": TOTAL, "tarjetas": tarjetas, "vista_tienda": vista_tienda}


def _datos_asesor(a, t, ctx, inicio_hist) -> dict:
	usuarios = [a.usuario]
	sps = a.sales_persons
	filas_hist = ventas.facturas_atribuidas(sps, a.usuario, ctx.company, inicio_hist, ctx.hasta, t.modelo_por_defecto)
	ordenes = consultas.ordenes_del_periodo(list(sps), ctx.company, ctx.desde, ctx.hasta)
	for o in ordenes:
		o.modelo = o.sales_model_1 or sps.get(o.asesor) or t.modelo_por_defecto
		o.monto = flt(o.base_net_total) * flt(o.distribucion) / 100
	# En la tarjeta de la tienda cada documento dice de qué asesor es su parte.
	for fila in (*filas_hist, *ordenes):
		fila.asesor_nombre = a.nombre
	return {
		"meta": metas.meta_por_modelo(sps, t.tipo_meta, ctx.desde, ctx.hasta, ctx.company),
		"facturas": [f for f in filas_hist if ctx.desde <= f.fecha <= ctx.hasta],
		"facturado_por_mes": ventas.por_mes(filas_hist),
		"ordenes": ordenes,
		"cotizaciones_mes": consultas.cotizaciones_del_periodo(usuarios, t, ctx.company, ctx.desde, ctx.hasta),
		"cotizaciones_vigentes": consultas.cotizaciones_vigentes(usuarios, t, ctx.company, ctx.hoy),
		"abiertas": consultas.oportunidades_abiertas(usuarios, t, ctx.company),
		"creadas": consultas.oportunidades_creadas(usuarios, t, ctx.company, ctx.desde, ctx.hasta),
	}


def _suma(lista, campo="monto") -> float:
	return sum(flt(x.get(campo)) for x in lista)


def _tarjeta(nombre, empleado, datos: list[dict], modelos, meses, ctx, detalle: bool) -> dict:
	junta = defaultdict(list)
	for d in datos:
		for clave in ("facturas", "ordenes", "cotizaciones_mes", "cotizaciones_vigentes", "abiertas", "creadas"):
			junta[clave].extend(d[clave])
	meta = defaultdict(float)
	por_mes = defaultdict(float)
	for d in datos:
		for modelo, monto in d["meta"].items():
			meta[modelo] += monto
		for llave, monto in d["facturado_por_mes"].items():
			por_mes[llave] += monto

	def de(lista, modelo, campo="modelo"):
		return lista if modelo == TOTAL else [x for x in lista if x.get(campo) == modelo]

	columnas = {}
	for modelo in modelos + [TOTAL]:
		facturas = de(junta["facturas"], modelo)
		ordenes = de(junta["ordenes"], modelo)
		cot_mes = de(junta["cotizaciones_mes"], modelo, "sales_model")
		cot_vig = de(junta["cotizaciones_vigentes"], modelo, "sales_model")
		abiertas = de(junta["abiertas"], modelo, "sales_model")
		creadas = de(junta["creadas"], modelo, "sales_model")
		m = sum(meta.values()) if modelo == TOTAL else meta.get(modelo, 0)
		f = _suma(facturas)
		columnas[modelo] = {
			"meta": m,
			"facturado": f,
			"porcentaje": round(f / m * 100) if m else 0,
			"facturas": sorted({x.name for x in facturas}),
			"ordenes": {"monto": _suma(ordenes), "nombres": sorted({x.name for x in ordenes})},
			"cotizado": {"monto": _suma(cot_mes, "base_net_total"), "nombres": [x.name for x in cot_mes]},
			"vigentes": {"monto": _suma(cot_vig, "base_net_total"), "nombres": [x.name for x in cot_vig]},
			"abiertas": {"cantidad": len(abiertas), "nombres": [x.name for x in abiertas]},
			"creadas": {
				"cantidad": len(creadas),
				"nombres": [x.name for x in creadas],
				"ganadas": sum(1 for x in creadas if x.status == "Converted"),
				"perdidas": sum(1 for x in creadas if x.status == "Lost"),
			},
		}
	total = columnas[TOTAL]
	tarjeta = {
		"nombre": nombre,
		"empleado": empleado,
		"es_tienda": empleado is None,
		"estado": ritmo(total["facturado"], total["meta"], ctx.fraccion_del_mes),
		"columnas": columnas,
		"barras": [
			{
				"etiqueta": etiqueta_mes_corta(mes),
				"por_modelo": {modelo: por_mes.get((mes.strftime("%Y-%m"), modelo), 0) for modelo in modelos},
			}
			for mes in meses
		],
	}
	# La operación de comisión se ve en todas las tarjetas; el detalle por factura
	# y los documentos vinculados, en la del asesor elegido y en la de la tienda.
	tarjeta["comision"] = _comision(junta["facturas"], modelos, con_filas=detalle)
	tarjeta["detalle"] = detalle
	if detalle:
		tarjeta["documentos"] = _documentos(junta)
	return tarjeta


def _comision(facturas, modelos, con_filas: bool) -> dict:
	resumen = {}
	for modelo in modelos + [TOTAL]:
		lista = facturas if modelo == TOTAL else [f for f in facturas if f.modelo == modelo]
		resumen[modelo] = {
			# Una factura repartida entre dos asesores es una sola factura.
			"cantidad": len({f.name for f in lista}),
			"atribuido": _suma(lista),
			"cobrado": sum(f.cobrado * f.distribucion / 100 for f in lista),
			"tasas": sorted({f.tasa for f in lista}),
			"comision": _suma(lista, "comision"),
			"futura": _suma(lista, "comision_futura"),
			"por_cobrar": _suma(lista, "por_cobrar"),
		}
	return {
		"resumen": resumen,
		"filas": [
			{
				"factura": f.name,
				"asesor": f.asesor_nombre,
				"fecha": str(f.fecha),
				"cliente": f.cliente,
				"modelo": f.modelo,
				"nota_de_credito": f.nota_de_credito,
				"propia": f.propia,
				"neto": f.neto,
				"gran_total": f.gran_total,
				"saldo": f.saldo,
				"cobrado": f.cobrado,
				"distribucion": f.distribucion,
				"tasa": f.tasa,
				"comision": f.comision,
				"por_cobrar": f.por_cobrar,
				"futura": f.comision_futura,
			}
			for f in sorted(facturas, key=lambda x: -x.comision)
		]
		if con_filas
		else [],
	}


def _documentos(junta) -> dict:
	ordenes = junta["ordenes"]
	cadena = consultas.cadena_de_ordenes(
		list({o.name for o in ordenes} | {f.sales_order for f in junta["facturas"] if f.sales_order})
	)

	def eslabones(orden):
		c = cadena.get(orden) or {}
		return c.get("oportunidad"), c.get("cotizacion"), c.get("facturas", [])

	facturas = []
	for f in junta["facturas"]:
		oportunidad, cotizacion, _facturas = eslabones(f.sales_order)
		facturas.append(
			{
				"name": f.name,
				"asesor": f.asesor_nombre,
				"fecha": str(f.fecha),
				"cliente": f.cliente,
				"monto": f.monto,
				"modelo": f.modelo,
				"distribucion": f.distribucion,
				"propia": f.propia,
				"nota_de_credito": f.nota_de_credito,
				"oportunidad": oportunidad,
				"cotizacion": cotizacion,
				"orden": f.sales_order,
			}
		)
	filas_ordenes = []
	for o in ordenes:
		oportunidad, cotizacion, de_factura = eslabones(o.name)
		filas_ordenes.append(
			{
				"name": o.name,
				"asesor": o.asesor_nombre,
				"fecha": str(getdate(o.transaction_date)),
				"cliente": o.customer_name,
				"monto": o.monto,
				"modelo": o.modelo,
				"distribucion": flt(o.distribucion),
				"facturado": flt(o.per_billed),
				"oportunidad": oportunidad,
				"cotizacion": cotizacion,
				"facturas": de_factura,
			}
		)

	def fila_cotizacion(q):
		return {
			"name": q.name,
			"fecha": str(getdate(q.transaction_date)),
			"cliente": q.customer_name or q.party_name,
			"monto": flt(q.base_net_total),
			"modelo": q.sales_model,
			"status": q.status,
			"valid_till": str(q.valid_till) if q.valid_till else None,
			"oportunidad": q.opportunity,
		}

	return {
		"facturas": facturas,
		"ordenes": filas_ordenes,
		"cotizaciones_mes": [fila_cotizacion(q) for q in junta["cotizaciones_mes"]],
		"cotizaciones_vigentes": [fila_cotizacion(q) for q in junta["cotizaciones_vigentes"]],
	}
