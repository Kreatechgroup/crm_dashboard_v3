"""Configuración del tablero CRM Proyectos: asesores de Plus con sus dos Sales Person.

Cada asesor de Plus tiene un Sales Person de Proyectos ("Asesor de Proyectos
Retail X - UM") y uno de Retail ("Asesor Retail X - UM"). El tablero junta las
oportunidades, metas y ventas de los dos; las oportunidades Retail de Plus usan
las mismas etapas que las de Proyectos.
"""

from crm_dashboard_v3.crm_tableros.common.etapas import ConfigModelo, Etapa
from crm_dashboard_v3.crm_tableros.common.tableros import ConfigTablero

PROYECTOS = "Proyectos"
RETAIL = "Retail"

ETAPAS = ConfigModelo(
	nombre="CRM Proyectos",
	etapas=(
		Etapa(
			"cal",
			"1 · Calificar",
			10,
			activa=True,
			requisitos=("cliente", "tipo", "origen"),
			texto_requisitos="cliente, tipo y origen",
		),
		Etapa(
			"req",
			"2 · Requerimiento y diseño",
			25,
			activa=True,
			requisitos=("monto", "fecha_cierre", "proximo_paso"),
			texto_requisitos="presupuesto, fecha estimada y próximo paso",
		),
		Etapa(
			"prop",
			"3 · Propuesta enviada",
			50,
			activa=True,
			requisitos=("cotizacion_enviada", "fecha_cierre", "proximo_paso"),
			texto_requisitos="cotización enviada ligada",
			actualiza_monto_con_cotizacion=True,
		),
		Etapa(
			"neg",
			"4 · Negociación",
			75,
			activa=True,
			requisitos=("monto", "fecha_cierre", "proximo_paso_vigente"),
			texto_requisitos="próximo paso con fecha vigente",
		),
		Etapa(
			"pausa",
			"En pausa",
			None,
			activa=False,
			requisitos=("fecha_retomar",),
			texto_requisitos="fecha para retomar",
			cuenta_pronostico=False,
		),
		Etapa(
			"ganada",
			"Ganada",
			100,
			activa=False,
			requisitos=("orden_de_venta",),
			texto_requisitos="orden de venta creada",
			status="Converted",
		),
		Etapa(
			"perdida",
			"Perdida",
			0,
			activa=False,
			requisitos=("motivo_perdida",),
			texto_requisitos="motivo de pérdida",
			status="Lost",
			cuenta_pronostico=False,
		),
	),
	mapa_legado={
		"Investigar al cliente": "cal",
		"Clasificar": "cal",
		"Presentar empresa": "cal",
		"Conocer": "cal",
		"Tomar requerimiento": "req",
		"Definir la solución": "req",
		"Presentar solución": "req",
		"Crear el diseño": "req",
		"Presentar diseño": "req",
		"Crear la cotización": "prop",
		"Presentar cotización": "prop",
		"Dar seguimiento": "neg",
		"Negociar": "neg",
		"Ganada": "ganada",
		"Perdida": "perdida",
		"Descartada": "perdida",
		"Llamar después": "pausa",
	},
	umbral_escalar=50000,
	dias_verde_max=7,
	dias_amarillo_max=14,
	motivos_perdida_excluidos=("Especificar motivo",),
)

TABLERO = ConfigTablero(
	clave="proyectos",
	titulo="CRM Proyectos",
	establecimientos=("Plus Fontabella Importado",),
	sales_models=(PROYECTOS, RETAIL),
	roles_jefe=("Jefe de Plus",),
	etapas=ETAPAS,
	tipo_meta="Monto de VENTA (Sales Invoice)",
	texto_sales_person_por_modelo=((PROYECTOS, "Proyectos"),),
	modelo_por_defecto=RETAIL,
)
