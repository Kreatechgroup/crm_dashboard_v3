"""Criterios de aceptación del tablero CRM Proyectos (sección 4.4 de CLAUDE.md).

Crean documentos reales en el sitio de pruebas; FrappeTestCase revierte la
transacción al terminar cada clase.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from crm_dashboard_v3.crm_tableros.common import api as api_comun
from crm_dashboard_v3.crm_tableros.common import consultas, etapas, eventos, flujo
from crm_dashboard_v3.crm_tableros.common.contexto import Asesor
from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA, CAMPO_FECHA_PROXIMO_PASO, CAMPO_PROXIMO_PASO
from crm_dashboard_v3.crm_tableros.proyectos import api, embudo
from crm_dashboard_v3.crm_tableros.proyectos.config import RETAIL
from crm_dashboard_v3.crm_tableros.tests.utilidades import (
	CFG,
	MOTIVO_PRUEBA,
	BaseCRMProyectos,
	contexto_de_prueba,
	crear_actividad,
	crear_cotizacion,
	crear_oportunidad,
	mover,
	poner_en,
)


def _asesor_de_prueba():
	return Asesor(None, "Asesor de prueba", frappe.session.user, {})


class TestCriterio1RequerimientoYDiseno(BaseCRMProyectos):
	"""1. No se puede pasar a «Requerimiento y diseño» sin monto, fecha de cierre y próximo paso con fecha."""

	def test_sin_ningun_dato_no_avanza(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			mover(op, "req")
		self.assertEqual(frappe.db.get_value("Opportunity", op.name, CAMPO_ETAPA), CFG.etapa("cal").valor)

	def test_sin_proximo_paso_no_avanza(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000, fecha_estimada_aprobacion=nowdate())
		with self.assertRaises(frappe.ValidationError):
			mover(op, "req")

	def test_proximo_paso_sin_fecha_no_avanza(self):
		op = crear_oportunidad(
			presupuesto_declarado_por_el_cliente=5000,
			fecha_estimada_aprobacion=nowdate(),
			**{CAMPO_PROXIMO_PASO: "Presentar diseño"},
		)
		with self.assertRaises(frappe.ValidationError):
			mover(op, "req")

	def test_sin_fecha_de_cierre_no_avanza(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000)
		crear_actividad(op)
		with self.assertRaises(frappe.ValidationError):
			mover(op, "req")

	def test_con_todo_avanza_usando_la_actividad(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000, fecha_estimada_aprobacion=nowdate())
		crear_actividad(op)
		mover(op, "req")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("req").valor)

	def test_con_todo_avanza_usando_los_campos_de_proximo_paso(self):
		op = crear_oportunidad(
			presupuesto_declarado_por_el_cliente=5000,
			fecha_estimada_aprobacion=nowdate(),
			**{CAMPO_PROXIMO_PASO: "Presentar diseño", CAMPO_FECHA_PROXIMO_PASO: add_days(nowdate(), 2)},
		)
		mover(op, "req")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("req").valor)

	def test_la_actividad_actualiza_el_proximo_paso(self):
		op = crear_oportunidad()
		crear_actividad(op, dias=4)
		op.reload()
		self.assertEqual(getdate(op.get(CAMPO_FECHA_PROXIMO_PASO)), getdate(add_days(nowdate(), 4)))
		self.assertTrue(op.get(CAMPO_PROXIMO_PASO))

	def test_la_api_tambien_valida(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			api.mover_etapa(op.name, "req")


class TestCriterio2ProbabilidadYPronostico(BaseCRMProyectos):
	"""2. La probabilidad cambia sola al mover de etapa y el pronóstico ponderado se recalcula."""

	def test_probabilidad_sigue_a_la_etapa(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000, fecha_estimada_aprobacion=nowdate())
		self.assertEqual(flt(op.probability), 10)
		crear_actividad(op)
		mover(op, "req")
		self.assertEqual(flt(op.probability), 25)

	def test_probabilidad_no_se_puede_editar_a_mano(self):
		op = crear_oportunidad()
		op.probability = 90
		op.save()
		self.assertEqual(flt(op.probability), 10)

	def test_pronostico_se_recalcula_al_mover(self):
		monto = 40000
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=monto, fecha_estimada_aprobacion=nowdate())
		crear_actividad(op)
		ctx = contexto_de_prueba()
		asesores = [_asesor_de_prueba()]

		antes = embudo.construir(self.tablero, ctx, asesores)["kpis"]["pronostico"]
		api.mover_etapa(op.name, "req")
		despues = embudo.construir(self.tablero, ctx, asesores)["kpis"]["pronostico"]

		self.assertIn(op.name, despues["nombres_total"])
		self.assertAlmostEqual(despues["total"] - antes["total"], monto * (25 - 10) / 100, places=2)
		self.assertAlmostEqual(despues["mes"] - antes["mes"], monto * (25 - 10) / 100, places=2)

	def test_en_pausa_no_cuenta_en_el_pronostico(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=10000, fecha_estimada_aprobacion=nowdate())
		api.mover_etapa(op.name, "pausa", fecha_retomar=add_days(nowdate(), 10))
		pronostico = embudo.construir(self.tablero, contexto_de_prueba(), [_asesor_de_prueba()])["kpis"]["pronostico"]
		self.assertNotIn(op.name, pronostico["nombres_total"])

	def test_pausa_exige_fecha_para_retomar(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			api.mover_etapa(op.name, "pausa")


class TestCriterio3PropuestasVencidas(BaseCRMProyectos):
	"""3. Una cotización vencida aparece en «Propuestas vencidas» y sale al renovarla o perderla."""

	def _vencida(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=10000, fecha_estimada_aprobacion=nowdate())
		q = crear_cotizacion(op, valid_till=add_days(nowdate(), -1), transaction_date=add_days(nowdate(), -30))
		return op, q

	def _nombres_vencidas(self, op):
		return [v.name for v in consultas.cotizaciones_vencidas([op.name], getdate(nowdate()))]

	def test_vencida_aparece(self):
		op, q = self._vencida()
		self.assertIn(q.name, self._nombres_vencidas(op))

	def test_vencida_aparece_en_el_tablero(self):
		op, q = self._vencida()
		datos = embudo.construir(self.tablero, contexto_de_prueba(), [_asesor_de_prueba()])
		self.assertIn(q.name, datos["kpis"]["vencidas"]["nombres"])

	def test_vigente_no_aparece(self):
		op = crear_oportunidad()
		q = crear_cotizacion(op, valid_till=add_days(nowdate(), 10))
		self.assertNotIn(q.name, self._nombres_vencidas(op))

	def test_sale_al_renovar(self):
		op, q = self._vencida()
		nueva = api.renovar_cotizacion(q.name)
		self.assertNotIn(q.name, self._nombres_vencidas(op))
		self.assertNotIn(nueva, self._nombres_vencidas(op))
		self.assertGreaterEqual(getdate(frappe.db.get_value("Quotation", nueva, "valid_till")), getdate(nowdate()))
		self.assertEqual(frappe.db.get_value("Quotation", nueva, "docstatus"), 1)

	def test_sale_al_perder_y_la_oportunidad_queda_perdida(self):
		op, q = self._vencida()
		api.perder_cotizacion(q.name, MOTIVO_PRUEBA)
		self.assertNotIn(q.name, self._nombres_vencidas(op))
		op.reload()
		self.assertEqual(op.status, "Lost")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("perdida").valor)

	def test_perder_exige_motivo_especifico(self):
		op, q = self._vencida()
		with self.assertRaises(frappe.ValidationError):
			api.perder_cotizacion(q.name, "Especificar motivo")
		self.assertIn(q.name, self._nombres_vencidas(op))

	def test_perder_con_otra_vigente_tambien_pierde_la_oportunidad(self):
		op, q = self._vencida()
		crear_cotizacion(op, valid_till=add_days(nowdate(), 10), transaction_date=add_days(nowdate(), -40))
		api.perder_cotizacion(q.name, MOTIVO_PRUEBA)
		op.reload()
		self.assertEqual(frappe.db.get_value("Quotation", q.name, "status"), "Lost")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("perdida").valor)
		self.assertEqual(op.status, "Lost")

	def test_perder_bloqueado_por_workflow_no_toca_la_cotizacion(self):
		op, q = self._vencida()
		with patch.object(flujo, "bloqueo", return_value="El workflow no permite pasar a Perdida"):
			with self.assertRaises(frappe.ValidationError):
				api.perder_cotizacion(q.name, MOTIVO_PRUEBA)
		self.assertNotEqual(frappe.db.get_value("Quotation", q.name, "status"), "Lost")
		self.assertIn(q.name, self._nombres_vencidas(op))


class TestCriterio4GanadaConverted(BaseCRMProyectos):
	"""4. Una oportunidad en Ganada siempre tiene status = Converted (y Perdida = Lost)."""

	def test_no_se_marca_ganada_sin_orden_de_venta(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			mover(op, "ganada")
		self.assertNotEqual(frappe.db.get_value("Opportunity", op.name, "status"), "Converted")

	def test_ganada_pone_status_converted(self):
		op = poner_en(crear_oportunidad(), "neg")  # Ganada solo se permite desde Propuesta o Negociación
		siempre = ("orden de venta creada", lambda d, r, c: True)
		with patch.dict(etapas.REQUISITOS, {"orden_de_venta": siempre}):
			mover(op, "ganada")
		self.assertEqual(op.status, "Converted")
		self.assertEqual(flt(op.probability), 100)

	def test_orden_de_venta_enviada_marca_ganada(self):
		op = crear_oportunidad()
		eventos.marcar_ganada(op.name)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("ganada").valor)
		self.assertEqual(op.status, "Converted")

	def test_ganada_no_regresa_a_otra_etapa(self):
		op = crear_oportunidad()
		eventos.marcar_ganada(op.name)
		with self.assertRaises(frappe.ValidationError):
			mover(op, "neg")

	def test_perdida_pone_status_lost(self):
		op = crear_oportunidad()
		api.mover_etapa(op.name, "perdida", motivo=MOTIVO_PRUEBA)
		op.reload()
		self.assertEqual(op.status, "Lost")
		self.assertEqual(flt(op.probability), 0)

	def test_lost_desde_erpnext_arrastra_la_etapa(self):
		op = crear_oportunidad()
		op.status = "Lost"
		op.lost_reason = MOTIVO_PRUEBA
		op.save()
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("perdida").valor)

	def test_especificar_motivo_no_es_valido(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			api.mover_etapa(op.name, "perdida", motivo="Especificar motivo")
		self.assertEqual(frappe.db.get_value("Opportunity", op.name, "status"), "Open")


class TestWorkflowCompartido(BaseCRMProyectos):
	"""Etapas con nombre real en embudo_state_v2 y scripts viejos que no rompen nada."""

	def _guardar_con(self, op, valor):
		op.reload()
		op.set(CAMPO_ETAPA, valor)
		op.save()
		return op

	def test_la_oportunidad_nueva_empieza_en_calificar(self):
		op = crear_oportunidad()
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.inicial.valor)
		self.assertEqual(frappe.db.get_value("Opportunity", op.name, CAMPO_ETAPA), "1 · Calificar")
		self.assertEqual(flt(op.probability), 10)

	def test_script_con_valor_viejo_se_ignora_sin_error(self):
		# Como Quotation-Client o Integración de costos: escriben «Presentar cotización».
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=4000)
		op = self._guardar_con(op, "Presentar cotización")
		self.assertEqual(op.get(CAMPO_ETAPA), "1 · Calificar")
		# Lo demás que guarda el script sí se conserva.
		self.assertEqual(flt(op.presupuesto_declarado_por_el_cliente), 4000)

	def test_ganada_escrita_por_un_script_desde_calificar_se_ignora(self):
		# Como Sales Order-Client: desde Calificar el workflow no permite Ganada.
		op = self._guardar_con(crear_oportunidad(), "Ganada")
		self.assertEqual(op.get(CAMPO_ETAPA), "1 · Calificar")
		self.assertNotEqual(op.status, "Converted")

	def test_el_tablero_escribe_el_nombre_real_de_la_etapa(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000, fecha_estimada_aprobacion=nowdate())
		crear_actividad(op)
		mover(op, "req")
		self.assertEqual(op.get(CAMPO_ETAPA), "2 · Requerimiento y diseño")
		self.assertEqual(flt(op.probability), 25)

	def test_cotizacion_enviada_pasa_a_propuesta_enviada(self):
		op = crear_oportunidad(
			presupuesto_declarado_por_el_cliente=5000,
			fecha_estimada_aprobacion=add_days(nowdate(), 20),
			**{CAMPO_PROXIMO_PASO: "Presentar propuesta", CAMPO_FECHA_PROXIMO_PASO: add_days(nowdate(), 2)},
		)
		crear_cotizacion(op, valid_till=add_days(nowdate(), 15), monto=8000)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), "3 · Propuesta enviada")
		self.assertEqual(flt(op.probability), 50)

	def test_cotizacion_enviada_sin_requisitos_no_mueve_ni_bloquea(self):
		op = crear_oportunidad()  # sin fecha estimada ni próximo paso
		q = crear_cotizacion(op, valid_till=add_days(nowdate(), 15))
		self.assertEqual(q.docstatus, 1)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), "1 · Calificar")

	def test_descartar_en_plus_pide_motivo_y_da_por_perdida(self):
		op = crear_oportunidad()
		regla = api_comun.como_descartar(op.name)
		self.assertTrue(regla["pedir_motivo"])
		self.assertIn(MOTIVO_PRUEBA, regla["motivos"])
		api_comun.descartar_oportunidad(op.name, MOTIVO_PRUEBA)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), "Perdida")
		self.assertEqual(op.status, "Lost")

	def test_descartar_sin_motivo_valido_no_procede(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			api_comun.descartar_oportunidad(op.name, "Especificar motivo")


class TestWorkflowDeLaEtapa(BaseCRMProyectos):
	"""El workflow que controla embudo_state_v2 nunca hace fallar un guardado por el hook."""

	def test_lost_sin_transicion_no_rompe_el_guardado(self):
		op = crear_oportunidad()
		with patch.object(flujo, "bloqueo", return_value="El workflow no permite"):
			op.status = "Lost"
			op.lost_reason = MOTIVO_PRUEBA
			op.save()
		self.assertEqual(op.status, "Lost")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("cal").valor)

	def test_la_page_explica_la_transicion_que_falta(self):
		op = crear_oportunidad()
		with patch.object(flujo, "bloqueo", return_value="El workflow no permite pasar de A a B"):
			with self.assertRaises(frappe.ValidationError) as error:
				api.mover_etapa(op.name, "pausa", fecha_retomar=add_days(nowdate(), 5))
		self.assertIn("El workflow no permite pasar de A a B", str(error.exception))
		self.assertEqual(frappe.db.get_value("Opportunity", op.name, CAMPO_ETAPA), CFG.etapa("cal").valor)

	def test_el_detalle_avisa_el_bloqueo_antes_de_mover(self):
		op = crear_oportunidad()
		with patch.object(flujo, "bloqueo", return_value="Falta la transición"):
			detalle = api.get_oportunidad(op.name)
		self.assertEqual(detalle["bloqueos"]["pausa"], "Falta la transición")
		self.assertIn("Falta la transición", detalle["siguiente"]["faltantes"])


class TestRetailDePlus(BaseCRMProyectos):
	"""Las oportunidades Retail de los asesores de Plus usan las etapas de Proyectos y entran al tablero."""

	def test_retail_de_plus_valida_requisitos(self):
		op = crear_oportunidad(sales_model=RETAIL)
		self.assertEqual(flt(op.probability), 10)
		with self.assertRaises(frappe.ValidationError):
			mover(op, "req")

	def test_retail_de_plus_aparece_en_el_embudo_con_su_modelo(self):
		op = crear_oportunidad(sales_model=RETAIL, presupuesto_declarado_por_el_cliente=3000)
		datos = embudo.construir(self.tablero, contexto_de_prueba(), [_asesor_de_prueba()])
		tarjetas = [t for c in datos["columnas"] for t in c["tarjetas"]]
		tarjeta = next(t for t in tarjetas if t["name"] == op.name)
		self.assertEqual(tarjeta["modelo"], RETAIL)

	def test_fuera_del_establecimiento_no_entra(self):
		op = crear_oportunidad(sales_model=RETAIL)
		frappe.db.set_value("Opportunity", op.name, "establecimiento_lista", None)
		with self.assertRaises(frappe.ValidationError):
			api.get_oportunidad(op.name)
