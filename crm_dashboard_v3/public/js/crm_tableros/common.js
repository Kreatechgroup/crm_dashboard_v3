// Utilidades de UI compartidas por los tableros CRM (Proyectos y, después, Retail).
// Solo formato y navegación: los cálculos viven en el servidor.

frappe.provide("crm_tableros");

crm_tableros.esc = (texto) => frappe.utils.escape_html(texto == null ? "" : String(texto));

crm_tableros.dinero = (monto, moneda) =>
	format_currency(monto || 0, moneda, 2);

crm_tableros.fecha = (valor) => (valor ? frappe.datetime.str_to_user(valor) : "");

crm_tableros.plural = (n, singular, plural) => `${n} ${n === 1 ? singular : plural}`;

// Píldora de semáforo: siempre color + texto (Verde / Amarillo / Rojo).
crm_tableros.semaforo = (sem, texto) =>
	`<span class="crm-pill crm-pill-${crm_tableros.esc(sem.clave)}" title="${crm_tableros.esc(sem.texto)}">` +
	`${crm_tableros.esc(texto || sem.texto)}<span class="sr-only"> · ${crm_tableros.esc(sem.texto)}</span></span>`;

// Cada número del tablero abre la lista de ERPNext con los registros que lo forman.
crm_tableros.abrir_lista = (doctype, nombres) => {
	if (!nombres || !nombres.length) {
		frappe.show_alert({ message: __("No hay registros que mostrar."), indicator: "orange" });
		return;
	}
	frappe.route_options = { name: ["in", nombres] };
	frappe.set_route("List", doctype, "List");
};

crm_tableros.llamar = (method, args, opciones = {}) =>
	frappe
		.call({ method, args, freeze: opciones.freeze !== false, freeze_message: opciones.mensaje })
		.then((r) => r.message);

// Diálogo para elegir un Lost Reason válido (la lista ya viene filtrada del servidor).
crm_tableros.pedir_motivo_perdida = (motivos, titulo) =>
	new Promise((resolve) => {
		const d = new frappe.ui.Dialog({
			title: titulo || __("Dar por perdida"),
			fields: [
				{
					fieldname: "motivo",
					label: __("Motivo de pérdida"),
					fieldtype: "Select",
					options: [""].concat(motivos || []),
					reqd: 1,
				},
				{ fieldname: "detalle", label: __("Detalle (opcional)"), fieldtype: "Small Text" },
			],
			primary_action_label: __("Confirmar pérdida"),
			primary_action(valores) {
				d.hide();
				resolve(valores);
			},
		});
		d.show();
	});
