// Página CRM Proyectos (asesores de Plus, Proyectos y Retail juntos).
// Solo pinta lo que calcula el servidor y llama acciones.

const API_PROYECTOS = "crm_dashboard_v3.crm_tableros.proyectos.api.";

frappe.pages["crm-proyectos"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("CRM Proyectos"),
		single_column: true,
	});
	frappe.require("/assets/crm_dashboard_v3/js/crm_tableros/common.js", () => {
		wrapper.tablero = new TableroProyectos(page);
	});
};

frappe.pages["crm-proyectos"].on_page_show = function (wrapper) {
	// Al volver de un formulario (cotización, orden de venta) se recalcula todo.
	if (wrapper.tablero && wrapper.tablero.datos) {
		wrapper.tablero.cargar();
	}
};

class TableroProyectos {
	constructor(page) {
		this.page = page;
		this.estado = {
			vista: "embudo",
			mes: null,
			asesor: null,
			establecimiento: null,
			tipo: "",
			modelo: "",
			modo_consolidado: "",
			ver_cerradas: false,
			sel: null,
			tab: "datos",
			expandido: {},
			comision_abierta: false,
		};
		this.datos = null;
		this.consolidado = null;
		this.historico = null;
		this.op = null;
		this.crear_filtros();
		this.$body = $('<div class="crm-tablero"></div>').appendTo(this.page.main);
		this.enlazar_eventos();
		this.cargar();
	}

	// ------------------------------------------------------------------
	// Filtros de la barra superior
	// ------------------------------------------------------------------

	crear_filtros() {
		this.f_mes = this.page.add_field({
			fieldname: "mes",
			label: __("Mes"),
			fieldtype: "Select",
			change: () => {
				this.estado.mes = this.f_mes.get_value() || null;
				this.cargar();
			},
		});
		this.f_establecimiento = this.page.add_field({
			fieldname: "establecimiento",
			label: __("Establecimiento"),
			fieldtype: "Select",
			change: () => {
				this.estado.establecimiento = this.f_establecimiento.get_value() || null;
				this.estado.asesor = null;
				this.cargar();
			},
		});
		this.f_asesor = this.page.add_field({
			fieldname: "asesor",
			label: __("Ver"),
			fieldtype: "Select",
			change: () => this.elegir_asesor(this.f_asesor.get_value() || null),
		});
		$(this.f_establecimiento.wrapper).hide();
		$(this.f_asesor.wrapper).hide();
		this.page.set_secondary_action(__("Actualizar"), () => this.cargar(), "refresh");
	}

	actualizar_filtros() {
		const d = this.datos;
		this.poner_opciones(
			this.f_mes,
			d.meses.map((m) => ({ value: m.valor, label: m.etiqueta })),
			d.mes
		);
		const jefe = d.es_jefe;
		$(this.f_establecimiento.wrapper).toggle(jefe && d.establecimientos.length > 1);
		$(this.f_asesor.wrapper).toggle(jefe);
		if (jefe) {
			this.poner_opciones(
				this.f_establecimiento,
				d.establecimientos.map((e) => ({ value: e, label: e })),
				d.establecimiento
			);
			this.poner_opciones(
				this.f_asesor,
				[{ value: "", label: __("Toda la tienda") }].concat(
					d.asesores.map((a) => ({ value: a.empleado, label: a.nombre }))
				),
				d.asesor || ""
			);
		}
	}

	poner_opciones(control, opciones, valor) {
		control.df.options = opciones;
		control.refresh();
		// set_input no dispara "change": evita recargas en bucle.
		control.set_input(valor);
	}

	elegir_asesor(empleado) {
		this.estado.asesor = empleado;
		this.estado.sel = null;
		this.estado.comision_abierta = false;
		this.op = null;
		this.cargar();
	}

	// ------------------------------------------------------------------
	// Carga de datos
	// ------------------------------------------------------------------

	args() {
		const { mes, asesor, establecimiento } = this.estado;
		return { mes, asesor, establecimiento };
	}

	cargar() {
		this.consolidado = null;
		this.historico = null;
		return crm_tableros
			.llamar(API_PROYECTOS + "get_tablero", this.args(), { mensaje: __("Calculando tablero…") })
			.then((d) => {
				this.datos = d;
				this.estado.mes = d.mes;
				this.estado.establecimiento = d.establecimiento;
				this.actualizar_filtros();
				this.page.set_title(d.titulo || __("CRM Proyectos"));
				this.pintar();
				if (d.mensaje) return;
				if (this.estado.sel) this.cargar_oportunidad(this.estado.sel, false);
				if (this.estado.vista === "consolidado") this.cargar_consolidado();
				else this.cargar_historico();
			});
	}

	cargar_historico() {
		return crm_tableros
			.llamar(API_PROYECTOS + "get_historico", this.args(), { freeze: false })
			.then((h) => {
				this.historico = h;
				this.$body.find(".crm-historico").html(this.html_historico());
			});
	}

	cargar_consolidado() {
		return crm_tableros
			.llamar(API_PROYECTOS + "get_consolidado", this.args(), { mensaje: __("Calculando consolidado…") })
			.then((c) => {
				this.consolidado = c;
				this.$body.find(".crm-consolidado").html(this.html_consolidado());
			});
	}

	cargar_oportunidad(nombre, cambiar_tab = true, tab = "datos", pagina = 0) {
		return crm_tableros
			.llamar(API_PROYECTOS + "get_oportunidad", { nombre, pagina_historial: pagina }, { freeze: false })
			.then((op) => {
				this.op = op;
				this.estado.sel = nombre;
				if (cambiar_tab) this.estado.tab = tab;
				this.pintar_lateral();
				this.marcar_tarjeta();
			});
	}

	refrescar_tras_accion(mensaje) {
		if (mensaje) frappe.show_alert({ message: mensaje, indicator: "green" });
		return this.cargar();
	}

	// ------------------------------------------------------------------
	// Pintado general
	// ------------------------------------------------------------------

	dinero(monto) {
		return crm_tableros.dinero(monto, this.datos.moneda);
	}

	// "Proyectos y Retail" a partir de los modelos que manda el servidor.
	texto_modelos() {
		return this.datos.modelos.join(__(" y "));
	}

	pintar() {
		const d = this.datos;
		const e = crm_tableros.esc;
		if (d.mensaje) {
			this.$body.html(`
				<div class="crm-vacio">
					<p class="crm-vacio-titulo">${e(d.titulo)}</p>
					<p>${e(d.mensaje)}</p>
				</div>`);
			return;
		}
		const vistas = [
			["embudo", __("Embudo · {0}", [this.texto_modelos()])],
			["consolidado", __("Consolidado por asesor · {0}", [this.texto_modelos()])],
		]
			.map(
				([k, label]) =>
					`<button class="crm-vista ${this.estado.vista === k ? "crm-vista-on" : ""}" data-accion="vista"
						data-vista="${k}" aria-pressed="${this.estado.vista === k}">${e(label)}</button>`
			)
			.join("");
		this.$body.html(`
			<p class="crm-subtitulo">${e(d.subtitulo)}</p>
			<nav class="crm-vistas">${vistas}</nav>
			${this.estado.vista === "consolidado" ? this.html_vista_consolidado() : this.html_vista_embudo()}`);
		if (this.estado.vista !== "consolidado") this.pintar_lateral();
	}

	html_vista_embudo() {
		return `
			<section class="crm-kpis">${this.html_kpis()}</section>
			${this.datos.resumen ? this.html_resumen() : ""}
			${this.html_incoherentes()}
			<div class="crm-principal">
				<section class="crm-embudo" aria-label="${__("Embudo")}">${this.html_embudo()}</section>
				<aside class="crm-lateral"></aside>
			</div>
			<section class="crm-historico">${this.historico ? this.html_historico() : this.html_cargando()}</section>`;
	}

	html_vista_consolidado() {
		return `<section class="crm-consolidado">${
			this.consolidado ? this.html_consolidado() : this.html_cargando()
		}</section>`;
	}

	html_cargando() {
		return `<p class="crm-ayuda">${__("Cargando…")}</p>`;
	}

	// ------------------------------------------------------------------
	// Indicadores
	// ------------------------------------------------------------------

