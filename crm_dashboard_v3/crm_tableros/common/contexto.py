"""Contexto de sesión: usuario -> empleado, Sales Person(s), empresa, establecimiento y periodo.

- Un asesor ve solo su información: todos sus Sales Person del tablero juntos
  (en Plus, el de Proyectos y el de Retail).
- Un jefe (rol configurado en el tablero) ve la tienda completa y puede elegir
  a cada asesor.
"""

from dataclasses import dataclass, field
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_months, get_first_day, get_last_day, getdate, nowdate

from crm_dashboard_v3.crm_tableros.common.formato import etiqueta_mes
from crm_dashboard_v3.crm_tableros.common.tableros import ConfigTablero

MESES_SELECCIONABLES = 6


@dataclass
class Asesor:
	empleado: str | None
	nombre: str
	usuario: str
	# Sales Person del asesor en el establecimiento: nombre -> modelo de venta.
	sales_persons: dict[str, str] = field(default_factory=dict)

	def sales_persons_de(self, modelo: str | None = None) -> list[str]:
		return [sp for sp, m in self.sales_persons.items() if modelo in (None, m)]


@dataclass
class Contexto:
	usuario: str
	nombre: str
	desde: date
	hasta: date
	hoy: date
	empleado: str | None = None
	company: str | None = None
	moneda: str | None = None
	establecimiento: str | None = None
	sales_persons: dict[str, str] = field(default_factory=dict)
	es_jefe: bool = False
	establecimientos: list[str] = field(default_factory=list)
	mensaje: str | None = None

	@property
	def fraccion_del_mes(self) -> float:
		"""Parte del periodo transcurrida (1 para meses cerrados)."""
		corte = min(self.hoy, self.hasta)
		total = (self.hasta - self.desde).days + 1
		return max(0, (corte - self.desde).days + 1) / total

	@property
	def dia_de_corte(self) -> date:
		return min(self.hoy, self.hasta)

	def como_asesor(self) -> Asesor:
		return Asesor(self.empleado, self.nombre, self.usuario, dict(self.sales_persons))


def periodo(mes: str | None = None) -> tuple[date, date]:
	"""Del día 1 al último día del mes (formato ``YYYY-MM``); por defecto el mes en curso."""
	hoy = getdate(nowdate())
	if not mes:
		return get_first_day(hoy), get_last_day(hoy)
	try:
		desde = getdate(f"{mes}-01")
	except Exception:
		frappe.throw(_("Mes inválido: {0}").format(mes))
	if desde > get_first_day(hoy):
		frappe.throw(_("No se puede consultar un mes futuro."))
	return desde, get_last_day(desde)


def meses_disponibles(cantidad: int = MESES_SELECCIONABLES) -> list[dict]:
	inicio = get_first_day(getdate(nowdate()))
	meses = []
	for i in range(cantidad):
		fecha = add_months(inicio, -i)
		meses.append({"valor": fecha.strftime("%Y-%m"), "etiqueta": etiqueta_mes(fecha)})
	return meses


def _sales_persons_del_usuario(t: ConfigTablero, usuario: str, empleado: str | None) -> list:
	"""Sales Person del usuario (por ``user`` o por su empleado) en los establecimientos del tablero.

	get_all: son los registros del propio usuario; los asesores no siempre tienen
	permiso de lectura sobre Sales Person y sin esto no podrían ver su tablero.
	"""
	or_filters = {"user": usuario}
	if empleado:
		or_filters["employee"] = empleado
	return frappe.get_all(
		"Sales Person",
		filters={"enabled": 1, "is_group": 0, "establecimiento": ["in", list(t.establecimientos)]},
		or_filters=or_filters,
		fields=["name", "company", "establecimiento"],
		order_by="name asc",
	)


