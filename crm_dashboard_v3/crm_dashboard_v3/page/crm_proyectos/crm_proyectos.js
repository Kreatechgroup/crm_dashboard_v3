// Página CRM Proyectos: solo pinta lo que calcula el servidor y llama acciones.

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
			mes: null,
			asesor: null,
			establecimiento: null,
			tipo: "",
			ver_cerradas: false,
			sel: null,
			tab: "datos",
			expandido: {},
		};
		this.datos = null;
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
		this.op = null;
		this.cargar();
	}

	// ------------------------------------------------------------------
	// Carga de datos
	// ------------------------------------------------------------------

	cargar() {
		const { mes, asesor, establecimiento } = this.estado;
		return crm_tableros
			.llamar(API_PROYECTOS + "get_tablero", { mes, asesor, establecimiento }, { mensaje: __("Calculando tablero…") })
			.then((d) => {
				this.datos = d;
				this.estado.mes = d.mes;
				this.estado.establecimiento = d.establecimiento;
				this.actualizar_filtros();
				this.page.set_title(d.titulo || __("CRM Proyectos"));
				this.pintar();
				if (this.estado.sel) {
					this.cargar_oportunidad(this.estado.sel, false);
				}
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
	// Pintado
	// ------------------------------------------------------------------

	pintar() {
		const d = this.datos;
		if (d.mensaje) {
			this.$body.html(`
				<div class="crm-vacio">
					<p class="crm-vacio-titulo">${crm_tableros.esc(d.titulo)}</p>
					<p>${crm_tableros.esc(d.mensaje)}</p>
				</div>`);
			return;
		}
		this.$body.html(`
			<p class="crm-subtitulo">${crm_tableros.esc(d.subtitulo)}</p>
			<section class="crm-kpis">${this.html_kpis()}</section>
			${d.resumen ? this.html_resumen() : ""}
			${this.html_incoherentes()}
			<div class="crm-principal">
				<section class="crm-embudo" aria-label="${__("Embudo")}">${this.html_embudo()}</section>
				<aside class="crm-lateral"></aside>
			</div>`);
		this.pintar_lateral();
	}

	dinero(monto) {
		return crm_tableros.dinero(monto, this.datos.moneda);
	}

	html_kpis() {
		const k = this.datos.kpis;
		const e = crm_tableros.esc;
		const avance = Math.min(100, k.meta.porcentaje);
		const etiqueta_meta = this.datos.asesor || !this.datos.es_jefe
			? __("Facturado vs meta del mes")
			: __("Facturado vs meta de la tienda");
		const pr = k.pronostico;
		const aviso = pr.sin_fecha
			? `<button class="crm-link crm-aviso" data-accion="lista" data-doctype="Opportunity" data-nombres="sin_fecha">
					<span class="crm-pill crm-pill-amarillo">${__("Faltan fechas")}</span>
					${e(__("{0} de {1} sin fecha estimada de aprobación: no entran al mes", [pr.sin_fecha, pr.activas]))}
				</button>`
			: `<span class="crm-ok">${__("Todas tienen fecha estimada de aprobación")} (${pr.con_fecha})</span>`;
		return `
			<div class="crm-kpi crm-kpi-meta">
				<div class="crm-kpi-titulo">${e(etiqueta_meta)}</div>
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
			</div>
			<div class="crm-kpi">
				<div class="crm-kpi-titulo">${e(__("Pronóstico de {0}", [this.datos.etiqueta_mes]))}</div>
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
		const mapa = {
			facturas: k.meta.facturas,
			pronostico_mes: k.pronostico.nombres_mes,
			pronostico_total: k.pronostico.nombres_total,
			sin_fecha: k.pronostico.nombres_sin_fecha,
			vigentes: k.vigentes.nombres,
			vencidas: k.vencidas.nombres,
			incoherentes: this.datos.incoherentes.nombres,
		};
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
			return col ? col.nombres : [];
		}
		if (clave.startsWith("grupo:")) {
			const g = this.datos.mi_dia.find((x) => x.clave === clave.slice(6));
			return g ? g.nombres : [];
		}
		return mapa[clave] || [];
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

	todas_las_columnas() {
		return this.datos.columnas.concat(this.datos.cerradas);
	}

	html_embudo() {
		const e = crm_tableros.esc;
		const d = this.datos;
		const total_cerradas = d.cerradas.reduce((s, c) => s + c.cantidad, 0);
		const opciones_tipo = [`<option value="">${__("Todos")}</option>`]
			.concat(d.tipos.map((t) => `<option value="${e(t)}" ${this.estado.tipo === t ? "selected" : ""}>${e(t)}</option>`))
			.join("");
		return `
			<div class="crm-seccion-titulo">
				<h3>${__("Embudo")}</h3>
				<span class="crm-ayuda">${__("Toca una tarjeta para abrirla")}</span>
			</div>
			<div class="crm-embudo-filtros">
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
				· ${__("Próximo paso = próximo contacto de la última Opportunity Activity; en rojo si no hay o si ya pasó.")}
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
		const tarjetas = col.tarjetas.filter((t) => !this.estado.tipo || t.tipo === this.estado.tipo);
		const prob = col.probabilidad == null ? "" : ` · ${col.probabilidad}%`;
		return `
			<div class="crm-columna crm-columna-${e(col.clave)}">
				<div class="crm-columna-cabecera">
					<div class="crm-columna-titulo">${e(col.titulo)}${e(prob)}</div>
					<button class="crm-link crm-columna-total" data-accion="lista" data-doctype="Opportunity"
						data-nombres="columna:${e(col.clave)}">
						${e(crm_tableros.plural(col.cantidad, __("oportunidad"), __("oportunidades")))} · ${e(this.dinero(col.total))}
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
		return `
			<button class="crm-tarjeta ${this.estado.sel === t.name ? "crm-tarjeta-sel" : ""}" data-accion="abrir" data-name="${e(t.name)}">
				<span class="crm-tarjeta-fila">
					<span class="crm-tarjeta-cliente">${e(t.cliente)}</span>
					${activa ? crm_tableros.semaforo(t.semaforo, __("{0} d", [t.dias])) : ""}
				</span>
				<span class="crm-tarjeta-fila crm-tarjeta-sub">
					<span>${t.monto > 0 ? e(this.dinero(t.monto)) : __("Sin monto")}</span>
					<span>${e(t.asesor || t.tipo || "")}</span>
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

	// ------------------------------------------------------------------
	// Panel lateral: Mi día o detalle de la oportunidad
	// ------------------------------------------------------------------

	pintar_lateral() {
		const $l = this.$body.find(".crm-lateral");
		if (!$l.length) return;
		$l.html(this.estado.sel && this.op ? this.html_detalle() : this.html_mi_dia());
	}

	html_mi_dia() {
		const e = crm_tableros.esc;
		const d = this.datos;
		const titulo = !d.es_jefe ? __("Mi día") : d.asesor ? __("Atención del asesor") : __("Atención de la tienda");
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
		return `
			<div class="crm-panel">
				<h3>${e(titulo)}</h3>
				<p class="crm-ayuda">${__("Lo que necesita atención, en orden de prioridad")}</p>
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
							(v.asesor ? v.asesor + " · " : "") +
								v.name +
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
			["actividad", __("Opportunity Activity")],
		]
			.map(
				([k, label]) =>
					`<button class="crm-tab ${this.estado.tab === k ? "crm-tab-on" : ""}" data-accion="tab" data-tab="${k}"
						aria-pressed="${this.estado.tab === k}">${e(label)}</button>`
			)
			.join("");
		return `
			<div class="crm-panel">
				<button class="crm-link" data-accion="cerrar-detalle">← ${
					!this.datos.es_jefe ? __("Mi día") : __("Atención")
				}</button>
				<div class="crm-detalle-cabecera">
					<span class="crm-chip crm-chip-${e(op.etapa.clave)}">${e(op.etapa.titulo)} · ${e(prob)}</span>
					<h3>${e(op.cliente)}</h3>
					<div class="crm-ayuda">
						<a href="/app/opportunity/${encodeURIComponent(op.name)}">${e(op.name)}</a>
						${op.tipo_de_oportunidad ? " · " + e(op.tipo_de_oportunidad) : ""} · ${e(__("Asesor: {0}", [op.asesor]))}
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
		const prox = pp.fecha
			? `${e(pp.tipo || "")} · ${e(crm_tableros.fecha(pp.fecha))}${pp.vencido ? " · " + __("vencido") : ""}`
			: __("Sin próximo paso: registra una Opportunity Activity con próximo contacto.");
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
				<dt>${__("Próximo paso")}</dt><dd class="${pp.fecha && !pp.vencido ? "" : "crm-rojo"}">${prox}</dd>
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
					: "";
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
			this.$body.find(".crm-embudo").html(this.html_embudo());
			this.marcar_tarjeta();
		});
		$b.on("change", "[data-campo]", (ev) => {
			const $c = $(ev.currentTarget);
			this.guardar_campo($c.data("campo"), $c.val());
		});
	}

	accion(nombre, $t) {
		const name = $t.attr("data-name");
		const acciones = {
			lista: () => crm_tableros.abrir_lista($t.attr("data-doctype"), this.nombres_de($t.attr("data-nombres"), $t.attr("data-fila"))),
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
			"toggle-cerradas": () => {
				this.estado.ver_cerradas = !this.estado.ver_cerradas;
				this.$body.find(".crm-embudo").html(this.html_embudo());
				this.marcar_tarjeta();
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
