"""Contexto de sesión: usuario -> empleado, Sales Person(s), empresa, establecimiento y periodo."""

from dataclasses import dataclass, field
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_months, get_first_day, get_last_day, getdate, nowdate

from crm_dashboard_v3.crm_tableros.common.etapas import ConfigModelo
from crm_dashboard_v3.crm_tableros.common.formato import etiqueta_mes

MESES_SELECCIONABLES = 6


@dataclass
class Asesor:
	empleado: str | None
	nombre: str
	usuario: str
	# Todos los Sales Person del asesor en la empresa (un usuario puede tener varios).
	sales_persons: list[str] = field(default_factory=list)


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
	sales_persons: list[str] = field(default_factory=list)
	sales_persons_modelo: list[str] = field(default_factory=list)
	es_jefe: bool = False
	establecimientos: list[str] = field(default_factory=list)
	mensaje: str | None = None

	@property
	def fraccion_del_mes(self) -> float:
		"""Parte del periodo transcurrida (1 para meses cerrados)."""
		corte = min(self.hoy, self.hasta)
		total = (self.hasta - self.desde).days + 1
		return max(0, (corte - self.desde).days + 1) / total

	def como_asesor(self) -> Asesor:
		return Asesor(self.empleado, self.nombre, self.usuario, list(self.sales_persons))


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


def _sales_persons_de(usuario: str, empleado: str | None) -> list:
	"""Sales Person del usuario: por ``user`` o por el empleado ligado.

	get_all: son los registros del propio usuario; los asesores no siempre tienen
	permiso de lectura sobre Sales Person y sin esto no podrían ver su tablero.
	"""
	or_filters = {"user": usuario}
	if empleado:
		or_filters["employee"] = empleado
	return frappe.get_all(
		"Sales Person",
		filters={"enabled": 1, "is_group": 0},
		or_filters=or_filters,
		fields=["name", "company", "establecimiento"],
		order_by="name asc",
	)


def obtener(cfg: ConfigModelo, mes: str | None = None, establecimiento: str | None = None, usuario=None) -> Contexto:
	usuario = usuario or frappe.session.user
	desde, hasta = periodo(mes)
	empleado = frappe.db.get_value(
		"Employee",
		{"user_id": usuario, "status": "Active"},
		["name", "employee_name", "company"],
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
		es_jefe=bool(set(frappe.get_roles(usuario)) & set(cfg.roles_jefe)),
	)

	sps = _sales_persons_de(usuario, ctx.empleado)
	del_modelo = [s for s in sps if cfg.texto_sales_person in s.name]
	ctx.company = (
		(empleado and empleado.company)
		or (del_modelo and del_modelo[0].company)
		or frappe.defaults.get_user_default("Company", usuario)
	)
	ctx.sales_persons = [s.name for s in sps if s.company == ctx.company]
	ctx.sales_persons_modelo = [s.name for s in del_modelo if s.company == ctx.company]
	propio = next((s.establecimiento for s in del_modelo if s.company == ctx.company and s.establecimiento), None)
	ctx.moneda = frappe.get_cached_value("Company", ctx.company, "default_currency") if ctx.company else None

	if ctx.es_jefe:
		ctx.establecimientos = establecimientos_del_modelo(cfg, ctx.company)
		if establecimiento and establecimiento not in ctx.establecimientos:
			frappe.throw(_("No hay asesores de {0} en el establecimiento {1}.").format(cfg.sales_model, establecimiento))
		ctx.establecimiento = establecimiento or (
			propio if propio in ctx.establecimientos else next(iter(ctx.establecimientos), None)
		)
		if not ctx.establecimiento:
			ctx.mensaje = _("No hay asesores de {0} configurados en {1}.").format(cfg.sales_model, ctx.company or "")
	else:
		ctx.establecimiento = propio
		if not ctx.sales_persons_modelo:
			ctx.mensaje = _(
				"Tu usuario no tiene un Sales Person de {0} activo. Pide a tu jefe que lo configure para ver este tablero."
			).format(cfg.sales_model)
	return ctx


def establecimientos_del_modelo(cfg: ConfigModelo, company: str | None) -> list[str]:
	if not company:
		return []
	return sorted(
		set(
			frappe.get_all(
				"Sales Person",
				filters={
					"enabled": 1,
					"is_group": 0,
					"company": company,
					"establecimiento": ["is", "set"],
					"name": ["like", f"%{cfg.texto_sales_person}%"],
				},
				pluck="establecimiento",
			)
		)
	)


def asesores_de_tienda(cfg: ConfigModelo, company: str, establecimiento: str) -> list[Asesor]:
	"""Asesores con Sales Person del modelo en la tienda, con empleado activo y usuario."""
	sps = frappe.get_all(
		"Sales Person",
		filters={
			"enabled": 1,
			"is_group": 0,
			"company": company,
			"establecimiento": establecimiento,
			"employee": ["is", "set"],
			"name": ["like", f"%{cfg.texto_sales_person}%"],
		},
		pluck="employee",
	)
	if not sps:
		return []
	empleados = frappe.get_all(
		"Employee",
		filters={"name": ["in", list(set(sps))], "status": "Active", "user_id": ["is", "set"]},
		fields=["name", "employee_name", "user_id"],
	)
	todos = frappe.get_all(
		"Sales Person",
		filters={"enabled": 1, "is_group": 0, "company": company, "employee": ["in", [e.name for e in empleados]]},
		fields=["name", "employee"],
	)
	asesores = [
		Asesor(e.name, e.employee_name, e.user_id, [s.name for s in todos if s.employee == e.name])
		for e in empleados
	]
	return sorted(asesores, key=lambda a: a.nombre)