	html_kpis() {
		const k = this.datos.kpis;
		const e = crm_tableros.esc;
		const avance = Math.min(100, k.meta.porcentaje);
		const etiqueta_meta = this.datos.asesor || !this.datos.es_jefe
			? __("Facturado vs meta del mes")
			: __("Facturado vs meta de la tienda");
		const desglose = this.datos.modelos
			.map((m) => {
				const x = k.meta.por_modelo[m] || { meta: 0, facturado: 0 };
				return __("{0}: {1} de {2}", [m, this.dinero(x.facturado), this.dinero(x.meta)]);
			})
			.join(" · ");
		const pr = k.pronostico;
		const aviso = pr.sin_fecha
			? `<button class="crm-link crm-aviso" data-accion="lista" data-doctype="Opportunity" data-nombres="sin_fecha">
					<span class="crm-pill crm-pill-amarillo">${__("Faltan fechas")}</span>
					${e(__("{0} de {1} sin fecha estimada de aprobación: no entran al mes", [pr.sin_fecha, pr.activas]))}
				</button>`
			: `<span class="crm-ok">${__("Todas tienen fecha estimada de aprobación")} (${pr.con_fecha})</span>`;
		return `
			<div class="crm-kpi crm-kpi-meta">
				<div class="crm-kpi-titulo">${e(etiqueta_meta)} · ${e(this.texto_modelos())}</div>
				<button class="crm-link crm-kpi-valor" data-accion="lista" data-doctype="Sales Invoice" data-nombres="facturas">
					${e(this.dinero(k.meta.facturado))}
				</button>
				<span class="crm-kpi-de">${__("de")} ${e(this.dinero(k.meta.meta))}</span>
				${crm_tableros.semaforo(k.meta.ritmo, k.meta.ritmo.texto)}
				<div class="crm-barra" role="img"
					aria-label="${e(__("{0}% de la meta; ritmo esperado {1}%", [k.meta.porcentaje, k.meta.ritmo_esperado]))}">
					<div class="crm-barra-avance" style="width:${avance}%"></div>
					<div class="crm-barra-ritmo" style="left:${k.meta.ritmo_esperado}%"></div>
				</div>
				<div class="crm-kpi-sub">
					${e(__("{0}% de la meta · {1} · la línea es el ritmo esperado hoy ({2}%)", [
						k.meta.porcentaje,
						crm_tableros.plural(k.meta.facturas.length, __("factura"), __("facturas")),
						k.meta.ritmo_esperado,
					]))}
				</div>
				<div class="crm-kpi-sub crm-ayuda">${e(desglose)}</div>
			</div>
			<div class="crm-kpi">
				<div class="crm-kpi-titulo">${e(__("Pronóstico de {0} · {1}", [this.datos.etiqueta_mes, this.texto_modelos()]))}</div>
				<button class="crm-link crm-kpi-valor" data-accion="lista" data-doctype="Opportunity" data-nombres="pronostico_mes">
					${e(this.dinero(pr.mes))}
				</button>
				<div class="crm-kpi-sub">
					<button class="crm-link" data-accion="lista" data-doctype="Opportunity" data-nombres="pronostico_total">
						${e(__("Todo el embudo: {0} ponderado", [this.dinero(pr.total)]))}
					</button>
				</div>
				<div class="crm-kpi-sub">${aviso}</div>
			</div>
			<div class="crm-kpi">
				<div class="crm-kpi-titulo">${__("Propuestas vigentes")}</div>
				<button class="crm-link crm-kpi-valor" data-accion="lista" data-doctype="Opportunity" data-nombres="vigentes">
					${e(this.dinero(k.vigentes.monto))}
				</button>
				<div class="crm-kpi-sub">${e(__("{0} en propuesta enviada o negociación", [k.vigentes.cantidad]))}</div>
			</div>
			<div class="crm-kpi">
				<div class="crm-kpi-titulo">${__("Propuestas vencidas")}</div>
				<button class="crm-link crm-kpi-valor crm-rojo" data-accion="lista" data-doctype="Quotation" data-nombres="vencidas">
					${e(this.dinero(k.vencidas.monto))}
				</button>
				<div class="crm-kpi-sub">${e(__("{0} por renovar o perder", [k.vencidas.cantidad]))}</div>
			</div>`;
	}

	// Mapa de "data-nombres" -> nombres de registros que forman cada número.
	nombres_de(clave, fila) {
		const k = this.datos.kpis;
		if (fila) {
			const r = fila === "total" ? this.datos.resumen.total : this.datos.resumen.filas[Number(fila)];
			return {
				facturas: r.meta.facturas,
				activas: r.activas.nombres,
				vencidas: r.vencidas.nombres,
				sin_actividad: r.sin_actividad.nombres,
				escalar: r.escalar.nombres,
				incoherentes: r.incoherentes.nombres,
			}[clave];
		}
		if (clave.startsWith("columna:")) {
			const col = this.todas_las_columnas().find((c) => c.clave === clave.slice(8));
			return col ? this.tarjetas_visibles(col).map((t) => t.name) : [];
		}
		if (clave.startsWith("grupo:")) {
			const g = this.datos.mi_dia.find((x) => x.clave === clave.slice(6));
			return g ? g.nombres : [];
		}
		if (clave.startsWith("hist:")) {
			const [, campo, i] = clave.split(":");
			return this.historico.meses[Number(i)][campo];
		}
		if (clave.startsWith("estado:")) {
			return this.historico.mes_actual.por_estado[clave.slice(7)].nombres;
		}
		if (clave.startsWith("cons:")) {
			const [, i, modelo, campo] = clave.split(":");
			const col = this.consolidado.tarjetas[Number(i)].columnas[modelo];
			return campo === "facturas" ? col.facturas : col[campo].nombres;
		}
		return (
			{
				facturas: k.meta.facturas,
				pronostico_mes: k.pronostico.nombres_mes,
				pronostico_total: k.pronostico.nombres_total,
				sin_fecha: k.pronostico.nombres_sin_fecha,
				vigentes: k.vigentes.nombres,
				vencidas: k.vencidas.nombres,
				incoherentes: this.datos.incoherentes.nombres,
			}[clave] || []
		);
	}

	html_resumen() {
		const e = crm_tableros.esc;
		const r = this.datos.resumen;
		const celda = (n, clave, fila, tono) =>
			`<td class="crm-num"><button class="crm-link ${n ? tono : "crm-verde"}" data-accion="lista"
				data-doctype="${clave === "vencidas" ? "Quotation" : clave === "facturas" ? "Sales Invoice" : "Opportunity"}"
				data-nombres="${clave}" data-fila="${fila}">${e(n)}</button></td>`;
		const fila = (x, i, total) => `
			<tr class="${total ? "crm-fila-total" : ""}">
				<th scope="row">${
					total
						? e(x.nombre)
						: `<button class="crm-link" data-accion="asesor" data-empleado="${e(x.empleado)}">${e(x.nombre)}</button>`
				}</th>
				<td class="crm-num"><button class="crm-link" data-accion="lista" data-doctype="Sales Invoice"
					data-nombres="facturas" data-fila="${i}">${e(this.dinero(x.meta.facturado))} · ${e(x.meta.porcentaje)}%</button></td>
				<td>${crm_tableros.semaforo(x.meta.ritmo, x.meta.ritmo.texto)}</td>
				<td class="crm-num"><button class="crm-link" data-accion="lista" data-doctype="Opportunity"
					data-nombres="activas" data-fila="${i}">${e(x.activas.cantidad)} · ${e(this.dinero(x.activas.monto))}</button></td>
				<td class="crm-num">${e(this.dinero(x.pronostico))}</td>
				<td class="crm-num"><button class="crm-link" data-accion="lista" data-doctype="Quotation"
					data-nombres="vencidas" data-fila="${i}">${e(x.vencidas.cantidad)} · ${e(this.dinero(x.vencidas.monto))}</button></td>
				${celda(x.sin_actividad.cantidad, "sin_actividad", i, "crm-ambar")}
				${celda(x.escalar.cantidad, "escalar", i, "crm-rojo")}
				${celda(x.incoherentes.cantidad, "incoherentes", i, "crm-ambar")}
			</tr>`;
		return `
			<section class="crm-resumen">
				<div class="crm-seccion-titulo">
					<h3>${__("Resumen por asesor")}</h3>
					<span class="crm-ayuda">${__("Toca un nombre para ver solo su información")}</span>
				</div>
				<p class="crm-ayuda">${__(
					"Etapa ≠ status: oportunidades con etapa Ganada o Perdida pero status abierto. No aparecen en el embudo y hay que corregirlas."
				)}</p>
				<div class="crm-tabla-scroll">
					<table class="crm-tabla">
						<thead><tr>
							<th>${__("Asesor")}</th><th>${__("Facturado vs meta")}</th><th>${__("Estado")}</th>
							<th>${__("Embudo activo")}</th><th>${__("Pronóstico")}</th><th>${__("Vencidas")}</th>
							<th>${e(__("Sin actividad +{0} d", [this.datos.dias_verde_max]))}</th><th>${__("Escalar")}</th><th>${__("Etapa ≠ status")}</th>
						</tr></thead>
						<tbody>
							${r.filas.map((x, i) => fila(x, i, false)).join("")}
							${fila(r.total, "total", true)}
						</tbody>
					</table>
				</div>
			</section>`;
	}

