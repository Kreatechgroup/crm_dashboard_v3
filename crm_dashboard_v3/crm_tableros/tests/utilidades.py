"""Datos de prueba compartidos por las pruebas de CRM Proyectos.

Las oportunidades de prueba se crean en un establecimiento real del sitio de
pruebas (el de Plus si existe). El tablero se sustituye por una copia que
atiende ese establecimiento, para no depender de los datos de producción.
"""

import dataclasses
import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_first_day, get_last_day, getdate, nowdate

from crm_dashboard_v3.crm_tableros.common import acciones, flujo
from crm_dashboard_v3.crm_tableros.common.campos import crear_campos
from crm_dashboard_v3.crm_tableros.common.contexto import Contexto
from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA
from crm_dashboard_v3.crm_tableros.proyectos.config import PROYECTOS, TABLERO

CFG = TABLERO.etapas
MOTIVO_PRUEBA = "Prueba CRM V3 · eligió a la competencia"
ORIGEN_PRUEBA = "Prueba CRM V3"
ITEM_PRUEBA = "_Test Item CRM V3"

# Se llena en BaseCRMProyectos.setUpClass.
PRUEBA = {}


def compania():
	return frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name", limit=1)[0]


def asegurar(doctype, nombre, **campos):
	if not frappe.db.exists(doctype, nombre):
		frappe.get_doc({"doctype": doctype, **campos}).insert()
	return nombre


def _establecimiento_de_prueba() -> str:
	for nombre in TABLERO.establecimientos:
		if frappe.db.exists("Establecimiento", nombre):
			return nombre
	existente = frappe.get_all("Establecimiento", pluck="name", limit=1)
	if not existente:
		raise unittest.SkipTest("El sitio de pruebas no tiene ningún Establecimiento.")
	return existente[0]


def _tipo_de_oportunidad():
	campo = frappe.get_meta("Opportunity").get_field("tipo_de_oportunidad")
	return next(o for o in (campo.options or "").split("\n") if o)


def crear_lead():
	return frappe.get_doc(
		{
			"doctype": "Lead",
			"first_name": "Cliente Prueba CRM V3",
			"lead_name": f"Cliente Prueba CRM V3 {frappe.generate_hash(length=6)}",
			"company": compania(),
		}
	).insert()


def crear_oportunidad(sales_model=PROYECTOS, **campos):
	lead = crear_lead()
	doc = frappe.get_doc(
		{
			"doctype": "Opportunity",
			"opportunity_from": "Lead",
			"party_name": lead.name,
			"company": compania(),
			"sales_model": sales_model,
			"establecimiento_lista": PRUEBA["establecimiento"],
			"tipo_de_oportunidad": _tipo_de_oportunidad(),
			"source": ORIGEN_PRUEBA,
			"transaction_date": nowdate(),
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
			"sales_model": oportunidad.sales_model,
			"transaction_date": transaction_date or nowdate(),
			"valid_till": valid_till,
			"items": [{"item_code": ITEM_PRUEBA, "qty": 1, "rate": monto}],
		}
	)
	q.insert()
	q.submit()
	return q


def poner_en(oportunidad, clave):
	"""Deja la oportunidad en una etapa sin pasar por el workflow (solo para preparar pruebas)."""
	frappe.db.set_value("Opportunity", oportunidad.name, CAMPO_ETAPA, CFG.etapa(clave).valor)
	oportunidad.reload()
	return oportunidad


def mover(oportunidad, clave, **extra):
	"""Mueve de etapa como lo hace el tablero (con validación de requisitos en el servidor)."""
	from crm_dashboard_v3.crm_tableros.proyectos import api

	api.mover_etapa(oportunidad.name, clave, **extra)
	oportunidad.reload()
	return oportunidad


def contexto_de_prueba():
	hoy = getdate(nowdate())
	return Contexto(
		usuario=frappe.session.user,
		nombre="Asesor de prueba",
		desde=get_first_day(hoy),
		hasta=get_last_day(hoy),
		hoy=hoy,
		company=compania(),
		moneda=frappe.get_cached_value("Company", compania(), "default_currency"),
	)


class BaseCRMProyectos(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		crear_campos()
		asegurar("Lead Source", ORIGEN_PRUEBA, source_name=ORIGEN_PRUEBA)
		for motivo in (MOTIVO_PRUEBA, "Especificar motivo"):
			asegurar("Lost Reason", motivo, lost_reason_name=motivo)
			asegurar("Quotation Lost Reason", motivo, order_lost_reason=motivo)
		PRUEBA["establecimiento"] = _establecimiento_de_prueba()
		# Las pruebas mueven etapas a través del workflow compartido real del sitio.
		if not flujo.estado_existe(CFG.inicial.valor):
			raise unittest.SkipTest(
				"El workflow activo no tiene las etapas nuevas: ejecuta migracion.workflow.instalar() en el sitio de pruebas."
			)
		if PRUEBA["establecimiento"] not in TABLERO.establecimientos:
			raise unittest.SkipTest(
				f"El sitio de pruebas no tiene el establecimiento {TABLERO.establecimientos[0]!r} que usa el workflow."
			)
		PRUEBA["tablero"] = dataclasses.replace(TABLERO, establecimientos=(PRUEBA["establecimiento"],))
		cls._parches = [
			patch("crm_dashboard_v3.crm_tableros.common.tableros.todos", return_value=[PRUEBA["tablero"]]),
			patch("crm_dashboard_v3.crm_tableros.proyectos.api.TABLERO", PRUEBA["tablero"]),
		]
		for p in cls._parches:
			p.start()

	@classmethod
	def tearDownClass(cls):
		for p in cls._parches:
			p.stop()
		super().tearDownClass()

	@property
	def tablero(self):
		return PRUEBA["tablero"]
