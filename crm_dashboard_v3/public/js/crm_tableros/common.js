// Plantilla de UI común de los tableros CRM (Proyectos y, después, Retail).
// Solo formato, navegación y el esqueleto de la página: los cálculos viven en el servidor.

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

crm_tableros.API_COMUN = "crm_dashboard_v3.crm_tableros.common.api.";
crm_tableros.MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

// Contexto de sesión sin datos del tablero (usuario, empleado, Sales Person, empresa, jefe, mes).
crm_tableros.get_contexto = (tablero, args = {}) =>
	crm_tableros.llamar(crm_tableros.API_COMUN + "get_contexto", { tablero, ...args }, { freeze: false });

/**
 * Esqueleto de un tablero.
 *
 * El método principal del servidor (opciones.metodo) devuelve los datos base del
 * alcance (common/alcance.py: título, mes, tienda, jefe, asesores…) más los propios
 * del tablero. La plantilla pinta el encabezado, el mensaje de sin acceso y el
 * selector "Ver:" de los jefes; cada tablero implementa:
 *   - html_contenido()          lo que va debajo del encabezado
 *   - despues_de_pintar()       ajustes tras pintar (opcional)
 *   - antes_de_cargar()         limpiar datos secundarios (opcional)
 *   - despues_de_cargar(datos)  pedir datos secundarios (opcional)
 *   - al_cambiar_alcance()      limpiar selección al cambiar de asesor/tienda/mes (opcional)
 *   - accion(nombre, $boton)    botones con data-accion propios
 *   - cambio(clave, valor)      selects con data-cambio propios
 */
