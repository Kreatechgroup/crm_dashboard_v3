# Diseño · Workflow compartido de Opportunity (etapas nuevas para Plus y Abito)

Fase 0, solo análisis. No se modificó nada en producción ni en el servidor de pruebas.
Datos tomados de producción con consultas de solo lectura el 2026-11-13.

## 1. Decisión y alcance (2026-11-13)

- Se usa un **workflow compartido** sobre `embudo_state_v2`:
  - **Demás empresas:** conservan sus **17 estados y 48 transiciones actuales**, igual que hoy.
  - **Tiendas de los tableros:** usan sus **etapas nuevas**.
- Frappe solo permite **un workflow activo por DocType**. Por eso cada transición se separa con una **condición por tienda**.

| Tablero | Establecimiento (`establecimiento_lista`) | Empresa | Modelos | Etapas | Fase |
|---|---|---|---|---|---|
| CRM Proyectos | Plus Fontabella Importado | Umob S.A. | Proyectos y Retail | 7 etapas de Proyectos | **1 (ahora)** |
| CRM Retail · Abito GT | Abito Fontabella | Umob S.A. | Retail | Cotizada → Seguimiento → Ganada / Perdida | 2 (con el tablero Retail) |
| CRM Retail · Abito PA | Grupo Creative (Abito Dream Plaza) | Grupo Creative, S.A. / Panamá | Retail | Cotizada → Seguimiento → Ganada / Perdida | 2 (con el tablero Retail) |

**Fuera de alcance (siguen con las 17):**
- Plus Fontabella Servicios.
- Los establecimientos "Abito", "Abito III", "Abito Accesorios" y "Abito Concepcion IV" de Grupo Creative S.A.
- Las oportunidades de Proyectos de las tiendas Abito.
- Todas las demás empresas: Creative, Creucon, Banyo, El Salvador y Creamex.

**Abito usa etapas Retail, no las 7 de Proyectos.** Lo dice la especificación de Retail, sección 5: *"Para `sales_model = "Retail"` solo se permiten estas etapas en `embudo_state_v2` (o en un campo nuevo): Cotizada → Seguimiento (máx. 14 días) → Ganada o Perdida + motivo"*.

## 2. Estados

| Estado | Para | ¿Existe hoy? | Probabilidad |
|---|---|---|---|
| Los 17 actuales (Investigar al cliente … Descartada) | demás empresas | Sí | sin cambio |
| 1 · Calificar | Plus | **Nuevo** | 10% |
| 2 · Requerimiento y diseño | Plus | **Nuevo** | 25% |
| 3 · Propuesta enviada | Plus | **Nuevo** | 50% |
| 4 · Negociación | Plus | **Nuevo** | 75% |
| En pausa | Plus | **Nuevo** | — (no cuenta en el pronóstico) |
| Cotizada | Abito (fase 2) | **Nuevo** | por definir en la fase Retail |
| Seguimiento | Abito (fase 2) | **Nuevo** | por definir en la fase Retail |
| Ganada | todos | Sí (se comparte) | 100% |
| Perdida | todos | Sí (se comparte) | 0% |

"Ganada" y "Perdida" **mantienen su nombre**. Así siguen funcionando sin cambios:
- los Server Scripts "Validar motivo de pérdida" y "Perdida marca cotizaciones Lost";
- la notificación "Oportunidad Perdida / Descartada";
- los reportes que filtran por Ganada o Perdida.

Los estados nuevos se agregan a:
- las opciones del Custom Field `embudo_state_v2`;
- el maestro *Workflow State*;
- la tabla de estados del workflow.

## 3. Transiciones

### 3.1 Las 48 actuales
Se conservan tal cual, con una condición extra: **que la oportunidad no pertenezca a un tablero activo**. Si ya tienen condición (hoy una sola: `doc.contact_email`), se combina con `and`.

```python
not (doc.establecimiento_lista == "Plus Fontabella Importado" and doc.sales_model in ("Proyectos", "Retail"))
```

La condición se **genera desde la configuración de los tableros** (`ConfigTablero`), no se escribe a mano. En la fase 2 se le suman las tiendas de Abito.

