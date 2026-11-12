"""Registro de tableros CRM y a cuál pertenece cada oportunidad.

Un tablero define a quién atiende (establecimientos y modelos de venta), quién
lo ve como jefe (roles) y qué etapas usa. CRM Proyectos atiende a los asesores
de Plus con sus dos Sales Person (Proyectos y Retail); CRM Retail atenderá a
los asesores de Abito cuando exista ``crm_tableros/retail/config.py``.
"""

import importlib
from dataclasses import dataclass

from crm_dashboard_v3.crm_tableros.common.etapas import ConfigModelo

# Claves de los tableros con configuración propia (módulo crm_tableros.<clave>.config).
TABLEROS = ("proyectos",)


@dataclass(frozen=True)
class ConfigTablero:
	clave: str
	titulo: str
	# Establecimientos (Sales Person.establecimiento y Opportunity.establecimiento_lista) que atiende.
	establecimientos: tuple[str, ...]
	# Modelos de venta (Opportunity.sales_model) que se juntan en el tablero.
	sales_models: tuple[str, ...]
	# Roles que ven la vista de tienda (todos los asesores y cada uno por separado).
	roles_jefe: tuple[str, ...]
	etapas: ConfigModelo
	tipo_meta: str
	# Modelo de cada Sales Person: el primero cuyo texto aparece en su nombre;
	# si ninguno aparece, ``modelo_por_defecto``.
	texto_sales_person_por_modelo: tuple[tuple[str, str], ...]
	modelo_por_defecto: str
	meses_historico: int = 6

	def incluye(self, sales_model: str | None, establecimiento: str | None) -> bool:
		return sales_model in self.sales_models and establecimiento in self.establecimientos

	def modelo_de_sales_person(self, nombre: str) -> str:
		for modelo, texto in self.texto_sales_person_por_modelo:
			if texto in (nombre or ""):
				return modelo
		return self.modelo_por_defecto


def tablero(clave: str) -> ConfigTablero:
	if clave not in TABLEROS:
		raise KeyError(clave)
	return importlib.import_module(f"crm_dashboard_v3.crm_tableros.{clave}.config").TABLERO


def todos() -> list[ConfigTablero]:
	return [tablero(clave) for clave in TABLEROS]


def tablero_de(sales_model: str | None, establecimiento: str | None) -> ConfigTablero | None:
	"""Tablero que atiende la oportunidad, o None si ninguno la atiende todavía."""
	return next((t for t in todos() if t.incluye(sales_model, establecimiento)), None)


def tablero_de_oportunidad(doc) -> ConfigTablero | None:
	return tablero_de(doc.get("sales_model"), doc.get("establecimiento_lista"))


def titulos_de_todas_las_etapas() -> list[str]:
	titulos: list[str] = []
	for t in todos():
		for etapa in t.etapas.etapas:
			if etapa.titulo not in titulos:
				titulos.append(etapa.titulo)
	return titulos
