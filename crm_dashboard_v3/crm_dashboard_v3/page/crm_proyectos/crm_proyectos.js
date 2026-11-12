// Página CRM Proyectos (asesores de Plus, Proyectos y Retail juntos) · diseño de docs/mockup.html.
// Hereda la plantilla común crm_tableros.TableroBase (public/js/crm_tableros/common.js):
// contexto, encabezado, mes, tienda, "Ver:" de jefes y mensaje de sin acceso.

const API_PROYECTOS = "crm_dashboard_v3.crm_tableros.proyectos.api.";

frappe.pages["crm-proyectos"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("CRM Proyectos"),
		single_column: true,
	});
	wrapper.tablero = new TableroProyectos(page);
};

frappe.pages["crm-proyectos"].on_page_show = function (wrapper) {
	// Al volver de un formulario (cotización, orden de venta) se recalcula todo.
	if (wrapper.tablero && wrapper.tablero.datos) {
		wrapper.tablero.cargar();
	}
};

class TableroProyectos extends crm_tableros.TableroBase {
	constructor(page) {
		super(page, { metodo: API_PROYECTOS + "get_tablero", titulo: __("CRM Proyectos") });
		Object.assign(this.estado, {
			vista: "embudo",
			filtro_modelo: "",
			filtro_tipo: "",
			ver_cerradas: false,
			lista: null,
			sel: null,
			tab: "datos",
			sec: null,
			intento: null,
			ganar: null,
			perdiendo: null,
			motivo_vencida: "",
			intento_vencida: false,
			af: this.actividad_vacia(),
			act_ok: false,
			df: { tipo: "", fecha: "", desc: "" },
			sec_vals: { retomar: "", motivo: "", detalle: "" },
			modo_cons: "",
			com_abierta: null,
			det: null,
		});
		this.historico = null;
		this.consolidado = null;
		this.op = null;
		this.enlazar_eventos();
		this.cargar();
	}

	actividad_vacia() {
		return { tipo: "", com: "", prox: "" };
	}

	texto_modelos() {
		return this.datos.modelos.join(__(" y "));
	}

	es_modelo_principal(modelo) {
		return modelo === this.datos.modelos[0];
	}

	// ------------------------------------------------------------------
	// Puntos de extensión de la plantilla
	// ------------------------------------------------------------------

	antes_de_cargar() {
		this.historico = null;
		this.consolidado = null;
	}

	despues_de_cargar() {
		if (this.estado.sel) this.cargar_oportunidad(this.estado.sel, false);
		if (this.estado.vista === "consolidado") this.cargar_consolidado();
		else this.cargar_historico();
	}

	al_cambiar_alcance() {
		Object.assign(this.estado, { sel: null, lista: null, det: null, com_abierta: null, perdiendo: null });
		this.op = null;
	}

	html_contenido() {
		const vistas = [
			["embudo", __("Embudo · {0}", [this.texto_modelos()])],
			["consolidado", __("Consolidado por asesor · {0}", [this.texto_modelos()])],
		]
			.map(
				([k, label]) =>
					`<button type="button" role="tab" class="crm-vista" aria-selected="${this.estado.vista === k}"
						data-accion="vista" data-valor="${k}">${this.e(label)}</button>`
			)
			.join("");
		return `
			<div role="tablist" aria-label="${__("Vistas del tablero")}" class="crm-vistas">${vistas}</div>
			${this.html_ver()}
			${this.estado.vista === "consolidado" ? `<section class="crm-consolidado crm-card">${this.html_cargando()}</section>` : this.html_vista_embudo()}`;
	}

	despues_de_pintar() {
		if (this.estado.vista === "consolidado") {
			if (this.consolidado) this.pintar_consolidado();
		} else {
			this.pintar_panel();
		}
	}

	// ------------------------------------------------------------------
	// Carga de datos secundarios
	// ------------------------------------------------------------------

	cargar_historico() {
		return crm_tableros.llamar(API_PROYECTOS + "get_historico", this.args(), { freeze: false }).then((h) => {
			this.historico = h;
			this.$body.find(".crm-historico").replaceWith(this.html_historico());
		});
	}

	cargar_consolidado() {
		return crm_tableros
			.llamar(API_PROYECTOS + "get_consolidado", this.args(), { mensaje: __("Calculando consolidado…") })
			.then((c) => {
				this.consolidado = c;
				this.pintar_consolidado();
			});
	}

	cargar_oportunidad(nombre, reiniciar = true, tab = "datos", pagina = 0) {
		return crm_tableros
			.llamar(API_PROYECTOS + "get_oportunidad", { nombre, pagina_historial: pagina }, { freeze: false })
			.then((op) => {
				this.op = op;
				this.estado.sel = nombre;
				this.estado.lista = null;
				if (reiniciar) {
					this.estado.tab = tab;
					this.reiniciar_formularios();
				}
				this.pintar_panel();
				this.marcar_tarjeta();
			});
	}

	reiniciar_formularios() {
		Object.assign(this.estado, {
			sec: null,
			intento: null,
			ganar: null,
			af: this.actividad_vacia(),
			act_ok: false,
			df: { tipo: "", fecha: "", desc: "" },
			sec_vals: { retomar: "", motivo: "", detalle: "" },
		});
	}

	refrescar_tras_accion(mensaje) {
		if (mensaje) frappe.show_alert({ message: mensaje, indicator: "green" });
		return this.cargar();
	}

	// ------------------------------------------------------------------
	// Vista Embudo
	// ------------------------------------------------------------------

	html_vista_embudo() {
		return `
			<section aria-label="${__("Indicadores")}" class="crm-kpis">${this.html_kpis()}</section>
			<div class="crm-cuerpo">
				<div class="crm-principal">
					${this.datos.resumen ? this.html_resumen() : ""}
					${this.html_incoherentes()}
					<section aria-label="${__("Embudo")}" class="crm-card crm-embudo">${this.html_embudo()}</section>
					<div class="crm-cerradas-wrap">${this.html_cerradas()}</div>
				</div>
				<aside class="crm-card crm-panel" aria-live="polite"></aside>
			</div>
			${this.historico ? this.html_historico() : `<section class="crm-historico crm-card">${this.html_cargando()}</section>`}`;
	}

	// ------------------------------------------------------------------
	// Indicadores
	// ------------------------------------------------------------------

	html_kpis() {
		const d = this.datos;
		const k = d.kpis;
		const pr = k.pronostico;
		const avance = Math.min(100, k.meta.porcentaje);
		const etiqueta = this.es_alcance_individual() ? __("Facturado vs meta del mes") : __("Facturado vs meta de la tienda");
		const modelos = d.modelos.join(" + ");
		const aviso = pr.sin_fecha
			? `<div class="crm-aviso-mal">${this.e(__("{0} de {1} sin fecha estimada de aprobación: no entran al mes", [pr.sin_fecha, pr.activas]))}</div>`
			: `<div class="crm-aviso-ok">${__("Todas tienen fecha estimada de aprobación")}</div>`;
		const desglose = d.modelos
			.map((m) => {
				const x = k.meta.por_modelo[m] || { meta: 0, facturado: 0 };
				return __("{0} {1} de {2}", [m, this.dinero(x.facturado), this.dinero(x.meta)]);
			})
			.join(" · ");
		return `
			<div class="crm-card">
				<div class="crm-kpi-titulo">${this.e(etiqueta)}</div>
				<div class="crm-kpi-fila">
					<button type="button" class="crm-kpi-valor" data-accion="lista" data-valor="won">${this.e(this.dinero(k.meta.facturado))}</button>
					<span class="crm-kpi-de">${__("de")} ${this.e(this.dinero(k.meta.meta))}</span>
					${this.tag(k.meta.ritmo, k.meta.ritmo.texto)}
				</div>
				<div class="crm-barra" role="img" aria-label="${this.e(
					__("{0}% de la meta; ritmo esperado {1}%", [k.meta.porcentaje, k.meta.ritmo_esperado])
				)}">
					<div class="crm-barra-avance" style="width:${avance}%"></div>
					<div class="crm-barra-ritmo" style="left:${k.meta.ritmo_esperado}%" title="${__("Ritmo esperado hoy")}"></div>
				</div>
				<div class="crm-kpi-pie">${this.e(
					__("{0}% de la meta · {1} facturas · {2} · la línea es el ritmo esperado hoy ({3}%)", [
						k.meta.porcentaje,
						k.meta.facturas.length,
						modelos,
						k.meta.ritmo_esperado,
					])
				)}</div>
				<div class="crm-kpi-pie">${this.e(desglose)}</div>
			</div>
			<div class="crm-card">
				<div class="crm-kpi-titulo">${this.e(__("Pronóstico de {0} · {1}", [this.mes_en_texto(), modelos]))}</div>
				<button type="button" class="crm-kpi-valor crm-kpi-morado" data-accion="lista" data-valor="mes">${this.e(this.dinero(pr.mes))}</button>
				<div class="crm-kpi-pie">${__("Todo el embudo:")} <button type="button" class="crm-boton-texto" data-accion="lista"
					data-valor="fc">${this.e(this.dinero(pr.total))}</button> ${__("ponderado")}</div>
				${aviso}
			</div>
			<div class="crm-card">
				<div class="crm-kpi-titulo">${__("Propuestas vigentes")}</div>
				<button type="button" class="crm-kpi-valor" data-accion="lista" data-valor="vig">${this.e(this.dinero(k.vigentes.monto))}</button>
				<div class="crm-kpi-pie">${this.e(__("{0} en propuesta enviada o negociación", [k.vigentes.cantidad]))}</div>
			</div>
			<div class="crm-card">
				<div class="crm-kpi-titulo">${__("Propuestas vencidas")}</div>
				<button type="button" class="crm-kpi-valor crm-kpi-rojo" data-accion="erp" data-doctype="Quotation"
					data-nombres="vencidas">${this.e(this.dinero(k.vencidas.monto))}</button>
				<div class="crm-kpi-pie">${this.e(
					__("{0} por renovar o perder · en {1}", [k.vencidas.cantidad, this.titulo_mi_dia()])
				)}</div>
			</div>`;
	}

