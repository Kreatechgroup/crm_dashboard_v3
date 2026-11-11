# CLAUDE.md · Tableros CRM en ERPNext (Frappe)

Este repositorio construye los tableros CRM que reemplazan al **CRM Dashboard V2** (DocType de la app `custom_crm`).
Habrá dos tableros:

| Tablero | Modelo de venta | Estado |
|---|---|---|
| **Tablero 2 · CRM Proyectos** | `Opportunity.sales_model = "Proyectos"` | **En construcción ahora** |
| Tablero 1 · CRM Retail | `Opportunity.sales_model = "Retail"` | Fase siguiente. **No implementar todavía.** |

La especificación vigente está en `docs/` (Especificación CRM Proyectos). Léela completa antes de escribir código; si algo de este archivo contradice la especificación, manda la especificación y avísame de la diferencia.

---

## 1. Alcance de esta fase

Construye **solo el tablero de Proyectos** y los **cambios comunes** que pide su especificación (sección 3 del PDF).
Pero diseña todo lo compartido pensando en que después se agregará Retail sobre la misma base, sin duplicar código.

No hagas en esta fase:
- La página `crm-retail`, sus indicadores (meta del mes, ritmo, embudo de Visit Log, "Mi lista de hoy", "Cerrar el ciclo").
- Las etapas Retail (Cotizada → Seguimiento → Ganada/Perdida).
- Cambios en Visit Log.

Sí deja preparado:
- Un módulo común reutilizable (ver sección 3).
- Que cualquier filtro por modelo de venta sea un **parámetro** (`sales_model`), nunca un valor escrito dentro de la lógica.
- Que las etapas y probabilidades vivan en una configuración por modelo de venta, para que Retail agregue las suyas.

---

## 2. Implementación

- Una **Page de Frappe** llamada `crm-proyectos` dentro de la app `custom_crm` (la futura será `crm-retail`).
- **No** se crea un documento por asesor. Los 35 registros de `CRM Dashboard V2` dejan de usarse (no los borres; eso lo decide el negocio).
- Todo el cálculo pesado va en **métodos Python whitelisted** (agregaciones en servidor con SQL/`frappe.qb`), no en el navegador.
- El JavaScript de la página solo pinta y llama acciones.
- Meta de rendimiento: la página carga en **menos de 3 segundos** con un mes de datos.

### Estructura sugerida

```
custom_crm/
  custom_crm/
    crm_tableros/
      common/
        contexto.py        # usuario → Sales Person, empleado, company, establecimiento, periodo
        metas.py           # lectura de Tabla de metas (reutilizable por Retail)
        etapas.py          # configuración de etapas y probabilidades por sales_model
        formato.py         # nombres de personas, moneda, semáforos
        acciones.py        # renovar/perder cotización, lost reason, etc. (compartidas)
      proyectos/
        api.py             # métodos whitelisted del tablero Proyectos
      # retail/            # se creará en la fase siguiente
    page/
      crm_proyectos/       # crm_proyectos.json / .js / .css
    patches/               # migraciones (etapas, ToDos, establecimiento Panamá)
    public/js/crm_tableros/common.js   # utilidades de UI compartidas
docs/
```

Ajusta los nombres si el repositorio ya tiene otra convención; respeta la existente.

---

## 3. Base común (servirá a los dos tableros)

**Contexto de sesión** (`contexto.py`), sin filtros manuales:
- `Sales Person.user = frappe.session.user` → asesor. Un mismo usuario puede tener más de un Sales Person (por ejemplo uno Retail "- UM" y uno de Proyectos); el tablero de Proyectos usa el de proyectos.
- Empresa: Umob S.A. o Grupo Creative, S.A. / Panamá, derivada del Sales Person o del empleado.
- Periodo por defecto: del día 1 al último día del mes en curso. Debe aceptar un mes anterior como parámetro.
- Si el usuario no tiene Sales Person, muestra un mensaje claro; no falles con error.

**Nombres de personas**: mostrar siempre el nombre del empleado ("Marielos Moreira"), nunca el correo ni el nombre del Sales Person con su puesto.

