"""Workflow compartido de Opportunity (docs/diseno_workflow_compartido.md).

Crea «Embudo de ventas 2026» a partir de «Embudo de ventas 2019»:

- conserva sus estados y transiciones para las demás empresas, con la condición
  «no es de un tablero»;
- agrega los estados de cada tablero (sus etapas con nombre real) y sus transiciones,
  con la condición «es de este tablero».

«Embudo de ventas 2019» no se modifica ni se borra: queda desactivado como respaldo
y ``revertir()`` lo vuelve a activar. Nada de esto corre en ``migrate``; se ejecuta a
mano y primero en simulación:

    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.workflow.simular
    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.workflow.instalar
    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.workflow.revertir
"""

import frappe

from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA, ConfigModelo
from crm_dashboard_v3.crm_tableros.common.tableros import ConfigTablero, todos

ORIGEN = "Embudo de ventas 2019"
NUEVO = "Embudo de ventas 2026"
ROL = "Embudo de ventas"
ESTILO_ESTADO = {"Converted": "Success", "Lost": "Danger"}


# ---------------------------------------------------------------------------
# Definición (funciones puras: se prueban sin base de datos)
# ---------------------------------------------------------------------------


def condicion_de(t: ConfigTablero) -> str:
	"""Condición de workflow: la oportunidad pertenece al tablero."""
	return (
		f"(doc.establecimiento_lista in {list(t.establecimientos)!r}"
		f" and doc.sales_model in {list(t.sales_models)!r})"
	)


def condicion_de_tableros(tableros: list[ConfigTablero]) -> str:
	return " or ".join(condicion_de(t) for t in tableros)


def condicion_legado(tableros: list[ConfigTablero], condicion_original: str | None) -> str:
	"""Condición para una transición del workflow viejo: solo si no es de un tablero."""
	condicion = f"not ({condicion_de_tableros(tableros)})"
	if condicion_original:
		condicion += f" and ({condicion_original})"
	return condicion


def _accion(destino, cfg: ConfigModelo) -> str:
	if destino.status == "Converted":
		return "Marcar como ganada"
	if destino.status == "Lost":
		return "Marcar como perdida"
	if not destino.activa:
		return "Poner en pausa"
	# El nombre de la etapa sin su número: «3 · Propuesta enviada» → «Propuesta enviada».
	return destino.titulo.split(" · ", 1)[-1]


def transiciones_de(t: ConfigTablero) -> list[dict]:
	"""Transiciones de un tablero: avanzar, regresar, pausar, retomar, ganar y perder."""
	cfg = t.etapas
	activas = cfg.activas
	pausa = next((e for e in cfg.etapas if not e.activa and not e.status), None)
	ganada = cfg.por_status("Converted")
	perdida = cfg.por_status("Lost")
	pares = []
	for i, etapa in enumerate(activas):
		if i + 1 < len(activas):
			pares.append((etapa, activas[i + 1]))
		if i > 0:
			pares.append((etapa, activas[i - 1]))
		if etapa.puede_ganar and ganada:
			pares.append((etapa, ganada))
		if pausa:
			pares.append((etapa, pausa))
		if perdida:
			pares.append((etapa, perdida))
	if pausa:
		pares.extend((pausa, etapa) for etapa in activas)
		if perdida:
			pares.append((pausa, perdida))
	condicion = condicion_de(t)
	return [
		{
			"state": desde.valor,
			"action": _accion(hacia, cfg),
			"next_state": hacia.valor,
			"allowed": ROL,
			"allow_self_approval": 1,
			"condition": condicion,
		}
		for desde, hacia in pares
	]


def estados_de(t: ConfigTablero) -> list[str]:
	return t.etapas.valores


# ---------------------------------------------------------------------------
# Simulación, instalación y reversa
# ---------------------------------------------------------------------------


def _faltantes(doctype: str, nombres: list[str]) -> list[str]:
	return [n for n in dict.fromkeys(nombres) if not frappe.db.exists(doctype, n)]


def _opciones_del_campo() -> list[str]:
	opciones = frappe.db.get_value("Custom Field", {"dt": "Opportunity", "fieldname": CAMPO_ETAPA}, "options")
	return [o for o in (opciones or "").split("\n") if o]


