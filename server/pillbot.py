from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, Update,
                      ReplyKeyboardMarkup, KeyboardButton)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, ContextTypes, filters
)
import subprocess
import requests
import schedule
import threading
import time
from datetime import datetime, timedelta

BOT_TOKEN = ""
CAMPOS = {
    "nombre": 4,
    "apellidos": 6,
    "dni": 8,
    "grupo": 10,
    "alergias": 12,
    "contacto": 14
}
EDITANDO_CAMPO = 1
CREANDO_PERFIL = 2
usuario_en_edicion = {}
perfil_creado_por_usuario = {}

datos_perfil = ["nombre", "apellidos", "dni", "grupo", "alergias", "contacto"]
datos_temporales = {}
TOMAS_DEL_DIA = [9, 14, 18, 21]

def send_mqtt_text_update(texto, page=0, id_label=6):
    msg = {"page": page, "id": id_label, "obj": "label", "text": texto}
    json_msg = str(msg).replace("'", '"')
    subprocess.run(["mosquitto_pub", "-h", "141.94.247.154", "-t", "hasp/plate/command", "-u", "MQTT", "-P", "TFG", "-m", json_msg])

def send_mqtt_bar_update(value):
    msg = {"page": 1, "id": 2, "obj": "bar", "val": value}
    json_msg = str(msg).replace("'", '"')
    subprocess.run(["mosquitto_pub", "-h", "141.94.247.154", "-t", "hasp/plate/command", "-u", "MQTT", "-P", "TFG", "-m", json_msg])

def tarea_contador_toma():
    ahora = datetime.now()
    siguientes = [h for h in TOMAS_DEL_DIA if h > ahora.hour]
    if not siguientes:
        objetivo = ahora.replace(hour=TOMAS_DEL_DIA[0], minute=0, second=0) + timedelta(days=1)
    else:
        objetivo = ahora.replace(hour=siguientes[0], minute=0, second=0, microsecond=0)
    total_segundos = int((objetivo - ahora).total_seconds())
    horas = total_segundos // 3600
    minutos = (total_segundos % 3600) // 60
    segundos = total_segundos % 60
    texto = f"{horas:02}:{minutos:02}:{segundos:02}"
    porcentaje = int((total_segundos / (3 * 3600)) * 100)
    porcentaje = min(100, max(0, porcentaje))
    send_mqtt_text_update(texto, page=1, id_label=3)
    send_mqtt_bar_update(porcentaje)

def obtener_tiempo_madrid():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {"latitude": 40.4168, "longitude": -3.7038, "current_weather": True}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if "current_weather" in data:
            weather = data["current_weather"]
            temperatura = weather["temperature"]
            viento = weather["windspeed"]
            return f"{temperatura}C, viento {viento} km/h"
        else:
            return "Tiempo no disponible"
    except Exception:
        return "Error al obtener el tiempo"

def tarea_actualizar_tiempo():
    tiempo = obtener_tiempo_madrid()
    send_mqtt_text_update(tiempo, page=0, id_label=6)
    print(f"[{datetime.now()}] Tiempo actualizado: {tiempo}")

def run_scheduler():
    schedule.every().day.at("00:00").do(tarea_actualizar_tiempo)
    while True:
        schedule.run_pending()
        tarea_contador_toma()
        time.sleep(1)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("Menu")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Hola! Usa el boton 'Menu' para ver las opciones.", reply_markup=reply_markup)

async def mostrar_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    perfil_creado = perfil_creado_por_usuario.get(user_id, False)
    if not perfil_creado:
        keyboard = [[InlineKeyboardButton("Crear nuevo perfil", callback_data="crear_perfil")]]
    else:
        keyboard = [
            [InlineKeyboardButton("Editar informacion", callback_data="editar")],
            [InlineKeyboardButton("Programar toma de pastilla", callback_data="programar_toma")],
            [InlineKeyboardButton("Añadir pastilla", callback_data="agregar_pastilla")]
        ]
    await update.message.reply_text("Menu:", reply_markup=InlineKeyboardMarkup(keyboard))

