"""Oportunidades por estado e histórico de los últimos meses (Proyectos y Retail juntos)."""

from collections import defaultdict

from frappe.utils import add_months, flt, get_first_day, getdate

from crm_dashboard_v3.crm_tableros.common import consultas, ventas
from crm_dashboard_v3.crm_tableros.common.formato import etiqueta_mes_corta

# Status de Opportunity -> grupo que se grafica.
ESTADOS = (
	("abierta", "Abierta", ("Open", "Replied")),
	("cotizada", "Cotizada", ("Quotation",)),
	("ganada", "Ganada", ("Converted",)),
	("perdida", "Perdida", ("Lost", "Closed")),
)


def _estado_de(status: str) -> str:
	return next((clave for clave, _t, lista in ESTADOS if status in lista), "abierta")


def construir(t, ctx, asesores: list) -> dict:
	usuarios = [a.usuario for a in asesores]
	inicio = get_first_day(add_months(ctx.desde, -(t.meses_historico - 1)))
	meses = [add_months(inicio, i) for i in range(t.meses_historico)]
	llave = [m.strftime("%Y-%m") for m in meses]

	creadas = consultas.oportunidades_creadas(usuarios, t, ctx.company, inicio, ctx.hasta)
	conteo = defaultdict(lambda: defaultdict(list))
	for o in creadas:
		conteo[getdate(o.creation).strftime("%Y-%m")][_estado_de(o.status)].append(o.name)

	cotizado = defaultdict(float)
	cot_nombres = defaultdict(list)
	for q in consultas.cotizaciones_del_periodo(usuarios, t, ctx.company, inicio, ctx.hasta):
		mes = getdate(q.transaction_date).strftime("%Y-%m")
		cotizado[mes] += flt(q.base_net_total)
		cot_nombres[mes].append(q.name)

	facturado = defaultdict(float)
	fac_nombres = defaultdict(set)
	for a in asesores:
		for f in ventas.facturas_atribuidas(
			a.sales_persons, a.usuario, ctx.company, inicio, ctx.hasta, t.modelo_por_defecto
		):
			mes = f.fecha.strftime("%Y-%m")
			facturado[mes] += f.monto
			fac_nombres[mes].add(f.name)

	ganadas = sum(len(conteo[m]["ganada"]) for m in llave)
	perdidas = sum(len(conteo[m]["perdida"]) for m in llave)
	actual = llave[-1]
	return {
		"estados": [{"clave": c, "titulo": titulo} for c, titulo, _l in ESTADOS],
		"mes_actual": {
			"total": sum(len(v) for v in conteo[actual].values()),
			"por_estado": {c: {"cantidad": len(conteo[actual][c]), "nombres": conteo[actual][c]} for c, *_r in ESTADOS},
		},
		"tasa_cierre": round(ganadas / (ganadas + perdidas) * 100) if ganadas + perdidas else None,
		"meses": [
			{
				"etiqueta": etiqueta_mes_corta(m),
				"oportunidades": {c: len(conteo[k][c]) for c, *_r in ESTADOS},
				"nombres_oportunidades": [n for c, *_r in ESTADOS for n in conteo[k][c]],
				"cotizado": cotizado[k],
				"nombres_cotizado": cot_nombres[k],
				"facturado": facturado[k],
				"nombres_facturado": sorted(fac_nombres[k]),
			}
			for m, k in zip(meses, llave)
		],
		"dia_de_corte": str(ctx.dia_de_corte),
	}