**Metas** (`metas.py`): leer la Tabla de metas con `docstatus = 1`, `disabled = 0`, Sales Person correspondiente y vigencia que se cruce con el periodo (`date_from ≤ fin` y `date_to ≥ inicio`). Si una meta abarca varios meses, aplica completa en cada mes. Retail usará la misma función con `tipo_de_meta = "Monto de VENTA (Sales Invoice)"`.

**Navegación**: cada número del tablero abre la vista de lista filtrada con los registros que lo forman.

**Colores**: todo semáforo lleva texto además del color (Verde / Amarillo / Rojo).

---

## 4. Tablero Proyectos (resumen de la especificación)

### 4.1 Etapas (reemplazan las 17 actuales de `embudo_state_v2`)

| Etapa | Probabilidad | Para entrar se exige |
|---|---|---|
| 1 · Calificar | 10% | Cliente o lead, tipo de oportunidad, origen |
| 2 · Requerimiento y diseño | 25% | Monto estimado > 0, fecha esperada de cierre, próximo paso con fecha |
| 3 · Propuesta enviada | 50% | Cotización enviada (submit) ligada; el monto se actualiza con el de la cotización |
| 4 · Negociación | 75% | Próximo paso con fecha vigente |
| Ganada | 100% | Orden de venta creada; `status = Converted` |
| Perdida | 0% | `Lost Reason` obligatorio; `status = Lost` |
| En pausa | — | Fecha para retomar; no cuenta en el pronóstico |

- `Opportunity.probability` se fija sola según la etapa (server-side, en un hook `validate`); el usuario no la edita.
- Campos nuevos en Opportunity: `custom_proximo_paso` (Data) y `custom_fecha_proximo_paso` (Date). Créalos como **fixtures / Custom Field en código**, no a mano.
- Etapa y status siempre coherentes: Ganada ↔ Converted, Perdida ↔ Lost.
- No permitir el texto genérico "Especificar motivo" como razón de pérdida.
- La validación de campos obligatorios por etapa vive en **servidor** (la UI solo muestra qué falta y no mueve la tarjeta).

**Migración** (patch idempotente) de los valores actuales:
- Investigar al cliente, Clasificar, Presentar empresa, Conocer → 1 · Calificar
- Tomar requerimiento, Definir la solución, Presentar solución, Crear el diseño, Presentar diseño → 2 · Requerimiento y diseño
- Crear la cotización, Presentar cotización → 3 · Propuesta enviada
- Dar seguimiento, Negociar → 4 · Negociación
- Ganada → Ganada · Perdida → Perdida · Descartada → Perdida con motivo "No calificó"
- Llamar después → En pausa

Antes de migrar, genera un reporte de cuántas oportunidades hay en cada etapa vieja y cuáles quedarían incoherentes (por ejemplo Ganada sin `Converted`). Muéstramelo y espera confirmación.

### 4.2 Indicadores

- **Universo**: Opportunity con `sales_model = "Proyectos"`, del asesor (`owner` o `asesor_comercial_user_id`), con status distinto de Lost, Converted y Closed.
- **Meta proyectos**: Tabla de metas del Sales Person de proyectos (ej. "Asesor de Proyectos Retail Guillermo González - UM"), contra lo ganado en el mes (órdenes o facturas de oportunidades de proyectos cerradas en el mes).
- **Propuestas vigentes**: oportunidades en etapa 3 o 4 → Σ `opportunity_amount` y conteo.
- **Pronóstico ponderado**: Σ `opportunity_amount × probabilidad` de todas las activas. Mostrar cuántas tienen `expected_closing`; si falta alguna, etiqueta "Faltan fechas". El pronóstico del mes solo suma las que cierran dentro del mes. En Pausa no cuenta.
- **Propuestas vencidas**: Quotation `docstatus = 1`, ligada a oportunidad activa de proyectos, `valid_till < hoy` y sin orden de venta → Σ `base_grand_total` y conteo. Lista lateral ordenada por monto con botones **Renovar** (copia con nueva `valid_till`) y **Perder** (flujo de Lost Reason).
- **Tarjeta de oportunidad**: cliente, monto ("sin monto" si es 0), días sin moverse (hoy − última modificación o actividad), tipo de oportunidad, próximo paso. Días: verde hasta 7, amarillo 8–14, rojo > 14. Próximo paso en rojo si está vacío o vencido.
- **Monto provisional**: mientras exista el histórico con monto 0, usar como monto el de la cotización ligada más alta.

