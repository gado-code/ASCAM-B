import os
import threading
import sqlite3
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import ollama
from datetime import datetime

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── System prompt ──────────────────────────────────────────────────────────────
# Edita este texto para cambiar cómo se comporta el asistente.
# Se envía al modelo al inicio de cada conversación, antes de los mensajes.
SYSTEM_PROMPT = """Eres un asistente personal local llamado Asistente.
La persona que te escribe es el usuario: él pregunta, tú respondes.
Nunca confundas los roles: tú eres el asistente, no el usuario.
Si el usuario te dice su nombre u otro dato personal, recuérdalo y úsalo.
Responde siempre en español, de forma clara, directa y útil.
No te presentes en cada respuesta; solo hazlo si el usuario te lo pide."""

# ── Configuración general ──────────────────────────────────────────────────────

# Ruta absoluta al lado del script, sin importar desde dónde se ejecute
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memoria.db")

# Nombre de la marca que usamos en el widget de chat para saber dónde
# empieza el texto de la respuesta en curso (necesario para el streaming)
MARCA_RESPUESTA = "inicio_respuesta"

# Colores del botón Enviar en el tema azul por defecto de CustomTkinter
# Los guardamos aquí para poder restaurarlos después de mostrar "Detener"
COLOR_ENVIAR_FG    = ("#3B8ED0", "#1F6AA5")
COLOR_ENVIAR_HOVER = ("#36719F", "#144870")

# Colores del botón Detener (rojo)
COLOR_DETENER_FG    = ("#c0392b", "#922b21")
COLOR_DETENER_HOVER = ("#a93226", "#7b241c")

# Variables globales de estado
sesion_actual_id    = None   # ID de la sesión visible en el chat
historial           = []     # Mensajes de la sesión activa (lo que recibe Ollama)
botones_sesion      = {}     # {sesion_id: CTkButton} para el sidebar

# Flag de cancelación: cuando el usuario presiona "Detener", se activa con .set()
# El hilo del modelo lo revisa en cada token y sale del bucle si está activado
cancelar_generacion = threading.Event()

# ── Base de datos ──────────────────────────────────────────────────────────────

