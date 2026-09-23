# AutoTrx — Product & Engineering Backlog

Este documento reúne las iniciativas estratégicas, especificaciones funcionales y arquitectura técnica para la evolución de **AutoTrx**.

---

## 📌 Iniciativa 1: Clasificación Inteligente en 1 Clic (Smart Quick-Save)

### 1.1. Contexto y Problema
Actualmente, el registro de cada gasto requiere navegar un árbol de 4 a 5 pasos en Telegram:
1. `¿Deseas registrarla?` (Sí / No)
2. `¿Personal o Pareja?`
3. `Categoría Principal`
4. `Subcategoría` o `Tipo de Acción`
5. `Confirmar guardado`

El 80% de las transacciones recurrentes corresponden a comercios con patrones predecibles (e.g. *D1*, *Uber*, *Netflix*, *EPM*, *Spotify*). El objetivo es reducir la fricción a **1 solo toque** para transacciones conocidas, manteniendo total control manual cuando sea necesario.

### 1.2. El Reto: Compras con Múltiples Categorías (Splits) y Comercios Ambiguos
Existen comercios donde una compra no siempre va a una sola categoría, o donde frecuentemente se divide el monto:
* **Comercios híbridos / Grandes superficies:** *Éxito*, *Falabella*, *Carulla*, *Amazon* (donde una compra puede ser parte *Mercado*, parte *Ropa/Personal*, o parte *Hogar*).
* **Múltiples categorías en una sola compra:** Si una factura de $200.000 se suele dividir ($150k Mercado + $50k Farmacia/Aseo).
* **Comercios con Scope variable:** Lugares donde a veces paga Juanma algo personal y otras veces es gasto de pareja.

### 1.3. Reglas de Negocio y Lógica de Decisión
Para resolver la ambigüedad sin frustrar al usuario, el bot operará bajo un **umbral de confianza (Confidence Score)**:

1. **Alta Confianza (Confidence $\ge$ 80% y mono-categoría histórica):**
   * El bot propone la sugerencia con botón de 1 clic:
     ```text
     💰 Compra: $34.500 en D1 * MEDELLIN
     🎯 Sugerencia: 🛒 Mercado - Supermercado (Pareja)

     [⚡ Guardar Directo (1 Clic)]
     [✏️ Cambiar / Dividir]   [❌ Descartar]
     ```
   * Si el usuario presiona `[⚡ Guardar Directo]`: Se guarda de inmediato en Sheets y SQLite.
   * Si presiona `[✏️ Cambiar / Dividir]`: Abre el flujo completo permitiendo seleccionar o dividir el monto (Splits).

2. **Baja Confianza o Comercio Históricamente Dividido / Ambiguo:**
   * Si el comercio tiene registros históricos con múltiples categorías dispares (e.g. *Éxito* dividido entre Mercado 60% y Ropa 40%), o si el usuario suele usar "Dividir Monto":
   * **El bot NO asume 1 solo clic a ciegas.**
   * Presenta las opciones más frecuentes como accesos directos o entra al flujo de categorización/split tradicional para evitar errores en las cuentas.

3. **Comercio Nuevo:**
   * Entra directamente al flujo estándar de categorización.

### 1.4. Arquitectura de Datos (`merchant_memory`)
Tabla dedicada en `autotrx.db`:
```sql
CREATE TABLE IF NOT EXISTS merchant_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_pattern TEXT NOT NULL,         -- Substring o nombre limpio (ej. 'D1', 'UBER')
    category_full TEXT NOT NULL,            -- 'Mercado - Supermercado'
    scope TEXT NOT NULL,                    -- 'Personal' o 'Pareja'
    tx_type TEXT NOT NULL,                  -- 'Gasto', 'Ingreso', 'Ahorro'
    usuario TEXT NOT NULL,                  -- 'Juanma' o 'Leydi'
    frequency INTEGER DEFAULT 1,            -- Veces clasificado así
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(merchant_pattern, category_full, scope, usuario)
);
```

### 1.5. Estrategia de Siembra (Seeding)
* **Paso Inicial:** Un script de lectura única sobre `Base_Transacciones` en Google Sheets para poblar `merchant_memory` con todo el historial de meses anteriores.
* **Aprendizaje Continuo:** Cada guardado confirmado en Telegram actualiza o incrementa la frecuencia en `merchant_memory`.

