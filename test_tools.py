#!/usr/bin/env python3
"""
test_tools.py — Evaluación de Tool Calling para Camino B
=========================================================
Somete a llama3.2:3b (y opcionalmente qwen2.5:7b) a 3 escenarios de
function-calling de complejidad creciente.  100 % offline, sin APIs externas.

Modos de ejecución:
  python test_tools.py                  # Usa llama3.2:3b (modo 1 — nativo Ollama)
  python test_tools.py --modo 2         # Modo 2: JSON forzado en el prompt
  python test_tools.py --modelo qwen2.5:7b   # Cambia el modelo
  python test_tools.py --verbose        # Muestra la respuesta cruda completa
"""

import json
import re
import sys
import time
import argparse
from datetime import datetime
import ollama

# ── Configuración ──────────────────────────────────────────────────────────────

DEFAULT_MODEL = "llama3.2:3b"

# System prompt para MODO 2 (JSON forzado)
# Se usa cuando el modelo NO usa la API nativa de tools de Ollama
SYSTEM_PROMPT_MODO2 = """You are a function-calling assistant. Your ONLY job is to call functions.

RULES — follow them without exception:
1. When the user asks something, respond ONLY with a JSON object in this exact format:
   {"name": "<function_name>", "arguments": {<key>: <value>, ...}}
2. Do NOT add any text before or after the JSON.
3. Do NOT explain yourself. Do NOT say "I will call...".
4. If no function fits, respond with: {"name": "none", "arguments": {}}

Available functions:
{tools_block}

Now respond to the user's request with a single JSON object."""

# ── Definición de herramientas ─────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Returns the current weather for a given city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The name of the city, e.g. 'Madrid'"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "Temperature unit. Default is celsius."
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluates a simple math expression and returns the numeric result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A math expression, e.g. '(15 * 4) / 3'"
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Creates a reminder for the user at a specific time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title of the reminder"
                    },
                    "datetime_iso": {
                        "type": "string",
                        "description": "Date and time in ISO 8601 format, e.g. '2025-01-15T09:00:00'"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Priority level. Default is medium."
                    }
                },
                "required": ["title", "datetime_iso"]
            }
        }
    }
]

# ── Escenarios de prueba ───────────────────────────────────────────────────────

SCENARIOS = [
    {
        "id": 1,
        "name": "🌤  Clima simple",
        "description": "Una sola herramienta, un solo argumento obligatorio.",
        "message": "What is the weather like in Tokyo right now?",
        "expected_tool": "get_current_weather",
        "expected_args": {"city": "Tokyo"}
    },
    {
        "id": 2,
        "name": "🔢  Cálculo con expresión",
        "description": "Herramienta con un argumento de tipo string que es una expresión.",
        "message": "Calculate the result of (128 / 4) + 17 for me.",
        "expected_tool": "calculate",
        "expected_args": {"expression": "(128 / 4) + 17"}
    },
    {
        "id": 3,
        "name": "⏰  Recordatorio con múltiples args",
        "description": "Tres argumentos: dos obligatorios y uno opcional de enum.",
        "message": (
            "Set a high-priority reminder called 'Team standup' "
            "for tomorrow at 9 AM. Use ISO format for the date: 2025-01-16T09:00:00"
        ),
        "expected_tool": "create_reminder",
        "expected_args": {
            "title": "Team standup",
            "datetime_iso": "2025-01-16T09:00:00",
            "priority": "high"
        }
    }
]

# ── Implementaciones simuladas (offline) ──────────────────────────────────────

def get_current_weather(city: str, unit: str = "celsius") -> dict:
    """Respuesta simulada — sin API externa."""
    return {
        "city": city,
        "temperature": "22",
        "unit": unit,
        "condition": "Partly cloudy",
        "humidity": "60%",
        "source": "[SIMULATED — offline]"
    }

def calculate(expression: str) -> dict:
    """Evalúa la expresión de forma segura."""
    try:
        # Solo permitimos caracteres matemáticos básicos
        if not re.fullmatch(r"[\d\s\+\-\*\/\(\)\.]+", expression):
            return {"error": "Expresión no permitida"}
        result = eval(expression)  # nosec
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": str(e)}

def create_reminder(title: str, datetime_iso: str, priority: str = "medium") -> dict:
    """Crea un recordatorio simulado."""
    return {
        "status": "created",
        "title": title,
        "datetime": datetime_iso,
        "priority": priority,
        "id": f"REM-{hash(title) % 10000:04d}"
    }

TOOL_REGISTRY = {
    "get_current_weather": get_current_weather,
    "calculate": calculate,
    "create_reminder": create_reminder,
}

# ── Lógica de evaluación ───────────────────────────────────────────────────────