	html_resumen() {
		const r = this.datos.resumen;
		const celda = (n, tono, clave, i) =>
			`<td><button type="button" class="crm-boton-texto ${n ? tono : "crm-celda-ok"}" data-accion="erp" data-doctype="Opportunity"
				data-nombres="${clave}" data-fila="${i}">${this.e(n)}</button></td>`;
		const filas = r.filas
			.map(
				(x, i) => `
				<tr>
					<td><button type="button" class="crm-nombre-asesor" data-accion="asesor" data-valor="${this.e(x.empleado)}">${this.e(x.nombre)}</button></td>
					<td><strong>${this.e(this.dinero(x.meta.facturado))}</strong> <span class="crm-sub">· ${this.e(x.meta.porcentaje)}%</span></td>
					<td>${this.tag(x.meta.ritmo, x.meta.ritmo.texto)}</td>
					<td>${this.e(x.activas.cantidad)} · ${this.e(this.dinero(x.activas.monto))}</td>
					<td>${this.e(this.dinero(x.pronostico))}</td>
					<td class="crm-rojo-txt">${this.e(x.vencidas.cantidad)} · ${this.e(this.dinero(x.vencidas.monto))}</td>
					${celda(x.sin_actividad.cantidad, "crm-celda-ambar", "sin_actividad", i)}
					${celda(x.escalar.cantidad, "crm-celda-rojo", "escalar", i)}
					${celda(x.incoherentes.cantidad, "crm-celda-ambar", "incoherentes", i)}
				</tr>`
			)
			.join("");
		const t = r.total;
		return `
			<section aria-label="${__("Resumen por asesor")}" class="crm-card">
				<div class="crm-card-titulo">
					<h2>${__("Resumen por asesor")}</h2>
					<span class="crm-sub">${__("Toca un nombre para ver solo su información")}</span>
				</div>
				<p class="crm-nota"><strong>${__("Etapa ≠ status:")}</strong> ${__(
					"oportunidades con etapa Ganada o Perdida pero status abierto. No aparecen en el embudo y hay que corregirlas."
				)}</p>
				<div class="crm-scroll">
					<table class="crm-tabla crm-tabla-resumen">
						<thead><tr>
							<th>${__("Asesor")}</th><th>${__("Facturado vs meta")}</th><th>${__("Estado")}</th><th>${__("Embudo activo")}</th>
							<th>${__("Pronóstico")}</th><th>${__("Vencidas")}</th>
							<th>${this.e(__("Sin actividad +{0} d", [this.datos.dias_verde_max]))}</th><th>${__("Escalar")}</th><th>${__("Etapa ≠ status")}</th>
						</tr></thead>
						<tbody>
							${filas}
							<tr class="crm-fila-total">
								<td>${__("Tienda")}</td>
								<td><strong>${this.e(this.dinero(t.meta.facturado))}</strong> <span class="crm-sub">· ${this.e(t.meta.porcentaje)}%</span></td>
								<td>${this.tag(t.meta.ritmo, t.meta.ritmo.texto)}</td>
								<td>${this.e(t.activas.cantidad)} · ${this.e(this.dinero(t.activas.monto))}</td>
								<td>${this.e(this.dinero(t.pronostico))}</td>
								<td class="crm-rojo-txt">${this.e(t.vencidas.cantidad)} · ${this.e(this.dinero(t.vencidas.monto))}</td>
								<td>${this.e(t.sin_actividad.cantidad)}</td><td>${this.e(t.escalar.cantidad)}</td><td>${this.e(t.incoherentes.cantidad)}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</section>`;
	}

	html_incoherentes() {
		const inc = this.datos.incoherentes;
		if (!inc.cantidad || this.datos.resumen) return "";
		return `
			<p class="crm-nota"><strong>${__("Etapa ≠ status:")}</strong>
				<button type="button" class="crm-boton-texto" data-accion="erp" data-doctype="Opportunity" data-nombres="incoherentes">${this.e(
					__("{0} con etapa Ganada o Perdida pero status abierto: no aparecen en el embudo, corrígelas.", [
						crm_tableros.plural(inc.cantidad, __("oportunidad"), __("oportunidades")),
					])
				)}</button></p>`;
	}

	// Nombres de los registros que forman un número (para abrir la lista de ERPNext).
	nombres_de(clave, fila) {
		const d = this.datos;
		if (fila !== undefined && fila !== null && fila !== "") {
			const r = d.resumen.filas[Number(fila)];
			return { sin_actividad: r.sin_actividad.nombres, escalar: r.escalar.nombres, incoherentes: r.incoherentes.nombres }[clave] || [];
		}
		if (clave.startsWith("columna:")) {
			const col = this.todas_las_columnas().find((c) => c.clave === clave.slice(8));
			return col ? this.tarjetas_visibles(col).map((t) => t.name) : [];
		}
		if (clave.startsWith("hist:")) {
			const [, campo, i] = clave.split(":");
			return this.historico.meses[Number(i)][campo];
		}
		if (clave.startsWith("estado:")) return this.historico.mes_actual.por_estado[clave.slice(7)].nombres;
		if (clave.startsWith("cons:")) {
			const [, i, modelo, campo] = clave.split(":");
			const col = this.consolidado.tarjetas[Number(i)].columnas[modelo];
			return campo === "facturas" ? col.facturas : col[campo].nombres;
		}
		const k = d.kpis;
		return (
			{
				facturas: k.meta.facturas,
				pronostico_mes: k.pronostico.nombres_mes,
				pronostico_total: k.pronostico.nombres_total,
				vigentes: k.vigentes.nombres,
				vencidas: k.vencidas.nombres,
				incoherentes: d.incoherentes.nombres,
			}[clave] || []
		);
	}

	// ------------------------------------------------------------------
	// Embudo
	// ------------------------------------------------------------------

	todas_las_columnas() {
		return this.datos.columnas.concat(this.datos.cerradas);
	}

	tarjeta_por_nombre(nombre) {
		for (const c of this.todas_las_columnas()) {
			const t = c.tarjetas.find((x) => x.name === nombre);
			if (t) return t;
		}
		return null;
	}

	tarjetas_visibles(col) {
		const { filtro_tipo, filtro_modelo } = this.estado;
		return col.tarjetas.filter((t) => (!filtro_tipo || t.tipo === filtro_tipo) && (!filtro_modelo || t.modelo === filtro_modelo));
	}

	html_embudo() {
		const d = this.datos;
		const total_cerradas = d.cerradas.reduce((s, c) => s + this.tarjetas_visibles(c).length, 0);
		const opc_modelo = [["", this.texto_modelos()]]
			.concat(d.modelos.map((m) => [m, __("Solo {0}", [m])]))
			.map(([v, l]) => `<option value="${this.e(v)}" ${this.estado.filtro_modelo === v ? "selected" : ""}>${this.e(l)}</option>`)
			.join("");
		const opc_tipo = [`<option value="">${__("Todos")}</option>`]
			.concat(d.tipos.map((t) => `<option ${this.estado.filtro_tipo === t ? "selected" : ""}>${this.e(t)}</option>`))
			.join("");
		const ej = (clave, dias, texto) =>
			`<span class="crm-leyenda-item">${this.tag({ clave, texto: { verde: __("Verde"), amarillo: __("Amarillo"), rojo: __("Rojo") }[clave] }, dias + " d", true)}${this.e(texto)}</span>`;
		return `
			<div class="crm-embudo-cab">
				<h2>${__("Embudo")}</h2>
				<span class="crm-sub">${__("Toca una tarjeta para abrirla")}</span>
				<div class="crm-embudo-filtros">
					<label class="crm-campo-inline-sm">${__("Modelo")}<select class="crm-select" data-cambio="filtro_modelo">${opc_modelo}</select></label>
					<label class="crm-campo-inline-sm">${__("Tipo")}<select class="crm-select" data-cambio="filtro_tipo">${opc_tipo}</select></label>
					<button type="button" class="crm-boton-sec" data-accion="toggle-cerradas" aria-expanded="${this.estado.ver_cerradas}">${this.e(
						(this.estado.ver_cerradas ? __("Ocultar") : __("Ver")) + " " + __("en pausa y cerradas ({0})", [total_cerradas])
					)}</button>
				</div>
			</div>
			<p class="crm-nota crm-leyenda">
				<strong>${__("Días sin moverse:")}</strong>
				${ej("verde", 3, __("verde, hasta {0}", [d.dias_verde_max]))}
				${ej("amarillo", d.dias_verde_max + 3, __("ámbar, de {0} a {1}", [d.dias_verde_max + 1, d.dias_amarillo_max]))}
				${ej("rojo", d.dias_amarillo_max + 6, __("rojo, más de {0}", [d.dias_amarillo_max]))}
				<span>${__("· Próximo paso en rojo si no hay o si ya pasó · «Para entrar» = lo que exige cada etapa")}</span>
			</p>
			<div class="crm-scroll">
				<div class="crm-columnas">${d.columnas.map((c) => this.html_columna(c)).join("")}</div>
			</div>`;
	}

	html_columna(col) {
		const tarjetas = this.tarjetas_visibles(col).slice().sort((a, b) => b.monto - a.monto);
		const total = tarjetas.reduce((s, t) => s + t.monto, 0);
		return `
			<div class="crm-columna">
				<div class="crm-columna-cab">
					<div class="crm-columna-tit"><strong>${this.e(col.titulo)}</strong>
						<span class="crm-columna-prob">${col.probabilidad == null ? __("sin prob.") : this.e(col.probabilidad + "%")}</span></div>
					<button type="button" class="crm-columna-total" data-accion="erp" data-doctype="Opportunity" data-nombres="columna:${this.e(col.clave)}">${this.e(
						crm_tableros.plural(tarjetas.length, __("oportunidad"), __("oportunidades"))
					)} · ${this.e(this.dinero(total))}</button>
					<div class="crm-columna-req">${this.e(__("Para entrar: {0}", [col.requisitos]))}</div>
				</div>
				${tarjetas.length ? tarjetas.map((t) => this.html_tarjeta(t)).join("") : `<div class="crm-vacia">${__("Sin oportunidades")}</div>`}
			</div>`;
	}

	quien_de(t) {
		const partes = [];
		if (!this.es_modelo_principal(t.modelo)) partes.push(t.modelo);
		if (t.asesor) partes.push(this.primer_nombre(t.asesor));
		return partes.join(" · ");
	}

	html_tarjeta(t) {
		const p = t.proximo;
		const tiene = p.estado !== "vacio";
		const texto_paso = !tiene ? __("Sin próximo paso") : (p.estado === "vencido" ? __("Vencido:") + " " : "") + p.texto + " · " + this.fecha(p.fecha);
		return `
			<button type="button" class="crm-tarjeta" data-accion="abrir" data-name="${this.e(t.name)}" aria-current="${this.estado.sel === t.name}">
				<span class="crm-tarjeta-fila">
					<span class="crm-tarjeta-cliente">${this.e(t.cliente)}</span>
					${this.tag(t.semaforo, t.dias + " d", true)}
				</span>
				<span class="crm-tarjeta-fila">
					<span class="crm-tarjeta-monto">${t.monto > 0 ? this.e(this.dinero(t.monto)) : __("Sin monto")}</span>
					<span class="crm-tarjeta-quien ${this.es_modelo_principal(t.modelo) ? "" : "crm-tarjeta-quien-retail"}">${this.e(this.quien_de(t))}</span>
				</span>
				<span class="crm-tarjeta-paso ${p.estado === "ok" ? "" : "crm-tarjeta-paso-mal"}">${this.e(texto_paso)}</span>
			</button>`;
	}

	html_cerradas() {
		if (!this.estado.ver_cerradas) return "";
		const vacios = { pausa: __("Nada en pausa"), ganada: __("Aún no hay ganadas"), perdida: __("Aún no hay perdidas") };
		const cols = this.datos.cerradas
			.map((col) => {
				const tarjetas = this.tarjetas_visibles(col);
				const total = tarjetas.reduce((s, t) => s + t.monto, 0);
				return `
					<div class="crm-columna crm-columna-${this.e(col.clave)}">
						<div class="crm-columna-cab">
							<strong>${this.e(col.titulo)}</strong>
							<button type="button" class="crm-columna-total" data-accion="erp" data-doctype="Opportunity"
								data-nombres="columna:${this.e(col.clave)}">${this.e(tarjetas.length)} · ${this.e(this.dinero(total))}</button>
						</div>
						${
							tarjetas.length
								? tarjetas
										.map(
											(t) => `
							<button type="button" class="crm-tarjeta" data-accion="abrir" data-name="${this.e(t.name)}" aria-current="${this.estado.sel === t.name}">
								<span class="crm-tarjeta-cliente" style="display:block">${this.e(t.cliente)}</span>
								<span class="crm-tarjeta-monto" style="display:block;margin-top:3px">${t.monto > 0 ? this.e(this.dinero(t.monto)) : __("Sin monto")}</span>
								<span class="crm-tarjeta-extra">${this.e(t.extra || t.etapa)}</span>
							</button>`
										)
										.join("")
								: `<div class="crm-vacia">${vacios[col.clave] || __("Sin oportunidades")}</div>`
						}
					</div>`;
			})
			.join("");
		return `
			<section aria-label="${__("En pausa y cerradas")}" class="crm-card">
				<div class="crm-card-titulo"><h2>${__("En pausa y cerradas del mes")}</h2><span class="crm-sub">${__("No suman al pronóstico")}</span></div>
				<div class="crm-scroll"><div class="crm-columnas crm-columnas-3">${cols}</div></div>
			</section>`;
	}

