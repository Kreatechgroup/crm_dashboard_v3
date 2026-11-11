"""Reglas de etapas, montos y semáforos (sin escribir en la base de datos)."""

from datetime import date

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from crm_dashboard_v3.crm_tableros.common import etapas, formato
from crm_dashboard_v3.crm_tableros.common.contexto import Contexto
from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA

CFG = etapas.config_de("Proyectos")


class RelacionadosFalsos:
	"""Sustituye a DatosRelacionados para probar requisitos sin documentos reales."""

	def __init__(self, proximo_contacto=None, cotizaciones=0, ordenes=0):
		self.ultima_actividad = (
			frappe._dict(activity_type="Llamada", next_contact_date=proximo_contacto) if proximo_contacto else None
		)
		self.cotizaciones_enviadas = [frappe._dict(name=f"QTN-{i}") for i in range(cotizaciones)]
		self.ordenes_de_venta = [f"SO-{i}" for i in range(ordenes)]
		self.monto_cotizacion = 0


def oportunidad(**campos):
	base = {
		"name": "OPTY-PRUEBA",
		"party_name": "LEAD-1",
		"tipo_de_oportunidad": "Mobiliario para oficina",
		"source": "Referencia",
		"status": "Open",
	}
	base.update(campos)
	return frappe._dict(base)


class TestConfiguracionEtapas(FrappeTestCase):
	def test_modelo_sin_config_no_aplica(self):
		self.assertIsNone(etapas.config_de("Retail"))
		self.assertIsNone(etapas.config_de(None))

	def test_probabilidades_por_etapa(self):
		esperado = {"cal": 10, "req": 25, "prop": 50, "neg": 75, "ganada": 100, "perdida": 0, "pausa": None}
		self.assertEqual({e.clave: e.probabilidad for e in CFG.etapas}, esperado)

	def test_status_coherente_de_etapas_de_cierre(self):
		self.assertEqual(CFG.etapa("ganada").status, "Converted")
		self.assertEqual(CFG.etapa("perdida").status, "Lost")
		self.assertFalse(CFG.etapa("pausa").cuenta_pronostico)

	def test_orden_de_etapas(self):
		self.assertEqual(CFG.siguiente("cal").clave, "req")
		self.assertEqual(CFG.siguiente("neg").clave, "ganada")
		self.assertIsNone(CFG.anterior("cal"))
		self.assertEqual(CFG.anterior("prop").clave, "req")

	def test_mapa_legado(self):
		casos = {
			"Investigar al cliente": "cal",
			"Presentar diseño": "req",
			"Presentar cotización": "prop",
			"Negociar": "neg",
			"Descartada": "perdida",
			"Llamar después": "pausa",
		}
		for viejo, nuevo in casos.items():
			fila = oportunidad(embudo_state_v2=viejo)
			self.assertEqual(etapas.etapa_efectiva(fila, CFG).clave, nuevo, viejo)

	def test_etapa_nueva_tiene_prioridad_sobre_legado(self):
		fila = oportunidad(**{CAMPO_ETAPA: "4 · Negociación", "embudo_state_v2": "Conocer"})
		self.assertEqual(etapas.etapa_efectiva(fila, CFG).clave, "neg")

	def test_incoherencia_etapa_status(self):
		self.assertTrue(etapas.es_incoherente(oportunidad(embudo_state_v2="Ganada", status="Open"), CFG))
		self.assertFalse(etapas.es_incoherente(oportunidad(embudo_state_v2="Ganada", status="Converted"), CFG))
		self.assertFalse(etapas.es_incoherente(oportunidad(embudo_state_v2="Negociar"), CFG))