def init_db():
    """Crea las tablas si no existen todavía."""
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS sesiones (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT    NOT NULL,
                creada DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS mensajes (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                sesion_id INTEGER  NOT NULL,
                rol       TEXT     NOT NULL,
                contenido TEXT     NOT NULL,
                enviado   DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sesion_id) REFERENCES sesiones(id)
            )
        """)

def nueva_sesion_db():
    """Inserta una nueva sesión en la DB y devuelve su id y nombre."""
    nombre = datetime.now().strftime("Sesión %d %b, %H:%M")
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("INSERT INTO sesiones (nombre) VALUES (?)", (nombre,))
        return cur.lastrowid, nombre

def obtener_sesiones():
    """Devuelve todas las sesiones ordenadas de más reciente a más antigua."""
    with sqlite3.connect(DB_PATH) as con:
        return con.execute(
            "SELECT id, nombre FROM sesiones ORDER BY creada DESC"
        ).fetchall()

def obtener_ultimos_mensajes(sesion_id, limite=20):
    """Devuelve los últimos `limite` mensajes de una sesión en orden cronológico."""
    with sqlite3.connect(DB_PATH) as con:
        # Toma los últimos N en orden inverso y luego los voltea al orden correcto
        return con.execute("""
            SELECT rol, contenido FROM (
                SELECT rol, contenido, enviado
                FROM mensajes
                WHERE sesion_id = ?
                ORDER BY enviado DESC
                LIMIT ?
            ) ORDER BY enviado ASC
        """, (sesion_id, limite)).fetchall()

def insertar_mensaje(sesion_id, rol, contenido):
    """Guarda un mensaje en la base de datos."""
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO mensajes (sesion_id, rol, contenido) VALUES (?, ?, ?)",
            (sesion_id, rol, contenido)
        )

def renombrar_sesion_db(sesion_id, nuevo_nombre):
    """Actualiza el nombre de una sesión en la base de datos."""
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "UPDATE sesiones SET nombre = ? WHERE id = ?",
            (nuevo_nombre, sesion_id)
        )

def eliminar_sesion_db(sesion_id):
    """Borra todos los mensajes de la sesión y luego la sesión misma."""
    with sqlite3.connect(DB_PATH) as con:
        # Primero borramos los mensajes para no dejar registros huérfanos
        con.execute("DELETE FROM mensajes WHERE sesion_id = ?", (sesion_id,))
        con.execute("DELETE FROM sesiones WHERE id = ?", (sesion_id,))

# ── Modelo ─────────────────────────────────────────────────────────────────────

def llamar_modelo(mensaje_usuario):
    """Llama al modelo usando streaming y muestra los tokens a medida que llegan.

    Corre en un hilo separado. Todas las actualizaciones de la interfaz
    se hacen con ventana.after(0, ...) para que sean thread-safe.
    """
    global historial

    # Limpia el flag de cancelación antes de empezar una nueva generación
    cancelar_generacion.clear()

    # Guarda el mensaje del usuario en memoria y en la base de datos
    historial.append({"role": "user", "content": mensaje_usuario})
    insertar_mensaje(sesion_actual_id, "user", mensaje_usuario)

    try:
        # El system prompt siempre va primero; el historial de la sesión va después
        mensajes_para_modelo = [{"role": "system", "content": SYSTEM_PROMPT}] + historial

        # Muestra el encabezado "🤖 Asistente:" en el chat antes del primer token
        ventana.after(0, iniciar_mensaje_streaming)

        # stream=True: el modelo devuelve tokens de a poco en vez de esperar
        stream = ollama.chat(
            model="llama3.2:3b",
            messages=mensajes_para_modelo,
            stream=True
        )

        texto_completo = ""
        for chunk in stream:
            # Si el usuario presionó "Detener", salimos del bucle
            if cancelar_generacion.is_set():
                break
            token = chunk["message"]["content"]
            texto_completo += token
            # Actualiza el chat con el texto acumulado hasta ahora (thread-safe)
            ventana.after(0, actualizar_mensaje_streaming, texto_completo)

        # Solo guardamos si la respuesta llegó completa (no fue cancelada por el usuario)
        if not cancelar_generacion.is_set() and texto_completo:
            historial.append({"role": "assistant", "content": texto_completo})
            insertar_mensaje(sesion_actual_id, "assistant", texto_completo)

    except Exception as e:
        ventana.after(0, mostrar_mensaje, "Error", f"No se pudo conectar con Ollama: {e}")

    finally:
        # Siempre restauramos la interfaz al terminar, ya sea normal o por cancelación
        ventana.after(0, finalizar_modo_generando)

# ── Chat display ───────────────────────────────────────────────────────────────

def mostrar_mensaje(remitente, texto):
    """Agrega un bloque de texto completo al área de chat."""
    area_chat.configure(state="normal")
    etiqueta = {"Tú": "▶ Tú:\n", "Asistente": "🤖 Asistente:\n"}.get(
        remitente, f"⚠ {remitente}:\n"
    )
    area_chat.insert("end", etiqueta + texto + "\n\n")
    area_chat.configure(state="disabled")
    area_chat.see("end")

def iniciar_mensaje_streaming():
    """Muestra el encabezado del asistente y pone una marca donde irán los tokens."""
    area_chat.configure(state="normal")
    area_chat.insert("end", "🤖 Asistente:\n")
    # La marca con gravedad "left" se queda fija en su posición aunque
    # insertemos texto después de ella (esto nos permite reemplazar el texto)
    area_chat.mark_set(MARCA_RESPUESTA, "end")
    area_chat.mark_gravity(MARCA_RESPUESTA, "left")
    area_chat.configure(state="disabled")

def actualizar_mensaje_streaming(texto):
    """Reemplaza el contenido de la respuesta en curso con el texto acumulado."""
    area_chat.configure(state="normal")
    # Borra desde la marca hasta el final y reescribe con el texto nuevo
    area_chat.delete(MARCA_RESPUESTA, "end")
    area_chat.insert(MARCA_RESPUESTA, texto + "\n\n")
    area_chat.configure(state="disabled")
    area_chat.see("end")

def limpiar_chat():
    """Borra todo el contenido visible del área de chat."""
    area_chat.configure(state="normal")
    area_chat.delete("1.0", "end")
    area_chat.configure(state="disabled")

# ── Control del botón Enviar / Detener ────────────────────────────────────────

def iniciar_modo_generando():
    """Transforma el botón 'Enviar' en 'Detener' y bloquea el campo de texto."""
    entrada.configure(state="disabled")
    boton_enviar.configure(
        text="■ Detener",
        fg_color=COLOR_DETENER_FG,
        hover_color=COLOR_DETENER_HOVER,
        command=detener_generacion,
        state="normal"   # El botón Detener debe estar activo para poder usarlo
    )

def finalizar_modo_generando():
    """Restaura el botón 'Enviar' y habilita el campo de texto."""
    boton_enviar.configure(
        text="Enviar",
        fg_color=COLOR_ENVIAR_FG,
        hover_color=COLOR_ENVIAR_HOVER,
        command=enviar_mensaje
    )
    # Solo habilitamos la entrada si hay una sesión activa
    if sesion_actual_id is not None:
        entrada.configure(state="normal")
        boton_enviar.configure(state="normal")
        entrada.focus()

def detener_generacion():
    """Activa el flag de cancelación para que el hilo del modelo pare el streaming."""
    cancelar_generacion.set()

def enviar_mensaje(evento=None):
    """Lee la entrada del usuario y lanza el modelo en un hilo separado."""
    if sesion_actual_id is None:
        return
    mensaje = entrada.get().strip()
    if not mensaje:
        return
    entrada.delete(0, "end")
    mostrar_mensaje("Tú", mensaje)
    # Transforma el botón inmediatamente (antes de que el hilo empiece)
    iniciar_modo_generando()
    threading.Thread(target=llamar_modelo, args=(mensaje,), daemon=True).start()

# ── Sesiones ───────────────────────────────────────────────────────────────────

def resaltar_boton(sesion_id):
    """Pone azul el botón de la sesión activa y apaga el resto."""
    for sid, btn in botones_sesion.items():
        color = ("#3a7ebf", "#1f6aa5") if sid == sesion_id else ("gray75", "gray25")
        btn.configure(fg_color=color)

def seleccionar_sesion(sesion_id, nombre=""):
    """Carga una sesión: muestra sus mensajes en el chat y reconstruye el historial."""
    global sesion_actual_id, historial
    sesion_actual_id = sesion_id
    historial = []
    limpiar_chat()

    # Carga los últimos 20 mensajes desde la base de datos
    mensajes = obtener_ultimos_mensajes(sesion_id)

    if not mensajes:
        # Sesión vacía: saludo de bienvenida (no se guarda, es solo visual)
        mostrar_mensaje(
            "Asistente",
            "¡Hola! Soy tu asistente personal local. ¿En qué puedo ayudarte hoy?"
        )
    else:
        # Sesión con historial: carga los mensajes al chat y al historial de Ollama
        for rol, contenido in mensajes:
            mostrar_mensaje("Tú" if rol == "user" else "Asistente", contenido)
            historial.append({"role": rol, "content": contenido})

    etiqueta_sesion.configure(text=nombre)
    entrada.configure(state="normal")
    boton_enviar.configure(state="normal")
    resaltar_boton(sesion_id)
    entrada.focus()

def mostrar_menu_sesion(event, sesion_id, nombre):
    """Muestra el menú contextual al hacer clic derecho sobre una sesión."""
    menu = tk.Menu(
        ventana, tearoff=0,
        bg="#2b2b2b", fg="white",
        activebackground="#3a7ebf", activeforeground="white",
        font=("Consolas", 11), bd=0
    )
    menu.add_command(
        label="  ✏  Renombrar",
        command=lambda: renombrar_sesion(sesion_id, nombre)
    )
    menu.add_separator()
    menu.add_command(
        label="  🗑  Eliminar",
        command=lambda: eliminar_sesion(sesion_id, nombre)
    )
    menu.tk_popup(event.x_root, event.y_root)

def renombrar_sesion(sesion_id, nombre_actual):
    """Pide un nuevo nombre y lo actualiza en la DB y en la interfaz."""
    dialogo = ctk.CTkInputDialog(
        text=f"Nuevo nombre para '{nombre_actual}':",
        title="Renombrar sesión"
    )
    nuevo_nombre = dialogo.get_input()

    # Si el usuario canceló o dejó el campo vacío, no hace nada
    if not nuevo_nombre or not nuevo_nombre.strip():
        return

    nuevo_nombre = nuevo_nombre.strip()

    # Guarda en DB y reconstruye la lista para que los closures queden actualizados
    renombrar_sesion_db(sesion_id, nuevo_nombre)
    actualizar_lista_sesiones()
    resaltar_boton(sesion_actual_id)

    # Si es la sesión activa, actualiza el título sobre el chat
    if sesion_id == sesion_actual_id:
        etiqueta_sesion.configure(text=nuevo_nombre)

def eliminar_sesion(sesion_id, nombre):
    """Pide confirmación y borra la sesión y todos sus mensajes."""
    confirmar = messagebox.askyesno(
        title="Eliminar sesión",
        message=f"¿Seguro que quieres eliminar '{nombre}'?\n\nEsta acción no se puede deshacer."
    )
    if not confirmar:
        return

    # Borra de la base de datos (mensajes primero para no dejar huérfanos)
    eliminar_sesion_db(sesion_id)

    # Quita el botón del sidebar
    if sesion_id in botones_sesion:
        botones_sesion[sesion_id].destroy()
        del botones_sesion[sesion_id]

    # Si era la sesión activa, abre la siguiente disponible o crea una nueva
    if sesion_id == sesion_actual_id:
        sesiones_restantes = obtener_sesiones()
        if sesiones_restantes:
            seleccionar_sesion(sesiones_restantes[0][0], sesiones_restantes[0][1])
        else:
            crear_nueva_sesion()

def actualizar_lista_sesiones():
    """Reconstruye todos los botones de sesión en el sidebar desde la base de datos."""
    for btn in botones_sesion.values():
        btn.destroy()
    botones_sesion.clear()

    for sesion_id, nombre in obtener_sesiones():
        nombre_corto = nombre if len(nombre) <= 21 else nombre[:18] + "..."
        btn = ctk.CTkButton(
            frame_lista_sesiones,
            text=nombre_corto,
            anchor="w",
            fg_color=("gray75", "gray25"),
            hover_color=("#2d6fba", "#1a5a8f"),
            height=30,
            command=lambda sid=sesion_id, n=nombre: seleccionar_sesion(sid, n)
        )
        btn.pack(fill="x", padx=2, pady=2)
        # Clic derecho → menú de renombrar / eliminar.
        # ButtonRelease-3 evita que el release active el primer ítem del menú.
        # add="+" propaga el bind al canvas y label internos del CTkButton.
        btn.bind(
            "<ButtonRelease-3>",
            lambda e, sid=sesion_id, n=nombre: mostrar_menu_sesion(e, sid, n),
            add="+"
        )
        botones_sesion[sesion_id] = btn

def crear_nueva_sesion():
    """Crea una sesión nueva en la DB y la abre en el chat."""
    sesion_id, nombre = nueva_sesion_db()
    actualizar_lista_sesiones()
    seleccionar_sesion(sesion_id, nombre)

# ── Ventana principal ──────────────────────────────────────────────────────────

ventana = ctk.CTk()
ventana.title("Asistente IA — llama3.2:3b")
ventana.geometry("980x640")
ventana.minsize(680, 460)

# Marco que ocupa toda la ventana, dividido en sidebar + chat
marco_principal = ctk.CTkFrame(ventana)
marco_principal.pack(fill="both", expand=True, padx=8, pady=8)
marco_principal.grid_columnconfigure(1, weight=1)   # El chat se expande
marco_principal.grid_rowconfigure(0, weight=1)

# ── Sidebar ────────────────────────────────────────────────────────────────────

sidebar = ctk.CTkFrame(marco_principal, width=210, corner_radius=8)
sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
sidebar.grid_propagate(False)           # Mantiene el ancho fijo de 210px
sidebar.grid_columnconfigure(0, weight=1)
sidebar.grid_rowconfigure(2, weight=1)  # La lista ocupa el espacio sobrante

ctk.CTkLabel(
    sidebar, text="Sesiones",
    font=("Consolas", 14, "bold")
).grid(row=0, column=0, padx=10, pady=(12, 8), sticky="ew")

ctk.CTkButton(
    sidebar, text="+ Nueva sesión",
    command=crear_nueva_sesion,
    fg_color=("#2ea055", "#1e7a3e"),
    hover_color=("#259048", "#186634"),
    height=34
).grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")

# Lista scrollable donde aparece un botón por cada sesión guardada
frame_lista_sesiones = ctk.CTkScrollableFrame(
    sidebar,
    label_text="Historial",
    label_font=("Consolas", 11)
)
frame_lista_sesiones.grid(row=2, column=0, sticky="nsew", padx=4, pady=(0, 6))

# ── Chat ───────────────────────────────────────────────────────────────────────

frame_chat = ctk.CTkFrame(marco_principal, corner_radius=8)
frame_chat.grid(row=0, column=1, sticky="nsew")
frame_chat.grid_columnconfigure(0, weight=1)
frame_chat.grid_rowconfigure(1, weight=1)

# Muestra el nombre de la sesión activa sobre el área de chat
etiqueta_sesion = ctk.CTkLabel(
    frame_chat, text="",
    font=("Consolas", 11),
    anchor="w",
    text_color=("gray50", "gray65")
)
etiqueta_sesion.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 2))

# Área de texto donde se muestra la conversación (solo lectura para el usuario)
area_chat = ctk.CTkTextbox(
    frame_chat,
    state="disabled",
    wrap="word",
    font=("Consolas", 13)
)
area_chat.grid(row=1, column=0, sticky="nsew", padx=6, pady=0)

# Barra inferior: campo de texto + botón Enviar/Detener
marco_inferior = ctk.CTkFrame(frame_chat, fg_color="transparent")
marco_inferior.grid(row=2, column=0, sticky="ew", padx=6, pady=8)

entrada = ctk.CTkEntry(
    marco_inferior,
    placeholder_text="Escribe tu mensaje...",
    font=("Consolas", 13),
    state="disabled"
)
entrada.pack(side="left", fill="x", expand=True, padx=(0, 6))
entrada.bind("<Return>", enviar_mensaje)

boton_enviar = ctk.CTkButton(
    marco_inferior,
    text="Enviar",
    width=100,
    fg_color=COLOR_ENVIAR_FG,
    hover_color=COLOR_ENVIAR_HOVER,
    command=enviar_mensaje,
    state="disabled"
)
boton_enviar.pack(side="right")

# ── Arranque ───────────────────────────────────────────────────────────────────

init_db()
actualizar_lista_sesiones()

# Abre la sesión más reciente, o crea una nueva si no hay ninguna
sesiones = obtener_sesiones()
if sesiones:
    seleccionar_sesion(sesiones[0][0], sesiones[0][1])
else:
    crear_nueva_sesion()

ventana.mainloop()
