"""Quién ve qué en CRM Proyectos, metas de los dos Sales Person y cálculo de comisión (sin escribir en la base)."""

from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm_dashboard_v3.crm_tableros.common import alcance, contexto, metas, ventas
from crm_dashboard_v3.crm_tableros.common import api as api_comun
from crm_dashboard_v3.crm_tableros.common.contexto import Asesor, Contexto
from crm_dashboard_v3.crm_tableros.proyectos import api, embudo
from crm_dashboard_v3.crm_tableros.proyectos.config import PROYECTOS, RETAIL, TABLERO

SP_PROYECTOS = "Asesor de Proyectos Retail Prueba - UM"
SP_RETAIL = "Asesor Retail Prueba - UM"


def _ctx(es_jefe=False, **campos):
	base = {
		"usuario": "asesora@prueba.test",
		"nombre": "Asesora de prueba",
		"desde": date(2026, 10, 1),
		"hasta": date(2026, 10, 31),
		"hoy": date(2026, 10, 28),
		"empleado": "EMP-PRUEBA",
		"company": "Compañía de prueba",
		"establecimiento": TABLERO.establecimientos[0],
		"sales_persons": {SP_PROYECTOS: PROYECTOS, SP_RETAIL: RETAIL},
		"es_jefe": es_jefe,
	}
	base.update(campos)
	return Contexto(**base)


class TestAlcance(FrappeTestCase):
	def test_asesor_solo_se_ve_a_si_mismo(self):
		with patch.object(contexto, "obtener", return_value=_ctx()):
			a = alcance.obtener(TABLERO, None, "EMP-DE-OTRO-ASESOR", None)
		self.assertIsNone(a.base["asesor"])
		self.assertFalse(a.vista_tienda)
		self.assertEqual(a.base["titulo"], "Mis proyectos · Asesora de prueba")
		self.assertEqual([x.usuario for x in a.seleccion], ["asesora@prueba.test"])
		self.assertEqual(set(a.seleccion[0].sales_persons), {SP_PROYECTOS, SP_RETAIL})

	def test_jefe_no_puede_elegir_un_asesor_de_otra_tienda(self):
		asesores = [Asesor("EMP-1", "Asesor 1", "a1@prueba.test", {})]
		with (
			patch.object(contexto, "obtener", return_value=_ctx(es_jefe=True, sales_persons={})),
			patch.object(contexto, "asesores_de_tienda", return_value=asesores),
		):
			with self.assertRaises(frappe.ValidationError):
				alcance.obtener(TABLERO, None, "EMP-9", None)
			tienda = alcance.obtener(TABLERO)
			uno = alcance.obtener(TABLERO, None, "EMP-1", None)
		self.assertEqual(tienda.base["titulo"], "Proyectos · toda la tienda")
		self.assertTrue(tienda.vista_tienda)
		self.assertEqual(tienda.seleccion, asesores)
		self.assertEqual(uno.base["titulo"], "Proyectos de Asesor 1")
		self.assertFalse(uno.vista_tienda)

	def test_usuario_sin_sales_person_de_plus_ve_un_mensaje(self):
		with patch.object(contexto, "obtener", return_value=_ctx(mensaje="Sin Sales Person")):
			resultado = api.get_tablero()
		self.assertEqual(resultado["mensaje"], "Sin Sales Person")

	def test_get_contexto_devuelve_el_contexto_del_tablero(self):
		with patch.object(contexto, "obtener", return_value=_ctx()):
			base = api_comun.get_contexto("proyectos", None, "EMP-DE-OTRO-ASESOR")
		self.assertEqual(base["tablero"], "proyectos")
		self.assertFalse(base["es_jefe"])
		self.assertEqual(base["mes"], "2026-10")
		self.assertEqual(base["company"], "Compañía de prueba")
		self.assertEqual({s["name"] for s in base["sales_persons"]}, {SP_PROYECTOS, SP_RETAIL})
		self.assertEqual(base["modelos"], list(TABLERO.sales_models))

	def test_get_contexto_de_tablero_inexistente(self):
		with self.assertRaises(frappe.ValidationError):
			api_comun.get_contexto("no-existe")

	def test_rol_asociado_no_es_jefe(self):
		with patch("frappe.get_roles", return_value=["Asociado", "Employee"]):
			self.assertFalse(contexto.es_jefe(TABLERO, "alguien@prueba.test"))
		with patch("frappe.get_roles", return_value=["Jefe de Plus"]):
			self.assertTrue(contexto.es_jefe(TABLERO, "aura@prueba.test"))

	def test_system_manager_ve_la_tienda(self):
		with patch("frappe.get_roles", return_value=["System Manager"]):
			self.assertTrue(contexto.es_jefe(TABLERO, "admin@prueba.test"))

	def _obtener(self, sps, empleados=None):
		empleados = [frappe._dict(name="EMP-A", employee_name="Asesora", status="Active")] if empleados is None else empleados
		with (
			patch.object(contexto, "_empleados_del_usuario", return_value=empleados),
			patch.object(contexto, "_sales_persons_del_usuario", return_value=sps),
			patch.object(contexto, "es_jefe", return_value=False),
			patch("frappe.get_cached_value", return_value="GTQ"),
		):
			return contexto.obtener(TABLERO, usuario="asesora@prueba.test")

	def test_asesor_entra_con_sus_dos_sales_person_de_plus(self):
		plus = TABLERO.establecimientos[0]
		ctx = self._obtener(
			[
				frappe._dict(name=SP_PROYECTOS, company="Umob", establecimiento=plus),
				frappe._dict(name=SP_RETAIL, company="Umob", establecimiento=plus),
				frappe._dict(name="Asesor de Proyectos Retail Prueba", company="Otra", establecimiento="Otra tienda"),
			]
		)
		self.assertIsNone(ctx.mensaje)
		self.assertEqual(ctx.company, "Umob")
		self.assertEqual(ctx.sales_persons, {SP_PROYECTOS: PROYECTOS, SP_RETAIL: RETAIL})

	def test_mensaje_explica_que_sales_person_encontro(self):
		ctx = self._obtener([frappe._dict(name="Asesor Retail Prueba", company="Umob", establecimiento="Otra tienda")])
		self.assertIn("Asesor Retail Prueba", ctx.mensaje)
		self.assertIn("Otra tienda", ctx.mensaje)

	def test_mensaje_sin_sales_person_menciona_al_empleado(self):
		ctx = self._obtener([])
		self.assertIn("EMP-A", ctx.mensaje)

	def test_jefes_no_aparecen_como_asesores(self):
		def get_all(doctype, **kwargs):
			return {
				"Sales Person": [
					frappe._dict(name=SP_PROYECTOS, employee="EMP-A"),
					frappe._dict(name=SP_RETAIL, employee="EMP-A"),
					frappe._dict(name="Gerente Retail Jefa - UM", employee="EMP-J"),
				],
				"Employee": [
					frappe._dict(name="EMP-A", employee_name="Asesora", user_id="asesora@prueba.test"),
					frappe._dict(name="EMP-J", employee_name="Jefa", user_id="jefa@prueba.test"),
				],
				"Has Role": ["jefa@prueba.test"],
			}[doctype]

		with patch("frappe.get_all", side_effect=get_all):
			asesores = contexto.asesores_de_tienda(TABLERO, TABLERO.establecimientos[0])
		self.assertEqual([a.nombre for a in asesores], ["Asesora"])
		self.assertEqual(asesores[0].sales_persons, {SP_PROYECTOS: PROYECTOS, SP_RETAIL: RETAIL})


