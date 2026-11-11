"""Criterios de aceptación del tablero CRM Proyectos (sección 4.4 de CLAUDE.md).

Crean documentos reales en el sitio de pruebas; FrappeTestCase revierte la
transacción al terminar cada clase.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, get_first_day, get_last_day, getdate, nowdate

from crm_dashboard_v3.crm_tableros.common import acciones, consultas, etapas
from crm_dashboard_v3.crm_tableros.common.campos import crear_campos
from crm_dashboard_v3.crm_tableros.common.contexto import Asesor, Contexto
from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA
from crm_dashboard_v3.crm_tableros.proyectos import api

CFG = etapas.config_de("Proyectos")
MOTIVO_PRUEBA = "Prueba CRM V3 · eligió a la competencia"
ORIGEN_PRUEBA = "Prueba CRM V3"
ITEM_PRUEBA = "_Test Item CRM V3"


def _compania():
	return frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name", limit=1)[0]


def _asegurar(doctype, nombre, **campos):
	if not frappe.db.exists(doctype, nombre):
		frappe.get_doc({"doctype": doctype, **campos}).insert()
	return nombre


def _tipo_de_oportunidad():
	campo = frappe.get_meta("Opportunity").get_field("tipo_de_oportunidad")
	return next(o for o in (campo.options or "").split("\n") if o)


def crear_lead():
	return frappe.get_doc(
		{
			"doctype": "Lead",
			"first_name": "Cliente Prueba CRM V3",
			"lead_name": f"Cliente Prueba CRM V3 {frappe.generate_hash(length=6)}",
			"company": _compania(),
		}
	).insert()


def crear_oportunidad(**campos):
	lead = crear_lead()
	doc = frappe.get_doc(
		{
			"doctype": "Opportunity",
			"opportunity_from": "Lead",
			"party_name": lead.name,
			"company": _compania(),
			"sales_model": "Proyectos",
			"tipo_de_oportunidad": _tipo_de_oportunidad(),
			"source": ORIGEN_PRUEBA,
			"transaction_date": nowdate(),
			CAMPO_ETAPA: CFG.etapa("cal").titulo,
			**campos,
		}
	)
	return doc.insert()


def crear_actividad(oportunidad, dias=3):
	return acciones.registrar_actividad(oportunidad, "Llamada", "Seguimiento de prueba", add_days(nowdate(), dias))


def crear_cotizacion(oportunidad, valid_till, transaction_date=None, monto=10000):
	from erpnext.stock.doctype.item.test_item import make_item

	make_item(ITEM_PRUEBA, {"is_stock_item": 0})
	q = frappe.get_doc(
		{
			"doctype": "Quotation",
			"quotation_to": "Lead",
			"party_name": oportunidad.party_name,
			"company": oportunidad.company,
			"opportunity": oportunidad.name,
			"sales_model": "Proyectos",
			"transaction_date": transaction_date or nowdate(),
			"valid_till": valid_till,
			"items": [{"item_code": ITEM_PRUEBA, "qty": 1, "rate": monto}],
		}
	)
	q.insert()
	q.submit()
	return q


def mover(oportunidad, clave):
	oportunidad.reload()
	oportunidad.set(CAMPO_ETAPA, CFG.etapa(clave).titulo)
	oportunidad.save()
	return oportunidad


def contexto_de_prueba():
	hoy = getdate(nowdate())
	return Contexto(
		usuario=frappe.session.user,
		nombre="Asesor de prueba",
		desde=get_first_day(hoy),
		hasta=get_last_day(hoy),
		hoy=hoy,
		company=_compania(),
		moneda=frappe.get_cached_value("Company", _compania(), "default_currency"),
	)


class BaseCRMProyectos(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		crear_campos()
		_asegurar("Lead Source", ORIGEN_PRUEBA, source_name=ORIGEN_PRUEBA)
		for motivo in (MOTIVO_PRUEBA, "Especificar motivo"):
			_asegurar("Lost Reason", motivo, lost_reason_name=motivo)
			_asegurar("Quotation Lost Reason", motivo, order_lost_reason=motivo)


class TestCriterio1RequerimientoYDiseno(BaseCRMProyectos):
	"""1. No se puede pasar a «Requerimiento y diseño» sin monto, fecha de cierre y próximo paso con fecha."""

	def test_sin_ningun_dato_no_avanza(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			mover(op, "req")
		self.assertEqual(frappe.db.get_value("Opportunity", op.name, CAMPO_ETAPA), CFG.etapa("cal").titulo)

	def test_sin_proximo_paso_no_avanza(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000, fecha_estimada_aprobacion=nowdate())
		with self.assertRaises(frappe.ValidationError):
			mover(op, "req")

	def test_sin_fecha_de_cierre_no_avanza(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000)
		crear_actividad(op)
		with self.assertRaises(frappe.ValidationError):
			mover(op, "req")

	def test_con_todo_avanza(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=5000, fecha_estimada_aprobacion=nowdate())
		crear_actividad(op)
		mover(op, "req")
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("req").titulo)

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
		asesores = [Asesor(None, "Asesor de prueba", frappe.session.user, [])]

		antes = api.construir_tablero(CFG, ctx, asesores)["kpis"]["pronostico"]
		api.mover_etapa(op.name, "req")
		despues = api.construir_tablero(CFG, ctx, asesores)["kpis"]["pronostico"]

		self.assertIn(op.name, despues["nombres_total"])
		self.assertAlmostEqual(despues["total"] - antes["total"], monto * (25 - 10) / 100, places=2)
		self.assertAlmostEqual(despues["mes"] - antes["mes"], monto * (25 - 10) / 100, places=2)

	def test_en_pausa_no_cuenta_en_el_pronostico(self):
		op = crear_oportunidad(presupuesto_declarado_por_el_cliente=10000, fecha_estimada_aprobacion=nowdate())
		ctx = contexto_de_prueba()
		asesores = [Asesor(None, "Asesor de prueba", frappe.session.user, [])]
		api.mover_etapa(op.name, "pausa", fecha_retomar=add_days(nowdate(), 10))
		pronostico = api.construir_tablero(CFG, ctx, asesores)["kpis"]["pronostico"]
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
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("perdida").titulo)

	def test_perder_exige_motivo_especifico(self):
		op, q = self._vencida()
		with self.assertRaises(frappe.ValidationError):
			api.perder_cotizacion(q.name, "Especificar motivo")
		self.assertIn(q.name, self._nombres_vencidas(op))


class TestCriterio4GanadaConverted(BaseCRMProyectos):
	"""4. Una oportunidad en Ganada siempre tiene status = Converted (y Perdida = Lost)."""

	def test_no_se_marca_ganada_sin_orden_de_venta(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			mover(op, "ganada")
		self.assertNotEqual(frappe.db.get_value("Opportunity", op.name, "status"), "Converted")

	def test_ganada_pone_status_converted(self):
		op = crear_oportunidad()
		siempre = ("orden de venta creada", lambda d, r, c: True)
		with patch.dict(etapas.REQUISITOS, {"orden_de_venta": siempre}):
			mover(op, "ganada")
		self.assertEqual(op.status, "Converted")
		self.assertEqual(flt(op.probability), 100)

	def test_orden_de_venta_enviada_marca_ganada(self):
		op = crear_oportunidad()
		etapas.marcar_ganada(op.name)
		op.reload()
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("ganada").titulo)
		self.assertEqual(op.status, "Converted")

	def test_ganada_no_regresa_a_otra_etapa(self):
		op = crear_oportunidad()
		etapas.marcar_ganada(op.name)
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
		self.assertEqual(op.get(CAMPO_ETAPA), CFG.etapa("perdida").titulo)

	def test_especificar_motivo_no_es_valido(self):
		op = crear_oportunidad()
		with self.assertRaises(frappe.ValidationError):
			api.mover_etapa(op.name, "perdida", motivo="Especificar motivo")
		self.assertEqual(frappe.db.get_value("Opportunity", op.name, "status"), "Open")
