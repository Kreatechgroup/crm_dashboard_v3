"""Migración de las oportunidades abiertas de un tablero a sus etapas nuevas (fase 1: Plus).

Reglas (docs/diseno_workflow_compartido.md, sección 7):

- valores viejos → etapa nueva según ``mapa_valores`` (especificación);
- «Ganada» con status abierto: con orden de venta → Converted; sin orden → revisión;
- «Descartada» → Perdida, status Lost, motivo ``motivo_descartada`` («No calificó»);
- «Perdida» con status abierto: con motivo → Lost; sin motivo → revisión;
- la probabilidad pasa a la de la etapa.

Escribe directo en la base (sin guardar documento por documento) para no disparar
scripts ni notificaciones, y guarda los valores anteriores en los campos de respaldo.
Nada corre en ``migrate``; se ejecuta a mano y primero en simulación:

    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.etapas_plus.simular
    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.etapas_plus.ejecutar --kwargs "{'confirmar': True}"
    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.etapas_plus.revertir --kwargs "{'confirmar': True}"
"""

from collections import Counter

import frappe
from frappe.utils import now_datetime

from crm_dashboard_v3.crm_tableros.common import flujo
from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_ETAPA_ANTERIOR,
	CAMPO_MIGRADA_EL,
	CAMPO_MOTIVO_ANTERIOR,
	CAMPO_ORDEN_DE_VENTA,
	CAMPO_PROBABILIDAD_ANTERIOR,
	CAMPO_STATUS_ANTERIOR,
	STATUS_CERRADOS,
	DatosRelacionados,
	orden_vinculada,
)
from crm_dashboard_v3.crm_tableros.common.tableros import ConfigTablero, tablero

TABLERO = "proyectos"
VALOR_DESCARTADA = "Descartada"
REVISAR = "revisar"


# ---------------------------------------------------------------------------
# Regla por oportunidad (función pura: se prueba sin base de datos)
# ---------------------------------------------------------------------------


def cambio_para(row, t: ConfigTablero, tiene_orden: bool) -> dict | None:
	"""Qué hacer con una oportunidad abierta del tablero.

	Devuelve None si no hay nada que cambiar, ``{"caso": REVISAR, ...}`` si debe
	revisarla una persona, o el caso y los valores nuevos.
	"""
	cfg = t.etapas
	valor = row.get(CAMPO_ETAPA)
	etapa = cfg.por_valor(valor)
	if not etapa:
		return {"caso": REVISAR, "motivo": f"etapa no reconocida: {valor!r}"}
	nuevo = {CAMPO_ETAPA: etapa.valor}
	if etapa.probabilidad is not None:
		nuevo["probability"] = etapa.probabilidad

	if etapa.status == "Converted":
		if not tiene_orden:
			return {"caso": REVISAR, "motivo": "Ganada sin orden de venta"}
		nuevo["status"] = "Converted"
		caso = "Ganada con orden → Converted"
	elif etapa.status == "Lost":
		if valor == VALOR_DESCARTADA:
			nuevo["status"] = "Lost"
			nuevo["lost_reason"] = row.get("lost_reason") or cfg.motivo_descartada
			caso = f"Descartada → Perdida ({cfg.motivo_descartada})"
		elif row.get("lost_reason"):
			nuevo["status"] = "Lost"
			caso = "Perdida con motivo → Lost"
		else:
			return {"caso": REVISAR, "motivo": "Perdida sin motivo"}
	else:
		caso = f"{valor} → {etapa.valor}"

	cambios = {k: v for k, v in nuevo.items() if row.get(k) != v}
	if not cambios:
		return None
	return {"caso": caso, "valores": cambios}


# ---------------------------------------------------------------------------
# Universo, simulación, ejecución y reversa
# ---------------------------------------------------------------------------


def _universo(t: ConfigTablero) -> list:
	"""Oportunidades abiertas del tablero (todas las empresas de sus establecimientos)."""
	return frappe.get_all(
		"Opportunity",
		filters=[
			["establecimiento_lista", "in", list(t.establecimientos)],
			["sales_model", "in", list(t.sales_models)],
			["status", "not in", list(STATUS_CERRADOS)],
		],
		fields=["name", "status", "probability", "lost_reason", CAMPO_ETAPA, CAMPO_MIGRADA_EL, CAMPO_ORDEN_DE_VENTA],
		order_by="name asc",
	)


def _tiene_orden(row) -> bool:
	return bool(DatosRelacionados(row.name).ordenes_de_venta or orden_vinculada(row))


def plan(t: ConfigTablero | None = None) -> list[dict]:
	t = t or tablero(TABLERO)
	resultado = []
	for row in _universo(t):
		etapa = t.etapas.por_valor(row.get(CAMPO_ETAPA))
		tiene_orden = etapa is not None and etapa.status == "Converted" and _tiene_orden(row)
		cambio = cambio_para(row, t, tiene_orden)
		if cambio:
			resultado.append({"name": row.name, "antes": row, **cambio})
	return resultado


