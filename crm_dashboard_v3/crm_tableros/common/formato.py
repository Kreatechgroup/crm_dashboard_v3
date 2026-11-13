"""Formato compartido: nombres de personas, meses y semáforos (siempre con texto)."""

import frappe
from frappe import _
from frappe.utils import getdate

MESES = (
	"enero",
	"febrero",
	"marzo",
	"abril",
	"mayo",
	"junio",
	"julio",
	"agosto",
	"septiembre",
	"octubre",
	"noviembre",
	"diciembre",
)

SEMAFORO = {
	"verde": _("Verde"),
	"amarillo": _("Amarillo"),
	"rojo": _("Rojo"),
}


def etiqueta_mes(fecha) -> str:
	fecha = getdate(fecha)
	return f"{MESES[fecha.month - 1].capitalize()} {fecha.year}"


def etiqueta_mes_corta(fecha) -> str:
	return MESES[getdate(fecha).month - 1][:3].capitalize()


def semaforo(clave: str) -> dict:
	return {"clave": clave, "texto": SEMAFORO[clave]}


def semaforo_dias(dias: int, verde_max: int, amarillo_max: int) -> dict:
	if dias <= verde_max:
		return semaforo("verde")
	if dias <= amarillo_max:
		return semaforo("amarillo")
	return semaforo("rojo")


def estado(clave: str, texto: str) -> dict:
	"""Semáforo con un mensaje propio; el color sigue en ``color`` (Verde / Amarillo / Rojo)."""
	return {"clave": clave, "color": SEMAFORO[clave], "texto": texto}


def ritmo(facturado: float, meta: float, fraccion_del_mes: float) -> dict:
	"""Estado de avance contra la meta, comparado con el ritmo esperado a la fecha (como el mockup)."""
	avance = facturado / meta if meta > 0 else 0
	pct = round(avance * 100)
	if meta <= 0:
		return estado("amarillo", _("Sin meta registrada"))
	if avance >= 1:
		return estado("verde", _("Llegó a meta"))
	if avance >= fraccion_del_mes:
		return estado("verde", _("En ritmo · {0}% de cumplimiento").format(pct))
	if avance >= fraccion_del_mes * 0.8:
		return estado("amarillo", _("Atención · {0}% de cumplimiento").format(pct))
	return estado("rojo", _("No ha llegado a la meta · {0}% de cumplimiento").format(pct))


def nombres_de_usuarios(usuarios: list[str]) -> dict[str, str]:
	"""Usuario -> nombre del empleado (o nombre completo del usuario). Nunca el correo."""
	usuarios = [u for u in set(usuarios) if u]
	if not usuarios:
		return {}
	# get_all: solo se lee el nombre visible de las personas, no datos del empleado.
	nombres = {
		e.user_id: e.employee_name
		for e in frappe.get_all(
			"Employee",
			filters={"user_id": ["in", usuarios]},
			fields=["user_id", "employee_name"],
			order_by="status asc",
		)
	}
	faltan = [u for u in usuarios if u not in nombres]
	if faltan:
		for u in frappe.get_all("User", filters={"name": ["in", faltan]}, fields=["name", "full_name"]):
			nombres[u.name] = u.full_name or _("Usuario sin nombre")
	return {u: nombres.get(u) or _("Usuario sin nombre") for u in usuarios}