	repintar_embudo() {
		this.$body.find(".crm-embudo").html(this.html_embudo());
		this.$body.find(".crm-cerradas-wrap").html(this.html_cerradas());
	}

	marcar_tarjeta() {
		this.$body.find(".crm-tarjeta").attr("aria-current", "false");
		this.$body.find(`.crm-tarjeta[data-name="${CSS.escape(this.estado.sel || "")}"]`).attr("aria-current", "true");
	}

	// ------------------------------------------------------------------
	// Panel lateral: Mi día, lista o detalle de la oportunidad
	// ------------------------------------------------------------------

	titulo_mi_dia() {
		const d = this.datos;
		if (!d.es_jefe) return __("Mi día");
		return d.asesor ? __("Atención · {0}", [this.primer_nombre(this.nombre_alcance())]) : __("Atención de la tienda");
	}

	pintar_panel() {
		const $p = this.$body.find(".crm-panel");
		if (!$p.length) return;
		let html;
		if (this.estado.sel && this.op) html = this.html_detalle();
		else if (this.estado.lista) html = this.html_lista();
		else html = this.html_mi_dia();
		$p.html(html);
	}

	html_mi_dia() {
		const d = this.datos;
		const sub = !d.es_jefe
			? __("Lo que necesita atención, en orden de prioridad")
			: d.asesor
			? __("Lo que este asesor tiene pendiente, en orden de prioridad")
			: __("Pendientes de todos los asesores, en orden de prioridad");
		const grupos = d.mi_dia
			.map((g) => {
				const ayuda = (g.ayuda_args || []).reduce(
					(txt, arg, i) => txt.replace(`{${i}}`, i === 0 ? this.dinero(arg) : arg),
					g.ayuda
				);
				const items = g.clave === "vencidas" ? this.html_vencidas() : g.items.slice(0, 3).map((it) => this.html_item(it)).join("");
				const mas = g.clave !== "vencidas" && g.items.length > 3
					? `<button type="button" class="crm-enlace" data-accion="lista" data-valor="${this.e(g.clave)}">${this.e(__("Ver las {0}", [g.cantidad]))}</button>`
					: "";
				return `
					<div class="crm-grupo">
						<div class="crm-grupo-cab">
							<span class="crm-badge crm-badge-${g.cantidad ? this.e(g.tono) : "verde"}">${this.e(g.cantidad)}</span>
							<strong>${this.e(g.titulo)}</strong>
						</div>
						<div class="crm-grupo-ayuda">${this.e(ayuda)}</div>
						${g.cantidad ? items + mas : `<div class="crm-al-dia">${__("Todo al día.")}</div>`}
					</div>`;
			})
			.join("");
		return `<h2>${this.e(this.titulo_mi_dia())}</h2><p class="crm-panel-sub">${this.e(sub)}</p>${grupos}`;
	}

	html_item(it) {
		let valor = it.valor ? this.dinero(it.valor) : __("{0} días", [it.dias]);
		if (it.valor && it.tab === "actividad") valor += ` · ${it.dias} d`;
		return `
			<div class="crm-item">
				<button type="button" class="crm-item-boton" data-accion="abrir" data-name="${this.e(it.name)}" data-tab="${this.e(it.tab)}">
					<span><strong>${this.e(it.cliente)}</strong><span class="crm-item-sub">${this.e(it.sub)}</span></span>
					<span class="crm-item-valor">${this.e(valor)}</span>
				</button>
			</div>`;
	}

	html_vencidas() {
		return this.datos.vencidas
			.map((v) => {
				const partes = [];
				if (!this.es_modelo_principal(v.modelo)) partes.push(v.modelo);
				if (v.asesor) partes.push(this.primer_nombre(v.asesor));
				partes.push(__("cotizada hace {0} días", [v.dias_cotizada]));
				const perdiendo = this.estado.perdiendo === v.name;
				const form = perdiendo
					? `
					<div class="crm-form" style="margin-top:8px;gap:6px">
						<label>${__("Motivo de pérdida")} *
							<select class="crm-select" data-modelo="motivo_vencida">
								<option value="">${__("Elige un motivo")}</option>
								${this.datos.motivos
									.map((m) => `<option ${this.estado.motivo_vencida === m ? "selected" : ""}>${this.e(m)}</option>`)
									.join("")}
							</select>
						</label>
						${this.estado.intento_vencida && !this.estado.motivo_vencida ? `<div role="alert" class="crm-alerta">${__("Elige un motivo para darla por perdida.")}</div>` : ""}
						<div class="crm-acciones-fila">
							<button type="button" class="crm-boton-rojo" data-accion="confirmar-perder-cotizacion" data-name="${this.e(v.name)}">${__("Confirmar pérdida")}</button>
							<button type="button" class="crm-boton-blanco" data-accion="cancelar-perder-cotizacion">${__("Cancelar")}</button>
						</div>
					</div>`
					: "";
				return `
					<div class="crm-item">
						<a class="crm-item-boton" href="/app/quotation/${encodeURIComponent(v.name)}">
							<span><strong>${this.e(v.cliente)}</strong><span class="crm-item-sub">${this.e(partes.join(" · "))} · <span class="crm-mono">${this.e(
					v.name
				)}</span></span></span>
							<span class="crm-item-valor">${this.e(this.dinero(v.monto))}</span>
						</a>
						<div class="crm-acciones-fila">
							<button type="button" class="crm-boton-morado" data-accion="renovar" data-name="${this.e(v.name)}">${__("Renovar")}</button>
							<button type="button" class="crm-boton-blanco" data-accion="perder-cotizacion" data-name="${this.e(v.name)}">${__("Perder")}</button>
						</div>
						${form}
					</div>`;
			})
			.join("");
	}

	// Listas laterales que abre cada indicador.
	definicion_lista(clave) {
		const d = this.datos;
		const k = d.kpis;
		const mostrar = d.mostrar_asesor;
		const fila = (t, valor) => ({
			name: t.name,
			cliente: t.cliente,
			sub: [this.es_modelo_principal(t.modelo) ? "" : t.modelo, mostrar && t.asesor ? this.primer_nombre(t.asesor) : "", t.etapa, t.name]
				.filter(Boolean)
				.join(" · "),
			valor,
			doctype: "Opportunity",
		});
		const de_nombres = (nombres) => nombres.map((n) => this.tarjeta_por_nombre(n)).filter(Boolean);
		if (clave === "won") {
			return {
				titulo: __("Facturado en {0}", [this.mes_en_texto()]),
				sub: __("Facturas atribuidas por Comisiones Asesor de su orden de venta, o creadas por el asesor sin orden"),
				doctype: "Sales Invoice",
				nombres: k.meta.facturas,
				filas: k.meta.filas.map((f) => ({
					name: f.name,
					cliente: f.cliente,
					sub: [
						mostrar ? this.primer_nombre(f.asesor) : "",
						f.name,
						this.fecha(f.fecha),
						f.modelo,
						f.propia ? __("sin orden de venta (la creó el asesor)") : f.distribucion !== 100 ? __("{0}% de distribución", [f.distribucion]) : "",
						f.nota_de_credito ? __("nota de crédito") : "",
					]
						.filter(Boolean)
						.join(" · "),
					valor: this.dinero(f.monto),
					doctype: "Sales Invoice",
				})),
			};
		}
		if (clave === "vig") {
			return {
				titulo: __("Propuestas vigentes"),
				sub: __("Etapas 3 y 4 · Σ monto"),
				doctype: "Opportunity",
				nombres: k.vigentes.nombres,
				filas: de_nombres(k.vigentes.nombres).sort((a, b) => b.monto - a.monto).map((t) => fila(t, this.dinero(t.monto))),
			};
		}
		if (clave === "fc" || clave === "mes") {
			const nombres = clave === "fc" ? k.pronostico.nombres_total : k.pronostico.nombres_mes;
			return {
				titulo: clave === "fc" ? __("Pronóstico de todo el embudo") : __("Pronóstico de {0}", [this.mes_en_texto()]),
				sub: clave === "fc" ? __("Activas · monto × probabilidad de la etapa") : __("Solo las que tienen cierre en el mes"),
				doctype: "Opportunity",
				nombres,
				filas: de_nombres(nombres).sort((a, b) => b.ponderado - a.ponderado).map((t) => fila(t, this.dinero(t.ponderado))),
			};
		}
		const g = d.mi_dia.find((x) => x.clave === clave);
		if (!g) return null;
		return {
			titulo: g.titulo,
			sub: (g.ayuda_args || []).reduce((txt, arg, i) => txt.replace(`{${i}}`, i === 0 ? this.dinero(arg) : arg), g.ayuda),
			doctype: "Opportunity",
			nombres: g.nombres,
			filas: g.items.map((it) => ({
				name: it.name,
				cliente: it.cliente,
				sub: it.sub,
				valor: it.valor ? this.dinero(it.valor) + (it.tab === "actividad" ? ` · ${it.dias} d` : "") : __("{0} días", [it.dias]),
				doctype: "Opportunity",
				tab: it.tab,
			})),
		};
	}

	html_lista() {
		const l = this.definicion_lista(this.estado.lista);
		if (!l) return this.html_mi_dia();
		const filas = l.filas.length
			? l.filas
					.map((r) =>
						r.doctype === "Opportunity"
							? `<button type="button" class="crm-lista-fila" data-accion="abrir" data-name="${this.e(r.name)}" data-tab="${this.e(r.tab || "datos")}">
									<span><strong>${this.e(r.cliente)}</strong><span class="crm-item-sub">${this.e(r.sub)}</span></span>
									<span class="crm-lista-valor">${this.e(r.valor)}</span></button>`
							: `<a class="crm-lista-fila" href="/app/${frappe.router.slug(r.doctype)}/${encodeURIComponent(r.name)}">
									<span><strong>${this.e(r.cliente)}</strong><span class="crm-item-sub">${this.e(r.sub)}</span></span>
									<span class="crm-lista-valor">${this.e(r.valor)}</span></a>`
					)
					.join("")
			: `<p class="crm-sub">${__("Sin registros todavía.")}</p>`;
		this.lista_actual = l;
		return `
			<button type="button" class="crm-enlace" data-accion="cerrar-lista">← ${this.e(this.titulo_mi_dia())}</button>
			<h2 style="margin-top:6px">${this.e(l.titulo)}</h2>
			<p class="crm-panel-sub">${this.e(l.sub)}</p>
			${filas}
			<button type="button" class="crm-enlace" data-accion="erp-lista">${__("Abrir en ERPNext")}</button>`;
	}

	// ------------------------------------------------------------------
	// Detalle de la oportunidad
	// ------------------------------------------------------------------