def evaluar_resultado(tool_name: str, tool_args: dict, scenario: dict) -> dict:
    """Compara el tool call del modelo con el esperado."""
    expected_tool = scenario["expected_tool"]
    expected_args = scenario["expected_args"]

    tool_ok = tool_name == expected_tool
    args_ok = {}
    for k, v in expected_args.items():
        model_val = tool_args.get(k, "⚠ MISSING")
        match = str(model_val).strip().lower() == str(v).strip().lower()
        args_ok[k] = {"expected": v, "got": model_val, "match": match}

    all_args_ok = all(info["match"] for info in args_ok.values())
    return {
        "tool_ok": tool_ok,
        "all_args_ok": all_args_ok,
        "args_detail": args_ok,
        "pass": tool_ok and all_args_ok
    }

# ── Modo 1: API nativa de Ollama (tools=[...]) ─────────────────────────────────

def run_modo1(scenario: dict, model: str, verbose: bool) -> dict:
    """Usa el parámetro `tools` nativo de ollama.chat()."""
    start = time.perf_counter()
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": scenario["message"]}],
        tools=TOOLS
    )
    elapsed = time.perf_counter() - start

    tool_calls = response.message.tool_calls or []
    raw_content = response.message.content or ""

    if verbose:
        print(f"\n  [RAW content]: {raw_content!r}")
        print(f"  [RAW tool_calls]: {tool_calls}")

    if not tool_calls:
        return {
            "status": "NO_TOOL_CALL",
            "raw": raw_content,
            "elapsed": elapsed,
            "pass": False
        }

    tc = tool_calls[0]
    tool_name = tc.function.name
    tool_args = dict(tc.function.arguments)

    evaluation = evaluar_resultado(tool_name, tool_args, scenario)

    # Ejecuta la herramienta si el nombre es correcto
    tool_result = None
    if tool_name in TOOL_REGISTRY:
        try:
            tool_result = TOOL_REGISTRY[tool_name](**tool_args)
        except Exception as e:
            tool_result = {"error": str(e)}

    return {
        "status": "TOOL_CALLED",
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "evaluation": evaluation,
        "elapsed": elapsed,
        "pass": evaluation["pass"]
    }