def obtener(t: ConfigTablero, mes: str | None = None, establecimiento: str | None = None, usuario=None) -> Contexto:
	usuario = usuario or frappe.session.user
	desde, hasta = periodo(mes)
	empleado = frappe.db.get_value(
		"Employee",
		{"user_id": usuario, "status": "Active"},
		["name", "employee_name"],
		as_dict=True,
	)
	nombre = (empleado and empleado.employee_name) or frappe.utils.get_fullname(usuario)
	ctx = Contexto(
		usuario=usuario,
		nombre=nombre,
		desde=desde,
		hasta=hasta,
		hoy=getdate(nowdate()),
		empleado=empleado.name if empleado else None,
		es_jefe=es_jefe(t, usuario),
	)

	if ctx.es_jefe:
		ctx.establecimientos = establecimientos_con_asesores(t)
		if establecimiento and establecimiento not in ctx.establecimientos:
			frappe.throw(_("{0} no atiende el establecimiento {1}.").format(t.titulo, establecimiento))
		propios = [s.establecimiento for s in _sales_persons_del_usuario(t, usuario, ctx.empleado)]
		ctx.establecimiento = establecimiento or next(
			(e for e in propios if e in ctx.establecimientos), next(iter(ctx.establecimientos), None)
		)
		if not ctx.establecimiento:
			ctx.mensaje = _("No hay asesores activos en {0}.").format(", ".join(t.establecimientos))
			return ctx
		ctx.company = frappe.db.get_value(
			"Sales Person", {"establecimiento": ctx.establecimiento, "enabled": 1, "is_group": 0}, "company"
		)
	else:
		sps = _sales_persons_del_usuario(t, usuario, ctx.empleado)
		if not sps:
			ctx.mensaje = _(
				"{0} es para los asesores de {1}. Tu usuario no tiene un Sales Person activo ahí; "
				"si debería tenerlo, pide a tu jefe que lo configure."
			).format(t.titulo, ", ".join(t.establecimientos))
			return ctx
		ctx.establecimiento = sps[0].establecimiento
		ctx.company = sps[0].company
		ctx.sales_persons = {
			s.name: t.modelo_de_sales_person(s.name)
			for s in sps
			if s.establecimiento == ctx.establecimiento and s.company == ctx.company
		}
	ctx.moneda = frappe.get_cached_value("Company", ctx.company, "default_currency") if ctx.company else None
	return ctx


def es_jefe(t: ConfigTablero, usuario: str) -> bool:
	return bool(set(frappe.get_roles(usuario)) & set(t.roles_jefe))


def establecimientos_con_asesores(t: ConfigTablero) -> list[str]:
	return sorted(
		set(
			frappe.get_all(
				"Sales Person",
				filters={
					"enabled": 1,
					"is_group": 0,
					"establecimiento": ["in", list(t.establecimientos)],
					"employee": ["is", "set"],
				},
				pluck="establecimiento",
			)
		)
	)


def asesores_de_tienda(t: ConfigTablero, establecimiento: str) -> list[Asesor]:
	"""Asesores con Sales Person en la tienda, empleado activo y usuario.

	Los jefes del tablero (por rol) no se cuentan como asesores aunque tengan
	Sales Person en la tienda.
	"""
	sps = frappe.get_all(
		"Sales Person",
		filters={"enabled": 1, "is_group": 0, "establecimiento": establecimiento, "employee": ["is", "set"]},
		fields=["name", "employee"],
	)
	if not sps:
		return []
	empleados = frappe.get_all(
		"Employee",
		filters={"name": ["in", list({s.employee for s in sps})], "status": "Active", "user_id": ["is", "set"]},
		fields=["name", "employee_name", "user_id"],
	)
	jefes = set(
		frappe.get_all(
			"Has Role",
			filters={
				"parenttype": "User",
				"parent": ["in", [e.user_id for e in empleados] or [""]],
				"role": ["in", list(t.roles_jefe)],
			},
			pluck="parent",
		)
	)
	asesores = [
		Asesor(
			e.name,
			e.employee_name,
			e.user_id,
			{s.name: t.modelo_de_sales_person(s.name) for s in sps if s.employee == e.name},
		)
		for e in empleados
		if e.user_id not in jefes
	]
	return sorted(asesores, key=lambda a: a.nombre)