class TestRequisitos(FrappeTestCase):
	"""Criterio 1 (lógica): requisitos para entrar a «2 · Requerimiento y diseño»."""

	def test_requerimiento_sin_datos_lista_lo_que_falta(self):
		falta = etapas.faltantes(oportunidad(), CFG.etapa("req"), CFG, RelacionadosFalsos())
		self.assertEqual(len(falta), 3)

	def test_requerimiento_completo(self):
		op = oportunidad(presupuesto_declarado_por_el_cliente=1000, fecha_estimada_aprobacion=nowdate())
		rel = RelacionadosFalsos(proximo_contacto=add_days(nowdate(), 2))
		self.assertEqual(etapas.faltantes(op, CFG.etapa("req"), CFG, rel), [])

	def test_negociacion_exige_proximo_paso_vigente(self):
		op = oportunidad(opportunity_amount=1000, fecha_estimada_aprobacion=nowdate())
		vencido = RelacionadosFalsos(proximo_contacto=add_days(nowdate(), -1))
		vigente = RelacionadosFalsos(proximo_contacto=nowdate())
		self.assertEqual(len(etapas.faltantes(op, CFG.etapa("neg"), CFG, vencido)), 1)
		self.assertEqual(etapas.faltantes(op, CFG.etapa("neg"), CFG, vigente), [])

	def test_propuesta_exige_cotizacion_enviada(self):
		op = oportunidad(fecha_estimada_aprobacion=nowdate())
		rel = RelacionadosFalsos(proximo_contacto=nowdate())
		self.assertEqual(len(etapas.faltantes(op, CFG.etapa("prop"), CFG, rel)), 1)
		rel.cotizaciones_enviadas = [frappe._dict(name="QTN-1")]
		self.assertEqual(etapas.faltantes(op, CFG.etapa("prop"), CFG, rel), [])

	def test_ganada_exige_orden_de_venta(self):
		self.assertEqual(len(etapas.faltantes(oportunidad(), CFG.etapa("ganada"), CFG, RelacionadosFalsos())), 1)
		self.assertEqual(etapas.faltantes(oportunidad(), CFG.etapa("ganada"), CFG, RelacionadosFalsos(ordenes=1)), [])

	def test_motivo_generico_no_es_valido(self):
		generico = oportunidad(lost_reason="Especificar motivo")
		especifico = oportunidad(lost_reason="Oportunidad Duplicada")
		self.assertEqual(len(etapas.faltantes(generico, CFG.etapa("perdida"), CFG, RelacionadosFalsos())), 1)
		self.assertEqual(etapas.faltantes(especifico, CFG.etapa("perdida"), CFG, RelacionadosFalsos()), [])


class TestMontosYFormato(FrappeTestCase):
	def test_monto_usa_cotizacion_cuando_el_historico_esta_en_cero(self):
		self.assertEqual(etapas.monto_de(oportunidad(opportunity_amount=0), CFG, 4500), 4500)
		self.assertEqual(etapas.monto_de(oportunidad(presupuesto_declarado_por_el_cliente=800), CFG, 4500), 800)
		self.assertEqual(etapas.monto_de(oportunidad(opportunity_amount=1200), CFG, 4500), 1200)

	def test_fecha_cierre(self):
		self.assertEqual(
			etapas.fecha_cierre_de(oportunidad(fecha_estimada_aprobacion="2026-11-20"), CFG), date(2026, 11, 20)
		)
		self.assertEqual(etapas.fecha_cierre_de(oportunidad(expected_closing="2026-12-01"), CFG), date(2026, 12, 1))
		self.assertIsNone(etapas.fecha_cierre_de(oportunidad(), CFG))

	def test_semaforo_de_dias_lleva_texto(self):
		self.assertEqual(formato.semaforo_dias(7, 7, 14)["clave"], "verde")
		self.assertEqual(formato.semaforo_dias(8, 7, 14)["clave"], "amarillo")
		self.assertEqual(formato.semaforo_dias(14, 7, 14)["clave"], "amarillo")
		self.assertEqual(formato.semaforo_dias(15, 7, 14)["clave"], "rojo")
		for dias in (0, 10, 30):
			self.assertTrue(formato.semaforo_dias(dias, 7, 14)["texto"])

	def test_ritmo(self):
		self.assertEqual(formato.ritmo(100, 100, 0.5)["clave"], "verde")
		self.assertEqual(formato.ritmo(50, 100, 0.5)["clave"], "verde")
		self.assertEqual(formato.ritmo(42, 100, 0.5)["clave"], "amarillo")
		self.assertEqual(formato.ritmo(10, 100, 0.5)["clave"], "rojo")

	def test_fraccion_del_mes(self):
		ctx = Contexto("u", "n", date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 31))
		self.assertEqual(ctx.fraccion_del_mes, 1)
		ctx.hoy = date(2026, 12, 5)
		self.assertEqual(ctx.fraccion_del_mes, 1)
