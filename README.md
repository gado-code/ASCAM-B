# ASCAM-B — Asistente con Memoria para Linux

Asistente de IA conversacional con interfaz gráfica, memoria persistente entre sesiones y soporte de streaming, ejecutado **100% localmente** usando [Ollama](https://ollama.com/).

---

## ✨ Características

- 🖥️ **Interfaz gráfica moderna** construida con CustomTkinter (tema oscuro)
- 🧠 **Memoria persistente** — las conversaciones se guardan en SQLite y puedes retomarlas desde el historial
- ⚡ **Streaming en tiempo real** — las respuestas aparecen token a token mientras el modelo genera
- 🛑 **Botón Detener** — cancela la generación en cualquier momento
- 💬 **Múltiples sesiones** — gestiona varias conversaciones desde el panel lateral
- 🔒 **100% local** — ningún dato sale de tu equipo; no requiere conexión a internet

---

## 📋 Requisitos

| Herramienta | Versión mínima |
|-------------|---------------|
| Python      | 3.10+          |
| Ollama      | última estable |
| CustomTkinter | 5.x          |
| ollama (librería Python) | última estable |

---

## 🚀 Instalación

### 1. Clona el repositorio

```bash
git clone https://github.com/gado-code/ASCAM-B.git
cd ASCAM-B
```

### 2. Instala Ollama y descarga un modelo

```bash
# Instala Ollama (Linux)
curl -fsSL https://ollama.com/install.sh | sh

# Descarga el modelo (puedes elegir otro)
ollama pull llama3.2
```

### 3. Crea un entorno virtual e instala dependencias

```bash
python -m venv venv
source venv/bin/activate

pip install customtkinter ollama
```

### 4. Ejecuta el asistente

```bash
python asistente.py
```

---

## 🗂️ Estructura del proyecto

```
ASCAM-B/
├── asistente.py       # Aplicación principal
├── test_tools.py      # Pruebas de herramientas y funciones
├── icono.png          # Ícono de la ventana
├── memoria.db         # Base de datos SQLite (generada al ejecutar)
├── requirements.txt   # Dependencias Python
└── .gitignore
```

---

## ⚙️ Configuración

Puedes personalizar el comportamiento del asistente editando la constante `SYSTEM_PROMPT` en la parte superior de `asistente.py`:

```python
SYSTEM_PROMPT = """Eres un asistente personal local llamado Asistente.
Responde siempre en español, de forma clara, directa y útil."""
```

Para cambiar el modelo de IA, busca la línea que llama a `ollama.chat()` y cambia el nombre del modelo.

---

## 📄 Licencia

MIT — libre para usar, modificar y distribuir.