	html_detalle() {
		const op = this.op;
		const prob = op.etapa.probabilidad == null ? __("sin prob.") : `${op.etapa.probabilidad}%`;
		const volver = this.estado.lista ? this.definicion_lista(this.estado.lista).titulo : this.titulo_mi_dia();
		const tabs = [
			["datos", __("Datos y etapa")],
			["actividad", __("Opportunity Activity ({0})", [op.historial_total])],
			["entregables", __("Entregables ({0})", [op.entregables.length])],
		]
			.map(
				([k, l]) =>
					`<button type="button" role="tab" class="crm-tab" aria-selected="${this.estado.tab === k}" data-accion="tab" data-valor="${k}">${this.e(l)}</button>`
			)
			.join("");
		const cuerpo =
			this.estado.tab === "actividad" ? this.html_tab_actividad() : this.estado.tab === "entregables" ? this.html_tab_entregables() : this.html_tab_datos();
		return `
			<button type="button" class="crm-enlace" data-accion="cerrar-detalle">← ${this.e(volver)}</button>
			<div style="margin-top:6px"><span class="crm-chip-etapa crm-chip-etapa-${this.e(op.etapa.clave)}">${this.e(op.etapa.titulo)} · ${this.e(prob)}</span></div>
			<div class="crm-op-nombre">${this.e(op.cliente)}</div>
			<div class="crm-op-meta">
				<a class="crm-mono" href="/app/opportunity/${encodeURIComponent(op.name)}">${this.e(op.name)}</a>
				${op.tipo_de_oportunidad ? " · " + this.e(op.tipo_de_oportunidad) : ""}
				· ${op.dias === 0 ? __("movida hoy") : this.e(__("{0} días sin moverse", [op.dias]))}
			</div>
			<div class="crm-op-meta">${__("Asesor:")} <strong>${this.e(op.asesor)}</strong> · ${__("Modelo:")} <strong>${this.e(op.modelo)}</strong></div>
			${op.incoherente ? `<div class="crm-alerta" style="margin-top:8px">${this.e(__("Etapa {0} con status {1}: corrígela en el formulario.", [op.etapa.titulo, op.status]))}</div>` : ""}
			<button type="button" class="crm-boton-acento" data-accion="tab" data-valor="actividad">${__("Opportunity Activity")}</button>
			<div role="tablist" aria-label="${__("Secciones de la oportunidad")}" class="crm-tabs">${tabs}</div>
			${cuerpo}`;
	}

	html_tab_datos() {
		const op = this.op;
		if (op.cerrada) {
			const txt =
				op.status === "Converted"
					? __("Ganada con la orden de venta {0}. Status Converted, probabilidad 100%.", [op.ordenes_de_venta.join(", ") || "—"])
					: __("Perdida por «{0}». Status Lost, probabilidad 0%.", [op.lost_reason || "—"]);
			return `<p style="margin:14px 0 0;font-size:13px;line-height:1.5">${this.e(txt)}</p>`;
		}
		const pp = op.proximo_paso;
		const sig = op.siguiente;
		const mostrar_cot = sig && sig.clave === "prop";
		const cotizaciones = op.cotizaciones.filter((q) => !["Lost", "Cancelled"].includes(q.status));
		const caja_cot = mostrar_cot
			? `
			<div class="crm-caja-acento">
				<div class="crm-caja-acento-tit">${__("Para pasar a Propuesta enviada")}</div>
				${
					cotizaciones.length
						? cotizaciones
								.map(
									(q) =>
										`<div style="font-size:12.5px"><a class="crm-mono" href="/app/quotation/${encodeURIComponent(q.name)}">${this.e(q.name)}</a> · ${this.e(
											this.dinero(q.monto)
										)} · ${this.e(__("vigente hasta {0}", [this.fecha(q.valid_till)]))}</div>`
								)
								.join("")
						: `<div style="font-size:12.5px">${__("Aún no hay una cotización enviada (submit) ligada a esta oportunidad.")}</div>
							<button type="button" class="crm-boton-blanco" data-accion="crear-cotizacion">${__("Crear cotización desde la oportunidad")}</button>`
				}
				<div class="crm-pista">${__("El monto de la cotización reemplaza el monto estimado de la oportunidad.")}</div>
			</div>`
			: "";
		let primaria = "";
		if (sig) {
			const es_ganada = sig.clave === "ganada";
			const label = es_ganada
				? __("Ganada · crear orden de venta")
				: op.etapa.clave === "pausa"
				? __("Retomar en {0}", [sig.titulo])
				: __("Avanzar a {0}", [sig.titulo]);
			const pista = es_ganada
				? __("La oportunidad queda Converted con probabilidad 100%.")
				: op.etapa.probabilidad != null && sig.probabilidad != null
				? __("La probabilidad pasa de {0}% a {1}%.", [op.etapa.probabilidad, sig.probabilidad])
				: "";
			primaria = `
				${this.estado.intento === "prim" && sig.faltantes.length ? `<div role="alert" class="crm-alerta">${this.e(__("Para avanzar falta: {0}", [sig.faltantes.join(", ")]))}</div>` : ""}
				<button type="button" class="${es_ganada ? "crm-boton-verde" : "crm-boton-morado"} crm-boton-grande" data-accion="primaria">${this.e(label)}</button>
				${this.estado.ganar ? this.html_ganar() : ""}
				<div class="crm-pista-centro">${this.e(pista)}</div>`;
		}
		return `
			<div class="crm-form">
				${op.etapa.clave === "pausa" ? `<div class="crm-aviso-gris">${this.e(__("En pausa hasta el {0}. No cuenta en el pronóstico.", [this.fecha(op.fecha_retomar)]))}</div>` : ""}
				<label>${this.e(__("Presupuesto declarado por el cliente ({0})", [this.datos.moneda]))}
					<input type="number" min="0" step="0.01" class="crm-input" data-campo="presupuesto_declarado_por_el_cliente"
						value="${this.e(op.presupuesto_declarado_por_el_cliente || "")}"></label>
				<label>${__("Fecha estimada de aprobación")}
					<input type="date" class="crm-input" data-campo="fecha_estimada_aprobacion" value="${this.e(op.fecha_estimada_aprobacion || "")}"></label>
				<div class="crm-form-2">
					<label>${__("Próximo paso")}
						<input type="text" class="crm-input" data-campo="custom_proximo_paso" value="${this.e(pp.texto || "")}" placeholder="${__("Ej.: enviar render")}"></label>
					<label>${__("Fecha")}
						<input type="date" class="crm-input" data-campo="custom_fecha_proximo_paso" value="${this.e(pp.fecha || "")}"></label>
				</div>
				${pp.de_actividad && pp.fecha ? `<div class="crm-pista">${__("Tomado de la última Opportunity Activity.")}</div>` : ""}
				${caja_cot}
				<div class="crm-pista">${__("Los datos se guardan al cambiar cada campo.")}</div>
				${primaria}
				${this.html_otras_acciones()}
			</div>`;
	}

	html_ganar() {
		const op = this.op;
		const g = this.estado.ganar;
		const ordenes = op.ordenes_del_cliente;
		let cuerpo;
		if (g.modo === "nueva") {
			cuerpo = op.cotizacion_para_orden
				? `
				<div style="display:grid;gap:8px;font-size:12.5px">
					<div>${__("Cliente:")} <strong>${this.e(op.cliente)}</strong></div>
					<div>${__("Desde la cotización vigente")} <span class="crm-mono">${this.e(op.cotizacion_para_orden)}</span> · ${__("monto")} <strong>${this.e(
						this.dinero(op.monto_cotizacion_para_orden)
					)}</strong></div>
					<label style="display:grid;gap:4px">${__("Fecha de entrega")} *
						<input type="date" class="crm-input" data-modelo="ganar.fecha" min="${this.e(this.datos.hoy)}" value="${this.e(g.fecha || "")}"></label>
				</div>`
				: `<div class="crm-aviso-gris">${__("No hay una cotización enviada y vigente para crear la orden de venta. Renueva la cotización o vincula una orden existente.")}</div>`;
		} else {
			cuerpo = `
				<div>
					<div class="crm-pista" style="margin-bottom:6px">${__("Órdenes de venta de este cliente de los últimos 6 meses")}</div>
					${
						ordenes.length
							? ordenes
									.map(
										(o) => `
						<button type="button" class="crm-orden" data-accion="elegir-orden" data-valor="${this.e(o.name)}" aria-pressed="${g.orden === o.name}"
							${o.ligada_a ? "disabled" : ""}>
							<span><strong class="crm-mono" style="display:block">${this.e(o.name)}</strong>${this.e(this.fecha(o.fecha))} · ${this.e(this.dinero(o.monto))} · ${this.e(o.status)}</span>
							<span class="crm-orden-nota">${this.e(o.ligada_a ? __("Ya ligada a {0}", [o.ligada_a]) : __("Sin oportunidad ligada"))}</span>
						</button>`
									)
									.join("")
							: `<div class="crm-aviso-gris">${__("Este cliente no tiene órdenes de venta recientes. Crea una nueva.")}</div>`
					}
				</div>`;
		}
		const falta = g.modo === "nueva" ? (op.cotizacion_para_orden && !g.fecha ? [__("fecha de entrega")] : []) : g.orden ? [] : [__("la orden de venta a vincular")];
		return `
			<div role="group" aria-label="${__("Cerrar como ganada")}" class="crm-ganar">
				<div>
					<div class="crm-ganar-tit">${__("Cerrar como ganada")}</div>
					<div class="crm-pista">${__("Toda oportunidad ganada debe quedar ligada a una Sales Order. Elige una opción.")}</div>
				</div>
				<div class="crm-ganar-modos">
					<button type="button" class="crm-ganar-modo" aria-pressed="${g.modo === "nueva"}" data-accion="modo-ganar" data-valor="nueva">${__("Crear nueva Sales Order")}</button>
					<button type="button" class="crm-ganar-modo" aria-pressed="${g.modo === "vincular"}" data-accion="modo-ganar" data-valor="vincular">${this.e(
						__("Vincular una existente ({0})", [ordenes.length])
					)}</button>
				</div>
				${cuerpo}
				${g.intento && falta.length ? `<div role="alert" class="crm-alerta">${this.e(__("Falta: {0}", [falta.join(", ")]))}</div>` : ""}
				<div class="crm-acciones-fila">
					<button type="button" class="crm-boton-verde crm-boton-mediano" style="flex:1" data-accion="confirmar-ganar"
						${g.modo === "nueva" && !op.cotizacion_para_orden ? "disabled" : ""}>${
						g.modo === "nueva" ? __("Crear Sales Order") : __("Vincular y marcar ganada")
					}</button>
					<button type="button" class="crm-boton-blanco crm-boton-mediano" data-accion="cancelar-ganar">${__("Cancelar")}</button>
				</div>
				${g.modo === "nueva" ? `<div class="crm-pista">${__("La orden queda en borrador para que la revises; al enviarla, la oportunidad pasa sola a Ganada.")}</div>` : ""}
			</div>`;
	}

	opciones_secundarias() {
		const op = this.op;
		const lista = [];
		if (op.anterior) lista.push({ k: "regresar", d: op.anterior, label: __("Regresar a {0}", [op.anterior.titulo.replace(/^\d+ · /, "")]) });
		if (op.puede_pausar) lista.push({ k: "pausa", label: __("Poner en pausa") });
		lista.push({ k: "perder", label: __("Dar por perdida") });
		return lista;
	}

	// Lo que falta para confirmar una de "Otras acciones" (datos del formulario y bloqueos del workflow).
	faltantes_secundaria(sel) {
		const v = this.estado.sec_vals;
		const bloqueos = this.op.bloqueos;
		if (sel.k === "regresar") return sel.d.faltantes;
		if (sel.k === "pausa") return (v.retomar ? [] : [__("fecha para retomar")]).concat(bloqueos.pausa ? [bloqueos.pausa] : []);
		return (v.motivo ? [] : [__("motivo de pérdida")]).concat(bloqueos.perdida ? [bloqueos.perdida] : []);
	}

