// Pruebas de la fase 4: leyendas plegables (P2) y la estructura de Mi día de la que depende el
// CSS compacto (A4). Corren sin Frappe ni navegador, como embudo_por_partes.test.js.
// Ejecutar desde la raíz del repo: node --test crm_dashboard_v3/crm_tableros/tests/js/

const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP = path.resolve(__dirname, "../../..");
const ARCHIVOS = [
	path.join(APP, "public/js/crm_tableros/common.js"),
	path.join(APP, "crm_dashboard_v3/page/crm_proyectos/crm_proyectos.js"),
];

function cargar(extra = {}) {
	const contexto = {
		frappe: {
			provide(nombre) {
				contexto[nombre] = contexto[nombre] || {};
			},
			pages: { "crm-proyectos": {} },
			utils: {
				escape_html: (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
			},
			datetime: { get_diff: () => 1 },
		},
		__: (texto, args) => String(texto).replace(/\{(\d+)\}/g, (m, i) => (args ? args[i] : m)),
		format_currency: (monto, moneda) => `${moneda} ${Number(monto).toFixed(2)}`,
		CSS: { escape: (s) => s },
		...extra,
	};
	vm.createContext(contexto);
	ARCHIVOS.forEach((archivo) => vm.runInContext(fs.readFileSync(archivo, "utf8"), contexto, { filename: archivo }));
	return vm.runInContext("TableroProyectos", contexto);
}

const TableroProyectos = cargar();

function tarjeta(name, { revision = false } = {}) {
	return {
		name,
		cliente: `Cliente ${name}`,
		modelo: "Proyectos",
		monto: 1000,
		dias: 3,
		semaforo: { clave: "verde", texto: "", color: "" },
		tipo: "Diseño",
		asesor: "",
		proximo: { estado: "ok", texto: "Llamar", fecha: "2026-11-30" },
		etapa: "En pausa",
		extra: revision ? "Para revisión: sin orden" : "",
		revision,
	};
}

function tablero(clase = TableroProyectos) {
	const t = Object.create(clase.prototype);
	t.estado = {
		filtro_modelo: "",
		filtro_tipo: "",
		solo_accion: false,
		orden: "monto",
		expandidas: {},
		ver_requisitos: false,
		ayuda_abierta: false,
		ver_cerradas: true,
		sel: null,
		perdiendo: null,
		motivo_vencida: "",
		intento_vencida: false,
	};
	t.datos = {
		moneda: "GTQ",
		modelos: ["Proyectos"],
		tipos: ["Diseño"],
		hoy: "2026-11-26",
		es_jefe: false,
		dias_verde_max: 7,
		dias_amarillo_max: 14,
		motivos: ["Precio"],
		columnas: [
			{ clave: "calificar", titulo: "1 · Calificar", probabilidad: 10, requisitos: "cliente, tipo y origen", tarjetas: [tarjeta("OP-1")] },
			{ clave: "requerimiento", titulo: "2 · Requerimiento y diseño", probabilidad: 25, requisitos: "monto y fecha de cierre", tarjetas: [] },
		],
		cerradas: [{ clave: "ganada", titulo: "Ganada", tarjetas: [tarjeta("OP-9", { revision: true })] }],
		vencidas: [{ name: "QTN-0001", cliente: "Cliente Q", modelo: "Proyectos", asesor: "", dias_cotizada: 40, monto: 5000 }],
		mi_dia: [
			{ clave: "vencidas", titulo: "Cotizaciones vencidas", tono: "rojo", cantidad: 1, ayuda: "{0} por renovar", ayuda_args: [5000], items: [] },
			{ clave: "sin_paso", titulo: "Sin próximo paso", tono: "amarillo", cantidad: 0, ayuda: "nada pendiente", items: [] },
		],
	};
	return t;
}

const boton_req = (html) => (html.match(/<button[^>]*data-accion="ver-requisitos"[^>]*>[\s\S]*?<\/button>/) || [""])[0];

test("«Para entrar» por columna va oculto por defecto y el botón lo anuncia con aria-pressed=false", () => {
	const t = tablero();
	const html = t.html_embudo();
	assert.doesNotMatch(html, /crm-columna-req/);
	assert.match(boton_req(html), /aria-pressed="false"/);
	assert.match(boton_req(html), /Ver requisitos por etapa/);
});

test("«Ver requisitos por etapa» muestra los requisitos de todas las columnas y vuelve a ocultarlos", () => {
	const t = tablero();
	let repintadas = 0;
	t.repintar_embudo = () => repintadas++;
	t.marcar_tarjeta = () => {};
	let enfocado = 0;
	t.$body = {
		find: (selector) => (selector === '[data-accion="ver-requisitos"]' ? [{ focus: () => enfocado++ }] : []),
	};
	const $boton = { attr: () => undefined };

	t.accion("ver-requisitos", $boton);
	assert.equal(t.estado.ver_requisitos, true);
	assert.equal(repintadas, 1);
	assert.equal(enfocado, 1, "el foco vuelve al botón tras repintar el embudo");
	let html = t.html_embudo();
	assert.equal((html.match(/class="crm-columna-req"/g) || []).length, 2);
	assert.match(html, /Para entrar: cliente, tipo y origen/);
	assert.match(html, /Para entrar: monto y fecha de cierre/);
	assert.match(boton_req(html), /aria-pressed="true"/);

	t.accion("ver-requisitos", $boton);
	assert.equal(t.estado.ver_requisitos, false);
	html = t.html_embudo();
	assert.doesNotMatch(html, /crm-columna-req/);
});

test("La leyenda de colores va en un <details> nativo, cerrado salvo que el usuario la dejara abierta", () => {
	const t = tablero();
	let html = t.html_embudo();
	const details = (h) => (h.match(/<details class="crm-ayuda"[^>]*>/) || [""])[0];
	assert.ok(details(html), "falta el <details class=\"crm-ayuda\">");
	assert.doesNotMatch(details(html), /\bopen\b/);
	assert.match(html, /<summary>¿Qué significan los colores y «Para entrar»\?<\/summary>/);
	// El texto del semáforo sigue ahí, dentro de la leyenda.
	assert.match(html, /<details class="crm-ayuda"[^>]*>[\s\S]*Días sin moverse:[\s\S]*<\/details>/);

	t.estado.ayuda_abierta = true;
	html = t.html_embudo();
	assert.match(details(html), /\bopen\b/);
});

test("Lo que hay que corregir no se esconde: «Para revisión» y el texto del semáforo en las tarjetas", () => {
	const t = tablero();
	assert.match(t.html_cerradas(), /Para revisión: sin orden/);
	// Las columnas siguen mostrando su título, probabilidad y total aunque los requisitos estén ocultos.
	const col = t.html_columna(t.datos.columnas[0]);
	assert.match(col, /1 · Calificar/);
	assert.match(col, /10%/);
});

test("Preferencia de la leyenda: sin localStorage (o si lanza) no falla y vuelve a cerrada", () => {
	const sin_window = tablero();
	assert.equal(sin_window.leer_preferencia("x"), null);
	assert.doesNotThrow(() => sin_window.guardar_preferencia("x", "1"));

	const guardado = {};
	const Con = cargar({
		window: {
			localStorage: {
				getItem: (k) => (k in guardado ? guardado[k] : null),
				setItem: (k, v) => {
					guardado[k] = String(v);
				},
			},
		},
	});
	const t = tablero(Con);
	t.guardar_preferencia("crm-proyectos:ayuda-abierta", "1");
	assert.equal(t.leer_preferencia("crm-proyectos:ayuda-abierta"), "1");

	const Bloqueado = cargar({
		window: {
			get localStorage() {
				throw new Error("SecurityError");
			},
		},
	});
	const b = tablero(Bloqueado);
	assert.equal(b.leer_preferencia("crm-proyectos:ayuda-abierta"), null);
	assert.doesNotThrow(() => b.guardar_preferencia("crm-proyectos:ayuda-abierta", "1"));
});

test("Mi día: estructura que usa el CSS compacto (Renovar/Perder hijos directos; «Todo al día.» hijo del grupo)", () => {
	const t = tablero();
	const html = t.html_mi_dia();
	// Grupos con pendientes y sin pendientes, ninguno se oculta.
	assert.equal((html.match(/class="crm-grupo"/g) || []).length, 2);
	assert.match(html, /<div class="crm-al-dia">Todo al día\.<\/div>\s*<\/div>/);
	// La cotización vencida: enlace y, como hermano directo, la fila Renovar/Perder.
	assert.match(html, /<\/a>\s*<div class="crm-acciones-fila">\s*<button[^>]*data-accion="renovar"[\s\S]*?data-accion="perder-cotizacion"/);

	// Con «Perder» pulsado, «Confirmar pérdida» queda en un .crm-form aparte (va debajo, a todo el ancho).
	t.estado.perdiendo = "QTN-0001";
	const con_form = t.html_mi_dia();
	assert.match(con_form, /<div class="crm-form"[\s\S]*data-accion="confirmar-perder-cotizacion"/);
});