---

## 📌 Iniciativa 2: Gestión Proactiva de Presupuestos y Cierre Ponderado de Pareja

### 2.1. Contexto y Problema
* El cierre de cuentas a fin de mes es reactivo y consume tiempo: cruzar gastos compartidos, calcular quién pagó de más y determinar el monto de transferencia.
* No hay tiempo para redactar presupuestos estáticos en Excel ni para mantenerlos actualizados mes a mes.
* **Modelo Financiero de Pareja:**
  - Existe una **Bolsa Familiar** (gastos compartidos del hogar) y **Bolsas Personales** independientes.
  - La distribución **no es 50/50 fija**: se pondera según el porcentaje de ingresos de cada uno en el mes (e.g. Juanma ~80% / Leydi ~20%, pero de carácter dinámico mensual).

### 2.2. Solución Funcional: "Cierre en 15 Segundos" (`/cierre` o `/balance`)
El bot automatiza la liquidación del ciclo (del día 25 al 24 de cada mes):
1. **Configuración de Ingresos del Ciclo:**
   * Al iniciar el ciclo (o vía comando `/ingresos Juanma 80 Leydi 20` o montos absolutos), el bot registra la proporción del mes.
2. **Cálculo de Liquidación Proporcional:**
   $$\text{Aporte Esperado Juanma} = \text{Total Gastos Pareja} \times \%_{\text{Juanma}}$$
   $$\text{Saldo} = \text{Pagado por Juanma} - \text{Aporte Esperado Juanma}$$
3. **Reporte en Telegram:**
   ```text
   ⚖️ Liquidación Ciclo Pareja (25 Ago - 24 Sep)
   Ponderación: Juanma 80% | Leydi 20%

   • Total Gastos Compartidos: $4.500.000
     - Cuota Juanma (80%): $3.600.000
     - Cuota Leydi (20%):    $900.000

   💳 Pagos Realizados:
     - Juanma aportó en compras: $3.200.000
     - Leydi aportó en compras:  $1.300.000

   👉 Ajuste de Cuentas: Juanma le transfiere a Leydi $400.000 para quedar en balance exacto.
   ```

### 2.3. "Velocímetro" de Gasto en Tiempo Real (Pacing)
* En vez de presupuestos manuales en celdas, el sistema utiliza **promedios móviles históricos de los últimos 3 ciclos** por categoría.
* Si a mitad del ciclo (día 10-15) el ritmo de gasto en categorías discrecionales (Restaurantes, Salidas) supera la velocidad esperada en más de un 25%, el bot añade una alerta suave al mensaje de confirmación de gasto.

---

## 📌 Iniciativa 3: Notification Listener Nativo en Android (Reemplazo de Tasker)

### 3.1. Contexto y Problema
* Depender de Tasker en Android requiere configuración manual avanzada de perfiles XML y webhooks HTTP locales, lo que dificulta el mantenimiento e imposibilita escalar la app a terceros.
* La ingesta vía Gmail tiene restricciones de privacidad y costos prohibitivos de auditoría OAuth.

### 3.2. Solución Propuesta
* **Mini-App Android (Flutter / Kotlin):**
  - Aplicación ligera con permiso `NotificationListenerService`.
  - Escucha en segundo plano notificaciones push de apps bancarias (Bancolombia, Nu, Nequi, Davivienda, etc.).
  - Extrae el texto en el dispositivo y envía un payload cifrado por HTTPS al backend de AutoTrx.
  - Elimina la necesidad de Tasker y corre de forma 100% silenciosa en los teléfonos de Juanma y Leydi.

---

## 📌 Iniciativa 4: Telegram Mini App (Dashboard Visual Integrado)

### 4.1. Contexto y Problema
Telegram es ideal para input (notificación y clasificación), pero deficiente para visualización de métricas, reportes y tablas resumen.

### 4.2. Solución Propuesta
* Implementar una **Telegram Mini App (TMA)**:
  - Botón web dentro del chat de Telegram (`📊 Ver Dashboard`).
  - Interfaz web mobile-first oscura (React/Tailwind) montada sobre el backend FastAPI/AIOHTTP existente.
  - Visualización de gráficos de gasto por categoría, balance del ciclo actual y buscador/editor rápido de transacciones.
