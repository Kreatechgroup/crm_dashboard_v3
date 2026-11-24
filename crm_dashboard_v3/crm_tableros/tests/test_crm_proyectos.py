"""Criterios de aceptación del tablero CRM Proyectos (sección 4.4 de CLAUDE.md).

Crean documentos reales en el sitio de pruebas; FrappeTestCase revierte la
transacción al terminar cada clase.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, flt, getdate, nowdate

from crm_dashboard_v3.crm_tableros.common import api as api_comun
from crm_dashboard_v3.crm_tableros.common import consultas, etapas, eventos, flujo, venta_pos
from crm_dashboard_v3.crm_tableros.common.contexto import Asesor
from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_FACTURA_POS,
	CAMPO_FECHA_PROXIMO_PASO,
	CAMPO_PROXIMO_PASO,
)
from crm_dashboard_v3.crm_tableros.proyectos import api, embudo
from crm_dashboard_v3.crm_tableros.proyectos.config import RETAIL
from crm_dashboard_v3.crm_tableros.tests.utilidades import (
	CFG,
	MOTIVO_PRUEBA,
	BaseCRMProyectos,
	contexto_de_prueba,
	crear_actividad,
	crear_cotizacion,
	crear_devolucion,
	crear_factura,
	crear_oportunidad,
	marcar_pos,
	mover,
	poner_en,
)

# Usuario que no es el asesor de las oportunidades de prueba (solo se compara el correo).
OTRO_ASESOR = "otro.asesor.prueba@example.com"


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

	def test_pausa_no_informa_probabilidad(self):
		op = crear_oportunidad()
		r = api.mover_etapa(op.name, "pausa", fecha_retomar=add_days(nowdate(), 10))
		self.assertIsNone(r["probability"])

	def test_retomar_no_salta_la_propuesta_sin_cotizacion(self):
		# Con monto, fecha y próximo paso vigente cumple «Negociación», pero no tiene cotización.
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=10000, fecha_estimada_aprobacion=nowdate())
		crear_actividad(op)
		api.mover_etapa(op.name, "pausa", fecha_retomar=add_days(nowdate(), 10))
		self.assertEqual(api.get_oportunidad(op.name)["siguiente"]["clave"], "req")
		with self.assertRaises(frappe.ValidationError):
			api.mover_etapa(op.name, "neg")


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

	def test_renovada_no_trae_vencimientos_de_pago_pasados(self):
		# Si la copia conservara los vencimientos de la original, la orden de venta no se podría crear.
		op, q = self._vencida()
		nueva = api.renovar_cotizacion(q.name)
		vencimientos = frappe.get_all("Payment Schedule", filters={"parent": nueva, "parenttype": "Quotation"}, pluck="due_date")
		for fecha in vencimientos:
			self.assertGreaterEqual(getdate(fecha), getdate(nowdate()))

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

	def _orden_para(self, op, delivery_date):
		frappe.flags.args = frappe._dict(delivery_date=delivery_date)
		try:
			return api.orden_de_venta_para_oportunidad(op.name)
		finally:
			frappe.flags.args = None

	def test_ganar_abre_la_orden_sin_guardarla(self):
		op = crear_oportunidad()
		crear_cotizacion(op, valid_till=add_days(nowdate(), 10), transaction_date=add_days(nowdate(), -5))
		antes = frappe.db.count("Sales Order")
		orden = self._orden_para(op, add_days(nowdate(), 7))
		self.assertTrue(orden.is_new())
		self.assertEqual(frappe.db.count("Sales Order"), antes)
		self.assertEqual(getdate(orden.delivery_date), getdate(add_days(nowdate(), 7)))
		self.assertEqual(orden.get("sales_model_1"), op.sales_model)
		# Sin los vencimientos de la cotización (de otro día): ERPNext los recalcula al guardar.
		self.assertFalse(orden.payment_schedule)

	def test_ganar_exige_cotizacion_vigente_y_fecha_futura(self):
		op = crear_oportunidad()
		crear_cotizacion(op, valid_till=add_days(nowdate(), -1), transaction_date=add_days(nowdate(), -30))
		with self.assertRaises(frappe.ValidationError):
			self._orden_para(op, add_days(nowdate(), 7))
		crear_cotizacion(op, valid_till=add_days(nowdate(), 10))
		with self.assertRaises(frappe.ValidationError):
			self._orden_para(op, add_days(nowdate(), -1))

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

	# NUEVO-1 · Converted puesto a mano sin orden de venta ni venta POS no es una ganada.

	def test_converted_a_mano_sin_requisitos_se_revierte(self):
		op = poner_en(crear_oportunidad(), "prop")
		op.status = "Converted"
		op.save()
		op.reload()
		self.assertEqual(op.status, "Open")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("prop").valor)

	def test_converted_y_ganada_a_mano_sin_requisitos_se_revierten(self):
		op = poner_en(crear_oportunidad(), "prop")
		op.status = "Converted"
		op.set(CAMPO_ETAPA, CFG.etapa("ganada").valor)
		op.save()
		op.reload()
		self.assertEqual(op.status, "Open")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("prop").valor)

	def test_converted_a_mano_con_venta_pos_arrastra_la_etapa(self):
		# Desde 2 (acepta venta POS): con la venta ya guardada el workflow permite Ganada.
		op = poner_en(crear_oportunidad(), "req")
		factura = crear_factura(op)
		op.set(CAMPO_FACTURA_POS, factura.name)
		op.save()
		op.status = "Converted"
		op.save()
		op.reload()
		self.assertEqual(op.status, "Converted")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("ganada").valor)

	# NUEVO-5 · Converted a mano con requisitos, pero el workflow no permite pasar a Ganada.

	def test_converted_a_mano_bloqueado_por_el_workflow_se_revierte(self):
		op = poner_en(crear_oportunidad(), "req")
		factura = crear_factura(op)
		op.set(CAMPO_FACTURA_POS, factura.name)
		op.save()
		frappe.clear_messages()
		op.status = "Converted"
		with patch.object(flujo, "bloqueo", return_value="El workflow no permite pasar a Ganada"):
			op.save()
		op.reload()
		self.assertEqual(op.status, "Open")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("req").valor)
		self.assertTrue(any(self.tablero.titulo in str(m) for m in frappe.message_log))

	def test_converted_y_venta_pos_desde_calificar_en_el_mismo_guardado(self):
		# Requisitos cumplidos en memoria (venta POS), pero el workflow mira la versión
		# guardada (sin venta) y no permite Ganada desde Calificar: se guarda la venta y
		# el status vuelve a Open, junto con la etapa que no se movió.
		op = poner_en(crear_oportunidad(), CFG.inicial.clave)
		factura = crear_factura(op)
		op.set(CAMPO_FACTURA_POS, factura.name)
		op.status = "Converted"
		op.save()
		op.reload()
		self.assertEqual(op.get(CAMPO_FACTURA_POS), factura.name)
		self.assertEqual(op.status, "Open")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.inicial.valor)

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
		# Desde Calificar pasa por Requerimiento y diseño (el workflow solo avanza de una en una).
		self.assertEqual(op.get(CAMPO_ETAPA), "3 · Propuesta enviada")
		self.assertEqual(flt(op.probability), 50)
		self.assertEqual(flt(op.opportunity_amount), 8000)

	def test_cotizacion_enviada_sin_requisitos_no_mueve_ni_bloquea(self):
		op = crear_oportunidad()  # sin fecha estimada ni próximo paso
		q = crear_cotizacion(op, valid_till=add_days(nowdate(), 15))
		self.assertEqual(q.docstatus, 1)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), "1 · Calificar")

	def test_cotizacion_enviada_sin_proximo_paso_avisa_que_falta(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000, fecha_estimada_aprobacion=add_days(nowdate(), 20))
		frappe.clear_messages()
		q = crear_cotizacion(op, valid_till=add_days(nowdate(), 15))
		self.assertEqual(q.docstatus, 1)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), "1 · Calificar")
		avisos = " ".join(str(m) for m in frappe.message_log)
		self.assertIn("quedó en 1 · Calificar", avisos)
		self.assertIn("próximo paso con fecha", avisos)

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


class TestGanadaConVentaPOS(BaseCRMProyectos):
	"""El cliente compró en caja (POS) sin orden de venta: la oportunidad se gana ligando la factura POS.

	Las facturas se preparan en la prueba (crear_factura) y se revierten al terminar.
	"""

	def _candidatas(self, op):
		return [f.name for f in venta_pos.candidatas(op)]

	def test_venta_pos_cumple_el_requisito_de_ganada(self):
		op = crear_oportunidad()
		factura = crear_factura(op)
		self.assertTrue(etapas.faltantes(op, CFG.etapa("ganada"), CFG))
		op.set(CAMPO_FACTURA_POS, factura.name)
		self.assertEqual(etapas.faltantes(op, CFG.etapa("ganada"), CFG), [])

	def test_vincular_venta_pos_marca_ganada_desde_calificar(self):
		op = crear_oportunidad()
		factura = crear_factura(op)
		self.assertIn(factura.name, [f["name"] for f in api.get_oportunidad(op.name)["facturas_pos"]])
		api.vincular_factura_pos(op.name, factura.name)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("ganada").valor)
		self.assertEqual(op.status, "Converted")
		self.assertEqual(flt(op.probability), 100)
		self.assertEqual(op.get(CAMPO_FACTURA_POS), factura.name)

	def _vincular_y_verificar_ganada(self, clave):
		# El workflow permite Ganada desde 2 y En pausa solo con la venta POS guardada
		# (migracion.workflow.transiciones_de): vincular_factura_pos la guarda primero.
		op = poner_en(crear_oportunidad(), clave)
		factura = crear_factura(op)
		self.assertIn(factura.name, self._candidatas(op))
		api.vincular_factura_pos(op.name, factura.name)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("ganada").valor)
		self.assertEqual(op.status, "Converted")
		self.assertEqual(flt(op.probability), 100)
		self.assertEqual(op.get(CAMPO_FACTURA_POS), factura.name)

	def test_vincular_venta_pos_marca_ganada_desde_requerimiento(self):
		self._vincular_y_verificar_ganada("req")

	def test_vincular_venta_pos_marca_ganada_desde_pausa(self):
		self._vincular_y_verificar_ganada("pausa")

	def _rechazada(self, op, factura):
		"""La factura no es candidata y vincularla por nombre falla sin tocar la oportunidad."""
		self.assertNotIn(factura.name, self._candidatas(op))
		self.assertNotIn(factura.name, [f["name"] for f in api.get_oportunidad(op.name)["facturas_pos"]])
		with self.assertRaises(frappe.ValidationError):
			api.vincular_factura_pos(op.name, factura.name)
		campos = ["status", CAMPO_ETAPA, CAMPO_FACTURA_POS]
		datos = frappe.db.get_value("Opportunity", op.name, campos, as_dict=True)
		self.assertNotEqual(datos.status, "Converted")
		self.assertNotEqual(datos.get(CAMPO_ETAPA), CFG.etapa("ganada").valor)
		self.assertFalse(datos.get(CAMPO_FACTURA_POS))

	def test_venta_pos_de_otro_asesor_no_es_candidata(self):
		# Oportunidad desde un lead sin cliente: solo valdrían las ventas del propio asesor.
		op = crear_oportunidad()
		factura = crear_factura(op)
		self.assertIn(factura.name, self._candidatas(op))
		frappe.db.set_value("Sales Invoice", factura.name, "owner", OTRO_ASESOR)
		self._rechazada(op, factura)

	def test_venta_pos_de_otro_cliente_no_es_candidata(self):
		# Venta capturada por otro usuario: solo vale si es del cliente de la oportunidad.
		filtros = {"disabled": 0} if frappe.get_meta("Customer").has_field("disabled") else {}
		clientes = frappe.get_all("Customer", filters=filtros, pluck="name", limit=2, order_by="name")
		if len(clientes) < 2:
			self.skipTest("El sitio de pruebas necesita al menos dos clientes.")
		cliente, otro_cliente = clientes
		op = crear_oportunidad(opportunity_from="Customer", party_name=cliente)
		factura = crear_factura(op)
		frappe.db.set_value("Sales Invoice", factura.name, {"owner": OTRO_ASESOR, "customer": cliente})
		# Control: del mismo cliente sí es candidata aunque la haya capturado otro usuario.
		self.assertIn(factura.name, self._candidatas(op))
		frappe.db.set_value("Sales Invoice", factura.name, "customer", otro_cliente)
		self._rechazada(op, factura)

	def test_factura_que_no_es_pos_no_se_vincula(self):
		op = crear_oportunidad()
		factura = crear_factura(op, pos=False)
		with self.assertRaises(frappe.ValidationError):
			api.vincular_factura_pos(op.name, factura.name)
		op.reload()
		self.assertNotEqual(op.status, "Converted")
		self.assertFalse(op.get(CAMPO_FACTURA_POS))

	# ALTO-1 · Sin atajo por API ni por la acción del workflow en el formulario.

	def test_poner_por_api_una_factura_que_no_es_candidata_falla(self):
		op = crear_oportunidad()
		factura = crear_factura(op, pos=False)
		op.set(CAMPO_FACTURA_POS, factura.name)
		with self.assertRaises(frappe.ValidationError):
			op.save()
		self.assertFalse(frappe.db.get_value("Opportunity", op.name, CAMPO_FACTURA_POS))

	def test_ganada_por_el_workflow_sin_requisitos_se_revierte(self):
		# De 3 a Ganada el workflow no pide nada al campo: sin orden ni venta POS, la etapa no cambia.
		op = poner_en(crear_oportunidad(), "prop")
		op.set(CAMPO_ETAPA, CFG.etapa("ganada").valor)
		op.save()
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("prop").valor)
		self.assertNotEqual(op.status, "Converted")

	def test_ganada_por_el_workflow_con_venta_pos_valida(self):
		op = crear_oportunidad()
		factura = crear_factura(op)
		op.set(CAMPO_FACTURA_POS, factura.name)
		op.save()
		op.set(CAMPO_ETAPA, CFG.etapa("ganada").valor)
		op.save()
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("ganada").valor)
		self.assertEqual(op.status, "Converted")

	# Venta POS y etapa Ganada en el mismo guardado por API.

	def test_venta_pos_y_ganada_desde_propuesta_en_el_mismo_guardado_se_rechaza(self):
		# En 3 · Propuesta enviada no se acepta venta POS (decisión del negocio): el vínculo
		# se rechaza aunque venga con Ganada en el mismo guardado, y no se guarda nada.
		op = poner_en(crear_oportunidad(), "prop")
		factura = crear_factura(op)
		op.set(CAMPO_FACTURA_POS, factura.name)
		op.set(CAMPO_ETAPA, CFG.etapa("ganada").valor)
		with self.assertRaises(frappe.ValidationError):
			op.save()
		datos = frappe.db.get_value("Opportunity", op.name, ["status", CAMPO_ETAPA, CAMPO_FACTURA_POS], as_dict=True)
		self.assertFalse(datos.get(CAMPO_FACTURA_POS))
		self.assertEqual(datos.get(CAMPO_ETAPA), CFG.etapa("prop").valor)
		self.assertNotEqual(datos.status, "Converted")

	def test_venta_pos_y_ganada_desde_calificar_en_el_mismo_guardado(self):
		# Desde Calificar la transición a Ganada exige la venta POS, y Frappe evalúa la
		# condición sobre la versión guardada (sin venta): el hook ignora el cambio de etapa
		# y guarda la venta. Ganada va en un segundo guardado (vincular_factura_pos).
		op = poner_en(crear_oportunidad(), CFG.inicial.clave)
		factura = crear_factura(op)
		op.set(CAMPO_FACTURA_POS, factura.name)
		op.set(CAMPO_ETAPA, CFG.etapa("ganada").valor)
		op.save()
		op.reload()
		self.assertEqual(op.get(CAMPO_FACTURA_POS), factura.name)
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.inicial.valor)
		self.assertNotEqual(op.status, "Converted")

	# Venta POS por etapa (decisión del negocio): solo en 1, 2 y En pausa.

	def test_etapas_que_aceptan_venta_pos(self):
		self.assertEqual([e.clave for e in CFG.etapas_con_venta_pos], ["cal", "req", "pausa"])

	def _rechazada_por_etapa(self, clave):
		op = poner_en(crear_oportunidad(), clave)
		factura = crear_factura(op)
		detalle = api.get_oportunidad(op.name)
		self.assertFalse(detalle["acepta_venta_pos"])
		self.assertEqual(detalle["facturas_pos"], [])
		with self.assertRaises(frappe.ValidationError) as error:
			api.vincular_factura_pos(op.name, factura.name)
		self.assertIn(CFG.etapa(clave).titulo, str(error.exception))
		self.assertIn("orden de venta", str(error.exception))
		datos = frappe.db.get_value("Opportunity", op.name, ["status", CAMPO_ETAPA, CAMPO_FACTURA_POS], as_dict=True)
		self.assertNotEqual(datos.status, "Converted")
		self.assertEqual(datos.get(CAMPO_ETAPA), CFG.etapa(clave).valor)
		self.assertFalse(datos.get(CAMPO_FACTURA_POS))
		# Tampoco por API o desde el formulario: el hook validate aplica la misma regla.
		op.reload()
		op.set(CAMPO_FACTURA_POS, factura.name)
		with self.assertRaises(frappe.ValidationError):
			op.save()
		self.assertFalse(frappe.db.get_value("Opportunity", op.name, CAMPO_FACTURA_POS))

	def test_vincular_venta_pos_en_propuesta_enviada_se_rechaza(self):
		self._rechazada_por_etapa("prop")

	def test_vincular_venta_pos_en_negociacion_se_rechaza(self):
		self._rechazada_por_etapa("neg")

	def test_detalle_ofrece_venta_pos_en_1_2_y_pausa(self):
		for clave in ("cal", "req", "pausa"):
			op = poner_en(crear_oportunidad(), clave)
			factura = crear_factura(op)
			detalle = api.get_oportunidad(op.name)
			self.assertTrue(detalle["acepta_venta_pos"], clave)
			self.assertIn(factura.name, [f["name"] for f in detalle["facturas_pos"]], clave)

	# ALTO-2 · Una venta, una oportunidad, también con peticiones simultáneas.

	def test_campo_unico_en_la_base(self):
		self.assertTrue(frappe.get_meta("Opportunity").get_field(CAMPO_FACTURA_POS).unique)

	def test_venta_pos_ya_vinculada_a_otra_no_se_repite(self):
		primera = crear_oportunidad()
		factura = crear_factura(primera)
		api.vincular_factura_pos(primera.name, factura.name)
		op = crear_oportunidad()
		self.assertNotIn(factura.name, [f["name"] for f in api.get_oportunidad(op.name)["facturas_pos"] if not f["ligada_a"]])
		with self.assertRaises(frappe.ValidationError) as error:
			api.vincular_factura_pos(op.name, factura.name)
		self.assertIn(primera.name, str(error.exception))
		self.assertNotEqual(frappe.db.get_value("Opportunity", op.name, "status"), "Converted")

	def test_simultaneas_el_indice_unico_rechaza_con_mensaje_claro(self):
		primera = crear_oportunidad()
		factura = crear_factura(primera)
		frappe.db.set_value("Opportunity", primera.name, CAMPO_FACTURA_POS, factura.name)
		op = crear_oportunidad()
		# La otra petición todavía no se veía cuando esta validó: solo queda el índice único.
		with patch.object(venta_pos, "validar_vinculo"), self.assertRaises(frappe.ValidationError) as error:
			api.vincular_factura_pos(op.name, factura.name)
		self.assertNotIsInstance(error.exception, frappe.UniqueValidationError)
		self.assertIn(primera.name, str(error.exception))

	# MEDIO-1 · Venta cancelada o devuelta después de ganar: comentario y revisión, sin tocar la oportunidad.

	def _ganada_con_venta_pos(self):
		op = crear_oportunidad()
		factura = crear_factura(op)
		api.vincular_factura_pos(op.name, factura.name)
		return op, factura

	def _sin_cambios(self, op, factura):
		datos = frappe.db.get_value("Opportunity", op.name, ["status", CAMPO_ETAPA, CAMPO_FACTURA_POS], as_dict=True)
		self.assertEqual(datos.status, "Converted")
		self.assertEqual(datos.get(CAMPO_ETAPA), CFG.etapa("ganada").valor)
		self.assertEqual(datos.get(CAMPO_FACTURA_POS), factura.name)

	def _comentarios(self, op):
		return frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Opportunity", "reference_name": op.name, "comment_type": "Comment"},
			pluck="content",
		)

	def test_venta_pos_cancelada_comenta_y_queda_para_revision(self):
		op, factura = self._ganada_con_venta_pos()
		factura.reload()
		factura.cancel()
		self._sin_cambios(op, factura)
		self.assertTrue(any(factura.name in c for c in self._comentarios(op)))
		revision = embudo._revision_pos([frappe.session.user], self.tablero, contexto_de_prueba())
		self.assertIn(op.name, revision)
		self.assertTrue(api.get_oportunidad(op.name)["revision_pos"])

	def test_venta_pos_devuelta_comenta_y_queda_para_revision(self):
		op, factura = self._ganada_con_venta_pos()
		# La devolución se hace sin la marca POS: así no depende de las formas de pago del sitio.
		frappe.db.set_value("Sales Invoice", factura.name, "is_pos", 0)
		devolucion = crear_devolucion(factura)
		self._sin_cambios(op, factura)
		self.assertTrue(any(devolucion.name in c for c in self._comentarios(op)))
		self.assertIn(op.name, embudo._revision_pos([frappe.session.user], self.tablero, contexto_de_prueba()))

	def test_venta_vigente_no_queda_para_revision(self):
		op, _factura = self._ganada_con_venta_pos()
		self.assertNotIn(op.name, embudo._revision_pos([frappe.session.user], self.tablero, contexto_de_prueba()))

	# NUEVO-2 · Si el comentario falla, la cancelación y la devolución en caja se completan.

	def _sin_comentario(self):
		"""Hace fallar solo la creación del Comment del aviso; lo demás usa el get_doc real."""
		get_doc = frappe.get_doc

		def falla_comentario(*args, **kwargs):
			if args and isinstance(args[0], dict) and args[0].get("doctype") == "Comment":
				raise frappe.ValidationError("Comentario de prueba que falla")
			return get_doc(*args, **kwargs)

		return patch("frappe.get_doc", side_effect=falla_comentario)

	def _sin_error_log(self):
		"""Mock de frappe.log_error donde lo llama el aviso: el Error Log no persiste tras la prueba."""
		return patch.object(venta_pos.frappe, "log_error")

	def _assert_error_registrado(self, log_error, factura, oportunidad):
		llamadas = [c.kwargs for c in log_error.call_args_list if c.kwargs.get("reference_name") == factura]
		self.assertEqual(len(llamadas), 1, log_error.call_args_list)
		self.assertEqual(llamadas[0]["reference_doctype"], "Sales Invoice")
		self.assertIn(factura, llamadas[0]["title"])
		self.assertIn(oportunidad, llamadas[0]["title"])

	def test_cancelacion_se_completa_aunque_falle_el_comentario(self):
		op, factura = self._ganada_con_venta_pos()
		factura.reload()
		with self._sin_comentario(), self._sin_error_log() as log_error:
			factura.cancel()
		self.assertEqual(frappe.db.get_value("Sales Invoice", factura.name, "docstatus"), 2)
		self._sin_cambios(op, factura)
		self.assertFalse(any(factura.name in c for c in self._comentarios(op)))
		self._assert_error_registrado(log_error, factura.name, op.name)

	def test_devolucion_se_completa_aunque_falle_el_comentario(self):
		op, factura = self._ganada_con_venta_pos()
		frappe.db.set_value("Sales Invoice", factura.name, "is_pos", 0)
		with self._sin_comentario(), self._sin_error_log() as log_error:
			devolucion = crear_devolucion(factura)
		self.assertEqual(frappe.db.get_value("Sales Invoice", devolucion.name, "docstatus"), 1)
		self._sin_cambios(op, factura)
		self.assertFalse(any(devolucion.name in c for c in self._comentarios(op)))
		self._assert_error_registrado(log_error, factura.name, op.name)

	# MEDIO-2 · Fecha de la venta: desde la creación de la oportunidad (con margen) y 6 meses.

	def test_fecha_minima(self):
		hoy = getdate(nowdate())
		reciente = frappe._dict(creation=hoy)
		vieja = frappe._dict(creation=add_days(hoy, -400))
		self.assertEqual(venta_pos.fecha_minima(reciente), add_days(hoy, -venta_pos.DIAS_ANTES_DE_LA_OPORTUNIDAD))
		self.assertEqual(venta_pos.fecha_minima(vieja), getdate(add_months(hoy, -venta_pos.MESES_ATRAS)))

	def test_venta_anterior_a_la_oportunidad_no_se_ofrece_ni_se_vincula(self):
		op = crear_oportunidad()
		vieja = crear_factura(op, dias=-(venta_pos.DIAS_ANTES_DE_LA_OPORTUNIDAD + 3))
		self.assertNotIn(vieja.name, self._candidatas(op))
		with self.assertRaises(frappe.ValidationError):
			api.vincular_factura_pos(op.name, vieja.name)

	def test_venta_dentro_del_margen_se_ofrece(self):
		op = crear_oportunidad()
		reciente = crear_factura(op, dias=-2)
		self.assertIn(reciente.name, self._candidatas(op))

	# MEDIO-3 · Ventas con nota de crédito no son candidatas.

	def test_venta_con_devolucion_no_se_ofrece_ni_se_vincula(self):
		op = crear_oportunidad()
		factura = crear_factura(op, pos=False)
		crear_devolucion(factura)
		marcar_pos(factura)
		self.assertNotIn(factura.name, self._candidatas(op))
		with self.assertRaises(frappe.ValidationError):
			api.vincular_factura_pos(op.name, factura.name)

	# MEDIO-4 · Solo oportunidades abiertas, sin otra venta POS ni órdenes de venta.

	def test_no_vincula_en_oportunidad_perdida(self):
		op = crear_oportunidad()
		factura = crear_factura(op)
		frappe.db.set_value("Opportunity", op.name, "status", "Lost")
		with self.assertRaises(frappe.ValidationError):
			api.vincular_factura_pos(op.name, factura.name)
		self.assertFalse(frappe.db.get_value("Opportunity", op.name, CAMPO_FACTURA_POS))

	def test_no_vincula_si_ya_tiene_otra_venta_pos(self):
		op = crear_oportunidad()
		primera, segunda = crear_factura(op), crear_factura(op)
		op.set(CAMPO_FACTURA_POS, primera.name)
		op.save()
		with self.assertRaises(frappe.ValidationError):
			api.vincular_factura_pos(op.name, segunda.name)
		self.assertEqual(frappe.db.get_value("Opportunity", op.name, CAMPO_FACTURA_POS), primera.name)

	def test_no_vincula_si_ya_tiene_orden_de_venta(self):
		orden = frappe.get_all("Sales Order", filters={"docstatus": 1}, pluck="name", limit=1)
		if not orden:
			self.skipTest("El sitio de pruebas no tiene órdenes de venta enviadas.")
		op = crear_oportunidad()
		factura = crear_factura(op)
		# Dato preparado: una orden existente vinculada a mano (como al ganar con orden).
		frappe.db.set_value("Opportunity", op.name, etapas.CAMPO_ORDEN_DE_VENTA, orden[0])
		with self.assertRaises(frappe.ValidationError) as error:
			api.vincular_factura_pos(op.name, factura.name)
		self.assertIn(orden[0], str(error.exception))
		self.assertEqual(api.get_oportunidad(op.name)["facturas_pos"], [])