async def campo_seleccionado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "crear_perfil":
        datos_temporales[user_id] = {"index": 0, "respuestas": {}}
        await query.edit_message_text("Vamos a crear tu perfil. Introduce tu nombre:")
        return CREANDO_PERFIL

    elif query.data == "editar":
        keyboard = [
            [InlineKeyboardButton("Nombre", callback_data="nombre"),
             InlineKeyboardButton("Apellidos", callback_data="apellidos")],
            [InlineKeyboardButton("DNI", callback_data="dni"),
             InlineKeyboardButton("Grupo sanguineo", callback_data="grupo")],
            [InlineKeyboardButton("Alergias", callback_data="alergias"),
             InlineKeyboardButton("Contacto emergencia", callback_data="contacto")]
        ]
        await query.edit_message_text("Que campo deseas editar?", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    

    elif query.data == "programar_toma":
        await query.edit_message_text("Funcionalidad para programar una toma aun no implementada.")
        return ConversationHandler.END

    elif query.data in CAMPOS:
        usuario_en_edicion[user_id] = query.data
        await query.edit_message_text(f"Introduce el nuevo valor para *{query.data}*:", parse_mode="Markdown")
        return EDITANDO_CAMPO

    else:
        await query.edit_message_text("Opcion no valida.")
        return ConversationHandler.END

async def crear_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in datos_temporales:
        await update.message.reply_text("Error interno. Usa /start para comenzar de nuevo.")
        return ConversationHandler.END

    texto = update.message.text
    index = datos_temporales[user_id]["index"]
    campo = datos_perfil[index]
    id_obj = CAMPOS[campo]
    send_mqtt_text_update(texto, page=9, id_label=id_obj)
    datos_temporales[user_id]["respuestas"][campo] = texto

    if index + 1 < len(datos_perfil):
        siguiente = datos_perfil[index + 1]
        datos_temporales[user_id]["index"] += 1
        await update.message.reply_text(f"Introduce tu {siguiente}:")
        return CREANDO_PERFIL
    else:
        perfil_creado_por_usuario[user_id] = True
        del datos_temporales[user_id]
        await update.message.reply_text("Perfil creado exitosamente.")
        return ConversationHandler.END

async def guardar_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in usuario_en_edicion:
        await update.message.reply_text("No se ha seleccionado ningun campo. Usa /start.")
        return ConversationHandler.END

    campo = usuario_en_edicion[user_id]
    id_obj = CAMPOS[campo]
    valor = update.message.text
    send_mqtt_text_update(valor, page=9, id_label=id_obj)
    await update.message.reply_text(f"Campo *{campo}* actualizado a: `{valor}`", parse_mode="Markdown")
    del usuario_en_edicion[user_id]
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operacion cancelada.")
    return ConversationHandler.END

AGREGAR_PASTILLA_TEXTO = 3
AGREGAR_PASTILLA_HORARIO = 4
AGREGAR_PASTILLA_DIA = 5

pastilla_temp = {}
pastilla_id_counter = {
    "Desayuno": 100,
    "Comida": 300,
    "Merienda": 500,
    "Cena": 700
}

horario_a_tab_por_pagina = {
    3: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    4: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    5: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    6: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    7: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    8: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    9: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
}

def send_mqtt_json(msg):
    json_msg = str(msg).replace("'", '"')
    subprocess.run(["mosquitto_pub", "-h", "141.94.247.154", "-t", "hasp/plate/command", "-u", "MQTT", "-P", "TFG", "-m", json_msg])

async def comenzar_agregar_pastilla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pastilla_temp[user_id] = {}
    await update.callback_query.edit_message_text("Introduce el nombre de la pastilla:")
    return AGREGAR_PASTILLA_TEXTO

async def recibir_pastilla_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pastilla_temp[user_id]["texto"] = update.message.text
    keyboard = [[InlineKeyboardButton(h, callback_data=h)] for h in ["Desayuno", "Comida", "Merienda", "Cena"]]
    await update.message.reply_text("Selecciona el horario:", reply_markup=InlineKeyboardMarkup(keyboard))
    return AGREGAR_PASTILLA_HORARIO

async def recibir_pastilla_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    horario = query.data
    pastilla_temp[user_id]["horario"] = horario
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    keyboard = [[InlineKeyboardButton(d, callback_data=d)] for d in dias]
    await query.edit_message_text("Selecciona los días (haz click en todos los que quieras, y luego escribe 'ok'):")
    context.user_data["dias"] = []
    context.user_data["esperando_dias"] = True
    context.user_data["user_id"] = user_id
    await query.message.reply_text("Selecciona días:", reply_markup=InlineKeyboardMarkup(keyboard))
    return AGREGAR_PASTILLA_DIA

async def registrar_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dia = update.callback_query.data
    context.user_data["dias"].append(dia)
    await update.callback_query.answer(f"Día añadido: {dia}")
    return AGREGAR_PASTILLA_DIA


async def recibir_pastilla_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = context.user_data["user_id"]
    if update.message.text.lower() == "ok":
        dias = context.user_data.get("dias", [])
        texto = pastilla_temp[user_id]["texto"]
        horario = pastilla_temp[user_id]["horario"]
        base_id = pastilla_id_counter[horario]
        dias = context.user_data.get("dias", [])
        texto = pastilla_temp[user_id]["texto"]
        horario = pastilla_temp[user_id]["horario"]
        
        base_id = pastilla_id_counter[horario]

        for i, dia in enumerate(dias):
            y_pos = 10 + i * 40
            label_id = base_id + 1 + i * 2
            checkbox_id = base_id + 2 + i * 2

            dia_a_pagina = {
                "Lunes": 3,
                "Martes": 4,
                "Miércoles": 5,
                "Jueves": 6,
                "Viernes": 7,
                "Sábado": 8,
                "Domingo": 9
            }
            pagina = dia_a_pagina.get(dia, 4)
            parentid = horario_a_tab_por_pagina[pagina][horario]

            send_mqtt_json({
                "page": pagina,
                "id": label_id,
                "obj": "label",
                "x": 10,
                "y": y_pos,
                "w": 700,
                "h": 30,
                "parentid": parentid,
                "text": texto,
                "text_color": "#000000",
                "align": 0,
                "text_font": 24
            })
            send_mqtt_json({
                "page": pagina,
                "id": checkbox_id,
                "obj": "checkbox",
                "x": 700,
                "y": y_pos,
                "w": 30,
                "h": 30,
                "parentid": parentid,
                "text": "",
                "checked": False
            })

        pastilla_id_counter[horario] += len(dias) * 2
        del pastilla_temp[user_id]
        await update.message.reply_text("Pastilla agregada correctamente.")
        return ConversationHandler.END
    else:
        context.user_data["dias"].append(update.message.text)
        return AGREGAR_PASTILLA_DIA


if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    agregar_pastilla_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(comenzar_agregar_pastilla, pattern="^agregar_pastilla$")],
        states={
            AGREGAR_PASTILLA_TEXTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_pastilla_texto)],
            AGREGAR_PASTILLA_HORARIO: [CallbackQueryHandler(recibir_pastilla_horario)],
            AGREGAR_PASTILLA_DIA: [
                CallbackQueryHandler(registrar_dia, pattern="^(Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_pastilla_dia)
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancelar)]
    )

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(campo_seleccionado, pattern="^(crear_perfil|editar|programar_toma|nombre|apellidos|dni|grupo|alergias|contacto)$")],
        states={
            EDITANDO_CAMPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_valor)],
            CREANDO_PERFIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, crear_perfil)]
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("Menu"), mostrar_menu))
    app.add_handler(conv_handler)
    app.add_handler(agregar_pastilla_handler)

    print("Bot y tarea de tiempo arrancando...")
    app.run_polling()
