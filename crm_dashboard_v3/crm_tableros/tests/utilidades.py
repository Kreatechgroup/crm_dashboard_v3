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


_TEXTO_PRUEBA = "Prueba CRM V3"
_SIN_RELLENO = ("Table", "Table MultiSelect", "Dynamic Link", "Check", "Currency")
_NUMERICOS = ("Int", "Float", "Percent")


def _valor_de_prueba(df):
	"""Valor válido para un campo obligatorio, según su tipo (sin datos fijos del sitio)."""
	if df.fieldtype in _NUMERICOS:
		return 1
	if df.fieldtype == "Link":
		filtros = {"disabled": 0} if frappe.get_meta(df.options).has_field("disabled") else {}
		existente = frappe.get_all(df.options, filters=filtros, pluck="name", limit=1)
		return existente[0] if existente else None
	if df.fieldtype == "Select":
		return next((o for o in (df.options or "").split("\n") if o.strip()), None)
	if df.options == "Email":
		return f"prueba.crmv3.{frappe.generate_hash(length=8)}@example.com"
	if df.options == "Phone":
		return "55555555"
	if df.fieldtype in ("Date", "Datetime"):
		return nowdate()
	return _TEXTO_PRUEBA


def completar_obligatorios(doc):
	"""Llena los obligatorios que el sitio agregó y la prueba no usa.

	Los sitios reales suelen exigir campos propios (correo, teléfono, forma de pago…);
	así las pruebas no dependen de la personalización de cada sitio. Los números
	enteros quedan en 1, los montos no se llenan y los campos que la prueba ya llenó
	no se tocan.
	"""
	from erpnext.controllers.selling_controller import SellingController

	if isinstance(doc, SellingController) and doc.meta.has_field("items"):
		# Moneda, lista de precios y datos de los artículos los pone ERPNext, no la prueba.
		doc.set_missing_values()
	for df in doc.meta.fields:
		if df.reqd and df.fieldtype not in _SIN_RELLENO and doc.get(df.fieldname) in (None, ""):
			doc.set(df.fieldname, _valor_de_prueba(df))
	return doc


def crear_lead():
	lead = frappe.get_doc(
		{
			"doctype": "Lead",
			"first_name": "Cliente Prueba CRM V3",
			"lead_name": f"Cliente Prueba CRM V3 {frappe.generate_hash(length=6)}",
			"company_name": f"Cliente Prueba CRM V3 {frappe.generate_hash(length=6)}",
			"company": compania(),
			"source": ORIGEN_PRUEBA,
			"establecimiento_lista": PRUEBA.get("establecimiento"),
			# ERPNext crea el Customer desde el lead al hacer la orden, y lo exige.
			"territory": next(iter(frappe.get_all("Territory", filters={"is_group": 0}, pluck="name", limit=1)), None),
		}
	)
	return completar_obligatorios(lead).insert()


def _item_de_prueba() -> str:
	"""Artículo para las cotizaciones de prueba.

	Usa uno de venta que ya exista: los sitios reales nombran los artículos con su
	propia serie y exigen campos propios, y crear uno ahí falla por razones ajenas
	al tablero. La cotización se revierte al terminar la prueba.
	"""
	base = {"disabled": 0, "is_sales_item": 1, "has_variants": 0}
	for filtros in ({"item_name": ITEM_PRUEBA}, {**base, "is_stock_item": 0}, base):
		existente = frappe.get_all("Item", filters=filtros, pluck="name", limit=1)
		if existente:
			return existente[0]
	raise unittest.SkipTest("El sitio de pruebas no tiene artículos de venta.")


def _tipo_de_oportunidad_erpnext():
	# ERPNext pone "Sales" traducido al idioma de la sesión, que puede no existir.
	return "Sales" if frappe.db.exists("Opportunity Type", "Sales") else None


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
			"opportunity_type": _tipo_de_oportunidad_erpnext(),
			"source": ORIGEN_PRUEBA,
			"transaction_date": nowdate(),
			**campos,
		}
	)
	completar_obligatorios(doc)
	if not doc.get("presupuesto_declarado_por_el_cliente"):
		# Las pruebas de requisitos necesitan oportunidades sin monto (como las del
		# histórico), aunque el sitio exija el presupuesto al crearlas.
		doc.flags.ignore_mandatory = True
	return doc.insert()


def crear_actividad(oportunidad, dias=3):
	return acciones.registrar_actividad(oportunidad, "Llamada", "Seguimiento de prueba", add_days(nowdate(), dias))


def crear_cotizacion(oportunidad, valid_till, transaction_date=None, monto=10000):
	item = _item_de_prueba()
	q = frappe.get_doc(
		{
			"doctype": "Quotation",
			"quotation_to": "Lead",
			"party_name": oportunidad.party_name,
			"company": oportunidad.company,
			"currency": frappe.get_cached_value("Company", oportunidad.company, "default_currency"),
			"conversion_rate": 1,
			"opportunity": oportunidad.name,
			"sales_model": oportunidad.sales_model,
			"transaction_date": transaction_date or nowdate(),
			"valid_till": valid_till,
			"items": [{"item_code": item, "qty": 1, "rate": monto}],
		}
	)
	completar_obligatorios(q).insert()
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