### 4.3 Cambios comunes de esta fase

- **ToDos automáticos**: desactivar la asignación automática que crea "Asignación para Opportunity" y cerrar en bloque los ToDo abiertos de ese tipo (Marielos sola tiene ~900). El cierre en bloque se hace con un patch que primero **cuenta y me muestra** cuántos cerraría por usuario, y solo corre con mi confirmación.
- **Retirar la Nota CRM** como indicador (le daba peso 0 a la venta facturada).
- **Tienda Panamá**: las visitas con `establecimiento = "Grupo Creative"` se asignan a Abito Panamá (Dream Plaza). Aunque Visit Log es de Retail, este cambio está en la especificación común; prepáralo como patch separado y pregúntame antes de correrlo.
- **`custom_sales_model`** en Sales Order y Sales Invoice, heredado de la oportunidad (vía Quotation → Sales Order → Sales Invoice). Retail lo usará para separar su facturado en Plus.

### 4.4 Criterios de aceptación

1. No se puede pasar a "Requerimiento y diseño" sin monto, fecha de cierre y próximo paso con fecha.
2. La probabilidad cambia sola al mover de etapa y el pronóstico ponderado se recalcula en el momento.
3. Una cotización vencida aparece en "Propuestas vencidas" y sale al renovarla o perderla.
4. Una oportunidad en Ganada siempre tiene `status = Converted`.
5. Los ToDo automáticos dejan de crearse a partir de la puesta en marcha.

Escribe pruebas (`FrappeTestCase`) para cada criterio.

---

## 5. Errores del CRM Dashboard V2 que no se deben repetir

- Nada de listas fijas de asesores, metas fijas (333,333 / 4,000,000), umbrales sin moneda ni correos escritos en el código. Todo sale de la base de datos o de configuración.
- Nada de `limit 1000` silenciosos: agregar en servidor o paginar.
- Respetar siempre las fechas del periodo; ninguna consulta con fechas fijas (como "desde 2021-01-01").
- Toda acción masiva filtra por **empresa y asesor**; nunca buscar clientes con `LIKE` sin esos filtros.
- Filtros por usuario con el correo completo, nunca por prefijo.
- Si el usuario no aparece en un ranking o lista, no mostrar datos de otro como si fueran suyos.
- Sin librerías desde CDNs sin versión fija ni React en modo development. Usar lo que trae Frappe (frappe-ui, Frappe Charts, jQuery) y servir local cualquier dependencia extra.
- Sin código muerto ni `console.log` en lo entregado.
- Respetar los permisos de ERPNext en cada consulta (`frappe.get_list` / chequeo de permisos), no saltarlos con `ignore_permissions` salvo justificación explícita.

---

## 6. Forma de trabajo

- Antes de programar, propón un plan corto (archivos, campos, patches, métodos) y espera mi visto bueno.
- Para conocer datos reales usa solo consultas de lectura. **Nunca** crees, modifiques, cancele o borres registros del ERP de producción durante el desarrollo.
- Todo cambio de esquema va como Custom Field/fixture o patch versionado e idempotente; nada manual desde el escritorio.
- Patches que tocan datos existentes (migración de etapas, cierre de ToDos, Panamá): primero modo "simulación" con conteos, luego ejecución con mi confirmación.
- Commits pequeños y descriptivos por bloque (campos, etapas, API, página, patches, pruebas).
- Si encuentras algo en el sistema que contradice la especificación (por ejemplo un campo con otro nombre), detente y pregúntame en vez de suponer.
- Textos de la interfaz en español.

---

## 7. Notas para la fase Retail (solo referencia, no implementar)

Cuando llegue la especificación de Retail a `docs/`, se agregará sobre la base común:
- Página `crm-retail` con la meta del mes ("Monto de VENTA (Sales Invoice)"), facturado neto de notas de crédito por Sales Team, ritmo esperado, proyección al cierre, embudo desde Visit Log y la lista de cotizaciones del día.
- Etapas propias: Cotizada → Seguimiento (máx. 14 días) → Ganada / Perdida + motivo.
- En Plus, el mismo asesor verá su parte Retail en ese tablero y su parte de proyectos en este.

Por eso: no metas lógica de Proyectos dentro de `common/`, y no asumas que un usuario tiene un solo Sales Person.