def simular():
	"""Reporte de lo que haría ejecutar(), sin escribir nada."""
	t = tablero(TABLERO)
	cambios = plan(t)
	revisar = [c for c in cambios if c["caso"] == REVISAR]
	aplicar = [c for c in cambios if c["caso"] != REVISAR]
	print(f"Tablero: {t.titulo} · establecimientos {list(t.establecimientos)} · modelos {list(t.sales_models)}")
	print(f"Oportunidades abiertas: {len(_universo(t))} · se cambiarían: {len(aplicar)} · a revisión: {len(revisar)}")
	for caso, n in Counter(c["caso"] for c in aplicar).most_common():
		print(f"  {n:>4}  {caso}")
	if revisar:
		print("A revisión (no se cambian):")
		for c in revisar:
			print(f"  {c['name']}  {c['antes'].get(CAMPO_ETAPA)!r} · status {c['antes'].status} · {c['motivo']}")
	faltan = [e.valor for e in t.etapas.etapas if not flujo.estado_existe(e.valor)]
	if faltan:
		print(f"AVISO: el workflow activo todavía no tiene estos estados: {faltan}. Primero workflow.instalar().")
	if not frappe.db.exists("Lost Reason", t.etapas.motivo_descartada):
		print(f"AVISO: no existe el motivo «{t.etapas.motivo_descartada}» en Lost Reason; ejecutar() lo crearía.")
	print("Simulación: no se escribió nada.")


def ejecutar(confirmar: bool = False):
	"""Aplica la migración. Exige confirmar=True y el workflow compartido instalado."""
	if not confirmar:
		frappe.throw("Primero revisa simular(). Para ejecutar, pasa confirmar=True.")
	t = tablero(TABLERO)
	faltan = [e.valor for e in t.etapas.etapas if not flujo.estado_existe(e.valor)]
	if faltan:
		frappe.throw(f"El workflow activo no tiene los estados {faltan}. Ejecuta antes workflow.instalar().")
	motivo = t.etapas.motivo_descartada
	if motivo and not frappe.db.exists("Lost Reason", motivo):
		frappe.get_doc({"doctype": "Lost Reason", "lost_reason_name": motivo}).insert()

	momento = now_datetime()
	aplicadas = 0
	for c in plan(t):
		if c["caso"] == REVISAR:
			continue
		antes = c["antes"]
		valores = dict(c["valores"])
		if not antes.get(CAMPO_MIGRADA_EL):
			# Respaldo solo la primera vez: volver a ejecutar no pisa los valores originales.
			valores.update(
				{
					CAMPO_ETAPA_ANTERIOR: antes.get(CAMPO_ETAPA),
					CAMPO_STATUS_ANTERIOR: antes.status,
					CAMPO_PROBABILIDAD_ANTERIOR: antes.probability,
					CAMPO_MOTIVO_ANTERIOR: antes.lost_reason,
					CAMPO_MIGRADA_EL: momento,
				}
			)
		frappe.db.set_value("Opportunity", c["name"], valores, update_modified=False)
		aplicadas += 1
	frappe.db.commit()
	print(f"Migradas: {aplicadas}. Las que están a revisión no se tocaron (ver simular()).")


def revertir(confirmar: bool = False):
	"""Restaura los valores guardados en el respaldo de las oportunidades migradas."""
	if not confirmar:
		frappe.throw("Para revertir, pasa confirmar=True.")
	migradas = frappe.get_all(
		"Opportunity",
		filters={CAMPO_MIGRADA_EL: ["is", "set"]},
		fields=["name", CAMPO_ETAPA_ANTERIOR, CAMPO_STATUS_ANTERIOR, CAMPO_PROBABILIDAD_ANTERIOR, CAMPO_MOTIVO_ANTERIOR],
	)
	for m in migradas:
		frappe.db.set_value(
			"Opportunity",
			m.name,
			{
				CAMPO_ETAPA: m.get(CAMPO_ETAPA_ANTERIOR),
				"status": m.get(CAMPO_STATUS_ANTERIOR),
				"probability": m.get(CAMPO_PROBABILIDAD_ANTERIOR),
				"lost_reason": m.get(CAMPO_MOTIVO_ANTERIOR),
				CAMPO_ETAPA_ANTERIOR: None,
				CAMPO_STATUS_ANTERIOR: None,
				CAMPO_PROBABILIDAD_ANTERIOR: None,
				CAMPO_MOTIVO_ANTERIOR: None,
				CAMPO_MIGRADA_EL: None,
			},
			update_modified=False,
		)
	frappe.db.commit()
	print(f"Revertidas: {len(migradas)}.")
