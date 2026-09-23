# 🤖 Manual de Operación y Reglas Agénticas - AutoTrx

Bienvenido a **AutoTrx**. Si eres un agente de IA (Antigravity, Claude, Codex, Gemini, etc.) o un desarrollador iniciando una nueva sesión, **este documento es tu punto de partida obligatorio**. Contiene la arquitectura del sistema, el protocolo de diagnóstico rápido, los comandos de despliegue y las **Reglas de Oro innegociables** para mantener la estabilidad del sistema en producción.

---

## 🏛️ 1. Arquitectura y Entornos en 60 Segundos

AutoTrx es un sistema de finanzas personales y familiares "Human-in-the-Loop".
* **Ingesta:** Monitorea Gmail cada 60s (Bancolombia, RappiCard, Glim) y recibe webhooks de Tasker en Android.
* **Buffer & Persistencia:** Almacena de inmediato en SQLite local (`autotrx.db` en WAL mode) para evitar pérdida de transacciones ante caídas o reinicios.
* **Human-in-the-Loop:** Envía botones inline interactivos a Telegram (bots separados para Juanma y Leydi).
* **Carga (Destino final):** Guarda transacciones confirmadas en Google Sheets (pestaña `"Base_Transacciones"`).
* **Logs:** Transmite logs en vivo a **Google Cloud Logging** (sin saturar el disco de la VM).

### Mapa de Entornos
| Parámetro | Entorno Local (Windows) | Entorno Producción (GCP Compute Engine) |
| :--- | :--- | :--- |
| **Directorio** | `C:\Users\Administrador\Documents\Proyectos\autotrx` | `/home/juanbarco92/wallet_bot` |
| **Instancia VM** | N/A | `instance-20251217-175237` (zona `us-central1-c`) |
| **Proyecto GCP** | `autotrx-481014` | `autotrx-481014` |
| **Gestión Proceso**| Manual / Terminal (`poetry run ...`) | Systemd: `wallet_bot.service` (auto-restart) |
| **Script de Inicio**| `python main.py` | `/home/juanbarco92/wallet_bot/run_bot.sh` |
| **Autenticación** | `gcloud auth list` -> `juanbarco92@gmail.com` | Service Account de Compute Engine preconfigurada |

---

## 🛡️ 2. Las Reglas de Oro Agénticas (Guardrails Obligatorios)

Todo agente operando en este repositorio **DEBE** cumplir estrictamente las siguientes reglas:

### 🚨 Regla 1: Prohibido desplegar sin 100% de Tests Aprobados
**NUNCA** hagas `git push origin master` ni ejecutes `git pull` en la VM de GCP sin antes haber corrido y pasado la suite completa de pruebas localmente:
```powershell
pytest tests/ -v
```
Si aunque sea **un solo test falla**, el despliegue queda cancelado hasta corregirlo.

### 🔒 Regla 2: Despliegue Atómico y Verificación Post-Restart
No basta con reiniciar el servicio en la VM. El ciclo de vida de un despliegue siempre concluye verificando activamente:
1. `git pull origin master` en la VM.
2. `sudo systemctl restart wallet_bot`.
3. Comprobar que el servicio está `active (running)`.
4. Inspeccionar los logs inmediatamente para confirmar que los dos bots de Telegram iniciaron polling con código `200 OK` y la ingesta de emails está viva.

### 🧪 Regla 3: Aislamiento Total en Tests (Base de Datos en Memoria)
Las pruebas unitarias y de integración que interactúen con SQLite deben usar **estrictamente** `db_path=":memory:"`.
* **Prohibido:** Modificar, alterar o insertar registros basura en el archivo `autotrx.db` real durante ejecuciones de prueba.
* La clase `Storage` en `src/storage.py` preserva la conexión `_mem_conn` para bases en memoria entre llamadas.

### 👤 Regla 4: Privacidad y Filtrado Estricto por Usuario
Las transacciones están etiquetadas con su propietario (`target_user = "Juanma"` o `"Leydi"`).
* Los comandos `/pendientes` (`/p`) y `/ultimas` (`/u`) **deben filtrar exclusivamente por el usuario que envió el comando**.
* **Prohibido:** Crear "fallbacks" que muestren transacciones globales o de otro usuario si el solicitante actual no tiene pendientes.

### 📄 Regla 5: Respeto a Quirks de Google Sheets y Push de Telegram
* **Límite de grilla en Sheets:** Si la hoja alcanza su límite de filas con filtros activos, `append_row` pierde datos silenciosamente. Siempre se debe validar `sheet.row_count` y usar `sheet.add_rows(100)` antes de escribir vía `sheet.update(...)` (ver `src/loader.py`).
* **Mensajes de Confirmación en Telegram:** `edit_message_text` actualiza el mensaje interactivo en pantalla preservando siempre todos los datos originales de la transacción (Usuario, Comercio, Monto, Fecha) y añadiendo el desglose por categorías y acumulados. Se retiró el mensaje flotante redundante que decía solo `"guardado"`.
* **Robustez en Markdown:** Los comercios suelen incluir caracteres conflictivos (ej. `*EXITO*`, `DLO*NETFLIX`). Siempre usar sanitización de Markdown y envolver `edit_message_text` en un bloque `try/except` con fallback a texto plano si Telegram rechaza las entidades Markdown.