### 3.2 Nuevas · Plus (fase 1) · rol **Embudo de ventas**
Condición: `doc.establecimiento_lista == "Plus Fontabella Importado" and doc.sales_model in ("Proyectos", "Retail")`

| Desde | Acción (botón) | Hacia |
|---|---|---|
| 1 · Calificar | Requerimiento y diseño | 2 · Requerimiento y diseño |
| 1 · Calificar | Poner en pausa | En pausa |
| 1 · Calificar | Marcar como perdida | Perdida |
| 2 · Requerimiento y diseño | Propuesta enviada | 3 · Propuesta enviada |
| 2 · Requerimiento y diseño | Calificar | 1 · Calificar |
| 2 · Requerimiento y diseño | Poner en pausa | En pausa |
| 2 · Requerimiento y diseño | Marcar como perdida | Perdida |
| 3 · Propuesta enviada | Negociación | 4 · Negociación |
| 3 · Propuesta enviada | Requerimiento y diseño | 2 · Requerimiento y diseño |
| 3 · Propuesta enviada | Marcar como ganada | Ganada |
| 3 · Propuesta enviada | Poner en pausa | En pausa |
| 3 · Propuesta enviada | Marcar como perdida | Perdida |
| 4 · Negociación | Marcar como ganada | Ganada |
| 4 · Negociación | Propuesta enviada | 3 · Propuesta enviada |
| 4 · Negociación | Poner en pausa | En pausa |
| 4 · Negociación | Marcar como perdida | Perdida |
| En pausa | Calificar | 1 · Calificar |
| En pausa | Requerimiento y diseño | 2 · Requerimiento y diseño |
| En pausa | Propuesta enviada | 3 · Propuesta enviada |
| En pausa | Negociación | 4 · Negociación |
| En pausa | Marcar como perdida | Perdida |

Son **21 transiciones**.
- **Propuesta enviada → Ganada:** se incluye porque es común crear la orden de venta directamente desde la cotización.
- **Nombres de las acciones:** son el destino, para que no se repitan desde un mismo estado.
- **Acciones nuevas para Workflow Action Master:** "Requerimiento y diseño", "Propuesta enviada", "Negociación", "Calificar" y "Poner en pausa". "Marcar como ganada" y "Marcar como perdida" ya existen.
- **Requisitos de cada etapa:** desde el formulario estos botones no los validan. La page los valida en el servidor.

### 3.3 Nuevas · Abito GT y PA (fase 2, solo diseño)
Condición: `doc.establecimiento_lista in ("Abito Fontabella", "Grupo Creative") and doc.sales_model == "Retail"`

| Desde | Hacia |
|---|---|
| Cotizada | Seguimiento |
| Cotizada | Ganada |
| Cotizada | Perdida |
| Seguimiento | Ganada |
| Seguimiento | Perdida |
| Seguimiento | Cotizada (al renovar la cotización) |

Esto se confirma con la fase Retail. Hasta entonces, Abito sigue con sus 17 estados.

### 3.4 Lo que este diseño reemplaza
- **El PDF de 38 transiciones** (`docs/Transiciones_Workflow_Embudo_de_ventas_2019.pdf`) queda **obsoleto**. Era para escribir valores viejos.
- **Las transiciones viejas no aplican a Plus:** con este diseño, en Plus solo se usan las 21 nuevas.

## 4. Oportunidades nuevas

Frappe obliga a que toda oportunidad **nueva** empiece en el **primer estado** del workflow, que seguirá siendo "Investigar al cliente" por las demás empresas.

Para las de un tablero activo, el hook de nuestra app las pasa a su estado inicial al crearlas ("1 · Calificar" en Plus y "Cotizada" en Abito):
- se hace después de insertarlas, escribiendo directo en la base;
- es una normalización inicial, no un cambio de etapa del usuario.

## 5. Elementos del ERP que usan `embudo_state_v2`