# ── Modo 2: JSON forzado en system prompt ──────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """Intenta extraer el primer JSON válido de un string."""
    # Intento 1: parseo directo
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Intento 2: extrae bloques ```json ... ``` o ``` ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Intento 3: primer bloque { ... } en el texto
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None

def run_modo2(scenario: dict, model: str, verbose: bool) -> dict:
    """Usa un system prompt que fuerza respuesta JSON (sin API nativa de tools)."""
    tools_block = json.dumps(
        [t["function"] for t in TOOLS], indent=2, ensure_ascii=False
    )
    system = SYSTEM_PROMPT_MODO2.format(tools_block=tools_block)

    start = time.perf_counter()
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": scenario["message"]}
        ]
    )
    elapsed = time.perf_counter() - start

    raw_content = response.message.content or ""
    if verbose:
        print(f"\n  [RAW content]: {raw_content!r}")

    parsed = _extract_json(raw_content)
    if not parsed:
        return {
            "status": "PARSE_ERROR",
            "raw": raw_content,
            "elapsed": elapsed,
            "pass": False
        }

    tool_name = parsed.get("name", "")
    tool_args  = parsed.get("arguments", {})

    evaluation = evaluar_resultado(tool_name, tool_args, scenario)

    tool_result = None
    if tool_name in TOOL_REGISTRY:
        try:
            tool_result = TOOL_REGISTRY[tool_name](**tool_args)
        except Exception as e:
            tool_result = {"error": str(e)}

    return {
        "status": "TOOL_CALLED",
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "evaluation": evaluation,
        "elapsed": elapsed,
        "pass": evaluation["pass"]
    }

# ── Reporte en consola ─────────────────────────────────────────────────────────

VERDE  = "\033[92m"
ROJO   = "\033[91m"
AMARILLO = "\033[93m"
AZUL   = "\033[94m"
NEGRITA = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  return f"{VERDE}✔ {msg}{RESET}"
def fail(msg): return f"{ROJO}✘ {msg}{RESET}"
def warn(msg): return f"{AMARILLO}⚠ {msg}{RESET}"

def imprimir_resultado(scenario: dict, result: dict):
    passed = result.get("pass", False)
    sid    = scenario["id"]
    name   = scenario["name"]
    banner = f"{NEGRITA}{'═'*60}{RESET}"

    print(f"\n{banner}")
    print(f"  Escenario {sid}: {name}")
    print(f"  {scenario['description']}")
    print(f"  Consulta: «{scenario['message'][:80]}{'…' if len(scenario['message'])>80 else ''}»")
    print(f"{'-'*60}")

    elapsed = result.get("elapsed", 0)
    status  = result.get("status", "?")

    if status == "NO_TOOL_CALL":
        print(f"  {fail('SIN TOOL CALL')} — el modelo respondió en texto libre")
        print(f"  Respuesta: {result.get('raw','')[:150]!r}")
    elif status == "PARSE_ERROR":
        print(f"  {fail('ERROR DE PARSEO')} — no se pudo extraer JSON")
        print(f"  Respuesta raw: {result.get('raw','')[:200]!r}")
    else:
        ev = result.get("evaluation", {})
        tool_ok = ev.get("tool_ok", False)
        tn = result.get("tool_name","?")
        print(f"  Herramienta llamada : {ok(tn) if tool_ok else fail(tn)}")
        print(f"  Esperada            : {scenario['expected_tool']}")
        print(f"  Argumentos:")
        for k, info in ev.get("args_detail", {}).items():
            estado = ok(k) if info["match"] else fail(k)
            print(f"    {estado}")
            if not info["match"]:
                print(f"      esperado : {info['expected']!r}")
                print(f"      recibido : {info['got']!r}")

        if result.get("tool_result"):
            print(f"  Resultado simulado  : {json.dumps(result['tool_result'], ensure_ascii=False)}")

    print(f"  Tiempo de respuesta : {elapsed:.2f}s")
    print(f"  {'─'*20}")
    veredicto = ok("PASSED") if passed else fail("FAILED")
    print(f"  Veredicto           : {veredicto}")

def imprimir_resumen(resultados: list, model: str, modo: int):
    total  = len(resultados)
    passed = sum(1 for r in resultados if r.get("pass"))
    pct    = (passed / total * 100) if total else 0

    print(f"\n{'═'*60}")
    print(f"  {NEGRITA}RESUMEN FINAL{RESET}")
    print(f"  Modelo : {AZUL}{model}{RESET}  |  Modo : {modo}")
    print(f"  Resultado : {passed}/{total} escenarios ({pct:.0f}%)")
    print("─"*60)
    for i, r in enumerate(resultados):
        sc = SCENARIOS[i]
        estado = ok("PASS") if r.get("pass") else fail("FAIL")
        print(f"  [{estado}]  Escenario {sc['id']}: {sc['name']}")

    if pct == 100:
        print(f"\n  {VERDE}{NEGRITA}🎉 TOOL CALLING ESTABLE — Modelo apto para Camino B{RESET}")
    elif pct >= 66:
        print(f"\n  {AMARILLO}{NEGRITA}⚠ PARCIALMENTE FUNCIONAL — Revisar prompts o migrar a 7B{RESET}")
    else:
        print(f"\n  {ROJO}{NEGRITA}🚨 INESTABLE — Considerar migración a qwen2.5:7b{RESET}")
    print(f"{'═'*60}\n")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluación de tool calling offline para Camino B"
    )
    parser.add_argument(
        "--modelo", default=DEFAULT_MODEL,
        help=f"Nombre del modelo Ollama (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--modo", type=int, choices=[1, 2], default=1,
        help="1 = API nativa de tools (default)  |  2 = JSON forzado en system prompt"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Muestra la respuesta cruda completa del modelo"
    )
    args = parser.parse_args()

    print(f"\n{NEGRITA}{'═'*60}")
    print(f"  CAMINO B — Test de Tool Calling")
    print(f"  Modelo : {args.modelo}  |  Modo : {args.modo}")
    print(f"  Fecha  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*60}{RESET}")

    # Verifica que el modelo esté disponible
    try:
        modelos_disponibles = [m.model for m in ollama.list().models]
        modelo_base = args.modelo.split(":")[0] if ":" in args.modelo else args.modelo
        match = next(
            (m for m in modelos_disponibles if m.startswith(args.modelo) or m.startswith(modelo_base)),
            None
        )
        if not match:
            print(f"{ROJO}Error: El modelo '{args.modelo}' no está disponible en Ollama.{RESET}")
            print(f"Modelos disponibles: {', '.join(modelos_disponibles)}")
            sys.exit(1)
        # Usa el nombre exacto que devuelve Ollama
        args.modelo = match
    except Exception as e:
        print(f"{AMARILLO}No se pudo verificar la lista de modelos: {e}{RESET}")

    run_fn = run_modo1 if args.modo == 1 else run_modo2

    resultados = []
    for scenario in SCENARIOS:
        print(f"\n  ⏳ Ejecutando escenario {scenario['id']}...", end="", flush=True)
        try:
            result = run_fn(scenario, args.modelo, args.verbose)
        except Exception as e:
            result = {"status": "EXCEPTION", "raw": str(e), "pass": False, "elapsed": 0}
        resultados.append(result)
        imprimir_resultado(scenario, result)

    imprimir_resumen(resultados, args.modelo, args.modo)

if __name__ == "__main__":
    main()