	html_incoherentes() {
		const inc = this.datos.incoherentes;
		if (!inc.cantidad || this.datos.resumen) return "";
		return `
			<div class="crm-alerta">
				${crm_tableros.semaforo({ clave: "amarillo", texto: __("Amarillo") }, __("Etapa ≠ status"))}
				<button class="crm-link" data-accion="lista" data-doctype="Opportunity" data-nombres="incoherentes">
					${crm_tableros.esc(
						__("{0} con etapa Ganada o Perdida pero status abierto: no aparecen en el embudo, corrígelas.", [
							crm_tableros.plural(inc.cantidad, __("oportunidad"), __("oportunidades")),
						])
					)}
				</button>
			</div>`;
	}

	// ------------------------------------------------------------------
	// Embudo
	// ------------------------------------------------------------------

	todas_las_columnas() {
		return this.datos.columnas.concat(this.datos.cerradas);
	}

	tarjetas_visibles(col) {
		const { tipo, modelo } = this.estado;
		return col.tarjetas.filter((t) => (!tipo || t.tipo === tipo) && (!modelo || t.modelo === modelo));
	}

	html_chips(accion, opciones, valor) {
		const e = crm_tableros.esc;
		return opciones
			.map(
				([v, label]) =>
					`<button class="crm-chip-filtro ${valor === v ? "crm-chip-filtro-on" : ""}" data-accion="${accion}"
						data-valor="${e(v)}" aria-pressed="${valor === v}">${e(label)}</button>`
			)
			.join("");
	}

	opciones_modelo() {
		return [["", this.texto_modelos()]].concat(this.datos.modelos.map((m) => [m, __("Solo {0}", [m])]));
	}

	html_embudo() {
		const e = crm_tableros.esc;
		const d = this.datos;
		const total_cerradas = d.cerradas.reduce((s, c) => s + this.tarjetas_visibles(c).length, 0);
		const opciones_tipo = [`<option value="">${__("Todos")}</option>`]
			.concat(d.tipos.map((t) => `<option value="${e(t)}" ${this.estado.tipo === t ? "selected" : ""}>${e(t)}</option>`))
			.join("");
		return `
			<div class="crm-seccion-titulo">
				<h3>${__("Embudo")}</h3>
				<span class="crm-ayuda">${__("Toca una tarjeta para abrirla")}</span>
			</div>
			<div class="crm-embudo-filtros">
				<span class="crm-chips" role="group" aria-label="${__("Modelo")}">
					${this.html_chips("filtro-modelo", this.opciones_modelo(), this.estado.modelo)}
				</span>
				<label>${__("Tipo")}
					<select class="form-control input-xs" data-accion="filtro-tipo">${opciones_tipo}</select>
				</label>
				<button class="btn btn-default btn-xs" data-accion="toggle-cerradas" aria-expanded="${this.estado.ver_cerradas}">
					${e((this.estado.ver_cerradas ? __("Ocultar") : __("Ver")) + " " + __("en pausa y cerradas ({0})", [total_cerradas]))}
				</button>
			</div>
			<p class="crm-ayuda crm-leyenda">
				${__("Días sin moverse:")}
				${crm_tableros.semaforo({ clave: "verde", texto: __("Verde") }, __("hasta {0} · Verde", [d.dias_verde_max]))}
				${crm_tableros.semaforo(
					{ clave: "amarillo", texto: __("Amarillo") },
					__("{0} a {1} · Amarillo", [d.dias_verde_max + 1, d.dias_amarillo_max])
				)}
				${crm_tableros.semaforo({ clave: "rojo", texto: __("Rojo") }, __("más de {0} · Rojo", [d.dias_amarillo_max]))}
				· ${__("Próximo paso en rojo si no hay o si ya pasó · «Para entrar» = lo que exige cada etapa.")}
			</p>
			<div class="crm-columnas">${d.columnas.map((c) => this.html_columna(c, true)).join("")}</div>
			${
				this.estado.ver_cerradas
					? `<div class="crm-seccion-titulo"><h4>${__("En pausa y cerradas del mes")}</h4>
						<span class="crm-ayuda">${__("No suman al pronóstico")}</span></div>
						<div class="crm-columnas crm-columnas-cerradas">${d.cerradas
							.map((c) => this.html_columna(c, false))
							.join("")}</div>`
					: ""
			}`;
	}

	html_columna(col, activa) {
		const e = crm_tableros.esc;
		const tarjetas = this.tarjetas_visibles(col);
		const total = tarjetas.reduce((s, t) => s + t.monto, 0);
		const prob = col.probabilidad == null ? "" : ` · ${col.probabilidad}%`;
		return `
			<div class="crm-columna crm-columna-${e(col.clave)}">
				<div class="crm-columna-cabecera">
					<div class="crm-columna-titulo">${e(col.titulo)}${e(prob)}</div>
					<button class="crm-link crm-columna-total" data-accion="lista" data-doctype="Opportunity"
						data-nombres="columna:${e(col.clave)}">
						${e(crm_tableros.plural(tarjetas.length, __("oportunidad"), __("oportunidades")))} · ${e(this.dinero(total))}
					</button>
					${activa ? `<div class="crm-ayuda">${e(__("Para entrar: {0}", [col.requisitos]))}</div>` : ""}
				</div>
				${tarjetas.length ? tarjetas.map((t) => this.html_tarjeta(t, activa)).join("") : `<p class="crm-ayuda">${__("Sin oportunidades")}</p>`}
			</div>`;
	}

	html_tarjeta(t, activa) {
		const e = crm_tableros.esc;
		const p = t.proximo;
		const prox_texto =
			p.estado === "vacio"
				? __("Sin próximo paso")
				: (p.estado === "vencido" ? __("Vencido:") + " " : "") + p.texto + " · " + crm_tableros.fecha(p.fecha);
		const quien = [t.modelo !== this.datos.modelos[0] ? t.modelo : "", t.asesor].filter(Boolean).join(" · ");
		return `
			<button class="crm-tarjeta ${this.estado.sel === t.name ? "crm-tarjeta-sel" : ""}" data-accion="abrir" data-name="${e(t.name)}">
				<span class="crm-tarjeta-fila">
					<span class="crm-tarjeta-cliente">${e(t.cliente)}</span>
					${activa ? crm_tableros.semaforo(t.semaforo, __("{0} d", [t.dias])) : ""}
				</span>
				<span class="crm-tarjeta-fila crm-tarjeta-sub">
					<span>${t.monto > 0 ? e(this.dinero(t.monto)) : __("Sin monto")}</span>
					<span class="crm-modelo-${e(frappe.scrub(t.modelo || ""))}">${e(quien || t.tipo || "")}</span>
				</span>
				${
					activa
						? `<span class="crm-tarjeta-prox ${p.estado === "ok" ? "" : "crm-rojo"}">${e(prox_texto)}</span>`
						: `<span class="crm-tarjeta-prox">${e(t.extra || t.etapa)}</span>`
				}
			</button>`;
	}

	marcar_tarjeta() {
		this.$body.find(".crm-tarjeta").removeClass("crm-tarjeta-sel");
		this.$body.find(`.crm-tarjeta[data-name="${CSS.escape(this.estado.sel || "")}"]`).addClass("crm-tarjeta-sel");
	}

	repintar_embudo() {
		this.$body.find(".crm-embudo").html(this.html_embudo());
		this.marcar_tarjeta();
	}

	// ------------------------------------------------------------------
	// Oportunidades por estado e histórico (barras con su valor en texto)
	// ------------------------------------------------------------------

