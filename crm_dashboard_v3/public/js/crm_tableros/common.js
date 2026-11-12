// Utilidades de UI compartidas por los tableros CRM (Proyectos y, después, Retail).
// Solo formato y navegación: los cálculos viven en el servidor.

frappe.provide("crm_tableros");

crm_tableros.esc = (texto) => frappe.utils.escape_html(texto == null ? "" : String(texto));

crm_tableros.dinero = (monto, moneda) => format_currency(monto || 0, moneda, 2);

crm_tableros.plural = (n, singular, plural) => `${n} ${n === 1 ? singular : plural}`;

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