### 5.1 Escriben la etapa (hay que adaptarlos para Plus en la fase 1)
| Elemento | Qué hace hoy | Problema en Plus | Cambio propuesto |
|---|---|---|---|
| Client Script **Quotation-Client** | Al cotizar desde una oportunidad pone `embudo_state_v2 = "Presentar cotización"` y copia `grand_total` al presupuesto | La transición no existe para Plus → error al guardar la cotización | Llamar a `marcar_etapa(oportunidad, "cotizada")`. En Plus no mueve la etapa: la etapa 3 exige una cotización **enviada**, y eso lo hace el hook del submit (ver 6). Para las demás empresas escribe "Presentar cotización" como hoy. |
| Client Script **Sales Order-Client** | Pone `embudo_state_v2 = "Ganada"` | Falla si la transición no existe desde la etapa actual | Llamar a `marcar_etapa(oportunidad, "ganada")`. Nuestro hook de Sales Order ya marca Ganada y Converted al enviar la orden. |
| Client Script **Opportunity-Client**: botón "Descartar" | Pone "Descartada" | "Descartada" no es estado de Plus | En Plus, ocultar el botón o convertirlo en "Dar por perdida" con motivo. Para las demás empresas, sin cambio. |
| Client Script **Opportunity-Client**: clasificación | Si la etapa es "Conocer" o "Presentar empresa", la pasa a "Tomar requerimiento" | Sin efecto en Plus: sus valores nuevos no cumplen la condición | Ninguno. |
| Server Script **Cambio de estado IDC** | Si la oportunidad está en "Investigar al cliente", la pasa a "Presentar cotización" | Sin efecto en Plus, por la misma razón | Ninguno. |
| Client Script **Customer-Client** | Pasa oportunidades en "Investigar al cliente" o "Clasificar" a "Presentar empresa" o "Descartada" | Sin efecto en Plus: filtra por valores viejos | Ninguno. |
| Client Script **Integracion de costos-Client** | El código que escribía la etapa está **comentado** | — | Ninguno. |

`marcar_etapa(oportunidad, evento)` sería un método de nuestra app. Decide el valor según la tienda: valor viejo para las demás empresas y valor nuevo para los tableros. Los Client Scripts los modifica el responsable del ERP.

### 5.2 Solo leen
| Elemento | Usa | Efecto en Plus | Cambio |
|---|---|---|---|
| Server Script Validar motivo de pérdida | "Perdida" | Funciona igual | Ninguno |
| Server Script Perdida marca cotizaciones Lost | "Perdida" | Funciona igual | Ninguno |
| Server Script Gclik (carga por arquitecto) | cuenta abiertas: todo lo que no sea Descartada, Ganada o Perdida | Las etapas nuevas cuentan como abiertas, que es lo correcto | Ninguno |
| Notification Oportunidad Perdida / Descartada (activa) | "Perdida", "Descartada" | Funciona con Perdida | Ninguno |
| Dashboard Chart **Pipeline** | agrupa por etapa | Aparecen las etapas nuevas como grupos propios | Opcional |
| Dashboard Chart **Monto OPTYS en negociación** | filtra "Negociar" | **No incluiría** "4 · Negociación" de Plus | Agregar "4 · Negociación" al filtro |
| 5 reportes (CS: Oportunidades perdidas, Oportunidad por Vendedor, Pendientes de cotizar, Sin asesor asignado, Seguimiento de cierre) | Ganada, Perdida, Descartada | Funcionan igual | Ninguno |
| Report "Oportunidades Alex Marroquin(Eliminar)" | — | — | Desactivar (está marcado para eliminar) |
| Client Scripts **CRM Dashboard V2** y **CRM Dashboard** | los 17 valores (kanban viejo) | Las oportunidades de Plus no se verían bien | Retirar el V2 para Plus el mismo día (la especificación ya lo indica) |

### 5.3 Código de otras apps (servidor de pruebas)
Ver la sección 9.

## 6. Cotización enviada (Plus)

La especificación pide que la etapa 3 tenga una cotización **enviada** ligada. Propuesta: al **enviar** (submit) una cotización de una oportunidad de Plus que esté en Calificar o Requerimiento, nuestro hook la pasa a "3 · Propuesta enviada":
- valida los requisitos de la etapa;
- respeta el workflow;
- si falta algo, no la mueve y no bloquea el envío de la cotización.