	html_historico() {
		const h = this.historico;
		if (!h || h.mensaje) return "";
		const e = crm_tableros.esc;
		const actual = h.mes_actual;
		const segmentos = h.estados
			.map((s) => {
				const n = actual.por_estado[s.clave].cantidad;
				const pct = actual.total ? Math.round((n / actual.total) * 100) : 0;
				return { ...s, n, pct };
			});
		const barra = segmentos
			.map((s) => `<span class="crm-seg crm-estado-${e(s.clave)}" style="width:${s.pct}%"></span>`)
			.join("");
		const leyenda = segmentos
			.map(
				(s) => `
				<button class="crm-link crm-leyenda-item" data-accion="lista" data-doctype="Opportunity" data-nombres="estado:${e(s.clave)}">
					<span class="crm-punto crm-estado-${e(s.clave)}"></span>${e(s.titulo)} · <strong>${e(s.n)}</strong> · ${e(s.pct)}%
				</button>`
			)
			.join("");
		const quien = this.datos.asesor || !this.datos.es_jefe ? this.nombre_alcance() : __("Toda la tienda");
		const grafica = (titulo, sub, campo_valor, campo_nombres, doctype, formato, apilada) => {
			const valores = h.meses.map((m) =>
				apilada ? Object.values(m.oportunidades).reduce((a, b) => a + b, 0) : m[campo_valor]
			);
			const max = Math.max(1, ...valores);
			const cols = h.meses
				.map((m, i) => {
					const alto = Math.round((valores[i] / max) * 100);
					const segs = apilada
						? h.estados
								.slice()
								.reverse()
								.map((s) => {
									const v = m.oportunidades[s.clave];
									return `<span class="crm-seg-v crm-estado-${e(s.clave)}" style="height:${valores[i] ? (v / valores[i]) * 100 : 0}%"
										title="${e(s.titulo)} ${e(v)}"></span>`;
								})
								.join("")
						: `<span class="crm-seg-v crm-estado-${e(campo_valor)}" style="height:100%"></span>`;
					return `
						<button class="crm-col-graf" data-accion="lista" data-doctype="${doctype}" data-nombres="hist:${campo_nombres}:${i}"
							aria-label="${e(m.etiqueta + ": " + formato(valores[i]))}">
							<span class="crm-col-valor">${e(formato(valores[i]))}</span>
							<span class="crm-col-barra" style="height:${alto}%">${segs}</span>
							<span class="crm-col-mes">${e(m.etiqueta)}</span>
						</button>`;
				})
				.join("");
			return `
				<div class="crm-grafica">
					<div class="crm-grafica-titulo">${e(titulo)}</div>
					<div class="crm-ayuda">${e(sub)}</div>
					<div class="crm-columnas-graf">${cols}</div>
				</div>`;
		};
		const compacto = (n) =>
			n >= 1000000 ? (n / 1000000).toFixed(1) + " M" : n >= 1000 ? Math.round(n / 1000) + "k" : String(Math.round(n));
		return `
			<div class="crm-panel crm-estados">
				<div class="crm-seccion-titulo">
					<h3>${e(__("Oportunidades por estado · {0}", [this.texto_modelos()]))}</h3>
					<span class="crm-ayuda">${e(__("{0} · creadas en {1} (al {2}) · {3} oportunidades", [
						quien,
						this.datos.etiqueta_mes,
						crm_tableros.fecha(h.dia_de_corte),
						actual.total,
					]))}</span>
				</div>
				<div class="crm-barra-estados" role="img" aria-label="${e(segmentos.map((s) => s.titulo + " " + s.n).join(", "))}">${barra}</div>
				<div class="crm-leyenda-estados">${leyenda}</div>
				<p class="crm-ayuda">${e(__("Tasa de cierre de los últimos {0} meses: {1} (ganadas ÷ ganadas + perdidas)", [
					h.meses.length,
					h.tasa_cierre == null ? "—" : h.tasa_cierre + "%",
				]))}</p>
			</div>
			<div class="crm-panel">
				<div class="crm-seccion-titulo">
					<h3>${e(__("Histórico · últimos {0} meses · {1}", [h.meses.length, this.texto_modelos()]))}</h3>
					<span class="crm-ayuda">${e(__("{0} · el mes en curso va al {1}. Toca una barra para ver sus registros.", [
						quien,
						crm_tableros.fecha(h.dia_de_corte),
					]))}</span>
				</div>
				<div class="crm-graficas">
					${grafica(__("Oportunidades creadas"), __("por mes, según su estado actual"), null, "nombres_oportunidades", "Opportunity", String, true)}
					${grafica(__("Monto cotizado"), __("cotizaciones enviadas por mes, sin IVA"), "cotizado", "nombres_cotizado", "Quotation", compacto, false)}
					${grafica(__("Venta facturada"), __("Sales Person de Proyectos + Retail"), "facturado", "nombres_facturado", "Sales Invoice", compacto, false)}
				</div>
			</div>`;
	}

	nombre_alcance() {
		if (!this.datos.es_jefe) return this.datos.nombre_usuario;
		const a = this.datos.asesores.find((x) => x.empleado === this.datos.asesor);
		return a ? a.nombre : "";
	}

	// ------------------------------------------------------------------
	// Consolidado por asesor
	// ------------------------------------------------------------------

	html_consolidado() {
		const c = this.consolidado;
		if (!c || c.mensaje) return "";
		const e = crm_tableros.esc;
		const modos = [["", __("{0} (separados)", [this.texto_modelos()])]].concat(
			c.modelos.map((m) => [m, __("Solo {0}", [m])])
		);
		const nota = c.vista_tienda
			? __("Resumen de la tienda. Toca «Ver como lo ve…» en la tarjeta de un asesor para abrir su consolidado con sus documentos y el cálculo de comisión factura por factura.")
			: __("Toca un monto subrayado para ver sus documentos vinculados. Facturado = facturas del mes atribuidas por la tabla Comisiones Asesor de su orden de venta (o creadas por el asesor sin orden), no por el Sales Team. Montos sin IVA.");
		return `
			<div class="crm-embudo-filtros">
				<span class="crm-chips" role="group" aria-label="${__("Modelo")}">
					${this.html_chips("modo-consolidado", modos, this.estado.modo_consolidado)}
				</span>
			</div>
			<p class="crm-ayuda">${e(nota)}</p>
			<div class="crm-tarjetas-cons">${c.tarjetas.map((t, i) => this.html_tarjeta_cons(t, i)).join("")}</div>`;
	}

	claves_consolidado() {
		const c = this.consolidado;
		return this.estado.modo_consolidado ? [this.estado.modo_consolidado] : c.modelos.concat([c.total]);
	}

	html_tarjeta_cons(t, i) {
		const e = crm_tableros.esc;
		const c = this.consolidado;
		const claves = this.claves_consolidado();
		const compacta = c.vista_tienda;
		const valor = (modelo, campo, texto, sub, doc) => {
			const contenido = `${e(texto)}${sub ? `<span class="crm-ayuda crm-sub">${e(sub)}</span>` : ""}`;
			if (!campo) return `<td class="crm-num">${contenido}</td>`;
			const accion = compacta ? "lista" : "documentos";
			return `<td class="crm-num"><button class="crm-link" data-accion="${accion}" data-doctype="${doc}"
				data-nombres="cons:${i}:${e(modelo)}:${campo}" data-tarjeta="${i}" data-modelo="${e(modelo)}"
				data-tipo="${campo}">${contenido}</button></td>`;
		};
		const filas = [
			[__("Meta del mes"), (m, x) => valor(m, null, this.dinero(x.meta))],
			[
				__("Facturado"),
				(m, x) =>
					valor(m, "facturas", this.dinero(x.facturado), __("{0} · {1}%", [
						crm_tableros.plural(x.facturas.length, __("factura"), __("facturas")),
						x.porcentaje,
					]), "Sales Invoice"),
			],
			[
				__("Órdenes de venta del mes"),
				(m, x) =>
					valor(m, "ordenes", this.dinero(x.ordenes.monto),
						crm_tableros.plural(x.ordenes.nombres.length, __("orden"), __("órdenes")), "Sales Order"),
			],
			[
				__("Cotizado en el mes"),
				(m, x) =>
					valor(m, "cotizado", this.dinero(x.cotizado.monto),
						crm_tableros.plural(x.cotizado.nombres.length, __("cotización"), __("cotizaciones")), "Quotation"),
			],
			[
				__("Cotizaciones vigentes"),
				(m, x) =>
					valor(m, "vigentes", this.dinero(x.vigentes.monto),
						crm_tableros.plural(x.vigentes.nombres.length, __("abierta"), __("abiertas")), "Quotation"),
			],
			[
				__("Oportunidades abiertas"),
				(m, x) =>
					`<td class="crm-num"><button class="crm-link" data-accion="lista" data-doctype="Opportunity"
						data-nombres="cons:${i}:${e(m)}:abiertas">${e(x.abiertas.cantidad)}</button></td>`,
			],
			[
				__("Oportunidades creadas en {0}", [this.datos.etiqueta_mes]),
				(m, x) =>
					`<td class="crm-num"><button class="crm-link" data-accion="lista" data-doctype="Opportunity"
						data-nombres="cons:${i}:${e(m)}:creadas">${e(x.creadas.cantidad)}<span class="crm-ayuda crm-sub">${e(
							__("{0} ganadas · {1} perdidas", [x.creadas.ganadas, x.creadas.perdidas])
						)}</span></button></td>`,
			],
		];
		const tabla = `
			<div class="crm-tabla-scroll">
				<table class="crm-tabla crm-tabla-cons">
					<thead><tr><th>${__("Indicador")}</th>${claves
						.map((k) => `<th class="crm-num crm-modelo-${e(frappe.scrub(k))}">${e(k)}</th>`)
						.join("")}</tr></thead>
					<tbody>${filas
						.map(([label, celda]) => `<tr><th scope="row">${e(label)}</th>${claves.map((k) => celda(k, t.columnas[k])).join("")}</tr>`)
						.join("")}</tbody>
				</table>
			</div>`;
		const pie = compacta && !t.es_tienda
			? `<button class="btn btn-default btn-xs" data-accion="asesor" data-empleado="${e(t.empleado)}">${e(
					__("Ver como lo ve {0} →", [t.nombre])
				)}</button>`
			: "";
		return `
			<article class="crm-tarjeta-cons ${t.es_tienda ? "crm-tarjeta-cons-tienda" : ""}">
				<header class="crm-seccion-titulo">
					<h3>${e(t.nombre)}</h3>
					${crm_tableros.semaforo(t.estado, t.estado.texto)}
				</header>
				${tabla}
				${this.html_barras_cons(t)}
				${t.comision ? this.html_comision(t) : ""}
				${pie}
			</article>`;
	}

