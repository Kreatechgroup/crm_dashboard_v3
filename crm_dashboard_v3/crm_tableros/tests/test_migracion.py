"""Workflow compartido y migración de etapas: reglas puras, sin escribir en la base."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA
from crm_dashboard_v3.crm_tableros.migracion import etapas_plus, scripts_erp, workflow
from crm_dashboard_v3.crm_tableros.proyectos.config import TABLERO


def fila(valor, status="Open", lost_reason=None, probability=100):
	return frappe._dict({"name": "OPTY-1", CAMPO_ETAPA: valor, "status": status, "lost_reason": lost_reason, "probability": probability})


class TestDefinicionWorkflow(FrappeTestCase):
	def test_veintiuna_transiciones_para_plus(self):
		transiciones = workflow.transiciones_de(TABLERO)
		self.assertEqual(len(transiciones), 21)
		pares = {(t["state"], t["next_state"]) for t in transiciones}
		self.assertIn(("1 · Calificar", "2 · Requerimiento y diseño"), pares)
		self.assertIn(("3 · Propuesta enviada", "Ganada"), pares)
		self.assertIn(("4 · Negociación", "Ganada"), pares)
		self.assertIn(("En pausa", "4 · Negociación"), pares)
		self.assertNotIn(("1 · Calificar", "Ganada"), pares)
		self.assertTrue(all(t["allowed"] == workflow.ROL for t in transiciones))

	def test_acciones_sin_repetir_desde_un_mismo_estado(self):
		transiciones = workflow.transiciones_de(TABLERO)
		vistos = [(t["state"], t["action"]) for t in transiciones]
		self.assertEqual(len(vistos), len(set(vistos)))

	def test_condiciones_por_tienda(self):
		condicion = workflow.condicion_de(TABLERO)
		self.assertIn("Plus Fontabella Importado", condicion)
		evalua = lambda c, doc: eval(c, {}, {"doc": frappe._dict(doc)})  # noqa: E731
		plus = {"establecimiento_lista": "Plus Fontabella Importado", "sales_model": "Retail"}
		otra = {"establecimiento_lista": "Creative Mobiliario", "sales_model": "Proyectos"}
		self.assertTrue(evalua(condicion, plus))
		self.assertFalse(evalua(condicion, otra))
		legado = workflow.condicion_legado([TABLERO], "doc.contact_email")
		self.assertFalse(evalua(legado, {**plus, "contact_email": "x@y.z"}))
		self.assertTrue(evalua(legado, {**otra, "contact_email": "x@y.z"}))
		self.assertFalse(evalua(legado, {**otra, "contact_email": None}))


class TestReglasMigracion(FrappeTestCase):
	def _cambio(self, row, tiene_orden=False):
		return etapas_plus.cambio_para(row, TABLERO, tiene_orden)

	def test_valores_viejos_a_etapas_nuevas(self):
		casos = {
			"Investigar al cliente": ("1 · Calificar", 10),
			"Presentar cotización": ("3 · Propuesta enviada", 50),
			"Dar seguimiento": ("4 · Negociación", 75),
			"Llamar después": ("En pausa", None),
		}
		for viejo, (nuevo, probabilidad) in casos.items():
			cambio = self._cambio(fila(viejo))
			self.assertEqual(cambio["valores"][CAMPO_ETAPA], nuevo, viejo)
			self.assertEqual(cambio["valores"].get("probability"), probabilidad, viejo)

	def test_ganada_con_orden_se_cierra_y_sin_orden_va_a_revision(self):
		con_orden = self._cambio(fila("Ganada", status="Quotation"), tiene_orden=True)
		self.assertEqual(con_orden["valores"]["status"], "Converted")
		sin_orden = self._cambio(fila("Ganada", status="Open"))
		self.assertEqual(sin_orden["caso"], etapas_plus.REVISAR)

	def test_descartada_pasa_a_perdida_con_no_califico(self):
		cambio = self._cambio(fila("Descartada"))
		self.assertEqual(cambio["valores"][CAMPO_ETAPA], "Perdida")
		self.assertEqual(cambio["valores"]["status"], "Lost")
		self.assertEqual(cambio["valores"]["lost_reason"], "No calificó")
		# Si ya tenía un motivo real, se respeta.
		self.assertNotIn("lost_reason", self._cambio(fila("Descartada", lost_reason="Precio"))["valores"])

	def test_perdida_abierta_con_y_sin_motivo(self):
		self.assertEqual(self._cambio(fila("Perdida", lost_reason="Precio", probability=0))["valores"], {"status": "Lost"})
		self.assertEqual(self._cambio(fila("Perdida"))["caso"], etapas_plus.REVISAR)

	def test_ya_migrada_no_cambia(self):
		self.assertIsNone(self._cambio(fila("2 · Requerimiento y diseño", probability=25)))

	def test_valor_desconocido_va_a_revision(self):
		self.assertEqual(self._cambio(fila("Algo raro"))["caso"], etapas_plus.REVISAR)


class TestCambiosEnScriptsDelERP(FrappeTestCase):
	SCRIPT = (
		'x();\r\ncur_frm.cscript.descartar = function (doc) {\r\n    frappe.call({\r\n        "args": {}\r\n'
		'    });\r\n    frappe.msgprint("Descartada");\r\n};\r\n\r\ncur_frm.cscript.otra = function (doc) {\r\n};'
	)

	def test_reemplaza_solo_el_boton_descartar(self):
		nuevo = scripts_erp._script_nuevo(self.SCRIPT)
		self.assertIn(scripts_erp.MARCA, nuevo)
		self.assertIn("como_descartar", nuevo)
		self.assertIn("cur_frm.cscript.otra = function (doc)", nuevo)
		self.assertTrue(nuevo.startswith("x();"))
		# Aplicarlo dos veces no cambia nada.
		self.assertIsNone(scripts_erp._script_nuevo(nuevo))

	def test_filtro_de_la_grafica_incluye_negociacion(self):
		filtro = '[["Opportunity", "embudo_state_v2", "=", "Negociar", 0]]'
		nuevo = scripts_erp._filtro_nuevo(filtro)
		self.assertIn("4 · Negociación", nuevo)
		self.assertIsNone(scripts_erp._filtro_nuevo(nuevo))
