"""Alcance de una petición a un tablero: quién mira y a quién se muestra.

Une el contexto de sesión (usuario → empleado → Sales Person, empresa, rol de
jefe y mes) con la elección de asesor, y arma los datos base que reciben todos
los endpoints de los tableros y la plantilla de UI común (``common.js``).

- Un asesor ve solo lo suyo: el parámetro ``asesor`` se ignora.
- Un jefe (rol de ``ConfigTablero.roles_jefe``) ve la tienda completa o el asesor elegido.
"""

from dataclasses import dataclass, field

import frappe
from frappe import _

from crm_dashboard_v3.crm_tableros.common import contexto
from crm_dashboard_v3.crm_tableros.common.contexto import Asesor, Contexto
from crm_dashboard_v3.crm_tableros.common.formato import etiqueta_mes
from crm_dashboard_v3.crm_tableros.common.tableros import ConfigTablero


@dataclass
class Alcance:
	tablero: ConfigTablero
	ctx: Contexto
	# Datos base de la respuesta (los que pinta el encabezado de la plantilla común).
	base: dict
	# Asesores cuyos datos se muestran.
	seleccion: list[Asesor] = field(default_factory=list)

	@property
	def mensaje(self) -> str | None:
		return self.base.get("mensaje")

	@property
	def vista_tienda(self) -> bool:
		"""Jefe sin asesor elegido: se ve toda la tienda."""
		return self.ctx.es_jefe and not self.base.get("asesor")


def obtener(t: ConfigTablero, mes: str | None = None, asesor: str | None = None, establecimiento: str | None = None) -> Alcance:
	ctx = contexto.obtener(t, mes, establecimiento)
	base = {
		"tablero": t.clave,
		"tablero_titulo": t.titulo,
		"meses": contexto.meses_disponibles(),
		"mes": ctx.desde.strftime("%Y-%m"),
		"etiqueta_mes": etiqueta_mes(ctx.desde),
		"desde": str(ctx.desde),
		"hasta": str(ctx.hasta),
		"hoy": str(ctx.hoy),
		"dia_de_corte": str(ctx.dia_de_corte),
		"usuario": ctx.usuario,
		"nombre_usuario": ctx.nombre,
		"empleado": ctx.empleado,
		"es_jefe": ctx.es_jefe,
		"company": ctx.company,
		"moneda": ctx.moneda,
		"establecimientos": ctx.establecimientos,
		"establecimiento": ctx.establecimiento,
		"modelos": list(t.sales_models),
		"sales_persons": [{"name": sp, "modelo": modelo} for sp, modelo in ctx.sales_persons.items()],
		"asesores": [],
		"asesor": None,
		"titulo": t.titulo,
	}
	if ctx.mensaje:
		return Alcance(t, ctx, {**base, "mensaje": ctx.mensaje})

	if ctx.es_jefe:
		asesores = contexto.asesores_de_tienda(t, ctx.establecimiento)
		base["asesores"] = [{"empleado": a.empleado, "nombre": a.nombre} for a in asesores]
		seleccion = asesores
		if asesor:
			seleccion = [a for a in asesores if a.empleado == asesor]
			if not seleccion:
				frappe.throw(_("El asesor elegido no pertenece a este establecimiento."))
			base["asesor"] = asesor
			base["titulo"] = _(t.titulo_jefe_asesor).format(seleccion[0].nombre)
		else:
			base["titulo"] = _(t.titulo_tienda)
		if not asesores:
			base["mensaje"] = _("No hay asesores activos en {0}.").format(ctx.establecimiento)
			return Alcance(t, ctx, base)
	else:
		# Un asesor nunca ve a otro: el parámetro ``asesor`` se ignora.
		seleccion = [ctx.como_asesor()]
		base["titulo"] = _(t.titulo_asesor).format(ctx.nombre)

	base["subtitulo"] = " · ".join(filter(None, [ctx.establecimiento, ctx.company, etiqueta_mes(ctx.desde)]))
	return Alcance(t, ctx, base, seleccion)