	html_otras_acciones() {
		const op = this.op;
		const opciones = this.opciones_secundarias();
		const sel = opciones.find((o) => o.k === this.estado.sec);
		const v = this.estado.sec_vals;
		let campos = "";
		const falta = sel ? this.faltantes_secundaria(sel) : [];
		if (sel) {
			if (sel.k === "regresar") {
				if (sel.d.clave === "cal") {
					campos += `<label>${__("Origen")} *<select class="crm-select" data-campo="source"><option value="">${__("Elige el origen")}</option>${op.opciones.origenes
						.map((o) => `<option ${o === op.source ? "selected" : ""}>${this.e(o)}</option>`)
						.join("")}</select></label>`;
				}
			} else if (sel.k === "pausa") {
				campos += `<label>${__("Fecha para retomar")} *<input type="date" class="crm-input" data-modelo="sec_vals.retomar" min="${this.e(
					this.datos.hoy
				)}" value="${this.e(v.retomar)}"></label>`;
			} else {
				campos += `<label>${__("Motivo de pérdida")} *<select class="crm-select" data-modelo="sec_vals.motivo"><option value="">${__("Elige un motivo")}</option>${op.opciones.motivos
					.map((m) => `<option ${m === v.motivo ? "selected" : ""}>${this.e(m)}</option>`)
					.join("")}</select></label>
					<label>${__("Detalle (opcional)")}<input type="text" class="crm-input" data-modelo="sec_vals.detalle" value="${this.e(v.detalle)}"></label>`;
			}
		}
		const confirmar = !sel
			? ""
			: `
				<div style="display:grid;gap:8px;margin-top:10px">
					${campos}
					${this.estado.intento === "sec" && falta.length ? `<div role="alert" class="crm-alerta">${this.e(__("Falta: {0}", [falta.join(", ")]))}</div>` : ""}
					<button type="button" class="crm-boton-confirmar ${sel.k === "perder" ? "crm-boton-confirmar-perder" : ""}" data-accion="confirmar-sec">${
						sel.k === "perder" ? __("Confirmar pérdida") : sel.k === "pausa" ? __("Confirmar pausa") : __("Confirmar regreso")
					}</button>
				</div>`;
		return `
			<div class="crm-otras">
				<div class="crm-otras-tit">${__("Otras acciones")}</div>
				<div class="crm-otras-botones">${opciones
					.map(
						(o) =>
							`<button type="button" class="crm-otra ${o.k === "perder" ? "crm-otra-perder" : ""}" aria-expanded="${this.estado.sec === o.k}"
								data-accion="sec" data-valor="${o.k}">${this.e(o.label)}</button>`
					)
					.join("")}</div>
				${confirmar}
			</div>`;
	}

	html_tab_actividad() {
		const op = this.op;
		const af = this.estado.af;
		const falta = [];
		if (!af.tipo) falta.push(__("tipo"));
		if (!af.com.trim()) falta.push(__("comentario"));
		if (!(af.prox || this.prox_por_defecto())) falta.push(__("próximo contacto"));
		const form = op.cerrada
			? ""
			: `
			<div class="crm-form">
				<label>${__("Tipo de actividad")} *<select class="crm-select" data-modelo="af.tipo"><option value="">${__("Elige el tipo")}</option>${op.opciones.tipos_actividad
					.map((t) => `<option ${t === af.tipo ? "selected" : ""}>${this.e(t)}</option>`)
					.join("")}</select></label>
				<label>${__("Comentario")} *<textarea class="crm-textarea" rows="3" data-modelo="af.com" placeholder="${__("Qué se habló y qué quedó pendiente")}">${this.e(af.com)}</textarea></label>
				<label>${__("Próximo contacto")} *<input type="date" class="crm-input" data-modelo="af.prox" min="${this.e(this.datos.hoy)}"
					value="${this.e(af.prox || this.prox_por_defecto())}"></label>
				${this.estado.intento === "act" && falta.length ? `<div role="alert" class="crm-alerta">${this.e(__("Falta: {0}", [falta.join(", ")]))}</div>` : ""}
				${this.estado.act_ok ? `<div role="status" class="crm-ok">${__("Actividad registrada. Los días sin moverse volvieron a 0.")}</div>` : ""}
				<button type="button" class="crm-boton-morado crm-boton-grande" style="font-weight:600" data-accion="guardar-actividad">${__("Guardar Opportunity Activity")}</button>
				<div class="crm-pista">${__("El próximo contacto pasa a ser el próximo paso de la oportunidad.")}</div>
			</div>`;
		const hist = op.historial.length
			? op.historial
					.map(
						(h) => `
				<div class="crm-hist">
					<div class="crm-hist-cab"><strong>${this.e(h.tipo)}</strong><span>${this.e(this.fecha(h.fecha))}${h.autor ? " · " + this.e(h.autor) : ""}</span></div>
					<div class="crm-hist-txt">${this.e(h.comentario)}</div>
					<div class="crm-hist-extra">${h.proximo ? this.e(__("Próximo contacto: {0}", [this.fecha(h.proximo)])) : __("Sin próximo contacto")}</div>
				</div>`
					)
					.join("")
			: `<p class="crm-sub">${__("Sin actividades registradas.")}</p>`;
		const mostradas = op.historial_pagina * op.historial_por_pagina + op.historial.length;
		const paginas =
			op.historial_total > op.historial_por_pagina
				? `<div class="crm-paginas">${this.e(__("Mostrando {0} de {1}", [mostradas, op.historial_total]))}
					${op.historial_pagina > 0 ? `<button type="button" class="crm-enlace" data-accion="historial" data-valor="${op.historial_pagina - 1}">${__("Más recientes")}</button>` : ""}
					${mostradas < op.historial_total ? `<button type="button" class="crm-enlace" data-accion="historial" data-valor="${op.historial_pagina + 1}">${__("Anteriores")}</button>` : ""}</div>`
				: "";
		return `${form}<h3 class="crm-hist-tit">${__("Historial")}</h3>${hist}${paginas}`;
	}

	prox_por_defecto() {
		return frappe.datetime.add_days(this.datos.hoy, 3);
	}

	html_tab_entregables() {
		const op = this.op;
		const df = this.estado.df;
		const falta = [];
		if (!df.tipo) falta.push(__("tipo"));
		if (!df.fecha) falta.push(__("fecha solicitada"));
		if (!df.desc.trim()) falta.push(__("descripción"));
		const tipos = op.opciones.tipos_entregable;
		const form = !tipos.length
			? `<p class="crm-sub" style="margin-top:14px">${__("No hay tipos de entregable configurados (Tipo Entregable).")}</p>`
			: `
			<div class="crm-form">
				<label>${__("Tipo de entregable")} *<select class="crm-select" data-modelo="df.tipo"><option value="">${__("Elige el tipo")}</option>${tipos
					.map((t) => `<option ${t === df.tipo ? "selected" : ""}>${this.e(t)}</option>`)
					.join("")}</select></label>
				<label>${__("Fecha solicitada")} *<input type="date" class="crm-input" data-modelo="df.fecha" min="${this.e(this.datos.hoy)}" value="${this.e(df.fecha)}"></label>
				<label>${__("Descripción")} *<textarea class="crm-textarea" rows="3" data-modelo="df.desc" placeholder="${__("Qué necesita el cliente")}">${this.e(df.desc)}</textarea></label>
				${this.estado.intento === "doc" && falta.length ? `<div role="alert" class="crm-alerta">${this.e(__("Falta: {0}", [falta.join(", ")]))}</div>` : ""}
				<button type="button" class="crm-boton-blanco crm-boton-grande" style="border-color:var(--crm-acento);color:var(--crm-acento-osc);font-weight:600"
					data-accion="solicitar-entregable">${__("Solicitar entregable")}</button>
			</div>`;
		const lista = op.entregables.length
			? op.entregables
					.map(
						(d) => `
				<div class="crm-hist">
					<div class="crm-hist-cab"><a href="/app/documento-entregable/${encodeURIComponent(d.name)}"><strong>${this.e(d.tipo)}</strong></a>
						${this.tag({ clave: d.clave === "gris" ? "gris" : d.clave, texto: d.estado }, d.estado, true)}</div>
					<div class="crm-hist-txt">${this.e(d.descripcion)}</div>
				</div>`
					)
					.join("")
			: `<p class="crm-sub">${__("Aún no hay entregables solicitados.")}</p>`;
		return `${form}<h3 class="crm-hist-tit">${__("Entregables de esta oportunidad")}</h3>${lista}`;
	}

	// ------------------------------------------------------------------
	// Oportunidades por estado e histórico
	// ------------------------------------------------------------------

	html_historico() {
		const h = this.historico;
		if (!h || h.mensaje) return `<section class="crm-historico"></section>`;
		const actual = h.mes_actual;
		const quien = this.es_alcance_individual() ? this.nombre_alcance() : __("Toda la tienda");
		const segmentos = h.estados.map((s) => {
			const n = actual.por_estado[s.clave].cantidad;
			return { ...s, n, pct: actual.total ? Math.round((n / actual.total) * 100) : 0 };
		});
		const corte = this.fecha(h.dia_de_corte);
		const barra = segmentos
			.map((s) => `<div class="crm-c-${this.e(s.clave)}" style="width:${s.pct}%" title="${this.e(s.titulo + ": " + s.n)}"></div>`)
			.join("");
		const lista = segmentos
			.map(
				(s) => `
				<button type="button" class="crm-estado-fila" data-accion="erp" data-doctype="Opportunity" data-nombres="estado:${this.e(s.clave)}">
					<span class="crm-punto crm-c-${this.e(s.clave)}" aria-hidden="true"></span>
					<span>${this.e(s.titulo)}</span>
					<strong class="crm-num">${this.e(s.n)}</strong>
					<span class="crm-estado-pct">${this.e(s.pct)}%</span>
				</button>`
			)
			.join("");
		const leyenda = `<div class="crm-grafica-leyenda">${h.estados
			.map((s) => `<span><span class="crm-punto crm-c-${this.e(s.clave)}" aria-hidden="true"></span>${this.e(s.titulo)}</span>`)
			.join("")}</div>`;
		const grafica = (titulo, sub, valores, segs, campo_nombres, doctype, formato, con_leyenda) => {
			const max = Math.max(1, ...valores);
			const cols = h.meses
				.map((m, i) => {
					const alto = (valores[i] / max) * 120;
					return `
						<button type="button" class="crm-barra-col" data-accion="erp" data-doctype="${doctype}" data-nombres="hist:${campo_nombres}:${i}"
							title="${this.e(m.etiqueta + ": " + formato(valores[i]))}" aria-label="${this.e(m.etiqueta + ": " + formato(valores[i]))}">
							<span class="crm-barra-val">${this.e(formato(valores[i]))}</span>
							${segs(m, i, alto)}
						</button>`;
				})
				.join("");
			return `
				<div class="crm-grafica">
					<div class="crm-grafica-tit">${this.e(titulo)}</div>
					<div class="crm-grafica-sub">${this.e(sub)}</div>
					${con_leyenda ? leyenda : ""}
					<div class="crm-barras">${cols}</div>
					<div class="crm-meses">${h.meses.map((m) => `<div>${this.e(m.etiqueta)}</div>`).join("")}</div>
				</div>`;
		};
		const totales = h.meses.map((m) => Object.values(m.oportunidades).reduce((a, b) => a + b, 0));
		const apiladas = (m, i, alto) =>
			h.estados
				.slice()
				.reverse()
				.map((s) => {
					const v = m.oportunidades[s.clave];
					return `<span class="crm-barra-seg crm-c-${this.e(s.clave)}" style="height:${totales[i] ? Math.max(v ? 2 : 0, (v / totales[i]) * alto) : 0}px"></span>`;
				})
				.join("");
		const simple = (clase) => (m, i, alto) => `<span class="crm-barra-seg ${clase}" style="height:${Math.max(alto > 0 ? 2 : 0, alto)}px"></span>`;
		return `
			<section aria-label="${__("Oportunidades por estado e histórico")}" class="crm-historico crm-card">
				<div class="crm-historico-fila">
					<div class="crm-estados">
						<h2>${this.e(__("Oportunidades por estado · {0}", [this.texto_modelos()]))}</h2>
						<p class="crm-historico-sub">${this.e(
							__("{0} · creadas en {1} (al {2}) · {3} oportunidades", [quien, this.mes_en_texto(), corte, actual.total])
						)}</p>
						<p class="crm-nota">${__("Tasa de cierre de los últimos {0} meses:", [h.meses.length])} <strong>${
			h.tasa_cierre == null ? "—" : this.e(h.tasa_cierre + "%")
		}</strong> ${__("(ganadas ÷ ganadas + perdidas)")}</p>
						<div class="crm-barra-estados" role="img" aria-label="${this.e(segmentos.map((s) => s.titulo + " " + s.n).join(", "))}">${barra}</div>
						<div class="crm-estados-lista">${lista}</div>
					</div>
					<div class="crm-graficas-col">
						<h2>${this.e(__("Histórico · últimos {0} meses · {1}", [h.meses.length, this.texto_modelos()]))}</h2>
						<p class="crm-historico-sub">${this.e(__("Calculado para {0} · el mes en curso va al {1} · toca una barra para ver sus registros", [quien, corte]))}</p>
						<div class="crm-graficas">
							${grafica(__("Oportunidades creadas"), __("por mes, según su estado actual"), totales, apiladas, "nombres_oportunidades", "Opportunity", String, true)}
							${grafica(
								__("Monto cotizado"),
								__("cotizaciones enviadas por mes, sin IVA"),
								h.meses.map((m) => m.cotizado),
								simple("crm-c-cotizada"),
								"nombres_cotizado",
								"Quotation",
								(n) => this.compacto(n),
								false
							)}
							${grafica(
								__("Venta facturada"),
								__("Sales Person de {0}", [this.datos.modelos.join(" + ")]),
								h.meses.map((m) => m.facturado),
								simple("crm-c-ganada"),
								"nombres_facturado",
								"Sales Invoice",
								(n) => this.compacto(n),
								false
							)}
						</div>
					</div>
				</div>
			</section>`;
	}