def _plan() -> dict:
	tableros = todos()
	origen = frappe.get_doc("Workflow", ORIGEN)
	estados = [e for t in tableros for e in estados_de(t)]
	nuevas = [tr for t in tableros for tr in transiciones_de(t)]
	estados_origen = [s.state for s in origen.states]
	return {
		"tableros": [t.titulo for t in tableros],
		"origen": origen,
		"estados_nuevos": [e for e in dict.fromkeys(estados) if e not in estados_origen],
		"transiciones_nuevas": nuevas,
		"transiciones_legado": len(origen.transitions),
		"workflow_state_por_crear": _faltantes("Workflow State", estados),
		"acciones_por_crear": _faltantes("Workflow Action Master", [tr["action"] for tr in nuevas]),
		"opciones_por_agregar": [e for e in dict.fromkeys(estados) if e not in _opciones_del_campo()],
		"nuevo_existe": bool(frappe.db.exists("Workflow", NUEVO)),
		"activo": frappe.db.get_value("Workflow", {"document_type": "Opportunity", "is_active": 1}, "name"),
	}


def simular():
	"""Muestra lo que haría instalar() sin escribir nada."""
	p = _plan()
	print(f"Workflow activo hoy: {p['activo']}")
	print(f"Tableros: {', '.join(p['tableros'])}")
	print(f"Se {'actualizaría' if p['nuevo_existe'] else 'crearía'} «{NUEVO}» a partir de «{ORIGEN}» (este queda intacto y desactivado).")
	print(f"Transiciones de {ORIGEN} que se conservan con la condición «no es de un tablero»: {p['transiciones_legado']}")
	print(f"Estados nuevos: {p['estados_nuevos']}")
	print(f"Transiciones nuevas: {len(p['transiciones_nuevas'])}")
	for tr in p["transiciones_nuevas"]:
		print(f"  {tr['state']} --[{tr['action']}]--> {tr['next_state']}")
	print(f"Workflow State por crear: {p['workflow_state_por_crear']}")
	print(f"Workflow Action Master por crear: {p['acciones_por_crear']}")
	print(f"Opciones por agregar a {CAMPO_ETAPA}: {p['opciones_por_agregar']}")
	print("Simulación: no se escribió nada.")


def instalar():
	"""Crea (o actualiza) el workflow compartido y lo activa. No borra nada."""
	p = _plan()
	origen = p["origen"]
	tableros = todos()
	estilo = {e.valor: ESTILO_ESTADO.get(e.status, "Primary") for t in tableros for e in t.etapas.etapas}

	for nombre in p["workflow_state_por_crear"]:
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": nombre, "style": estilo.get(nombre, "Primary")}).insert()
	for nombre in p["acciones_por_crear"]:
		frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": nombre}).insert()
	if p["opciones_por_agregar"]:
		campo = frappe.get_doc("Custom Field", {"dt": "Opportunity", "fieldname": CAMPO_ETAPA})
		campo.options = "\n".join(_opciones_del_campo() + p["opciones_por_agregar"])
		campo.save()

	nuevo = frappe.get_doc("Workflow", NUEVO) if p["nuevo_existe"] else frappe.new_doc("Workflow")
	nuevo.update(
		{
			"workflow_name": NUEVO,
			"document_type": origen.document_type,
			"workflow_state_field": origen.workflow_state_field,
			"send_email_alert": origen.send_email_alert,
			"override_status": origen.override_status,
			"is_active": 1,
		}
	)
	# Estados: los del workflow viejo (el primero sigue siendo el inicial) y los nuevos.
	nuevo.set("states", [])
	for s in origen.states:
		nuevo.append("states", {"state": s.state, "doc_status": s.doc_status, "allow_edit": s.allow_edit,
			"update_field": s.update_field, "update_value": s.update_value, "is_optional_state": s.is_optional_state})
	permiso_edicion = origen.states[0].allow_edit if origen.states else ROL
	for nombre in p["estados_nuevos"]:
		nuevo.append("states", {"state": nombre, "doc_status": "0", "allow_edit": permiso_edicion})
	# Transiciones: las viejas solo para quien no es de un tablero; las nuevas, por tablero.
	nuevo.set("transitions", [])
	for tr in origen.transitions:
		nuevo.append("transitions", {"state": tr.state, "action": tr.action, "next_state": tr.next_state,
			"allowed": tr.allowed, "allow_self_approval": tr.allow_self_approval,
			"send_email_to_creator": tr.send_email_to_creator,
			"condition": condicion_legado(tableros, tr.condition)})
	for tr in p["transiciones_nuevas"]:
		nuevo.append("transitions", tr)
	nuevo.save()
	frappe.db.commit()
	print(f"«{NUEVO}» activo con {len(nuevo.states)} estados y {len(nuevo.transitions)} transiciones. «{ORIGEN}» quedó desactivado, sin cambios.")


def revertir():
	"""Vuelve a activar el workflow viejo. No borra «Embudo de ventas 2026» ni los estados creados."""
	origen = frappe.get_doc("Workflow", ORIGEN)
	origen.is_active = 1
	origen.save()
	frappe.db.commit()
	print(f"«{ORIGEN}» activo de nuevo. «{NUEVO}» quedó desactivado (no se borró).")