crm_tableros.TableroBase = class TableroBase {
	constructor(page, opciones) {
		this.page = page;
		this.opciones = opciones;
		this.estado = { mes: null, asesor: null, establecimiento: null };
		this.datos = null;
		this.page.set_secondary_action(__("Actualizar"), () => this.cargar(), "refresh");
		this.$body = $('<div class="crm"></div>').appendTo(this.page.main);
		this.enlazar_eventos_base();
	}

	// ------------------------------------------------------------------
	// Formato
	// ------------------------------------------------------------------

	e(texto) {
		return crm_tableros.esc(texto);
	}

	dinero(monto) {
		return crm_tableros.dinero(monto, this.datos.moneda);
	}

	compacto(n) {
		if (Math.abs(n) >= 1000000) return (n / 1000000).toFixed(1) + " M";
		if (Math.abs(n) >= 1000) return Math.round(n / 1000) + "k";
		return String(Math.round(n));
	}

	// "16 oct" (con año si no es el actual).
	fecha(valor) {
		if (!valor) return "";
		const [y, m, d] = String(valor).slice(0, 10).split("-");
		const anio = String(new Date().getFullYear());
		return `${Number(d)} ${crm_tableros.MESES_CORTOS[Number(m) - 1]}${y !== anio ? " " + y : ""}`;
	}

	// Pastilla de estado: siempre color + texto (Verde / Amarillo / Rojo).
	tag(sem, texto, chica) {
		const color = sem.color || sem.texto;
		const extra = color && color !== texto ? `<span class="crm-sr"> · ${this.e(color)}</span>` : "";
		return `<span class="crm-tag crm-tag-${this.e(sem.clave)} ${chica ? "crm-tag-sm" : ""}">${this.e(texto)}${extra}</span>`;
	}

	html_cargando() {
		return `<p class="crm-cargando">${__("Cargando…")}</p>`;
	}

	// ------------------------------------------------------------------
	// Alcance: quién mira y a quién
	// ------------------------------------------------------------------

	args() {
		const { mes, asesor, establecimiento } = this.estado;
		return { mes, asesor, establecimiento };
	}

	// Asesor viendo lo suyo, o jefe con un asesor elegido.
	es_alcance_individual() {
		return !this.datos.es_jefe || !!this.datos.asesor;
	}

	nombre_alcance() {
		if (!this.datos.es_jefe) return this.datos.nombre_usuario;
		const a = this.datos.asesores.find((x) => x.empleado === this.datos.asesor);
		return a ? a.nombre : __("Toda la tienda");
	}

	primer_nombre(nombre) {
		return (nombre || "").split(" ")[0];
	}

	mes_en_texto() {
		return this.datos.etiqueta_mes.split(" ")[0].toLowerCase();
	}

	// "al 28 oct" solo en el mes en curso.
	texto_corte() {
		const d = this.datos;
		return d.dia_de_corte && d.mes === d.dia_de_corte.slice(0, 7) ? __("al {0}", [this.fecha(d.dia_de_corte)]) : "";
	}

	// ------------------------------------------------------------------
	// Carga y pintado
	// ------------------------------------------------------------------

	cargar() {
		this.antes_de_cargar();
		return crm_tableros
			.llamar(this.opciones.metodo, this.args(), { mensaje: this.opciones.mensaje_carga || __("Calculando tablero…") })
			.then((d) => {
				this.datos = d;
				this.estado.mes = d.mes;
				this.estado.establecimiento = d.establecimiento;
				this.page.set_title(d.tablero_titulo || this.opciones.titulo);
				this.pintar();
				if (!d.mensaje) this.despues_de_cargar(d);
			});
	}

	pintar() {
		const d = this.datos;
		if (d.mensaje) {
			this.$body.html(`
				${this.html_encabezado()}
				<div class="crm-vacio-total"><h2>${this.e(d.titulo)}</h2><p>${this.e(d.mensaje)}</p></div>`);
			return;
		}
		this.$body.html(this.html_encabezado() + this.html_contenido());
		this.despues_de_pintar();
	}

	html_encabezado() {
		const d = this.datos;
		const meses = (d.meses || [])
			.map((m) => `<option value="${this.e(m.valor)}" ${m.valor === d.mes ? "selected" : ""}>${this.e(m.etiqueta)}</option>`)
			.join("");
		const tiendas =
			d.es_jefe && d.establecimientos && d.establecimientos.length > 1
				? `<label class="crm-campo-inline">${__("Tienda")}
						<select class="crm-select" data-cambio="establecimiento">${d.establecimientos
							.map((x) => `<option ${x === d.establecimiento ? "selected" : ""}>${this.e(x)}</option>`)
							.join("")}</select></label>`
				: "";
		return `
			<div class="crm-encabezado">
				<div>
					<h1>${this.e(d.titulo)}</h1>
					<p>${this.e(this.subtitulo())}</p>
				</div>
				<div class="crm-encabezado-filtros">
					${tiendas}
					<label class="crm-campo-inline">${__("Mes")}<select class="crm-select" data-cambio="mes">${meses}</select></label>
				</div>
			</div>`;
	}

	subtitulo() {
		const d = this.datos;
		if (!d.subtitulo) return "";
		const corte = this.texto_corte();
		const sesion = d.es_jefe ? " · " + __("sesión: {0}", [d.nombre_usuario]) : "";
		return d.subtitulo + (corte ? " · " + corte : "") + sesion;
	}

	// Botones "Ver:" (Toda la tienda + cada asesor), solo para jefes.
	html_ver() {
		const d = this.datos;
		if (!d.es_jefe) return "";
		const opciones = [[null, __("Toda la tienda")]].concat(d.asesores.map((a) => [a.empleado, a.nombre]));
		return `
			<div role="group" aria-label="${__("Qué ver")}" class="crm-ver">
				<span class="crm-ver-label">${__("Ver:")}</span>
				${opciones
					.map(
						([v, label]) =>
							`<button type="button" class="crm-pildora" aria-pressed="${(d.asesor || null) === v}"
								data-accion="asesor" data-valor="${this.e(v || "")}">${this.e(label)}</button>`
					)
					.join("")}
			</div>`;
	}

	// ------------------------------------------------------------------
	// Eventos
	// ------------------------------------------------------------------

	enlazar_eventos_base() {
		this.$body.on("click", "button[data-accion]", (ev) => {
			ev.preventDefault();
			const $t = $(ev.currentTarget);
			const nombre = $t.attr("data-accion");
			if (nombre === "asesor") this.elegir_asesor($t.attr("data-valor"));
			else this.accion(nombre, $t);
		});
		this.$body.on("change", "[data-cambio]", (ev) => {
			const $t = $(ev.currentTarget);
			const clave = $t.attr("data-cambio");
			const valor = $t.val();
			if (clave === "mes") {
				this.estado.mes = valor || null;
				this.al_cambiar_alcance();
				this.cargar();
			} else if (clave === "establecimiento") {
				Object.assign(this.estado, { establecimiento: valor || null, asesor: null });
				this.al_cambiar_alcance();
				this.cargar();
			} else {
				this.cambio(clave, valor);
			}
		});
	}

	elegir_asesor(empleado) {
		this.estado.asesor = empleado || null;
		this.al_cambiar_alcance();
		this.cargar();
	}

	// ------------------------------------------------------------------
	// Puntos de extensión (cada tablero los redefine)
	// ------------------------------------------------------------------

	html_contenido() {
		return "";
	}

	despues_de_pintar() {}

	antes_de_cargar() {}

	despues_de_cargar() {}

	al_cambiar_alcance() {}

	accion() {}

	cambio() {}
};