	// ------------------------------------------------------------------
	// Consolidado por asesor
	// ------------------------------------------------------------------

	pintar_consolidado() {
		this.$body.find(".crm-consolidado").html(this.html_consolidado());
	}

	claves_cons() {
		const c = this.consolidado;
		return this.estado.modo_cons ? [this.estado.modo_cons] : c.modelos.concat([c.total]);
	}

	html_consolidado() {
		const c = this.consolidado;
		if (!c || c.mensaje) return "";
		const modos = [["", this.texto_modelos()]].concat(c.modelos.map((m) => [m, __("Solo {0}", [m])]));
		const nota = c.vista_tienda
			? `<strong>${__("Resumen de la tienda.")}</strong> ${__(
					"Toca «Ver como lo ve…» en la tarjeta de un asesor para abrir su consolidado tal como él lo ve, con sus documentos y el cálculo factura por factura."
			  )}`
			: `<strong>${__("Toca un monto subrayado")}</strong> ${__(
					"para ver sus documentos vinculados. Facturado = facturas del mes atribuidas por la tabla Comisiones Asesor de su orden de venta (o creadas por el asesor sin orden), no por el Sales Team. Montos sin IVA."
			  )}`;
		return `
			<div class="crm-cons-cab">
				<div>
					<h2>${__("Consolidado por asesor")}</h2>
					<p class="crm-sub" style="margin:2px 0 0">${this.e(
						__("{0} · separado por el Sales Person de cada modelo de cada asesor", [this.subtitulo_mes()])
					)}</p>
				</div>
				<div role="group" aria-label="${__("Separar por modelo de venta")}" class="crm-cons-modos">${modos
					.map(
						([v, l]) =>
							`<button type="button" class="crm-pildora crm-pildora-oscura crm-pildora-sm" aria-pressed="${this.estado.modo_cons === v}"
								data-accion="modo-cons" data-valor="${this.e(v)}">${this.e(l)}</button>`
					)
					.join("")}</div>
			</div>
			<p class="crm-nota">${nota}</p>
			<div class="crm-cons-tarjetas">${c.tarjetas.map((t, i) => this.html_tarjeta_cons(t, i)).join("")}</div>
			${this.estado.det ? this.html_documentos() : ""}`;
	}

	subtitulo_mes() {
		const corte = this.texto_corte();
		return this.datos.etiqueta_mes + (corte ? " " + corte : "");
	}

	clase_modelo(k) {
		const c = this.consolidado;
		if (k === c.total) return "crm-th-total";
		return this.es_modelo_principal(k) ? "crm-th-proyectos" : "crm-th-retail";
	}

	html_tarjeta_cons(t, i) {
		const c = this.consolidado;
		const claves = this.claves_cons();
		const detalle = t.detalle;
		const celda = (k, campo, v, sub, doctype) => {
			const td = k === c.total ? "crm-td-total" : "";
			const contenido = `<strong>${this.e(v)}</strong><span>${this.e(sub || "")}</span>`;
			if (!campo) return `<td class="${td}"><div class="crm-celda-plana">${contenido}</div></td>`;
			if (detalle && ["facturas", "ordenes", "cotizado", "vigentes"].includes(campo)) {
				const on = this.estado.det && this.estado.det.tarjeta === i && this.estado.det.modelo === k && this.estado.det.tipo === campo;
				return `<td class="${td}"><button type="button" class="crm-celda" aria-pressed="${!!on}" title="${__("Ver los documentos")}"
					data-accion="documentos" data-tarjeta="${i}" data-modelo="${this.e(k)}" data-tipo="${campo}">${contenido}</button></td>`;
			}
			return `<td class="${td}"><button type="button" class="crm-celda" data-accion="erp" data-doctype="${doctype}"
				data-nombres="cons:${i}:${this.e(k)}:${campo}">${contenido}</button></td>`;
		};
		const filas = [
			[__("Meta del mes"), (k, x) => celda(k, null, this.dinero(x.meta))],
			[__("Facturado"), (k, x) => celda(k, "facturas", this.dinero(x.facturado), __("{0} facturas · {1}%", [x.facturas.length, x.porcentaje]), "Sales Invoice")],
			[__("Órdenes de venta del mes"), (k, x) => celda(k, "ordenes", this.dinero(x.ordenes.monto), __("{0} órdenes", [x.ordenes.nombres.length]), "Sales Order")],
			[__("Cotizado en el mes"), (k, x) => celda(k, "cotizado", this.dinero(x.cotizado.monto), __("{0} cotizaciones", [x.cotizado.nombres.length]), "Quotation")],
			[__("Cotizaciones vigentes"), (k, x) => celda(k, "vigentes", this.dinero(x.vigentes.monto), __("{0} abiertas", [x.vigentes.nombres.length]), "Quotation")],
			[__("Oportunidades abiertas"), (k, x) => celda(k, "abiertas", String(x.abiertas.cantidad), "", "Opportunity")],
			[
				__("Oportunidades creadas en {0}", [this.mes_en_texto()]),
				(k, x) => celda(k, "creadas", String(x.creadas.cantidad), __("{0} ganadas · {1} perdidas", [x.creadas.ganadas, x.creadas.perdidas]), "Opportunity"),
			],
		];
		const cabeza = (primera) =>
			`<thead><tr><th>${this.e(primera)}</th>${claves.map((k) => `<th class="${this.clase_modelo(k)}">${this.e(k)}</th>`).join("")}</tr></thead>`;
		const tabla = `
			<div class="crm-scroll" style="margin-top:10px">
				<table class="crm-tabla crm-tabla-cons">
					${cabeza(__("Indicador"))}
					<tbody>${filas.map(([l, f]) => `<tr><td>${this.e(l)}</td>${claves.map((k) => f(k, t.columnas[k])).join("")}</tr>`).join("")}</tbody>
				</table>
			</div>`;
		const abrir =
			c.vista_tienda && !t.es_tienda
				? `<button type="button" class="crm-cons-abrir" data-accion="asesor" data-valor="${this.e(t.empleado)}">${this.e(
						__("Ver como lo ve {0} →", [this.primer_nombre(t.nombre)])
				  )}</button>`
				: "";
		return `
			<div class="crm-cons-tarjeta ${t.es_tienda ? "crm-cons-tarjeta-tienda" : ""}">
				<div class="crm-cons-tarjeta-cab"><strong>${this.e(t.nombre)}</strong>${this.tag(t.estado, t.estado.texto)}${abrir}</div>
				${tabla}
				${this.html_comision(t, i, cabeza)}
				${this.html_barras_cons(t)}
			</div>`;
	}

	html_comision(t, i, cabeza) {
		const claves = this.claves_cons();
		const r = t.comision.resumen;
		const tasa = (x) => (x.tasas.length ? x.tasas.map((v) => v + "%").join(" / ") : "—");
		const fila = (label, f, clase) =>
			`<tr class="${clase || ""}"><td>${this.e(label)}</td>${claves
				.map((k) => {
					const [v, sub] = f(r[k]);
					return `<td class="${k === this.consolidado.total && !clase ? "crm-td-total" : ""}"><div class="crm-celda-plana"><strong>${this.e(v)}</strong><span>${this.e(
						sub || ""
					)}</span></div></td>`;
				})
				.join("")}</tr>`;
		const mes = this.mes_en_texto();
		const resumen = `
			<div class="crm-scroll">
				<table class="crm-tabla crm-tabla-cons">
					${cabeza(__("Cálculo"))}
					<tbody>
						${fila(__("Facturas atribuidas en {0}", [mes]), (x) => [this.dinero(x.atribuido), __("{0} facturas · neto × distribución", [x.cantidad])])}
						${fila(__("Cantidad pagada"), (x) => [this.dinero(x.cobrado), __("{0}% de lo facturado", [x.atribuido ? Math.round((x.cobrado / x.atribuido) * 100) : 0])])}
						${fila(__("× commission_rate del Sales Person"), (x) => [tasa(x), __("campo commission_rate")])}
						${fila(__("÷ 100 = Comisión"), (x) => [this.dinero(x.comision), ""], "crm-fila-comision")}
						${fila(__("Comisión futura (cuando el cliente pague)"), (x) => [this.dinero(x.futura), __("saldo pendiente sin IVA × tasa ÷ 100")], "crm-fila-futura")}
					</tbody>
				</table>
			</div>`;
		const abierta = this.estado.com_abierta === i;
		const filas_todas = t.comision.filas;
		let detalle = "";
		if (t.detalle) {
			const grupos = (this.estado.modo_cons ? [this.estado.modo_cons] : this.consolidado.modelos)
				.map((m) => {
					const lista = filas_todas.filter((f) => f.modelo === m);
					const com = lista.reduce((s, f) => s + f.comision, 0);
					const fut = lista.reduce((s, f) => s + f.futura, 0);
					const clase = this.es_modelo_principal(m) ? "crm-grupo-proyectos" : "crm-grupo-retail";
					return `
						<tr class="${clase}"><td colspan="11"><strong>${this.e(m)}</strong> <span class="crm-sub">· ${this.e(
						__("{0} facturas · comisión {1} · comisión futura {2}", [lista.length, this.dinero(com), this.dinero(fut)])
					)}</span></td></tr>
						${
							lista.length
								? lista
										.map(
											(f) => `
						<tr>
							<td class="crm-izq"><a class="crm-mono" href="/app/sales-invoice/${encodeURIComponent(f.factura)}"><strong>${this.e(f.factura)}</strong></a>
								<span class="crm-formula">${this.e(this.fecha(f.fecha))}${f.nota_de_credito ? " · " + __("nota de crédito") : ""}${f.propia ? " · " + __("sin orden") : ""}</span></td>
							<td class="crm-izq">${this.e(f.cliente)}</td>
							<td>${this.e(this.dinero(f.neto))}</td><td>${this.e(this.dinero(f.gran_total))}</td><td>${this.e(this.dinero(f.saldo))}</td>
							<td>${this.e(this.dinero(f.cobrado))}</td><td>${this.e(f.distribucion)}%</td><td>${this.e(f.tasa)}%</td>
							<td><strong class="${f.comision > 0 ? "crm-celda-ok" : ""}">${this.e(this.dinero(f.comision))}</strong>
								<span class="crm-formula">${this.e(this.dinero(f.cobrado) + (f.distribucion !== 100 ? ` × ${f.distribucion}%` : "") + ` × ${f.tasa} ÷ 100`)}</span></td>
							<td>${this.e(this.dinero(f.por_cobrar))}</td>
							<td><strong>${this.e(this.dinero(f.futura))}</strong><span class="crm-formula">${this.e(this.dinero(f.por_cobrar) + ` × ${f.tasa} ÷ 100`)}</span></td>
						</tr>`
										)
										.join("")
								: `<tr><td colspan="11" class="crm-izq crm-sub">${this.e(__("Sin facturas de {0}.", [m]))}</td></tr>`
						}`;
				})
				.join("");
			const cuantas = this.estado.modo_cons ? filas_todas.filter((f) => f.modelo === this.estado.modo_cons).length : filas_todas.length;
			detalle = `
				<button type="button" class="crm-boton-com" data-accion="toggle-comision" data-valor="${i}" aria-expanded="${abierta}">${this.e(
				__("{0} el cálculo factura por factura ({1})", [abierta ? __("Ocultar") : __("Ver"), cuantas])
			)}</button>
				${
					abierta
						? `<div class="crm-scroll" style="margin-top:8px"><table class="crm-tabla crm-tabla-facturas">
							<thead><tr>
								<th class="crm-izq">${__("Factura")}</th><th class="crm-izq">${__("Cliente")}</th><th>net_total</th><th>grand_total</th><th>outstanding</th>
								<th>${__("Pagado")}</th><th>${__("Distribución")}</th><th>${__("Tasa")}</th><th>${__("Comisión")}</th><th>${__("Por cobrar")}</th><th>${__("Comisión futura")}</th>
							</tr></thead>
							<tbody>${grupos}</tbody></table></div>`
						: ""
				}`;
		}
		return `
			<div class="crm-cons-seccion">
				<div class="crm-cons-seccion-tit">${this.e(__("Operación de comisión · {0}", [mes]))}</div>
				<p class="crm-nota" style="margin-top:4px">${__("Por cada factura:")} <strong>${__("cantidad pagada × commission_rate del Sales Person ÷ 100")}</strong>. ${__(
			"Cantidad pagada = net_total × (grand_total − outstanding_amount) ÷ grand_total, para quitar el IVA del saldo pendiente. La factura se atribuye al asesor por la tabla"
		)} <strong>${__("Comisiones Asesor")}</strong> ${__("de su orden de venta, no por el Sales Team de la factura.")}</p>
				${resumen}
				${detalle}
			</div>`;
	}