	html_barras_cons(t) {
		const e = crm_tableros.esc;
		const modelos = this.estado.modo_consolidado ? [this.estado.modo_consolidado] : this.consolidado.modelos;
		const totales = t.barras.map((b) => modelos.reduce((s, m) => s + (b.por_modelo[m] || 0), 0));
		const max = Math.max(1, ...totales);
		const compacto = (n) =>
			n >= 1000000 ? (n / 1000000).toFixed(1) + " M" : n >= 1000 ? Math.round(n / 1000) + "k" : String(Math.round(n));
		const cols = t.barras
			.map((b, i) => {
				const segs = modelos
					.slice()
					.reverse()
					.map((m) => {
						const v = b.por_modelo[m] || 0;
						return `<span class="crm-seg-v crm-modelo-bg-${e(frappe.scrub(m))}" style="height:${totales[i] ? (v / totales[i]) * 100 : 0}%"
							title="${e(m + ": " + this.dinero(v))}"></span>`;
					})
					.join("");
				const detalle = modelos.map((m) => m + " " + this.dinero(b.por_modelo[m] || 0)).join(" · ");
				return `
					<div class="crm-col-graf" role="img" aria-label="${e(b.etiqueta + ": " + detalle)}" title="${e(detalle)}">
						<span class="crm-col-valor">${e(compacto(totales[i]))}</span>
						<span class="crm-col-barra crm-col-barra-baja" style="height:${Math.round((totales[i] / max) * 100)}%">${segs}</span>
						<span class="crm-col-mes">${e(b.etiqueta)}</span>
					</div>`;
			})
			.join("");
		const leyenda = modelos
			.map((m) => `<span><span class="crm-punto crm-modelo-bg-${e(frappe.scrub(m))}"></span>${e(m)}</span>`)
			.join(" ");
		return `
			<div class="crm-grafica crm-grafica-cons">
				<div class="crm-grafica-titulo">${e(__("Facturado por mes"))} <span class="crm-ayuda">${leyenda}</span></div>
				<div class="crm-columnas-graf">${cols}</div>
			</div>`;
	}

	html_comision(t) {
		const e = crm_tableros.esc;
		const claves = this.claves_consolidado();
		const r = t.comision.resumen;
		const tasa = (x) => (x.tasas.length ? x.tasas.map((v) => v + "%").join(" / ") : "—");
		const fila = (label, f, destacada) =>
			`<tr class="${destacada ? "crm-fila-total" : ""}"><th scope="row">${e(label)}</th>${claves
				.map((k) => `<td class="crm-num">${f(r[k])}</td>`)
				.join("")}</tr>`;
		const sub = (texto) => `<span class="crm-ayuda crm-sub">${e(texto)}</span>`;
		const resumen = `
			<div class="crm-tabla-scroll">
				<table class="crm-tabla crm-tabla-cons">
					<thead><tr><th>${e(__("Comisión · {0}", [this.datos.etiqueta_mes]))}</th>${claves
						.map((k) => `<th class="crm-num">${e(k)}</th>`)
						.join("")}</tr></thead>
					<tbody>
						${fila(__("Facturas atribuidas"), (x) => e(this.dinero(x.atribuido)) + sub(crm_tableros.plural(x.cantidad, __("factura"), __("facturas"))))}
						${fila(__("Cantidad cobrada"), (x) => e(this.dinero(x.cobrado)) + sub(__("{0}% de lo facturado", [x.atribuido ? Math.round((x.cobrado / x.atribuido) * 100) : 0])))}
						${fila(__("× commission_rate del Sales Person"), (x) => e(tasa(x)))}
						${fila(__("÷ 100 = Comisión"), (x) => e(this.dinero(x.comision)), true)}
						${fila(__("Comisión futura (cuando el cliente pague)"), (x) => e(this.dinero(x.futura)) + sub(__("saldo sin IVA {0}", [this.dinero(x.por_cobrar)])))}
					</tbody>
				</table>
			</div>`;
		const abierta = this.estado.comision_abierta;
		const filas = t.comision.filas.filter((f) => !this.estado.modo_consolidado || f.modelo === this.estado.modo_consolidado);
		const detalle = abierta
			? `
				<div class="crm-tabla-scroll">
					<table class="crm-tabla">
						<thead><tr>
							<th>${__("Factura")}</th><th>${__("Cliente")}</th><th>${__("Modelo")}</th>
							<th class="crm-num">${__("Neto")}</th><th class="crm-num">${__("Total")}</th><th class="crm-num">${__("Saldo")}</th>
							<th class="crm-num">${__("Cobrado")}</th><th class="crm-num">${__("Distribución")}</th><th class="crm-num">${__("Tasa")}</th>
							<th class="crm-num">${__("Comisión")}</th><th class="crm-num">${__("Comisión futura")}</th>
						</tr></thead>
						<tbody>${
							filas.length
								? filas
										.map(
											(f) => `
							<tr>
								<td><a href="/app/sales-invoice/${encodeURIComponent(f.factura)}">${e(f.factura)}</a>
									<span class="crm-ayuda crm-sub">${e(crm_tableros.fecha(f.fecha))}${
										f.nota_de_credito ? " · " + __("nota de crédito") : ""
									}${f.propia ? " · " + __("sin orden de venta") : ""}</span></td>
								<td>${e(f.cliente)}</td><td>${e(f.modelo)}</td>
								<td class="crm-num">${e(this.dinero(f.neto))}</td>
								<td class="crm-num">${e(this.dinero(f.gran_total))}</td>
								<td class="crm-num">${e(this.dinero(f.saldo))}</td>
								<td class="crm-num">${e(this.dinero(f.cobrado))}</td>
								<td class="crm-num">${e(f.distribucion)}%</td>
								<td class="crm-num">${e(f.tasa)}%</td>
								<td class="crm-num"><strong>${e(this.dinero(f.comision))}</strong></td>
								<td class="crm-num">${e(this.dinero(f.futura))}</td>
							</tr>`
										)
										.join("")
								: `<tr><td colspan="11" class="crm-ayuda">${__("Sin facturas en el mes.")}</td></tr>`
						}</tbody>
					</table>
				</div>`
			: "";
		return `
			<div class="crm-comision">
				${resumen}
				<p class="crm-ayuda">${__(
					"Por factura: cantidad cobrada × distribución × commission_rate ÷ 100. Cobrado = neto × (total − saldo) ÷ total, para quitar el IVA del saldo pendiente."
				)}</p>
				<button class="btn btn-default btn-xs" data-accion="toggle-comision" aria-expanded="${abierta}">
					${e(__("{0} el cálculo factura por factura ({1})", [abierta ? __("Ocultar") : __("Ver"), filas.length]))}
				</button>
				${detalle}
			</div>`;
	}