**Pendiente de tu confirmación.**

## 7. Migración de Plus (fase 1) · simulación

Solo las oportunidades **abiertas** de Plus Fontabella Importado. Datos de producción, 2026-11-13.

**Equivalencias (especificación):**
- Investigar al cliente / Clasificar / Presentar empresa / Conocer → **1 · Calificar**
- Tomar requerimiento / Definir la solución / Presentar solución / Crear el diseño / Presentar diseño → **2 · Requerimiento y diseño**
- Crear la cotización / Presentar cotización → **3 · Propuesta enviada**
- Dar seguimiento / Negociar → **4 · Negociación**
- Llamar después → **En pausa**
- Ganada → Ganada
- Perdida → Perdida
- Descartada → Perdida con motivo "No calificó"

| Valor actual | Proyectos | Retail (Plus) | Pasa a |
|---|---|---|---|
| Investigar al cliente | 25 | 23 | 1 · Calificar |
| Presentar cotización | 41 | 28 | 3 · Propuesta enviada |
| Dar seguimiento | 14 | 2 | 4 · Negociación |
| Negociar | 2 | 4 | 4 · Negociación |
| **Ganada** con status abierto | **22** | **32** | ver regla |
| **Descartada** con status abierto | **9** | **27** | ver regla |
| **Perdida** con status abierto | **4** | 0 | ver regla |
| **Total abiertas** | **117** | **116** | **233** |

**Reglas propuestas para las 94 incoherentes:**
- **Ganada abierta:**
  - con orden de venta enviada ligada → status Converted;
  - sin orden → **lista de revisión** para el asesor, sin cambio automático.
- **Descartada abierta:** pasa a Perdida y status Lost, con motivo **"No calificó"**. Ese motivo **no existe** en `Lost Reason` y hay que crearlo antes.
- **Perdida abierta:**
  - con motivo → status Lost;
  - sin motivo → **lista de revisión**.

**Cómo se ejecuta:**
- **Escritura directa** en la base: sin guardar documento por documento, para no disparar en masa "Perdida marca cotizaciones Lost" ni la notificación de pérdida.
- **Respaldo:** cada oportunidad guarda su valor anterior en `custom_embudo_state_v2_anterior` y `custom_status_anterior`, más un `bench backup` previo.
- **Simulación primero:** el patch tiene modo simulación (solo cuenta). Se ejecuta de verdad solo con confirmación.
- **Reversa:** un patch de reversa restaura los valores y el workflow anterior desde una copia guardada en el repositorio.

**Cerradas:** las oportunidades cerradas de Plus conservan su valor viejo. Siguen siendo estados válidos del workflow.

## 8. Abito (fase 2) · panorama

Solo referencia. Abiertas Retail a hoy:
- **Abito Fontabella (Umob):** **73**.
- **Abito PA, "Grupo Creative":** **988**.
  - **701** están en "Perdida" con status abierto (620 en *Quotation* y 81 en *Open*).
  - 116 están en Descartada y 86 en Ganada, también con status abierto.

**La limpieza de Abito PA es grande** y conviene decidirla al diseñar el tablero Retail.

## 9. Código de otras apps que usa `embudo_state_v2`

Resultado del `grep` en el servidor de pruebas (`/home/creative/frappe-bench/apps`, sin incluir `crm_dashboard_v3`):

_pendiente: se completa con el resultado de la búsqueda._

## 10. Decisiones pendientes

1. **Abrir oportunidades de Plus en "1 · Calificar":** confirmar que se haga al crearlas (sección 4).
2. **Cotización enviada → "3 · Propuesta enviada":** ¿se mueve sola? (sección 6).
3. **Reglas para las 94 incoherentes de Plus** (sección 7) y **crear el motivo "No calificó"** en `Lost Reason`.
4. **Botón "Descartar" en Plus:** ¿se oculta o se convierte en "Dar por perdida"?
5. **Rol de las transiciones nuevas:** ¿solo "Embudo de ventas", o también "Jefe de Plus"?
6. **Retirar el CRM Dashboard V2 para Plus** el día que entre el workflow.