	html_barras_cons(t) {
		const modelos = this.estado.modo_cons ? [this.estado.modo_cons] : this.consolidado.modelos;
		const totales = t.barras.map((b) => modelos.reduce((s, m) => s + (b.por_modelo[m] || 0), 0));
		const max = Math.max(1, ...totales);
		const cols = t.barras
			.map((b, i) => {
				const alto = (totales[i] / max) * 70;
				const segs = modelos
					.slice()
					.reverse()
					.map((m) => {
						const v = b.por_modelo[m] || 0;
						const clase = this.es_modelo_principal(m) ? "crm-c-proyectos" : "crm-c-retail";
						return `<span class="crm-barra-seg ${clase}" style="height:${totales[i] ? (v / totales[i]) * alto : 0}px"></span>`;
					})
					.join("");
				const tip = b.etiqueta + ": " + modelos.map((m) => m + " " + this.dinero(b.por_modelo[m] || 0)).join(" · ");
				return `<div class="crm-barra-col" title="${this.e(tip)}" role="img" aria-label="${this.e(tip)}">
					<span class="crm-barra-val">${this.e(this.compacto(totales[i]))}</span>${segs}</div>`;
			})
			.join("");
		const rango = t.barras.length ? `${t.barras[0].etiqueta.toLowerCase()} a ${t.barras[t.barras.length - 1].etiqueta.toLowerCase()}` : "";
		return `
			<div style="margin-top:12px">
				<div style="font-size:12px;font-weight:600">${this.e(__("Facturado por mes · {0}", [rango]))}</div>
				<div class="crm-grafica-leyenda">${modelos
					.map((m) => `<span><span class="crm-punto ${this.es_modelo_principal(m) ? "crm-c-proyectos" : "crm-c-retail"}" aria-hidden="true"></span>${this.e(m)}</span>`)
					.join("")}</div>
				<div class="crm-barras crm-barras-bajas">${cols}</div>
				<div class="crm-meses">${t.barras.map((b) => `<div>${this.e(b.etiqueta)}</div>`).join("")}</div>
			</div>`;
	}

	// Documentos vinculados: oportunidad → cotización → orden de venta → factura.
	html_documentos() {
		const c = this.consolidado;
		const det = this.estado.det;
		const t = c.tarjetas[det.tarjeta];
		if (!t || !t.documentos) return "";
		const docs = t.documentos;
		const fuente = { facturas: docs.facturas, ordenes: docs.ordenes, cotizado: docs.cotizaciones_mes, vigentes: docs.cotizaciones_vigentes };
		const titulos = { facturas: __("Facturas"), ordenes: __("Órdenes de venta"), cotizado: __("Cotizaciones del mes"), vigentes: __("Cotizaciones vigentes") };
		const ayudas = {
			facturas: __("Facturas del mes atribuidas al asesor por la tabla Comisiones Asesor de su orden de venta (con su % de distribución), más las que él creó sin orden de venta. Son las que cuentan para la meta."),
			ordenes: __("Órdenes de venta del mes separadas por su modelo de venta. Una orden cuenta para la meta cuando se factura."),
			cotizado: __("Cotizaciones enviadas en el mes, con su estado actual y la oportunidad de la que vienen."),
			vigentes: __("Cotizaciones abiertas y vigentes hoy: lo que todavía puede convertirse en orden."),
		};
		const del_modelo = (lista) => (det.modelo === c.total ? lista : lista.filter((x) => x.modelo === det.modelo));
		const ruta = { op: "opportunity", qt: "quotation", so: "sales-order", inv: "sales-invoice" };
		const chip = (nombre, tipo) =>
			nombre ? `<a class="crm-doc crm-doc-${tipo}" href="/app/${ruta[tipo]}/${encodeURIComponent(nombre)}">${this.e(nombre)}</a>` : "";
		const estados_cot = { Open: __("Abierta"), Expired: __("Vencida"), Ordered: __("Con orden de venta"), "Partially Ordered": __("Con orden parcial"), Lost: __("Perdida") };
		const tipo_doc = { facturas: "inv", ordenes: "so", cotizado: "qt", vigentes: "qt" }[det.tipo];
		const fila = (x) => {
			let enlaces = "";
			let estado = "";
			let tono = "gris";
			let nota = "";
			if (det.tipo === "facturas") {
				enlaces = chip(x.oportunidad, "op") + chip(x.cotizacion, "qt") + chip(x.orden, "so");
				estado = __("Cuenta para la meta");
				tono = "verde";
				nota = x.propia
					? __("Sin orden de venta: la creó el asesor")
					: __("Orden de venta {0}", [x.modelo]) + (x.distribucion !== 100 ? " · " + __("{0}% de distribución", [x.distribucion]) : "");
				if (!x.oportunidad) nota += " · " + __("sin oportunidad");
			} else if (det.tipo === "ordenes") {
				enlaces = chip(x.oportunidad, "op") + chip(x.cotizacion, "qt") + x.facturas.map((f) => chip(f, "inv")).join("");
				estado = x.facturado >= 100 ? __("Facturada 100%") : x.facturado > 0 ? __("Facturada {0}%", [Math.round(x.facturado)]) : __("Sin facturar");
				tono = x.facturado >= 100 ? "verde" : "amarillo";
				nota = x.oportunidad ? "" : __("Sin oportunidad ni cotización ligada");
			} else {
				enlaces = chip(x.oportunidad, "op");
				estado = estados_cot[x.status] || x.status;
				tono = x.status === "Ordered" ? "verde" : x.status === "Expired" ? "rojo" : "gris";
				nota = x.oportunidad ? "" : __("Sin oportunidad");
			}
			return `
				<tr>
					<td>${chip(x.name, tipo_doc)}</td>
					<td style="white-space:nowrap">${this.e(this.fecha(x.fecha))}</td>
					<td>${this.e(x.cliente)}</td>
					<td class="crm-der crm-num" style="font-weight:600;white-space:nowrap">${this.e(this.dinero(x.monto))}</td>
					<td><div class="crm-enlaces">${enlaces || "—"}</div></td>
					<td>${this.tag({ clave: tono, texto: estado }, estado, true)}${nota ? `<span class="crm-doc-nota ${tono === "amarillo" ? "crm-doc-nota-mal" : ""}">${this.e(nota)}</span>` : ""}</td>
				</tr>`;
		};
		const lista = del_modelo(fuente[det.tipo]).slice().sort((a, b) => b.monto - a.monto);
		const suma = (l) => l.reduce((s, x) => s + x.monto, 0);
		const grupos = (det.modelo === c.total ? c.modelos : [det.modelo])
			.map((m) => {
				const filas = lista.filter((x) => x.modelo === m);
				const clase = this.es_modelo_principal(m) ? "crm-grupo-proyectos" : "crm-grupo-retail";
				return `
					<tr class="${clase}"><td colspan="6"><span class="crm-punto ${this.es_modelo_principal(m) ? "crm-c-proyectos" : "crm-c-retail"}" style="margin-right:6px"></span><strong>${this.e(
					m
				)}</strong> <span class="crm-sub">· ${this.e(__("{0} documentos · {1}", [filas.length, this.dinero(suma(filas))]))}</span></td></tr>
					${filas.length ? filas.map(fila).join("") : `<tr><td colspan="6" class="crm-sub">${this.e(__("Sin documentos de {0}.", [m]))}</td></tr>`}`;
			})
			.join("");
		const modelos = [[c.total, __("{0} (separados)", [this.texto_modelos()])]].concat(c.modelos.map((m) => [m, __("Solo {0}", [m])]));
		const tabs = Object.keys(titulos)
			.map(
				(k) =>
					`<button type="button" role="tab" class="crm-pildora crm-pildora-oscura crm-pildora-sm" aria-selected="${det.tipo === k}" aria-pressed="${det.tipo === k}"
						data-accion="tipo-docs" data-valor="${k}">${this.e(titulos[k] + " (" + del_modelo(fuente[k]).length + ")")}</button>`
			)
			.join("");
		const total_txt =
			det.modelo === c.total
				? __("Total: {0} en {1} documentos ({2}).", [
						this.dinero(suma(lista)),
						lista.length,
						c.modelos.map((m) => m + " " + this.dinero(suma(lista.filter((x) => x.modelo === m)))).join(" · "),
				  ])
				: __("Total: {0} en {1} documentos.", [this.dinero(suma(lista)), lista.length]);
		return `
			<div class="crm-docs">
				<div class="crm-docs-cab">
					<div>
						<h3>${this.e(__("Documentos vinculados · {0}", [t.nombre]))}</h3>
						<p>${__("Cada documento con la cadena que lo une al resto: oportunidad → cotización → orden de venta → factura.")}</p>
					</div>
					<button type="button" class="crm-cerrar" data-accion="cerrar-docs" aria-label="${__("Cerrar documentos")}">×</button>
				</div>
				<div role="group" aria-label="${__("Modelo de venta")}" class="crm-docs-filtros">
					<span class="crm-sub">${__("Mostrar:")}</span>
					${modelos
						.map(
							([v, l]) =>
								`<button type="button" class="crm-pildora crm-pildora-oscura crm-pildora-sm" aria-pressed="${det.modelo === v}"
									data-accion="modelo-docs" data-valor="${this.e(v)}">${this.e(l)}</button>`
						)
						.join("")}
				</div>
				<div role="tablist" aria-label="${__("Tipo de documento")}" class="crm-docs-filtros" style="margin-top:10px">${tabs}</div>
				<p class="crm-docs-hint">${this.e(ayudas[det.tipo] + " " + total_txt)}</p>
				<div class="crm-scroll" style="margin-top:8px">
					<table class="crm-tabla crm-tabla-docs">
						<thead><tr><th>${__("Documento")}</th><th>${__("Fecha")}</th><th>${__("Cliente")}</th><th class="crm-der">${__("Monto")}</th>
							<th>${__("Documentos vinculados")}</th><th>${__("Estado")}</th></tr></thead>
						<tbody>${grupos}</tbody>
					</table>
				</div>
			</div>`;
	}