	// Documentos vinculados: oportunidad → cotización → orden de venta → factura.
	mostrar_documentos(i, modelo, tipo) {
		const e = crm_tableros.esc;
		const c = this.consolidado;
		const t = c.tarjetas[Number(i)];
		const docs = t.documentos;
		const lista = {
			facturas: docs.facturas,
			ordenes: docs.ordenes,
			cotizado: docs.cotizaciones_mes,
			vigentes: docs.cotizaciones_vigentes,
		}[tipo];
		const titulos = {
			facturas: __("Facturas"),
			ordenes: __("Órdenes de venta"),
			cotizado: __("Cotizaciones del mes"),
			vigentes: __("Cotizaciones vigentes"),
		};
		const ayudas = {
			facturas: __("Facturas del mes atribuidas por la tabla Comisiones Asesor de su orden de venta (con su % de distribución), más las que el asesor creó sin orden. Son las que cuentan para la meta."),
			ordenes: __("Órdenes de venta del mes por su modelo de venta. Cuentan para la meta cuando se facturan."),
			cotizado: __("Cotizaciones enviadas en el mes, con su estado actual y la oportunidad de la que vienen."),
			vigentes: __("Cotizaciones abiertas y vigentes hoy: lo que todavía puede convertirse en orden."),
		};
		const ruta = { op: "opportunity", qt: "quotation", so: "sales-order", inv: "sales-invoice" };
		const chip = (nombre, tipo_doc) =>
			nombre
				? `<a class="crm-doc crm-doc-${tipo_doc}" href="/app/${ruta[tipo_doc]}/${encodeURIComponent(nombre)}">${e(nombre)}</a>`
				: "";
		const doc_tipo = { facturas: "inv", ordenes: "so", cotizado: "qt", vigentes: "qt" }[tipo];
		const estados_cot = { Open: __("Abierta"), Expired: __("Vencida"), Ordered: __("Con orden de venta"), Lost: __("Perdida") };
		const fila = (x) => {
			let enlaces = "";
			let estado = "";
			let nota = "";
			if (tipo === "facturas") {
				enlaces = chip(x.oportunidad, "op") + chip(x.cotizacion, "qt") + chip(x.orden, "so");
				estado = __("Cuenta para la meta");
				nota = x.propia
					? __("Sin orden de venta: la creó el asesor")
					: __("Orden de venta {0}", [x.modelo]) + (x.distribucion !== 100 ? " · " + __("{0}% de distribución", [x.distribucion]) : "");
				if (!x.oportunidad) nota += " · " + __("sin oportunidad");
			} else if (tipo === "ordenes") {
				enlaces = chip(x.oportunidad, "op") + chip(x.cotizacion, "qt") + x.facturas.map((f) => chip(f, "inv")).join("");
				estado = x.facturado >= 100 ? __("Facturada 100%") : x.facturado > 0 ? __("Facturada {0}%", [Math.round(x.facturado)]) : __("Sin facturar");
				nota = x.oportunidad ? "" : __("Sin oportunidad ni cotización ligada");
			} else {
				enlaces = chip(x.oportunidad, "op");
				estado = estados_cot[x.status] || x.status;
				nota = x.oportunidad ? "" : __("Sin oportunidad");
			}
			return `
				<tr>
					<td>${chip(x.name, doc_tipo)}</td>
					<td>${e(crm_tableros.fecha(x.fecha))}</td>
					<td>${e(x.cliente)}</td>
					<td class="crm-num">${e(this.dinero(x.monto))}</td>
					<td class="crm-enlaces">${enlaces || "—"}</td>
					<td>${e(estado)}${nota ? `<span class="crm-ayuda crm-sub">${e(nota)}</span>` : ""}</td>
				</tr>`;
		};
		const grupos = (modelo === c.total ? c.modelos : [modelo])
			.map((m) => {
				const filas = lista.filter((x) => x.modelo === m).sort((a, b) => b.monto - a.monto);
				const total = filas.reduce((s, x) => s + x.monto, 0);
				return `
					<tr class="crm-grupo-docs crm-modelo-${e(frappe.scrub(m))}"><th colspan="6">${e(m)} · ${e(
						crm_tableros.plural(filas.length, __("documento"), __("documentos"))
					)} · ${e(this.dinero(total))}</th></tr>
					${filas.length ? filas.map(fila).join("") : `<tr><td colspan="6" class="crm-ayuda">${e(__("Sin documentos de {0}.", [m]))}</td></tr>`}`;
			})
			.join("");
		const d = new frappe.ui.Dialog({
			title: __("Documentos vinculados · {0} · {1}", [t.nombre, titulos[tipo]]),
			size: "extra-large",
			fields: [{ fieldtype: "HTML", fieldname: "docs" }],
		});
		d.fields_dict.docs.$wrapper.html(`
			<div class="crm-tablero">
				<p class="crm-ayuda">${e(ayudas[tipo])} ${e(__("Montos sin IVA."))}</p>
				<div class="crm-tabla-scroll">
					<table class="crm-tabla">
						<thead><tr>
							<th>${__("Documento")}</th><th>${__("Fecha")}</th><th>${__("Cliente")}</th>
							<th class="crm-num">${__("Monto")}</th><th>${__("Documentos vinculados")}</th><th>${__("Estado")}</th>
						</tr></thead>
						<tbody>${grupos}</tbody>
					</table>
				</div>
			</div>`);
		d.show();
	}

	// ------------------------------------------------------------------
	// Panel lateral: Mi día o detalle de la oportunidad
	// ------------------------------------------------------------------

	pintar_lateral() {
		const $l = this.$body.find(".crm-lateral");
		if (!$l.length) return;
		$l.html(this.estado.sel && this.op ? this.html_detalle() : this.html_mi_dia());
	}

	titulo_mi_dia() {
		const d = this.datos;
		if (!d.es_jefe) return __("Mi día");
		return d.asesor ? __("Atención · {0}", [this.nombre_alcance()]) : __("Atención de la tienda");
	}

	html_mi_dia() {
		const e = crm_tableros.esc;
		const d = this.datos;
		const grupos = d.mi_dia
			.map((g) => {
				const ayuda = (g.ayuda_args || []).reduce(
					(txt, arg, i) => txt.replace(`{${i}}`, i === 0 ? this.dinero(arg) : arg),
					g.ayuda
				);
				const items = g.clave === "vencidas" ? this.html_vencidas() : this.html_items_grupo(g);
				return `
					<div class="crm-grupo">
						<div class="crm-grupo-cabecera">
							<span class="crm-badge crm-badge-${g.cantidad ? e(g.tono) : "verde"}">${e(g.cantidad)}</span>
							<div>
								<div class="crm-grupo-titulo">${e(g.titulo)}</div>
								<div class="crm-ayuda">${e(ayuda)}</div>
							</div>
						</div>
						${g.cantidad ? items : `<p class="crm-ayuda crm-verde">${__("Todo al día.")}</p>`}
					</div>`;
			})
			.join("");
		const sub = !d.es_jefe
			? __("Lo que necesita atención, en orden de prioridad")
			: d.asesor
			? __("Lo que este asesor tiene pendiente, en orden de prioridad")
			: __("Pendientes de todos los asesores, en orden de prioridad");
		return `
			<div class="crm-panel">
				<h3>${e(this.titulo_mi_dia())}</h3>
				<p class="crm-ayuda">${e(sub)}</p>
				${grupos}
			</div>`;
	}

	html_items_grupo(g) {
		const e = crm_tableros.esc;
		const expandido = this.estado.expandido[g.clave];
		const visibles = expandido ? g.items : g.items.slice(0, 3);
		const filas = visibles
			.map(
				(it) => `
				<button class="crm-item" data-accion="abrir" data-name="${e(it.name)}" data-tab="${e(it.tab)}">
					<span><strong>${e(it.cliente)}</strong> <span class="crm-ayuda">${e(it.sub)}</span></span>
					<span class="crm-item-valor">${
						it.valor ? e(this.dinero(it.valor)) + (it.tab === "actividad" ? ` · ${e(it.dias)} d` : "") : e(__("{0} días", [it.dias]))
					}</span>
				</button>`
			)
			.join("");
		const mas =
			g.items.length > 3
				? `<button class="crm-link" data-accion="expandir" data-grupo="${e(g.clave)}">
						${expandido ? __("Ver menos") : e(__("Ver las {0}", [g.items.length]))}
					</button> · `
				: "";
		return `${filas}<div class="crm-grupo-pie">${mas}<button class="crm-link" data-accion="lista"
			data-doctype="Opportunity" data-nombres="grupo:${e(g.clave)}">${__("Abrir en la lista")}</button></div>`;
	}

	html_vencidas() {
		const e = crm_tableros.esc;
		return this.datos.vencidas
			.map(
				(v) => `
				<div class="crm-item crm-item-vencida">
					<div>
						<a href="/app/quotation/${encodeURIComponent(v.name)}"><strong>${e(v.cliente)}</strong></a>
						<div class="crm-ayuda">${e(
							[v.modelo !== this.datos.modelos[0] ? v.modelo : "", v.asesor, v.name].filter(Boolean).join(" · ") +
								" · " +
								__("cotizada hace {0} días · venció el {1}", [v.dias_cotizada, crm_tableros.fecha(v.valid_till)])
						)}</div>
					</div>
					<div class="crm-item-acciones">
						<span class="crm-item-valor">${e(this.dinero(v.monto))}</span>
						<button class="btn btn-xs btn-default" data-accion="renovar" data-name="${e(v.name)}">${__("Renovar")}</button>
						<button class="btn btn-xs btn-danger" data-accion="perder-cotizacion" data-name="${e(v.name)}">${__("Perder")}</button>
					</div>
				</div>`
			)
			.join("");
	}

