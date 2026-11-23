"""Hooks de documentos: etapa, probabilidad y status coherentes (embudo_state_v2).

Workflow compartido (docs/diseno_workflow_compartido.md): las oportunidades de un
tablero usan sus etapas propias; las demás empresas, los 17 valores de siempre.

El hook validate corre en todo guardado —desde el tablero, el formulario o los
scripts existentes del ERP— y **nunca** hace fallar un guardado por la etapa:

- si un script escribe en una oportunidad de tablero un valor que el workflow no
  permite (p. ej. «Presentar cotización» desde Quotation-Client o Integración de
  costos), se ignora ese cambio de etapa y se guarda lo demás. Como en Frappe, la
  condición de la transición se mira sobre la versión guardada: venta POS y Ganada
  desde Calificar en un mismo guardado guardan la venta y dejan la etapa (Ganada va
  en un segundo guardado, como en ``vincular_factura_pos``);
- la probabilidad es la de la etapa;
- Ganada ↔ Converted y Perdida ↔ Lost cuando cambia la etapa;
- un cambio de status hecho desde ERPNext (declarar perdida) arrastra la etapa si
  el workflow lo permite;
- no se usa un motivo de pérdida genérico;
- pasar a Ganada fuera del tablero exige los requisitos de Ganada (si faltan, se
  ignora el cambio de etapa, como con un valor que el workflow no permite); lo mismo
  con un status Converted puesto a mano: si faltan los requisitos o el workflow no
  permite pasar a Ganada, se regresa al anterior (status Converted ⇔ etapa Ganada);
- la venta POS vinculada se valida siempre (``venta_pos.validar_vinculo``): ese
  error sí detiene el guardado, porque es un vínculo inválido, no una etapa.

Los requisitos de cada etapa se validan en el servidor al mover desde el tablero
(``acciones.cambiar_etapa``), que marca el documento con ``FLAG_TABLERO``.
"""

import frappe
from frappe import _

from crm_dashboard_v3.crm_tableros.common import flujo, venta_pos
from crm_dashboard_v3.crm_tableros.common.etapas import (
	CAMPO_ETAPA,
	CAMPO_FACTURA_POS,
	etapa_efectiva,
	faltantes,
	motivos_de,
)
from crm_dashboard_v3.crm_tableros.common.tableros import tablero_de_oportunidad

# Bandera del documento: el cambio de etapa viene del tablero (ya validado).
FLAG_TABLERO = "cambio_de_etapa_desde_tablero"