	// ------------------------------------------------------------------
	// Eventos
	// ------------------------------------------------------------------

	// Los botones data-accion y los selects data-cambio los reparte la plantilla
	// (accion / cambio); aquí solo los campos que se guardan y los formularios.
	enlazar_eventos() {
		const $b = this.$body;
		$b.on("change", "[data-campo]", (ev) => {
			const $c = $(ev.currentTarget);
			this.guardar_campo($c.attr("data-campo"), $c.val());
		});
		// Valores de formularios que se conservan entre repintados del panel.
		$b.on("input change", "[data-modelo]", (ev) => {
			const $c = $(ev.currentTarget);
			const ruta = $c.attr("data-modelo").split(".");
			if (ruta.length === 1) this.estado[ruta[0]] = $c.val();
			else this.estado[ruta[0]][ruta[1]] = $c.val();
			if (ruta[0] === "af") this.estado.act_ok = false;
		});
	}

	cambio(clave, valor) {
		if (clave === "filtro_modelo" || clave === "filtro_tipo") {
			this.estado[clave] = valor;
			this.repintar_embudo();
			this.marcar_tarjeta();
		}
	}

	accion(nombre, $t) {
		const valor = $t.attr("data-valor");
		const name = $t.attr("data-name");
		const acciones = {
			vista: () => {
				this.estado.vista = valor;
				this.pintar();
				if (valor === "consolidado" && !this.consolidado) this.cargar_consolidado();
				if (valor === "embudo" && !this.historico) this.cargar_historico();
			},
			erp: () => crm_tableros.abrir_lista($t.attr("data-doctype"), this.nombres_de($t.attr("data-nombres"), $t.attr("data-fila"))),
			"erp-lista": () => this.lista_actual && crm_tableros.abrir_lista(this.lista_actual.doctype, this.lista_actual.nombres),
			lista: () => {
				Object.assign(this.estado, { lista: valor, sel: null });
				this.op = null;
				this.pintar_panel();
				this.marcar_tarjeta();
			},
			"cerrar-lista": () => {
				this.estado.lista = null;
				this.pintar_panel();
			},
			abrir: () => {
				const lista = this.estado.lista;
				this.cargar_oportunidad(name, true, $t.attr("data-tab") || "datos").then(() => {
					// Al volver desde el detalle se regresa a la lista de la que vino.
					this.estado.lista = lista;
					this.pintar_panel();
				});
			},
			"cerrar-detalle": () => {
				this.estado.sel = null;
				this.op = null;
				this.pintar_panel();
				this.marcar_tarjeta();
			},
			tab: () => {
				this.estado.tab = valor;
				this.estado.intento = null;
				this.pintar_panel();
			},
			"toggle-cerradas": () => {
				this.estado.ver_cerradas = !this.estado.ver_cerradas;
				this.repintar_embudo();
				this.marcar_tarjeta();
			},
			historial: () => this.cargar_oportunidad(this.op.name, false, "actividad", Number(valor)),
			primaria: () => this.primaria(),
			"modo-ganar": () => {
				Object.assign(this.estado.ganar, { modo: valor, intento: false });
				this.pintar_panel();
			},
			"elegir-orden": () => {
				Object.assign(this.estado.ganar, { orden: valor, intento: false });
				this.pintar_panel();
			},
			"cancelar-ganar": () => {
				this.estado.ganar = null;
				this.pintar_panel();
			},
			"confirmar-ganar": () => this.confirmar_ganar(),
			sec: () => {
				this.estado.sec = this.estado.sec === valor ? null : valor;
				this.estado.intento = null;
				this.pintar_panel();
			},
			"confirmar-sec": () => this.confirmar_secundaria(),
			"crear-cotizacion": () =>
				frappe.model.open_mapped_doc({ method: "erpnext.crm.doctype.opportunity.opportunity.make_quotation", source_name: this.op.name }),
			"guardar-actividad": () => this.guardar_actividad(),
			"solicitar-entregable": () => this.solicitar_entregable(),
			renovar: () => this.renovar(name),
			"perder-cotizacion": () => {
				Object.assign(this.estado, { perdiendo: name, motivo_vencida: "", intento_vencida: false });
				this.pintar_panel();
			},
			"cancelar-perder-cotizacion": () => {
				this.estado.perdiendo = null;
				this.pintar_panel();
			},
			"confirmar-perder-cotizacion": () => this.perder_cotizacion(name),
			"modo-cons": () => {
				this.estado.modo_cons = valor;
				this.pintar_consolidado();
			},
			"toggle-comision": () => {
				this.estado.com_abierta = this.estado.com_abierta === Number(valor) ? null : Number(valor);
				this.pintar_consolidado();
			},
			documentos: () => {
				this.estado.det = { tarjeta: Number($t.attr("data-tarjeta")), modelo: $t.attr("data-modelo"), tipo: $t.attr("data-tipo") };
				this.pintar_consolidado();
				const $d = this.$body.find(".crm-docs");
				if ($d.length) $d[0].scrollIntoView({ behavior: "smooth", block: "start" });
			},
			"modelo-docs": () => {
				this.estado.det.modelo = valor;
				this.pintar_consolidado();
			},
			"tipo-docs": () => {
				this.estado.det.tipo = valor;
				this.pintar_consolidado();
			},
			"cerrar-docs": () => {
				this.estado.det = null;
				this.pintar_consolidado();
			},
		};
		if (acciones[nombre]) acciones[nombre]();
	}

	// ------------------------------------------------------------------
	// Acciones sobre la oportunidad
	// ------------------------------------------------------------------

	primaria() {
		const sig = this.op.siguiente;
		if (!sig) return;
		if (sig.faltantes.length && sig.clave !== "ganada") {
			this.estado.intento = "prim";
			this.pintar_panel();
			return;
		}
		if (sig.clave === "ganada") {
			this.estado.ganar = this.estado.ganar || { modo: this.op.cotizacion_para_orden ? "nueva" : "vincular", fecha: "", orden: "", intento: false };
			this.pintar_panel();
			return;
		}
		this.mover(sig.clave);
	}

	confirmar_ganar() {
		const g = this.estado.ganar;
		if (g.modo === "nueva") {
			if (!g.fecha) {
				g.intento = true;
				this.pintar_panel();
				return;
			}
			crm_tableros.llamar(API_PROYECTOS + "crear_orden_de_venta", { nombre: this.op.name, delivery_date: g.fecha }).then((orden) => {
				this.estado.ganar = null;
				frappe.show_alert({ message: __("Orden de venta {0} creada en borrador. Revísala y envíala para marcar la oportunidad como ganada.", [orden]), indicator: "green" }, 8);
				frappe.set_route("Form", "Sales Order", orden);
			});
			return;
		}
		if (!g.orden) {
			g.intento = true;
			this.pintar_panel();
			return;
		}
		crm_tableros.llamar(API_PROYECTOS + "vincular_orden_de_venta", { nombre: this.op.name, sales_order: g.orden }).then(() => {
			this.estado.ganar = null;
			this.estado.sel = null;
			this.op = null;
			this.refrescar_tras_accion(__("Ganada con la orden de venta {0}.", [g.orden]));
		});
	}

	confirmar_secundaria() {
		const sel = this.opciones_secundarias().find((o) => o.k === this.estado.sec);
		if (!sel) return;
		const v = this.estado.sec_vals;
		if (this.faltantes_secundaria(sel).length) {
			this.estado.intento = "sec";
			this.pintar_panel();
			return;
		}
		if (sel.k === "regresar") this.mover(sel.d.clave);
		else if (sel.k === "pausa") this.mover("pausa", { fecha_retomar: v.retomar });
		else this.mover("perdida", { motivo: v.motivo, detalle: v.detalle });
	}

	mover(etapa, extra = {}) {
		return crm_tableros.llamar(API_PROYECTOS + "mover_etapa", { nombre: this.op.name, etapa, ...extra }).then((r) => {
			this.reiniciar_formularios();
			if (["Lost", "Converted"].includes(r.status)) {
				this.estado.sel = null;
				this.op = null;
			}
			const prob = r.probability == null ? "" : " · " + __("probabilidad {0}%", [r.probability]);
			return this.refrescar_tras_accion(__("Etapa: {0}", [r.etapa]) + prob);
		});
	}

	guardar_campo(campo, valor) {
		if (!this.op) return;
		crm_tableros
			.llamar(API_PROYECTOS + "guardar_datos", { nombre: this.op.name, datos: { [campo]: valor } }, { freeze: false })
			.then(() => this.refrescar_tras_accion(__("Guardado")));
	}

	guardar_actividad() {
		const af = this.estado.af;
		const prox = af.prox || this.prox_por_defecto();
		if (!af.tipo || !af.com.trim() || !prox) {
			this.estado.intento = "act";
			this.pintar_panel();
			return;
		}
		crm_tableros
			.llamar(API_PROYECTOS + "registrar_actividad", { nombre: this.op.name, activity_type: af.tipo, comment: af.com, next_contact_date: prox })
			.then(() => {
				Object.assign(this.estado, { af: this.actividad_vacia(), act_ok: true, intento: null, tab: "actividad" });
				// cargar() vuelve a pedir la oportunidad abierta sin reiniciar el panel.
				this.cargar();
			});
	}

	solicitar_entregable() {
		const df = this.estado.df;
		if (!df.tipo || !df.fecha || !df.desc.trim()) {
			this.estado.intento = "doc";
			this.pintar_panel();
			return;
		}
		crm_tableros
			.llamar(API_PROYECTOS + "solicitar_entregable", { nombre: this.op.name, tipo_entregable: df.tipo, fecha: df.fecha, descripcion: df.desc })
			.then(() => {
				Object.assign(this.estado, { df: { tipo: "", fecha: "", desc: "" }, intento: null });
				frappe.show_alert({ message: __("Entregable solicitado"), indicator: "green" });
				this.cargar_oportunidad(this.op.name, false);
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
		if (!this.estado.motivo_vencida) {
			this.estado.intento_vencida = true;
			this.pintar_panel();
			return;
		}
		crm_tableros
			.llamar(API_PROYECTOS + "perder_cotizacion", { cotizacion, motivo: this.estado.motivo_vencida })
			.then(() => {
				Object.assign(this.estado, { perdiendo: null, motivo_vencida: "", intento_vencida: false });
				this.refrescar_tras_accion(__("Cotización dada por perdida"));
			});
	}
}