	html_detalle() {
		const e = crm_tableros.esc;
		const op = this.op;
		const prob = op.etapa.probabilidad == null ? __("sin prob.") : `${op.etapa.probabilidad}%`;
		const tabs = [
			["datos", __("Datos y etapa")],
			["actividad", __("Opportunity Activity ({0})", [op.historial_total])],
		]
			.map(
				([k, label]) =>
					`<button class="crm-tab ${this.estado.tab === k ? "crm-tab-on" : ""}" data-accion="tab" data-tab="${k}"
						aria-pressed="${this.estado.tab === k}">${e(label)}</button>`
			)
			.join("");
		return `
			<div class="crm-panel">
				<button class="crm-link" data-accion="cerrar-detalle">← ${e(this.titulo_mi_dia())}</button>
				<div class="crm-detalle-cabecera">
					<span class="crm-chip crm-chip-${e(op.etapa.clave)}">${e(op.etapa.titulo)} · ${e(prob)}</span>
					<h3>${e(op.cliente)}</h3>
					<div class="crm-ayuda">
						<a href="/app/opportunity/${encodeURIComponent(op.name)}">${e(op.name)}</a>
						${op.tipo_de_oportunidad ? " · " + e(op.tipo_de_oportunidad) : ""}
						· ${e(__("Asesor: {0}", [op.asesor]))} · ${e(__("Modelo: {0}", [op.modelo]))}
					</div>
					${
						op.incoherente
							? `<div class="crm-alerta">${e(__("Etapa {0} con status {1}: corrígela en el formulario.", [op.etapa.titulo, op.status]))}</div>`
							: ""
					}
				</div>
				<div class="crm-tabs" role="tablist">${tabs}</div>
				${this.estado.tab === "actividad" ? this.html_tab_actividad() : this.html_tab_datos()}
			</div>`;
	}

	html_tab_datos() {
		const e = crm_tableros.esc;
		const op = this.op;
		if (op.cerrada) {
			return `<p>${e(
				op.status === "Converted"
					? __("Ganada · órdenes de venta: {0}", [op.ordenes_de_venta.join(", ") || "—"])
					: __("Perdida · motivo: {0}", [op.lost_reason || "—"])
			)}</p>`;
		}
		const opciones = (lista, valor) =>
			[`<option value=""></option>`]
				.concat(lista.map((o) => `<option value="${e(o)}" ${o === valor ? "selected" : ""}>${e(o)}</option>`))
				.join("");
		const pp = op.proximo_paso;
		const cotizaciones = op.cotizaciones.length
			? op.cotizaciones
					.map(
						(q) =>
							`<li><a href="/app/quotation/${encodeURIComponent(q.name)}">${e(q.name)}</a> · ${e(this.dinero(q.monto))} · ${e(
								__("vigente hasta {0}", [crm_tableros.fecha(q.valid_till)])
							)} · ${e(q.status)}</li>`
					)
					.join("")
			: `<li class="crm-ayuda">${__("Sin cotizaciones enviadas.")}</li>`;
		return `
			${
				op.etapa.clave === "pausa"
					? `<p class="crm-alerta">${e(
							__("En pausa hasta el {0}. No cuenta en el pronóstico.", [crm_tableros.fecha(op.fecha_retomar)])
						)}</p>`
					: ""
			}
			<div class="crm-form">
				<label>${e(__("Presupuesto declarado por el cliente ({0})", [this.datos.moneda]))}
					<input type="number" min="0" step="0.01" class="form-control" data-campo="presupuesto_declarado_por_el_cliente"
						value="${e(op.presupuesto_declarado_por_el_cliente || "")}">
				</label>
				<label>${__("Fecha estimada de aprobación")}
					<input type="date" class="form-control" data-campo="fecha_estimada_aprobacion" value="${e(op.fecha_estimada_aprobacion || "")}">
				</label>
				<div class="crm-form-fila">
					<label>${__("Próximo paso")}
						<input type="text" class="form-control" data-campo="custom_proximo_paso" value="${e(pp.texto || "")}"
							placeholder="${__("Ej. Presentar diseño")}">
					</label>
					<label>${__("Fecha")}
						<input type="date" class="form-control" data-campo="custom_fecha_proximo_paso" value="${e(pp.fecha || "")}">
					</label>
				</div>
				${
					pp.de_actividad && pp.fecha
						? `<p class="crm-ayuda">${__("Tomado de la última Opportunity Activity. Al editarlo se guarda en la oportunidad.")}</p>`
						: ""
				}
				${pp.vencido ? `<p class="crm-rojo">${__("La fecha del próximo paso ya pasó.")}</p>` : ""}
				<label>${__("Origen")}
					<select class="form-control" data-campo="source">${opciones(op.opciones.origenes, op.source)}</select>
				</label>
				<label>${__("Tipo de oportunidad")}
					<select class="form-control" data-campo="tipo_de_oportunidad">${opciones(op.opciones.tipos, op.tipo_de_oportunidad)}</select>
				</label>
				<p class="crm-ayuda">${__("Los datos se guardan al cambiar cada campo.")}</p>
			</div>
			<dl class="crm-datos">
				<dt>${__("Monto que usa el tablero")}</dt><dd>${op.monto > 0 ? e(this.dinero(op.monto)) : __("Sin monto")}</dd>
				<dt>${__("Cotizaciones")}</dt><dd><ul class="crm-lista">${cotizaciones}</ul></dd>
			</dl>
			${this.html_acciones_etapa()}`;
	}

	html_acciones_etapa() {
		const e = crm_tableros.esc;
		const op = this.op;
		const sig = op.siguiente;
		let primaria = "";
		if (sig) {
			const es_ganada = sig.clave === "ganada";
			const falta = sig.faltantes;
			let boton;
			if (es_ganada && !op.ordenes_de_venta.length) {
				boton = op.cotizacion_para_orden
					? `<button class="btn btn-primary btn-sm" data-accion="crear-orden">${__("Ganada · crear orden de venta")}</button>`
					: `<p class="crm-ayuda">${__("Para marcarla como ganada necesita una cotización vigente de la cual crear la orden de venta.")}</p>`;
			} else {
				const label = es_ganada
					? __("Marcar como ganada")
					: op.etapa.clave === "pausa"
					? __("Retomar en {0}", [sig.titulo])
					: __("Avanzar a {0}", [sig.titulo]);
				boton = `<button class="btn btn-primary btn-sm" data-accion="mover" data-etapa="${e(sig.clave)}"
					${falta.length ? "disabled" : ""}>${e(label)}</button>`;
			}
			const pista = es_ganada
				? __("La oportunidad queda Converted con probabilidad 100% cuando la orden de venta se envía.")
				: op.etapa.probabilidad != null && sig.probabilidad != null
				? __("La probabilidad pasa de {0}% a {1}%.", [op.etapa.probabilidad, sig.probabilidad])
				: "";
			const falta_txt = falta.length
				? `<p class="crm-rojo">${e(__("Para avanzar falta: {0}", [falta.join(", ")]))}</p>`
				: "";
			primaria = `<div class="crm-acciones">${boton}${falta_txt}<p class="crm-ayuda">${e(pista)}</p></div>`;
		}
		const secundarias = [];
		if (op.anterior) {
			secundarias.push(
				`<button class="btn btn-default btn-xs" data-accion="mover" data-etapa="${e(op.anterior.clave)}"
					${op.anterior.faltantes.length ? `disabled title="${e(op.anterior.faltantes.join(", "))}"` : ""}>
					${e(__("Regresar a {0}", [op.anterior.titulo]))}</button>`
			);
		}
		if (op.puede_pausar) {
			secundarias.push(`<button class="btn btn-default btn-xs" data-accion="pausar">${__("Poner en pausa")}</button>`);
		}
		secundarias.push(`<button class="btn btn-danger btn-xs" data-accion="perder">${__("Dar por perdida")}</button>`);
		return `${primaria}<div class="crm-acciones-sec"><span class="crm-ayuda">${__("Otras acciones")}</span>${secundarias.join("")}</div>`;
	}