---

## ⚡ 3. Playbook de Comandos para Agentes (Chequeos y Operaciones)

Copia y ejecuta estos comandos directamente según la tarea:

### A. Chequeo Rápido de Salud Local
```powershell
# 1. Verificar estado del repositorio
git status

# 2. Ejecutar suite de pruebas completa
pytest tests/ -v

# 3. Validar sintaxis de archivos principales sin ejecutar
python -m py_compile main.py src/*.py
```

### B. Inspección de Logs en Vivo en Producción (Sin descargar archivos)
Gracias a la integración con Google Cloud CLI y SSH, puedes auditar la nube directamente:

```powershell
# Ver últimos 30 registros del servicio en la VM de GCP vía SSH:
gcloud compute ssh instance-20251217-175237 --zone=us-central1-c --command="sudo journalctl -u wallet_bot.service -n 30 --no-pager"

# Ver estado y PID del servicio en la VM:
gcloud compute ssh instance-20251217-175237 --zone=us-central1-c --command="systemctl status wallet_bot --no-pager"

# Consultar Google Cloud Logging directamente:
gcloud logging read 'resource.type="gce_instance" AND jsonPayload.message=~".*"' --limit=20 --format="value(timestamp, jsonPayload.message)"
```

### C. Procedimiento Estándar de Despliegue (1-Línea)
Una vez aprobados los tests locales y realizado el commit + push a `master`:
```powershell
gcloud compute ssh instance-20251217-175237 --zone=us-central1-c --command="sudo -u juanbarco92 git -C /home/juanbarco92/wallet_bot pull origin master && sudo systemctl restart wallet_bot && systemctl status wallet_bot --no-pager"
```

### D. Chequeo de Base de Datos SQLite Local (`autotrx.db`)
Para inspeccionar rápidamente las transacciones locales en Windows:
```powershell
python -c "import sqlite3; conn=sqlite3.connect('autotrx.db'); print(conn.execute('SELECT id, status, target_user, merchant, amount, created_at FROM transactions ORDER BY id DESC LIMIT 5').fetchall())"
```

---

## 📂 4. Mapa Clave del Código Fuente

* **[main.py](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/main.py):** Orquestador principal. Inicia los bots de Telegram, el scheduler de sondeo de Gmail (cada 60s) y el logger de GCP.
* **[src/bot.py](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/src/bot.py):** Lógica conversacional de Telegram. Maneja el teclado inline, guardado en Sheets, comando `/pendientes` (o `/p`), `/ultimas` (o `/u`), `/frecuentes` (o `/f`), `/fijos`, `/nuevo_frecuente` (o `/nf`), y recuperación de transacciones huérfanas desde SQLite.
* **[src/storage.py](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/src/storage.py):** Capa de persistencia SQLite. Gestiona transacciones (`transacciones_log`), memoria de comercios (`merchant_memory`) y plantillas frecuentes (`recurring_templates`).
* **[src/parser.py](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/src/parser.py):** Motor de extracción regex. Parsea notificaciones de Bancolombia, RappiCard, Glim y Tasker. Limpia asteriscos y normaliza fechas y montos.
* **[src/loader.py](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/src/loader.py):** Cliente de Google Sheets. Maneja el control de filas dinámicas (`add_rows`), autenticación con Service Account, escritura por lotes y sincronización de gastos fijos (`Config_Fijos`).
* **[src/ingestion.py](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/src/ingestion.py):** Cliente de Gmail API. Descarga correos no leídos y extrae el cuerpo MIME para el parser.
* **[backlog.md](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/backlog.md):** Hoja de ruta estratégica de producto (Iniciativa 1: Clasificación 1 Clic con memoria de comercios; Iniciativa 2: Presupuesto ponderado de pareja).
* **[context.md](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/context.md):** Bitácora histórica de quirks técnicos específicos de Google Sheets y Telegram.

---

## 💡 5. Buenas Prácticas Agénticas para Futuras Mejoras

1. **Idempotencia:** Diseña cualquier migración de base de datos o script para ser re-ejecutable sin causar duplicados (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN` condicional).
2. **Fail-Safe Persistence First:** Antes de interactuar con servicios externos (Telegram, Google Sheets), el dato original crudo siempre debe estar seguro en `autotrx.db`. Si Google Sheets se cae o la API falla, la transacción debe permanecer `PENDING` para poder ser reintentada en cualquier momento con `/pendientes`.
3. **Mantén el Backlog Vivo:** Cada vez que el usuario plantee una idea futura, regístrala en [backlog.md](file:///C:/Users/Administrador/Documents/Proyectos/autotrx/backlog.md) con su valor de negocio y propuesta técnica preliminar.
4. **Preserva la Documentación:** Actualiza este archivo (`AGENTS.md`) si se introducen nuevos comandos, nuevas variables de entorno o cambios en la infraestructura de GCP.
