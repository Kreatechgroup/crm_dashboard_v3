"""Workflow que controla embudo_state_v2: qué transiciones se permiten (sin escribir en la base)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm_dashboard_v3.crm_tableros.common import flujo
from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA

ROL = "Embudo de ventas"


def _workflow():
	return frappe._dict(
		name="Embudo de prueba",
		states=[frappe._dict(state="Investigar al cliente")],
		transitions=[
			frappe._dict(state="Investigar al cliente", next_state="Clasificar", allowed=ROL, condition=None),
			frappe._dict(state="Negociar", next_state="Presentar cotización", allowed="Support Agent", condition=None),
		],
	)


class _Doc(frappe._dict):
	doctype = "Opportunity"

	def is_new(self):
		return False

	def get_doc_before_save(self):
		# frappe._dict guarda los atributos como claves: «doc.guardado = x» queda aquí.
		return self.get("guardado")


class TestBloqueoWorkflow(FrappeTestCase):
	def _bloqueo(self, actual, destino, roles=(ROL,), workflow=True, doc=None, guardado=None):
		with (
			patch.object(flujo, "_workflow_de_etapa", return_value=_workflow() if workflow else None),
			patch("frappe.get_roles", return_value=list(roles)),
		):
			return flujo.bloqueo(doc or _Doc({CAMPO_ETAPA: actual}), destino, guardado=guardado)

	def test_transicion_existente_para_el_rol(self):
		self.assertIsNone(self._bloqueo("Investigar al cliente", "Clasificar"))

	def test_transicion_que_no_existe(self):
		mensaje = self._bloqueo("Investigar al cliente", "Tomar requerimiento")
		self.assertIn("Investigar al cliente", mensaje)
		self.assertIn("Tomar requerimiento", mensaje)

	def test_transicion_de_otro_rol_no_sirve(self):
		self.assertTrue(self._bloqueo("Negociar", "Presentar cotización"))
		self.assertIsNone(self._bloqueo("Negociar", "Presentar cotización", roles=("Support Agent",)))

	def test_mismo_valor_no_es_transicion(self):
		self.assertIsNone(self._bloqueo("Negociar", "Negociar"))

	def test_sin_workflow_no_hay_bloqueo(self):
		self.assertIsNone(self._bloqueo("Investigar al cliente", "Tomar requerimiento", workflow=False))

	def test_condicion_sobre_la_version_guardada_dentro_de_validate(self):
		# Como validate_workflow de Frappe: el hook validate pasa guardado=get_doc_before_save()
		# y la condición mira esa versión, no los cambios en memoria.
		doc = _Doc({CAMPO_ETAPA: "Investigar al cliente", "pos": "FAC-1"})
		anterior = _Doc({CAMPO_ETAPA: "Investigar al cliente", "pos": None})
		vistos = []

		def condicion(t, d):
			vistos.append(d)
			return bool(d.get("pos"))

		with patch.object(flujo, "is_transition_condition_satisfied", side_effect=condicion):
			self.assertTrue(self._bloqueo(None, "Clasificar", doc=doc, guardado=anterior))
			self.assertIs(vistos[-1], anterior)

	def test_fuera_de_un_guardado_se_ignora_la_version_anterior(self):
		# Frappe no limpia _doc_before_save al terminar save(): tras guardar el vínculo de la
		# venta POS, get_doc_before_save() sigue siendo la versión sin venta. Fuera de un
		# guardado (cambiar_etapa, la page) se evalúa el documento, que ya la tiene.
		doc = _Doc({CAMPO_ETAPA: "Investigar al cliente", "pos": "FAC-1"})
		doc.guardado = _Doc({CAMPO_ETAPA: "Investigar al cliente", "pos": None})
		vistos = []

		def condicion(t, d):
			vistos.append(d)
			return bool(d.get("pos"))

		with patch.object(flujo, "is_transition_condition_satisfied", side_effect=condicion):
			self.assertIsNone(self._bloqueo(None, "Clasificar", doc=doc))
			self.assertIs(vistos[-1], doc)
