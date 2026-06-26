# HISTORIAL TÉCNICO — Proyecto "Camino B"
> **Propósito:** Bitácora de experimentos, decisiones de arquitectura y resultados para consulta futura.
> **Última actualización:** 2026-06-14
> **Estado del proyecto:** 🟢 Activo — Tool Calling estabilizado con llama3.2:3b

---

## 📌 Índice

1. [Stack Tecnológico](#stack-tecnológico)
2. [Arquitectura Actual](#arquitectura-actual)
3. [Pruebas con Llama 3.2](#pruebas-con-llama-32)
4. [Ajustes de Prompt](#ajustes-de-prompt)
5. [Migración a Qwen (Contingencia)](#migración-a-qwen-contingencia)
6. [Pendientes y Próximos Pasos](#pendientes-y-próximos-pasos)
7. [Registro de Sesiones](#registro-de-sesiones)

---

## Stack Tecnológico

| Componente | Tecnología | Versión / Notas |
|---|---|---|
| Interfaz gráfica | CustomTkinter | Tema dark, fuente Consolas |
| Backend LLM | Ollama (local) | Sin API externa |
| Modelo primario | llama3.2:3b | 2.0 GB, cuantizado |
| Modelo contingencia | qwen2.5:7b | Pendiente de prueba |
| Memoria | SQLite (`memoria.db`) | Últimos 20 mensajes por sesión |
| Lenguaje | Python 3.x | Entorno virtual `/venv` |
| SO | Linux | Ejecución 100% offline |

---

## Arquitectura Actual

```
asistente.py
├── init_db()               → Crea tablas sesiones/mensajes en SQLite
├── llamar_modelo()         → Llama a ollama.chat() en hilo separado (streaming)
│   └── ollama.chat(
│         model="llama3.2:3b",
│         messages=[system] + historial,
│         stream=True
│       )                   ← ⚠️ Sin tools=[] todavía (próximo paso)
├── UI (CustomTkinter)
│   ├── Sidebar             → Lista de sesiones con menú contextual
│   └── Chat                → Streaming token a token, thread-safe con .after()
└── DB (SQLite)
    ├── sesiones            → id, nombre, creada
    └── mensajes            → id, sesion_id, rol, contenido, enviado
```

**Limitación actual:** `llamar_modelo()` no tiene herramientas definidas.
El parámetro `tools=[]` no está implementado aún en `asistente.py`.

---

## Pruebas con Llama 3.2

### Sesión 1 — 2026-06-14

**Objetivo:** Verificar si llama3.2:3b puede hacer tool calling con la API nativa de Ollama.

**Herramienta de evaluación:** `test_tools.py` (3 escenarios de complejidad creciente)

**Modo probado:** Modo 1 — API nativa `tools=[]` de Ollama

#### Resultados

| Escenario | Herramienta esperada | Resultado | Tiempo |
|---|---|---|---|
| 🌤 Clima simple | `get_current_weather(city)` | ✅ PASS | 10.9s |
| 🔢 Cálculo matemático | `calculate(expression)` | ✅ PASS | 20.1s |
| ⏰ Recordatorio (3 args) | `create_reminder(title, datetime_iso, priority)` | ✅ PASS | 29.3s |

**Veredicto:** `3/3 — 100% — 🎉 TOOL CALLING ESTABLE`

#### Observaciones técnicas

- El modelo devuelve `content: ""` y `tool_calls: [...]` cuando elige una herramienta. Comportamiento correcto.
- **Bug detectado y documentado:** En el test diagnóstico inicial, `city` llegó como `'\nMadrid'` (salto de línea prefijado). En la prueba formal de 3 escenarios no se reprodujo.
- **Mitigación aplicada:** Limpieza defensiva `str.strip()` en todos los argumentos string dentro de `test_tools.py`.
- Tiempo de inferencia: ~10-30s por llamada (hardware local sin GPU dedicada).

---

## Ajustes de Prompt

### System Prompt Original (asistente.py)

```
Eres un asistente personal local llamado Asistente.
La persona que te escribe es el usuario: él pregunta, tú respondes.
Nunca confundas los roles: tú eres el asistente, no el usuario.
Si el usuario te dice su nombre u otro dato personal, recuérdalo y úsalo.
Responde siempre en español, de forma clara, directa y útil.
No te presentes en cada respuesta; solo hazlo si el usuario te lo pide.
```

**Limitación:** No tiene instrucciones de tool calling. Si se añaden herramientas, el modelo podría no priorizarlas sobre respuestas en texto.

---

### System Prompt Propuesto — Modo 1 (API nativa, español)

```
Eres un asistente personal local llamado Asistente. Operas 100% offline.

REGLAS DE COMPORTAMIENTO:
- Responde siempre en español, de forma clara y directa.
- Si el usuario te dice su nombre u otro dato, recuérdalo.
- No te presentes en cada respuesta; solo si te lo piden.
- Nunca confundas tu rol con el del usuario.

REGLAS DE HERRAMIENTAS:
- Si la solicitud del usuario puede ser resuelta por una función disponible,
  DEBES llamar esa función. No respondas en texto cuando hay una herramienta aplicable.
- Solo responde en texto si NINGUNA función es apropiada.
- Nunca inventes valores que el usuario no haya proporcionado.
- Para parámetros opcionales, inclúyelos solo si el usuario los mencionó.
```

---

### System Prompt Propuesto — Modo 2 (JSON forzado, fallback)

> Usar solo si la API nativa `tools=[]` falla o el modelo alucina.

```
Eres un asistente de funciones. Tu ÚNICA salida es un objeto JSON.

FORMATO ESTRICTO:
{"name": "<nombre_funcion>", "arguments": {"<param>": <valor>}}

REGLAS — sin excepciones:
1. Solo JSON. Sin texto antes ni después.
2. Sin bloques de código (```). Sin explicaciones.
3. Usa exactamente los nombres de función y parámetros listados.
4. Si ninguna función aplica: {"name": "none", "arguments": {}}

FUNCIONES DISPONIBLES:
{tools_json}

Ejemplos:
Usuario: "¿Qué clima hace en París?"
Salida: {"name": "get_current_weather", "arguments": {"city": "París"}}

Usuario: "Calcula 15 por 4"
Salida: {"name": "calculate", "arguments": {"expression": "15 * 4"}}
```

> **Nota:** Los ejemplos `Usuario/Salida` son críticos para modelos 3B.
> Sin ellos la tasa de error aumenta significativamente.

---

## Migración a Qwen (Contingencia)

**Estado:** 🔵 No necesaria — llama3.2:3b pasó 3/3 pruebas.

### Criterios de activación del plan de contingencia

Migrar a `qwen2.5:7b` si:
- [ ] llama3.2:3b falla < 2/3 escenarios en pruebas reales del asistente
- [ ] El modelo alucina herramientas que no existen
- [ ] La latencia >45s se vuelve inaceptable para el uso cotidiano
- [ ] Se requieren herramientas con razonamiento complejo (multi-step)

### Pasos para migrar

```bash
# 1. Descargar el modelo
ollama pull qwen2.5:7b

# 2. Verificar tool calling
python test_tools.py --modelo qwen2.5:7b --verbose

# 3. Cambiar en asistente.py
# Línea 150: model="llama3.2:3b"  →  model="qwen2.5:7b"
# Línea 398: title="... llama3.2:3b"  →  title="... qwen2.5:7b"
```

---

## Pendientes y Próximos Pasos

### Alta prioridad
- [ ] **Integrar `tools=[]` en `asistente.py`** — añadir el parámetro a `llamar_modelo()` y manejar el ciclo tool call → ejecución → respuesta final
- [ ] **Definir catálogo de herramientas útiles** — propuestas: hora actual, calculadora, recordatorios en SQLite, búsqueda en archivos locales
- [ ] **Actualizar system prompt** — incluir reglas de tool calling en `SYSTEM_PROMPT`

### Media prioridad
- [ ] Mostrar en el chat el resultado de herramientas de forma legible (no JSON crudo)
- [ ] Manejar errores de herramienta en la UI (ej. herramienta no disponible)
- [ ] Agregar indicador visual cuando el modelo está "pensando" vs. "ejecutando herramienta"

### Baja prioridad
- [ ] Probar Modo 2 (JSON forzado) como benchmark de comparación
- [ ] Evaluar latencia real en flujo completo de UI (streaming + tool call)
- [ ] Considerar caché de respuestas para consultas repetidas offline

---

## Registro de Sesiones

> Añadir una entrada aquí después de cada sesión de desarrollo.

---

### Sesión 001 — 2026-06-14

**Participantes:** Usuario + Antigravity (Claude)
**Duración estimada:** ~1h
**Objetivo de la sesión:** Análisis inicial del proyecto y estabilización de tool calling

**Acciones realizadas:**
1. Análisis completo de `asistente.py` (499 líneas)
2. Diagnóstico de la conexión con Ollama — sin tools implementados
3. Test diagnóstico rápido → Bug detectado: `'\nMadrid'` en argumentos
4. Creación de `test_tools.py` (evaluador offline de 3 escenarios)
5. Ejecución del evaluador → **3/3 PASS** con llama3.2:3b, Modo 1
6. Propuesta de 2 system prompts optimizados (Modo 1 y Modo 2)
7. Creación de este archivo `HISTORIAL_CLAUDE.md`

**Decisiones tomadas:**
- ✅ Mantener llama3.2:3b como modelo principal (pasó todas las pruebas)
- ✅ Usar Modo 1 (API nativa `tools=[]`) como estrategia principal
- 🔵 Plan de contingencia con qwen2.5:7b en espera (no activado)

**Archivos creados/modificados:**
- `test_tools.py` — CREADO
- `HISTORIAL_CLAUDE.md` — CREADO

**Pendiente para próxima sesión:**
- Integrar tool calling en `asistente.py`
- Definir el catálogo de herramientas del asistente

---

<!-- PLANTILLA PARA PRÓXIMAS SESIONES

### Sesión 00X — YYYY-MM-DD

**Participantes:**
**Duración estimada:**
**Objetivo de la sesión:**

**Acciones realizadas:**
1.

**Decisiones tomadas:**
-

**Archivos creados/modificados:**
-

**Pendiente para próxima sesión:**
-

-->
