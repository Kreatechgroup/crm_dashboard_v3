// Pruebas del embudo por partes («Ver más»): corte por columna y tarjeta abierta fuera del corte.
// Corren sin Frappe ni navegador: cargan common.js y crm_proyectos.js en un contexto de Node con
// lo mínimo de Frappe que usan esas funciones.
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

function cargar() {
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
	};
	vm.createContext(contexto);
	ARCHIVOS.forEach((archivo) => vm.runInContext(fs.readFileSync(archivo, "utf8"), contexto, { filename: archivo }));
	return { crm_tableros: contexto.crm_tableros, TableroProyectos: vm.runInContext("TableroProyectos", contexto) };
}

const { crm_tableros, TableroProyectos } = cargar();
// Los arreglos creados dentro del contexto de vm tienen otro prototipo: se comparan como datos.
const plano = (x) => JSON.parse(JSON.stringify(x));

// n tarjetas con monto descendente; las de índice en `rojas` piden acción (semáforo rojo).
function tarjetas(prefijo, n, { rojas = [], revision = [] } = {}) {
	return Array.from({ length: n }, (_, i) => ({
		name: `${prefijo}-${String(i + 1).padStart(3, "0")}`,
		cliente: `Cliente ${i + 1}`,
		modelo: "Proyectos",
		monto: (n - i) * 1000,
		dias: 3,
		semaforo: { clave: rojas.includes(i) ? "rojo" : "verde", texto: "", color: "" },
		tipo: "Diseño",
		asesor: "",
		proximo: { estado: "ok", texto: "Llamar", fecha: "2026-11-30" },
		etapa: "En pausa",
		extra: revision.includes(i) ? "Para revisión: X" : "",
		revision: revision.includes(i),
	}));
}

function tablero({ activa = tarjetas("OP", 63, { rojas: [1, 10, 20, 30, 40] }), pausa = tarjetas("PA", 12, { revision: [9] }) } = {}) {
	const t = Object.create(TableroProyectos.prototype);
	t.estado = { filtro_modelo: "", filtro_tipo: "", solo_accion: false, orden: "monto", expandidas: {}, ver_cerradas: true, sel: null };
	t.datos = {
		moneda: "GTQ",
		modelos: ["Proyectos"],
		hoy: "2026-11-26",
		columnas: [{ clave: "requerimiento", titulo: "2 · Requerimiento y diseño", probabilidad: 25, requisitos: "monto", tarjetas: activa }],
		cerradas: [{ clave: "pausa", titulo: "En pausa", tarjetas: pausa }],
	};
	return t;
}

const pintadas = (html) => [...html.matchAll(/class="crm-tarjeta" data-accion="abrir" data-name="([^"]+)"/g)].map((m) => m[1]);
// El botón «Ver más» con sus atributos y, después, su texto sin etiquetas (como lo lee un lector de pantalla).
const boton = (html) => {
	const b = (html.match(/<button type="button" class="crm-columna-mas"[^>]*>[\s\S]*?<\/button>/) || [""])[0];
	return b && `${b.match(/^<button[^>]*>/)[0]} ${b.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim()}`;
};

test("cortar_lista: hasta 6 + 2 de holgura se muestran todas", () => {
	const items = [1, 2, 3, 4, 5, 6, 7, 8];
	assert.deepEqual(plano(crm_tableros.cortar_lista(items)), { visibles: items, ocultas: [], cortable: false });
});

test("cortar_lista: con 3 o más de sobra, 6 visibles y el resto oculto", () => {
	const r = plano(crm_tableros.cortar_lista([1, 2, 3, 4, 5, 6, 7, 8, 9]));
	assert.deepEqual(r.visibles, [1, 2, 3, 4, 5, 6]);
	assert.deepEqual(r.ocultas, [7, 8, 9]);
	assert.equal(r.cortable, true);
});

test("cortar_lista: ampliada muestra todas y sigue siendo cortable (botón «Ver menos»)", () => {
	const items = Array.from({ length: 20 }, (_, i) => i);
	assert.deepEqual(plano(crm_tableros.cortar_lista(items, { ampliada: true })), { visibles: items, ocultas: [], cortable: true });
});

test("cortar_lista: la fijada se muestra aunque quede después del corte", () => {
	const items = Array.from({ length: 50 }, (_, i) => i);
	const r = plano(crm_tableros.cortar_lista(items, { fijar: (x) => x === 39 }));
	assert.deepEqual(r.visibles, [0, 1, 2, 3, 4, 5, 39]);
	assert.equal(r.ocultas.length, 43);
	assert.ok(!r.ocultas.includes(39));
});

test("Columna de 63: 6 tarjetas, «Ver 57 más · 4 en rojo» y los totales cuentan todas", () => {
	const t = tablero();
	const html = t.html_columna(t.datos.columnas[0]);
	assert.deepEqual(pintadas(html), ["OP-001", "OP-002", "OP-003", "OP-004", "OP-005", "OP-006"]);
	const b = boton(html);
	assert.match(b, /aria-expanded="false"/);
	assert.match(b, /data-valor="requerimiento"/);
	assert.match(b, /Ver 57 más/);
	// Rojas en los índices 1, 10, 20, 30 y 40: la 1 está visible, quedan 4 ocultas.
	assert.match(b, /· 4 en rojo/);
	assert.match(html, /63 oportunidades · GTQ 2016000\.00/);
	assert.match(html, /5 en rojo/);
});

