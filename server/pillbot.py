from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, Update,
                      ReplyKeyboardMarkup, KeyboardButton)

from telegram import Bot
import asyncio
from asyncio import run_coroutine_threadsafe

from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, ContextTypes, filters
)
import subprocess
import requests
import schedule
import threading
import time
import json
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt

objetivo_simulado = None
main_loop = None


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
AGREGAR_PASTILLA_TEXTO = 3
AGREGAR_PASTILLA_HORARIO = 4
AGREGAR_PASTILLA_DIA = 5

usuario_en_edicion = {}
perfil_creado_por_usuario = {}
datos_perfil = ["nombre", "apellidos", "dni", "grupo", "alergias", "contacto"]
datos_temporales = {}
pastilla_temp = {}
TOMAS_DEL_DIA = [9, 14, 18, 21]

dia_a_pagina = {
    "Lunes": 2,
    "Martes": 3,
    "Miércoles": 4,
    "Jueves": 5,
    "Viernes": 6,
    "Sábado": 7,
    "Domingo": 8
}

pastilla_id_counter = {
    "Desayuno": 100,
    "Comida": 133,
    "Merienda": 166,
    "Cena": 200
}

msgbox_id_counter_por_horario = {
    "Desayuno": 24,
    "Comida": 24,
    "Merienda": 24,
    "Cena": 24
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

pastillas_por_dia_horario = {}

def send_mqtt_json(msg):
    json_msg = str(msg).replace("'", '"')
    subprocess.run(["mosquitto_pub", "-h", "141.94.247.154", "-t", "hasp/plate/command", "-u", "MQTT", "-P", "TFG", "-m", json_msg])

def run_scheduler():
    schedule.every().day.at("00:00").do(tarea_actualizar_tiempo)
    while True:
        schedule.run_pending()
        tarea_contador_toma()
        time.sleep(1)
        
async def notificar_telegram(texto_pastilla):
    bot = Bot(token=BOT_TOKEN)
    for uid, chat_id in user_chat_ids.items():
        await bot.send_message(chat_id=chat_id, text=f"💊 Se ha tomado la pastilla: *{texto_pastilla}*", parse_mode="Markdown")
        
def on_connect(client, userdata, flags, rc):
    print("📡 Conectado al broker MQTT con código", rc)
    client.subscribe("hasp/plate/LWT")
    client.subscribe("hasp/plate/state/#")

def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()
    print(f"📩 MQTT recibido en {topic}: {payload}")

    if topic == "hasp/plate/LWT" and payload.lower() == "online":
        print("🔄 Panel encendido. Enviando info de tiempo y botón...")
        mostrar_info_diaria_y_boton()
    
    elif topic.startswith("hasp/plate/state/p1b"):
        try:
            datos = json.loads(payload)
            if datos.get("event") == "up" and datos.get("text") == "Aceptar":
                boton_id = int(topic.split("p1b")[1])
                procesar_respuesta_pastilla(boton_id)
        except Exception as e:
            print(f"❌ Error procesando evento de botón: {e}")
            
def procesar_respuesta_pastilla(boton_id):
    ahora = datetime.now()
    hora_actual = ahora.hour

    if hora_actual < 12:
        horario = "Desayuno"
    elif hora_actual < 16:
        horario = "Comida"
    elif hora_actual < 20:
        horario = "Merienda"
    else:
        horario = "Cena"

    dia_nombre_en = ahora.strftime("%A")
    dia_es = {
        "Monday": "Lunes",
        "Tuesday": "Martes",
        "Wednesday": "Miércoles",
        "Thursday": "Jueves",
        "Friday": "Viernes",
        "Saturday": "Sábado",
        "Sunday": "Domingo"
    }.get(dia_nombre_en, "Lunes")

    clave = (dia_es, horario)
    pastillas = pastillas_por_dia_horario.get(clave, [])

    for p in pastillas:
        if p.get("msgbox_id") == boton_id:
            checkbox_id = p["checkbox_id"]
            pagina = p["pagina"]
            texto_pastilla = p["texto"]

            print(f"☑️ Marcando checkbox {checkbox_id} como checked en página {pagina}")
            send_mqtt_json({
                "page": pagina,
                "id": checkbox_id,
                "obj": "checkbox",
                "val": 1,
                "enabled": "false"
            })

            run_coroutine_threadsafe(notificar_telegram(texto_pastilla), main_loop)
            break
    else:
        print(f"⚠️ No se encontró pastilla con msgbox_id {boton_id} en {clave}")

def iniciar_listener_mqtt():
    client = mqtt.Client()
    client.username_pw_set("MQTT", "TFG")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("141.94.247.154", 1883, 60)
    client.loop_forever()

def send_mqtt_text_update(texto, page=0, id_label=6):
    msg = {"page": page, "id": id_label, "obj": "label", "text": texto}
    json_msg = str(msg).replace("'", '"')
    subprocess.run(["mosquitto_pub", "-h", "141.94.247.154", "-t", "hasp/plate/command", "-u", "MQTT", "-P", "TFG", "-m", json_msg])

def send_mqtt_bar_update(value):
    msg = {"page": 1, "id": 2, "obj": "bar", "val": value}
    json_msg = str(msg).replace("'", '"')
    subprocess.run(["mosquitto_pub", "-h", "141.94.247.154", "-t", "hasp/plate/command", "-u", "MQTT", "-P", "TFG", "-m", json_msg])


def tarea_contador_toma():
    global objetivo_simulado
    ahora = datetime.now()
    siguientes = [h for h in TOMAS_DEL_DIA if h > ahora.hour]

    if not siguientes:
        siguiente_hora = TOMAS_DEL_DIA[0]
        objetivo = ahora.replace(hour=siguiente_hora, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        siguiente_hora = siguientes[0]
        objetivo = ahora.replace(hour=siguiente_hora, minute=0, second=0, microsecond=0)

    siguiente_hora = objetivo.hour
    total_segundos = int((objetivo - ahora).total_seconds())

    # Lanzar notificaciones cuando llegue la hora exacta
    if total_segundos == 0:
        print(f"[{datetime.now()}] ⏰ Momento de la toma: {siguiente_hora}")

        dia_semana = ahora.strftime("%A")  # Ej: 'Monday'
        dia_es = {
            "Monday": "Lunes",
            "Tuesday": "Martes",
            "Wednesday": "Miércoles",
            "Thursday": "Jueves",
            "Friday": "Viernes",
            "Saturday": "Sábado",
            "Sunday": "Domingo"
        }.get(dia_semana, "Lunes")

        if 6 <= siguiente_hora < 12:
            horario_nombre = "Desayuno"
        elif 12 <= siguiente_hora < 16:
            horario_nombre = "Comida"
        elif 16 <= siguiente_hora < 20:
            horario_nombre = "Merienda"
        else:
            horario_nombre = "Cena"

        # Resetear el ID de msgbox para esta franja
        msgbox_id_counter_por_horario[horario_nombre] = 24

        # Buscar las pastillas programadas para ese día y franja
        clave = (dia_es, horario_nombre)
        pastillas = pastillas_por_dia_horario.get(clave, [])
        for p in pastillas:
            texto = p["texto"]
            label_id = p["label_id"]  # Ya lo tienes guardado
            lanzar_notificacion_pastilla(texto, horario_nombre, label_id)

    # Actualizar el reloj y barra
    horas = total_segundos // 3600
    minutos = (total_segundos % 3600) // 60
    segundos = total_segundos % 60
    texto = f"{horas:02}:{minutos:02}:{segundos:02}"
    porcentaje = int((total_segundos / (3 * 3600)) * 100)
    porcentaje = min(100, max(0, porcentaje))
    send_mqtt_bar_update(porcentaje)
    send_mqtt_text_update(texto, page=1, id_label=3)
    
def mostrar_info_diaria_y_boton():
    ahora = datetime.now()
    
    dia_nombre_en = ahora.strftime("%A")
    dia_es = {
        "Monday": "Lunes",
        "Tuesday": "Martes",
        "Wednesday": "Miércoles",
        "Thursday": "Jueves",
        "Friday": "Viernes",
        "Saturday": "Sábado",
        "Sunday": "Domingo"
    }.get(dia_nombre_en, "Lunes")

    # Obtener datos meteo
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 40.4168,
        "longitude": -3.7038,
        "current_weather": True
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        if "current_weather" in data:
            weather = data["current_weather"]
            temp = round(weather["temperature"])
            viento = round(weather["windspeed"])
            clima_codigo = weather.get("weathercode", 0)

            # Interpretar código del tiempo
            condiciones = {
                0: "Despejado ☀️",
                1: "Mayormente despejado 🌤️",
                2: "Parcialmente nublado ⛅",
                3: "Nublado ☁️",
                45: "Niebla 🌫️",
                48: "Neblina",
                51: "Lluvia ligera 🌦️",
                61: "Lluvia 🌧️",
                71: "Nieve ❄️",
                80: "Chubascos 🌦️",
                95: "Tormenta ⛈️",
            }
            clima_texto = condiciones.get(clima_codigo, "Clima desconocido")

            texto_final = f"{dia_es}, {temp} °C, viento {viento} km/h, {clima_texto}"

            # Mostrarlo en label (ejemplo: page 0, id 6)
            send_mqtt_text_update(texto_final, page=0, id_label=6)

            # Actualizar botón
            pagina_destino = dia_a_pagina.get(dia_es, 2)
            boton_msg = {
                "page": 1,
                "id": 10,
                "obj": "btn",
                "x": 300,
                "y": 320,
                "w": 200,
                "h": 60,
                "radius": 35,
                "bg_color": "#00A6FF",
                "text": "\uE0ED Ver recetario",
                "text_color": "#FFFFFF",
                "text_font": 24,
                "action": f"p{pagina_destino}"
            }
            send_mqtt_json(boton_msg)
            print("✅ Botón actualizado y texto enviado:", texto_final)

        else:
            print("⚠️ No se encontró 'current_weather' en la respuesta")

    except Exception as e:
        print("❌ Error al obtener el clima:", e)


def tarea_actualizar_tiempo():
    tiempo = mostrar_info_diaria_y_boton()
    send_mqtt_text_update(tiempo, page=0, id_label=6)
    print(f"[{datetime.now()}] Tiempo actualizado: {tiempo}")

user_chat_ids = {} 

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_chat_ids[user_id] = chat_id  # Guardamos el chat_id por usuario

    keyboard = [[KeyboardButton("Menu📚")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Hola! Usa el boton Menu📚 para ver las opciones.", reply_markup=reply_markup)

async def mostrar_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    perfil_creado = perfil_creado_por_usuario.get(user_id, False)
    if not perfil_creado:
        keyboard = [[InlineKeyboardButton("Crear nuevo perfil👤", callback_data="crear_perfil")]]
    else:
        keyboard = [
            [InlineKeyboardButton("Editar informacion📝", callback_data="editar")],
            [InlineKeyboardButton("Añadir pastilla💊", callback_data="agregar_pastilla")]
        ]
    await update.message.reply_text("Menu📚:", reply_markup=InlineKeyboardMarkup(keyboard))

async def campo_seleccionado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "crear_perfil":
        datos_temporales[user_id] = {"index": 0, "respuestas": {}}
        await query.edit_message_text("Vamos a crear tu perfil!🖌️ Introduce tu nombre:")
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
        await query.edit_message_text("Que campo deseas editar?🖌️", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    elif query.data in CAMPOS:
        usuario_en_edicion[user_id] = query.data
        await query.edit_message_text(f"Introduce el nuevo valor para *{query.data}*:", parse_mode="Markdown")
        return EDITANDO_CAMPO

    else:
        await query.edit_message_text("❌Opcion no valida.❌")
        return ConversationHandler.END

async def crear_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in datos_temporales:
        await update.message.reply_text("❌Error interno. Usa /start para comenzar de nuevo.❌")
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
        await update.message.reply_text(f"🔸Introduce tu {siguiente}:")
        return CREANDO_PERFIL
    else:
        perfil_creado_por_usuario[user_id] = True
        del datos_temporales[user_id]
        await update.message.reply_text("Perfil creado exitosamente✅")
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
    await update.message.reply_text(f"Campo *{campo}* actualizado a: `{valor}`✅", parse_mode="Markdown")
    del usuario_en_edicion[user_id]
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operacion cancelada.❌")
    return ConversationHandler.END

AGREGAR_PASTILLA_TEXTO = 3
AGREGAR_PASTILLA_HORARIO = 4
AGREGAR_PASTILLA_DIA = 5

pastilla_temp = {}
pastilla_id_counter = {
    "Desayuno": 10,
    "Comida": 20,
    "Merienda": 30,
    "Cena": 40
}

horario_a_tab_por_pagina = {
    2: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    3: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    4: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    5: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    6: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    7: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
    8: {"Desayuno": 51, "Comida": 52, "Merienda": 53, "Cena": 54},
}

async def comenzar_agregar_pastilla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pastilla_temp[user_id] = {}
    await update.callback_query.edit_message_text("💊Introduce el nombre de la pastilla:")
    return AGREGAR_PASTILLA_TEXTO

async def recibir_pastilla_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pastilla_temp[user_id]["texto"] = update.message.text
    keyboard = [[InlineKeyboardButton(h, callback_data=h)] for h in ["Desayuno", "Comida", "Merienda", "Cena"]]
    await update.message.reply_text("⏰Selecciona el horario:", reply_markup=InlineKeyboardMarkup(keyboard))
    return AGREGAR_PASTILLA_HORARIO

async def recibir_pastilla_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    horario = query.data
    pastilla_temp[user_id]["horario"] = horario
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    keyboard = [[InlineKeyboardButton(d, callback_data=d)] for d in dias]
    await query.edit_message_text("🗓️Selecciona los días (haz click en todos los que quieras, y luego escribe 'ok')!:")
    context.user_data["dias"] = []
    context.user_data["esperando_dias"] = True
    context.user_data["user_id"] = user_id
    await query.message.reply_text("🗓️Selecciona días:", reply_markup=InlineKeyboardMarkup(keyboard))
    return AGREGAR_PASTILLA_DIA

async def registrar_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dia = update.callback_query.data
    context.user_data["dias"].append(dia)
    await update.callback_query.answer(f"Día añadido: {dia}✅")
    return AGREGAR_PASTILLA_DIA

def lanzar_notificacion_pastilla(texto, horario, msgbox_id):
    msg = {
        "page": 1,
        "id": msgbox_id,
        "obj": "msgbox",
        "text": texto,
        "options": ["Aceptar", "Cerrar"]
    }
    send_mqtt_json(msg)

async def recibir_pastilla_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = context.user_data["user_id"]

    if update.message.text.lower() == "ok":
        dias = context.user_data.get("dias", [])
        texto = pastilla_temp[user_id]["texto"]
        horario = pastilla_temp[user_id]["horario"]
        base_id = pastilla_id_counter[horario]

        dia_a_pagina = {
            "Lunes": 2,
            "Martes": 3,
            "Miércoles": 4,
            "Jueves": 5,
            "Viernes": 6,
            "Sábado": 7,
            "Domingo": 8
        }

        for dia in dias:
            pagina = dia_a_pagina.get(dia, 4)
            parentid = horario_a_tab_por_pagina[pagina][horario]

            clave = (dia, horario)
            lista_pastillas = pastillas_por_dia_horario.get(clave, [])
            cantidad = len(lista_pastillas)

            y_pos = 10 + cantidad * 40
            
            if(cantidad == 0):
                y_pos_checkbox = y_pos
            else:
                y_pos_checkbox = y_pos + 10
            
            label_id = base_id + 1 + cantidad * 2
            checkbox_id = label_id + 10

            lista_pastillas.append({
                "texto": texto,
                "label_id": label_id,
                "checkbox_id": checkbox_id,
                "pagina": pagina,
                "msgbox_id": label_id
            })
            pastillas_por_dia_horario[clave] = lista_pastillas

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
                "y": y_pos_checkbox,
                "w": 30,
                "h": 30,
                "text": "",
                "parentid": parentid,
                "val": 0,
                "enabled": "false"
            })

        pastilla_id_counter[horario] += len(dias) * 2
        del pastilla_temp[user_id]
        await update.message.reply_text("✅ Pastilla agregada correctamente.")
        return ConversationHandler.END

    else:
        context.user_data["dias"].append(update.message.text)
        return AGREGAR_PASTILLA_DIA


if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    mqtt_listener_thread = threading.Thread(target=iniciar_listener_mqtt, daemon=True)
    mqtt_listener_thread.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    main_loop = asyncio.get_event_loop()

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
        entry_points=[CallbackQueryHandler(campo_seleccionado, pattern="^(crear_perfil|editar|nombre|apellidos|dni|grupo|alergias|contacto)$")],
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