def validar_oportunidad(doc, method=None):
	anterior = None if doc.is_new() else doc.get_doc_before_save()
	# La venta POS se valida en todo guardado (y en toda oportunidad): el campo es de
	# solo lectura en la UI, pero se puede escribir por API.
	factura = doc.get(CAMPO_FACTURA_POS)
	if factura and (anterior is None or anterior.get(CAMPO_FACTURA_POS) != factura):
		venta_pos.validar_vinculo(doc, anterior)

	t = tablero_de_oportunidad(doc)
	if not t:
		return
	cfg = t.etapas

	if anterior is None or anterior.get("lost_reason") != doc.get("lost_reason"):
		for motivo in motivos_de(doc):
			if motivo in cfg.motivos_perdida_excluidos:
				frappe.throw(
					_("«{0}» no es un motivo de pérdida válido. Elige el motivo real.").format(motivo),
					title=_("Motivo de pérdida"),
				)

	etapa_cambio = anterior is None or anterior.get(CAMPO_ETAPA) != doc.get(CAMPO_ETAPA)
	ganada_avisada = False

	# Un script escribió una etapa que el workflow no permite: se ignora ese cambio.
	# Lo mismo si la lleva a Ganada (acción del workflow en el formulario, API) sin
	# cumplir sus requisitos: el workflow solo mira que haya algo en el campo.
	if anterior is not None and etapa_cambio and not doc.flags.get(FLAG_TABLERO):
		if flujo.bloqueo(doc, doc.get(CAMPO_ETAPA), actual=anterior.get(CAMPO_ETAPA)):
			doc.set(CAMPO_ETAPA, anterior.get(CAMPO_ETAPA))
			etapa_cambio = False
		elif _faltan_para_ganar(doc, cfg):
			_avisar_ganada_revertida(doc, cfg)
			ganada_avisada = True
			doc.set(CAMPO_ETAPA, anterior.get(CAMPO_ETAPA))
			etapa_cambio = False

	status_cambio = anterior is not None and anterior.get("status") != doc.get("status")
	# Un cambio de status hecho desde ERPNext (p. ej. declarar perdida) arrastra la etapa,
	# si el workflow lo permite y, para Ganada, si cumple sus requisitos; si no, no se
	# toca para no hacer fallar el guardado.
	destino = cfg.por_status(doc.status) if status_cambio and not etapa_cambio else None
	if destino and not flujo.bloqueo(doc, destino.valor) and not _faltan_para_ganar(doc, cfg, destino):
		doc.set(CAMPO_ETAPA, destino.valor)
		etapa_cambio = True
	elif status_cambio and doc.status == "Converted" and not doc.flags.get(FLAG_TABLERO):
		# Converted puesto a mano (formulario, API) sin orden de venta ni venta POS, o con
		# ellas pero sin que el workflow permita pasar a Ganada (la etapa no se arrastró):
		# no es una ganada. Se regresa el status, como con la etapa, para que Converted y
		# Ganada sigan juntos. ERPNext y marcar_ganada escriben Converted con db_set /
		# set_value, sin pasar por aquí.
		ganada = cfg.por_status("Converted")
		if ganada and _faltan_para_ganar(doc, cfg, ganada):
			if not ganada_avisada:
				_avisar_ganada_revertida(doc, cfg)
			doc.status = anterior.status
		elif ganada and flujo.bloqueo(doc, ganada.valor):
			if not ganada_avisada:
				_avisar_ganada_bloqueada(doc, ganada)
			doc.status = anterior.status

	etapa = cfg.por_valor(doc.get(CAMPO_ETAPA))
	if not etapa:
		# Sin etapa reconocible no se toca nada.
		return

	if etapa.probabilidad is not None:
		doc.probability = etapa.probabilidad
	if not etapa_cambio:
		return
	# Solo se ajusta el status cuando la etapa cambia, para no alterar el histórico
	# que nadie toca. «Descartada» (valor viejo) no cambia el status.
	if etapa.status and doc.get(CAMPO_ETAPA) == etapa.valor:
		doc.status = etapa.status
	elif not etapa.status and doc.status in ("Lost", "Converted"):
		# Reabrir una perdida: vuelve a estar abierta.
		doc.status = "Open"


def _faltan_para_ganar(doc, cfg, etapa=None) -> list[str]:
	"""Requisitos de Ganada que no se cumplen, si la etapa (la de ``doc`` o ``etapa``) es Ganada."""
	etapa = etapa or cfg.por_valor(doc.get(CAMPO_ETAPA))
	if not etapa or etapa.status != "Converted":
		return []
	return faltantes(doc, etapa, cfg)


def _avisar_ganada_revertida(doc, cfg):
	ganada = cfg.por_status("Converted")
	frappe.msgprint(
		_("La oportunidad {0} no pasó a {1}: falta {2}. Se guardaron los demás cambios.").format(
			doc.name, ganada.titulo, ", ".join(faltantes(doc, ganada, cfg))
		),
		title=_("Etapa de la oportunidad"),
		indicator="orange",
	)


def _avisar_ganada_bloqueada(doc, ganada):
	frappe.msgprint(
		_(
			"La oportunidad {0} no pasó a {1}: el workflow no lo permite desde «{2}». Gánala desde el "
			"tablero CRM Proyectos o con la orden de venta. Se guardaron los demás cambios."
		).format(doc.name, ganada.titulo, doc.get(CAMPO_ETAPA)),
		title=_("Etapa de la oportunidad"),
		indicator="orange",
	)