class TestMetaDeLosDosSalesPerson(FrappeTestCase):
	def test_meta_suma_proyectos_y_retail(self):
		filas = [
			frappe._dict(asesor=SP_PROYECTOS, valor_deseado=171000),
			frappe._dict(asesor=SP_RETAIL, valor_deseado=171000),
		]
		with patch.object(metas, "metas_vigentes", return_value=filas):
			por_modelo = metas.meta_por_modelo(
				{SP_PROYECTOS: PROYECTOS, SP_RETAIL: RETAIL}, TABLERO.tipo_meta, date(2026, 10, 1), date(2026, 10, 31)
			)
			with patch.object(ventas, "facturado", return_value={"monto": 0, "facturas": [], "filas": []}):
				asesor = Asesor("EMP-A", "Asesora", "asesora@prueba.test", {SP_PROYECTOS: PROYECTOS, SP_RETAIL: RETAIL})
				total = embudo.meta_y_facturado(asesor, TABLERO, _ctx())
		self.assertEqual(por_modelo, {PROYECTOS: 171000, RETAIL: 171000})
		self.assertEqual(total["meta"], 342000)


class TestComision(FrappeTestCase):
	def test_comision_sobre_lo_cobrado_sin_iva(self):
		factura = frappe._dict(
			name="SINV-1",
			posting_date="2026-10-05",
			customer_name="Cliente",
			is_return=0,
			base_grand_total=1120,
			outstanding_amount=560,
			neto=1000,
		)
		fila = ventas._fila(factura, PROYECTOS, SP_PROYECTOS, 100, 1.25)
		self.assertAlmostEqual(fila.monto, 1000)
		self.assertAlmostEqual(fila.cobrado, 500)
		self.assertAlmostEqual(fila.comision, 6.25)
		self.assertAlmostEqual(fila.comision_futura, 6.25)

	def test_distribucion_reparte_monto_y_comision(self):
		factura = frappe._dict(
			name="SINV-2",
			posting_date="2026-10-05",
			customer_name="Cliente",
			is_return=0,
			base_grand_total=1120,
			outstanding_amount=0,
			neto=1000,
		)
		fila = ventas._fila(factura, RETAIL, SP_RETAIL, 50, 1.25)
		self.assertAlmostEqual(fila.monto, 500)
		self.assertAlmostEqual(fila.comision, 6.25)
		self.assertAlmostEqual(fila.comision_futura, 0)
