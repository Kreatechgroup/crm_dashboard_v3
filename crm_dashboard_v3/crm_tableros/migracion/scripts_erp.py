"""Cambios en configuración del ERP que necesita el workflow compartido (fase 1: Plus).

1. Client Script «Opportunity-Client»: el botón «Descartar» sigue igual para las
   demás empresas; en las oportunidades de un tablero pide un motivo y da la
   oportunidad por perdida («Descartada» no es una etapa de los tableros).
2. Dashboard Chart «Monto OPTYS en negociación»: también cuenta «4 · Negociación».

Antes de cambiar nada guarda una copia del valor original como archivo privado
(«respaldo_crm_tableros_…»), que usa ``revertir()``. No borra nada. Se ejecuta a mano:

    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.scripts_erp.simular
    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.scripts_erp.aplicar
    bench --site <sitio> execute crm_dashboard_v3.crm_tableros.migracion.scripts_erp.revertir
"""

import json
import re

import frappe
from frappe.utils import now_datetime

from crm_dashboard_v3.crm_tableros.common.etapas import CAMPO_ETAPA

CLIENT_SCRIPT = "Opportunity-Client"
GRAFICA = "Monto OPTYS en negociación"
PREFIJO_RESPALDO = "respaldo_crm_tableros_"
MARCA = "// crm_tableros: Descartar"

# Función completa del botón, desde su declaración hasta el cierre «};» en su propia línea.
PATRON_DESCARTAR = re.compile(r"cur_frm\.cscript\.descartar\s*=\s*function\s*\(doc\)\s*\{.*?\n\};", re.S)

DESCARTAR_NUEVO = """cur_frm.cscript.descartar = function (doc) {
    """ + MARCA + """ · en los tableros CRM pide motivo y da por perdida (crm_dashboard_v3).
    frappe.call({
        method: "crm_dashboard_v3.crm_tableros.common.api.como_descartar",
        args: { nombre: cur_frm.doc.name },
    }).then((r) => {
        const regla = r.message || {};
        if (!regla.pedir_motivo) {
            frappe.call({
                "method": "frappe.client.set_value",
                "args": {
                    "doctype": "Opportunity",
                    "name": cur_frm.doc.name,
                    "fieldname": { "embudo_state_v2": "Descartada" }
                }
            });
            frappe.msgprint("Descartada");
            return;
        }
        const dialogo = new frappe.ui.Dialog({
            title: __("Dar por perdida"),
            fields: [
                { fieldname: "motivo", label: __("Motivo de pérdida"), fieldtype: "Select", options: [""].concat(regla.motivos || []), reqd: 1 },
                { fieldname: "detalle", label: __("Detalle (opcional)"), fieldtype: "Small Text" },
            ],
            primary_action_label: __("Confirmar pérdida"),
            primary_action(valores) {
                frappe.call({
                    method: "crm_dashboard_v3.crm_tableros.common.api.descartar_oportunidad",
                    args: { nombre: cur_frm.doc.name, motivo: valores.motivo, detalle: valores.detalle },
                    freeze: true,
                }).then(() => {
                    dialogo.hide();
                    cur_frm.reload_doc();
                    frappe.show_alert({ message: __("Oportunidad dada por perdida"), indicator: "green" });
                });
            },
        });
        dialogo.show();
    });
};"""


def _etapa_negociacion() -> str:
	from crm_dashboard_v3.crm_tableros.common.tableros import todos

	return next(e.valor for t in todos() for e in t.etapas.etapas if e.clave == "neg")


def _script_nuevo(actual: str) -> str | None:
	"""Script con el botón nuevo, o None si ya está aplicado o no se encontró la función."""
	if MARCA in actual or not PATRON_DESCARTAR.search(actual):
		return None
	return PATRON_DESCARTAR.sub(lambda _m: DESCARTAR_NUEVO, actual, count=1)


def _filtro_nuevo(filtros_json: str) -> str | None:
	filtros = json.loads(filtros_json or "[]")
	negociacion = _etapa_negociacion()
	cambiado = False
	for f in filtros:
		if f[1] == CAMPO_ETAPA and f[2] == "=" and f[3] == "Negociar":
			f[2], f[3] = "in", ["Negociar", negociacion]
			cambiado = True
	return json.dumps(filtros, ensure_ascii=False) if cambiado else None


def _respaldar(nombre: str, contenido: str):
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{PREFIJO_RESPALDO}{nombre}_{now_datetime():%Y%m%d%H%M%S}.txt",
			"is_private": 1,
			"content": contenido,
		}
	).insert(ignore_permissions=True)


def _ultimo_respaldo(nombre: str) -> str | None:
	archivo = frappe.get_all(
		"File",
		filters={"file_name": ["like", f"{PREFIJO_RESPALDO}{nombre}_%"], "is_private": 1},
		order_by="creation desc",
		limit=1,
		pluck="name",
	)
	return frappe.get_doc("File", archivo[0]).get_content() if archivo else None


def simular():
	script = frappe.db.get_value("Client Script", CLIENT_SCRIPT, "script") or ""
	print(f"Client Script «{CLIENT_SCRIPT}»: ", end="")
	if MARCA in script:
		print("ya tiene el botón nuevo.")
	elif PATRON_DESCARTAR.search(script):
		print("se reemplazaría la función del botón «Descartar».")
	else:
		print("NO se encontró la función del botón «Descartar»; no se cambiaría.")
	filtros = frappe.db.get_value("Dashboard Chart", GRAFICA, "filters_json")
	nuevo = _filtro_nuevo(filtros) if filtros is not None else None
	print(f"Gráfica «{GRAFICA}»: {'filtro ' + filtros + ' → ' + nuevo if nuevo else 'sin cambios'}")
	print("Simulación: no se escribió nada.")


def aplicar():
	cambios = []
	script = frappe.db.get_value("Client Script", CLIENT_SCRIPT, "script") or ""
	nuevo_script = _script_nuevo(script)
	if nuevo_script:
		_respaldar(CLIENT_SCRIPT, script)
		frappe.db.set_value("Client Script", CLIENT_SCRIPT, "script", nuevo_script)
		cambios.append(CLIENT_SCRIPT)
	filtros = frappe.db.get_value("Dashboard Chart", GRAFICA, "filters_json")
	nuevo_filtro = _filtro_nuevo(filtros) if filtros is not None else None
	if nuevo_filtro:
		_respaldar(GRAFICA, filtros)
		frappe.db.set_value("Dashboard Chart", GRAFICA, "filters_json", nuevo_filtro)
		cambios.append(GRAFICA)
	frappe.clear_cache(doctype="Opportunity")
	frappe.db.commit()
	print(f"Aplicado: {cambios or 'nada (ya estaba aplicado)'}. Respaldos como archivos privados «{PREFIJO_RESPALDO}…».")


def revertir():
	restaurados = []
	for doctype, nombre, campo in (
		("Client Script", CLIENT_SCRIPT, "script"),
		("Dashboard Chart", GRAFICA, "filters_json"),
	):
		original = _ultimo_respaldo(nombre)
		if original is not None:
			frappe.db.set_value(doctype, nombre, campo, original)
			restaurados.append(nombre)
	frappe.clear_cache(doctype="Opportunity")
	frappe.db.commit()
	print(f"Restaurado desde respaldo: {restaurados or 'nada'}. Los archivos de respaldo se conservan.")