def estado_inicial(doc, method=None):
	"""Hook after_insert de Opportunity: las del tablero empiezan en su primera etapa.

	Frappe obliga a que toda oportunidad nueva nazca en el primer estado del
	workflow («Investigar al cliente», el de las demás empresas). Las de un tablero se
	pasan a su etapa inicial escribiendo directo en la base: es la normalización del
	alta, no un cambio de etapa del usuario.
	"""
	t = tablero_de_oportunidad(doc)
	if not t:
		return
	inicial = t.etapas.inicial
	if doc.get(CAMPO_ETAPA) == inicial.valor or not flujo.estado_existe(inicial.valor):
		return
	if t.etapas.por_valor(doc.get(CAMPO_ETAPA)) not in (None, inicial):
		# Nació en otra etapa a propósito (p. ej. creada desde otro documento): se respeta.
		return
	valores = {CAMPO_ETAPA: inicial.valor, "probability": inicial.probabilidad}
	doc.db_set(valores, update_modified=False)


def avanzar_con_cotizacion(doc, method=None):
	"""Hook on_submit de Quotation: la oportunidad del tablero pasa a la etapa de la propuesta.

	Solo si está en una etapa anterior. Avanza etapa por etapa (1 → 2 → 3), porque el
	workflow solo permite pasar a la siguiente y cada etapa intermedia tiene sus
	requisitos (la 2 exige monto, fecha de cierre y próximo paso con fecha). Se detiene
	en la primera que no se cumple y no bloquea el envío de la cotización: solo avisa
	qué faltó.
	"""
	if not doc.get("opportunity"):
		return
	from crm_dashboard_v3.crm_tableros.common import acciones

	oportunidad = frappe.get_doc("Opportunity", doc.opportunity)
	t = tablero_de_oportunidad(oportunidad)
	if not t:
		return
	cfg = t.etapas
	destino = next((e for e in cfg.activas if e.actualiza_monto_con_cotizacion), None)
	actual = etapa_efectiva(oportunidad, cfg)
	if not destino or actual not in cfg.activas or cfg.activas.index(actual) >= cfg.activas.index(destino):
		return
	pasos = cfg.activas[cfg.activas.index(actual) + 1 : cfg.activas.index(destino) + 1]
	for paso in pasos:
		try:
			acciones.cambiar_etapa(oportunidad, paso, cfg)
		except frappe.ValidationError as error:
			# frappe.throw dejó su mensaje en rojo; se reemplaza por un aviso que no asusta,
			# porque la cotización sí se envió.
			if frappe.message_log:
				frappe.message_log.pop()
			oportunidad.reload()  # la etapa guardada, no la que se intentó poner
			frappe.msgprint(
				_("La cotización se envió, pero la oportunidad {0} no pasó a {1} y quedó en {2}: {3}").format(
					oportunidad.name,
					destino.titulo,
					etapa_efectiva(oportunidad, cfg).titulo,
					frappe.utils.strip_html(str(error)),
				),
				title=_("Etapa de la oportunidad"),
				indicator="orange",
			)
			return


def marcar_ganada(oportunidad: str):
	"""Pone la etapa Ganada (y Converted) a una oportunidad cuya orden de venta ya existe."""
	row = frappe.db.get_value("Opportunity", oportunidad, ["sales_model", "establecimiento_lista"], as_dict=True)
	t = tablero_de_oportunidad(row) if row else None
	ganada = t.etapas.por_status("Converted") if t else None
	if not ganada:
		return
	# set_value: la orden de venta ya cumplió el requisito; replicamos lo que ERPNext
	# hace con el status (db_set) para que etapa y status no queden desalineados.
	frappe.db.set_value(
		"Opportunity",
		oportunidad,
		{CAMPO_ETAPA: ganada.valor, "probability": ganada.probabilidad, "status": "Converted"},
	)


def sincronizar_ganadas_desde_orden(doc, method=None):
	"""Hook on_submit de Sales Order: sus oportunidades pasan a Ganada."""
	cotizaciones = list({i.prevdoc_docname for i in doc.items if i.get("prevdoc_docname")})
	if not cotizaciones:
		return
	oportunidades = frappe.get_all(
		"Quotation",
		filters={"name": ["in", cotizaciones], "opportunity": ["is", "set"]},
		pluck="opportunity",
	)
	for oportunidad in set(oportunidades):
		marcar_ganada(oportunidad)