test("Columna ampliada: todas las tarjetas y «Ver menos» con aria-expanded=true", () => {
	const t = tablero();
	t.estado.expandidas.requerimiento = true;
	const html = t.html_columna(t.datos.columnas[0]);
	assert.equal(pintadas(html).length, 63);
	assert.match(boton(html), /aria-expanded="true"[\s\S]*Ver menos/);
	assert.doesNotMatch(boton(html), /en rojo/);
});

test("Los filtros se aplican antes del corte: 8 que pasan el filtro se ven todas, sin botón", () => {
	const activa = tarjetas("OP", 30).map((x, i) => ({ ...x, tipo: i < 8 ? "Mobiliario" : "Diseño" }));
	const t = tablero({ activa });
	t.estado.filtro_tipo = "Mobiliario";
	const html = t.html_columna(t.datos.columnas[0]);
	assert.equal(pintadas(html).length, 8);
	assert.equal(boton(html), "");
	assert.match(html, /8 oportunidades/);
});

test("La columna ampliada sigue ampliada al cambiar de filtro", () => {
	const t = tablero();
	t.estado.expandidas.requerimiento = true;
	t.estado.orden = "urgencia";
	t.estado.filtro_tipo = "Diseño";
	assert.equal(pintadas(t.html_columna(t.datos.columnas[0])).length, 63);
});

test("«Solo las que piden acción» corta sobre las filtradas", () => {
	const activa = tarjetas("OP", 40, { rojas: Array.from({ length: 12 }, (_, i) => i * 3) });
	const t = tablero({ activa });
	t.estado.solo_accion = true;
	const html = t.html_columna(t.datos.columnas[0]);
	assert.equal(pintadas(html).length, 6);
	assert.match(boton(html), /Ver 6 más · 6 en rojo/);
});

test("Por urgencia: las 6 visibles son las que piden acción", () => {
	const activa = tarjetas("OP", 30).map((x, i) => (i >= 20 ? { ...x, proximo: { estado: "vacio", texto: "", fecha: null } } : x));
	const t = tablero({ activa });
	t.estado.orden = "urgencia";
	const nombres = pintadas(t.html_columna(t.datos.columnas[0]));
	assert.equal(nombres.length, 6);
	nombres.forEach((n) => assert.ok(Number(n.slice(3)) > 20, n));
});

test("La tarjeta seleccionada en la posición 40 se pinta aunque esté después del corte", () => {
	const t = tablero();
	t.estado.sel = "OP-040";
	const html = t.html_columna(t.datos.columnas[0]);
	const nombres = pintadas(html);
	assert.equal(nombres.length, 7);
	assert.equal(nombres[6], "OP-040");
	assert.match(html, /data-name="OP-040" aria-current="true"/);
	assert.match(boton(html), /Ver 56 más · 4 en rojo/);
});

test("En pausa y cerradas también se cortan; cuentan las «para revisión» ocultas", () => {
	const t = tablero();
	const html = t.html_cerradas();
	assert.equal(pintadas(html).length, 6);
	assert.match(boton(html), /data-valor="pausa"/);
	assert.match(boton(html), /Ver 6 más · 1 para revisión/);
	assert.match(html, /12 · GTQ/);
});

test("marcar_tarjeta vuelve a pintar el embudo si la abierta (p. ej. desde Mi día) quedó oculta", () => {
	const t = tablero();
	let dom = pintadas(t.html_columna(t.datos.columnas[0]));
	let repintadas = 0;
	const marcadas = [];
	t.repintar_embudo = () => {
		repintadas++;
		dom = pintadas(t.html_columna(t.datos.columnas[0]));
	};
	t.$body = {
		find(selector) {
			const m = selector.match(/^\.crm-tarjeta\[data-name="([^"]*)"\]$/);
			const n = selector === ".crm-embudo" ? 1 : m ? (dom.includes(m[1]) ? 1 : 0) : dom.length;
			return {
				length: n,
				attr(nombre, valor) {
					if (m && valor === "true" && n) marcadas.push(m[1]);
					return this;
				},
			};
		},
	};
	t.estado.sel = "OP-040";
	t.marcar_tarjeta();
	assert.equal(repintadas, 1);
	assert.ok(dom.includes("OP-040"));
	assert.deepEqual(plano(marcadas), ["OP-040"]);

	// Ya pintada: no se vuelve a pintar.
	t.marcar_tarjeta();
	assert.equal(repintadas, 1);

	// No pasa los filtros (o no existe): no hay nada que mostrar y no se repinta.
	t.estado.sel = "NO-EXISTE";
	t.marcar_tarjeta();
	assert.equal(repintadas, 1);
});