	html_tab_actividad() {
		const e = crm_tableros.esc;
		const op = this.op;
		const tipos = [`<option value="">${__("Elige el tipo")}</option>`]
			.concat(op.opciones.tipos_actividad.map((t) => `<option value="${e(t)}">${e(t)}</option>`))
			.join("");
		const hist = op.historial.length
			? op.historial
					.map(
						(h) => `
					<li class="crm-hist">
						<div><strong>${e(h.tipo)}</strong> · ${e(crm_tableros.fecha(h.fecha))} · ${e(h.autor)}</div>
						<div>${e(h.comentario)}</div>
						<div class="crm-ayuda">${
							h.proximo ? e(__("Próximo contacto: {0}", [crm_tableros.fecha(h.proximo)])) : __("Sin próximo contacto")
						}</div>
					</li>`
					)
					.join("")
			: `<li class="crm-ayuda">${__("Sin actividades registradas.")}</li>`;
		const mostradas = op.historial_pagina * op.historial_por_pagina + op.historial.length;
		const paginas = `
			<div class="crm-grupo-pie">
				<span class="crm-ayuda">${e(__("Mostrando {0} de {1}", [mostradas, op.historial_total]))}</span>
				${op.historial_pagina > 0 ? `<button class="crm-link" data-accion="historial" data-pagina="${op.historial_pagina - 1}">${__("Más recientes")}</button>` : ""}
				${mostradas < op.historial_total ? `<button class="crm-link" data-accion="historial" data-pagina="${op.historial_pagina + 1}">${__("Anteriores")}</button>` : ""}
			</div>`;
		return `
			${
				op.cerrada
					? ""
					: `<div class="crm-form" data-form="actividad">
				<label>${__("Tipo de actividad")} *<select class="form-control" name="activity_type">${tipos}</select></label>
				<label>${__("Comentario")} *<textarea class="form-control" name="comment" rows="3"></textarea></label>
				<label>${__("Próximo contacto")} *<input type="date" class="form-control" name="next_contact_date"
					min="${e(this.datos.hoy)}" value="${e(frappe.datetime.add_days(this.datos.hoy, 3))}"></label>
				<p class="crm-ayuda">${__("El próximo contacto pasa a ser el próximo paso de la oportunidad.")}</p>
				<button class="btn btn-primary btn-sm" data-accion="guardar-actividad">${__("Guardar Opportunity Activity")}</button>
			</div>`
			}
			<h4>${__("Historial")}</h4>
			<ul class="crm-lista">${hist}</ul>
			${op.historial_total > op.historial_por_pagina ? paginas : ""}`;
	}

	// ------------------------------------------------------------------
	// Eventos
	// ------------------------------------------------------------------

	enlazar_eventos() {
		const $b = this.$body;
		$b.on("click", "[data-accion]", (ev) => {
			const $t = $(ev.currentTarget);
			if ($t.is("select, input")) return;
			ev.preventDefault();
			this.accion($t.data("accion"), $t);
		});
		$b.on("change", '[data-accion="filtro-tipo"]', (ev) => {
			this.estado.tipo = $(ev.currentTarget).val();
			this.repintar_embudo();
		});
		$b.on("change", "[data-campo]", (ev) => {
			const $c = $(ev.currentTarget);
			this.guardar_campo($c.data("campo"), $c.val());
		});
	}

	accion(nombre, $t) {
		const name = $t.attr("data-name");
		const acciones = {
			vista: () => {
				this.estado.vista = $t.attr("data-vista");
				this.pintar();
				if (this.estado.vista === "consolidado" && !this.consolidado) this.cargar_consolidado();
				if (this.estado.vista === "embudo" && !this.historico) this.cargar_historico();
			},
			lista: () => crm_tableros.abrir_lista($t.attr("data-doctype"), this.nombres_de($t.attr("data-nombres"), $t.attr("data-fila"))),
			documentos: () => this.mostrar_documentos($t.attr("data-tarjeta"), $t.attr("data-modelo"), $t.attr("data-tipo")),
			asesor: () => this.elegir_asesor($t.attr("data-empleado")),
			abrir: () => this.cargar_oportunidad(name, true, $t.attr("data-tab") || "datos"),
			"cerrar-detalle": () => {
				this.estado.sel = null;
				this.op = null;
				this.pintar_lateral();
				this.marcar_tarjeta();
			},
			tab: () => {
				this.estado.tab = $t.attr("data-tab");
				this.pintar_lateral();
			},
			expandir: () => {
				const g = $t.attr("data-grupo");
				this.estado.expandido[g] = !this.estado.expandido[g];
				this.pintar_lateral();
			},
			"filtro-modelo": () => {
				this.estado.modelo = $t.attr("data-valor");
				this.repintar_embudo();
			},
			"modo-consolidado": () => {
				this.estado.modo_consolidado = $t.attr("data-valor");
				this.$body.find(".crm-consolidado").html(this.html_consolidado());
			},
			"toggle-comision": () => {
				this.estado.comision_abierta = !this.estado.comision_abierta;
				this.$body.find(".crm-consolidado").html(this.html_consolidado());
			},
			"toggle-cerradas": () => {
				this.estado.ver_cerradas = !this.estado.ver_cerradas;
				this.repintar_embudo();
			},
			historial: () => this.cargar_oportunidad(this.op.name, false, "actividad", Number($t.attr("data-pagina"))),
			mover: () => this.mover($t.attr("data-etapa")),
			pausar: () => this.pausar(),
			perder: () => this.perder(),
			"crear-orden": () => this.crear_orden(),
			"guardar-actividad": () => this.guardar_actividad(),
			renovar: () => this.renovar(name),
			"perder-cotizacion": () => this.perder_cotizacion(name),
		};
		if (acciones[nombre]) acciones[nombre]();
	}

	mover(etapa, extra = {}) {
		return crm_tableros
			.llamar(API_PROYECTOS + "mover_etapa", { nombre: this.op.name, etapa, ...extra })
			.then((r) => this.refrescar_tras_accion(__("Etapa: {0} · probabilidad {1}%", [r.etapa, r.probability])));
	}

	pausar() {
		frappe.prompt(
			[{ fieldname: "fecha", label: __("Fecha para retomar"), fieldtype: "Date", reqd: 1 }],
			(v) => this.mover("pausa", { fecha_retomar: v.fecha }),
			__("Poner en pausa"),
			__("Confirmar")
		);
	}

	perder() {
		crm_tableros
			.pedir_motivo_perdida(this.op.opciones.motivos)
			.then((v) => this.mover("perdida", { motivo: v.motivo, detalle: v.detalle }));
	}

	crear_orden() {
		frappe.model.open_mapped_doc({
			method: "erpnext.selling.doctype.quotation.quotation.make_sales_order",
			source_name: this.op.cotizacion_para_orden,
		});
	}

	guardar_campo(campo, valor) {
		crm_tableros
			.llamar(API_PROYECTOS + "guardar_datos", { nombre: this.op.name, datos: { [campo]: valor } }, { freeze: false })
			.then(() => this.refrescar_tras_accion(__("Guardado")));
	}

	guardar_actividad() {
		const $f = this.$body.find('[data-form="actividad"]');
		const args = {
			nombre: this.op.name,
			activity_type: $f.find('[name="activity_type"]').val(),
			comment: $f.find('[name="comment"]').val(),
			next_contact_date: $f.find('[name="next_contact_date"]').val(),
		};
		const falta = [];
		if (!args.activity_type) falta.push(__("tipo"));
		if (!(args.comment || "").trim()) falta.push(__("comentario"));
		if (!args.next_contact_date) falta.push(__("próximo contacto"));
		if (falta.length) {
			frappe.msgprint(__("Falta: {0}", [falta.join(", ")]));
			return;
		}
		crm_tableros.llamar(API_PROYECTOS + "registrar_actividad", args).then(() => {
			this.estado.tab = "actividad";
			this.refrescar_tras_accion(__("Actividad registrada. Los días sin moverse volvieron a 0."));
		});
	}

	renovar(cotizacion) {
		frappe.confirm(__("¿Crear una copia de {0} con nueva vigencia y enviarla?", [cotizacion]), () =>
			crm_tableros
				.llamar(API_PROYECTOS + "renovar_cotizacion", { cotizacion })
				.then((nueva) => this.refrescar_tras_accion(__("Cotización renovada: {0}", [nueva])))
		);
	}

	perder_cotizacion(cotizacion) {
		crm_tableros
			.pedir_motivo_perdida(this.datos.motivos, __("Perder {0}", [cotizacion]))
			.then((v) =>
				crm_tableros.llamar(API_PROYECTOS + "perder_cotizacion", { cotizacion, motivo: v.motivo, detalle: v.detalle })
			)
			.then(() => this.refrescar_tras_accion(__("Cotización dada por perdida")));
	}
}
