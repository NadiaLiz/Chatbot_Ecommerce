import os
import unicodedata
import os
import unicodedata
import firebase_admin
from firebase_admin import credentials, firestore
from transformers import AutoTokenizer, AutoModelForCausalLM
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import torch
import threading
import requests

# --- Configuración de Twilio ---
TWILIO_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_TOKEN = "3aexxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"  # número sandbox de Twilio

# --- Firebase ---
if not firebase_admin._apps:
    cred = credentials.Certificate("./ninatec-ecc00-firebase-adminsdk-fbsvc-5d1171c4a7.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Modelo HF ---
model_name = "NadiaLiz/Llama-3.2.3B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
device = torch.device("cpu")  # Forzar uso de CPU
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.float32
).to(device)

# --- Funciones ---
def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    return texto

def extraer_producto(mensaje):
    mensaje_norm = normalizar(mensaje)
    productos_ref = db.collection("Productos").stream()
    for doc in productos_ref:
        nombre_producto = doc.to_dict().get("producto", "")
        nombre_norm = normalizar(nombre_producto)
        if nombre_norm in mensaje_norm:
            return doc.id
    return None

def buscar_precio(producto):
    ref = db.collection("Productos").document(producto)
    doc = ref.get()
    if doc.exists:
        data = doc.to_dict()
        return f"Claro, el {data.get('producto')} cuesta S/{data.get('precio')}."
    return None

def obtener_contexto():
    return (
        "Eres un asistente virtual de Ninatec, una empresa especializada en venta de accesorios tecnologicos "
        "Estás capacitado para responder preguntas sobre nuestros productos"
        "Responde siempre de manera amable, clara y profesional."
    )

def responder_en_segundo_plano(mensaje, numero_usuario):
    texto = mensaje.lower()

    if any(palabra in texto for palabra in ["precio", "cuánto cuesta", "cuanto vale"]):
        pid = extraer_producto(mensaje)
        if pid:
            respuesta = buscar_precio(pid)
        else:
            respuesta = "¿De qué producto deseas saber el precio? Por favor escribe el nombre exacto."
    else:
        prompt = f"{obtener_contexto()}\nUsuario: {mensaje}\nAsistente:"
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        output = model.generate(**inputs, max_new_tokens=100, do_sample=True, temperature=0.7)
        gen = tokenizer.decode(output[0], skip_special_tokens=True)
        respuesta = gen.replace(prompt, "").strip()

    # Enviar respuesta final con Twilio API
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    data = {
        "To": numero_usuario,
        "From": TWILIO_WHATSAPP_NUMBER,
        "Body": respuesta
    }
    response = requests.post(url, data=data, auth=(TWILIO_SID, TWILIO_TOKEN))
    print("Respuesta enviada vía API:", respuesta)
    print("Código HTTP:", response.status_code)

# --- Flask App ---
app = Flask(__name__)

@app.route("/whatsapp", methods=["POST"])
def whatsapp_twilio():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").strip()

    print(f"Mensaje recibido: {incoming_msg} de {from_number}")

    twilio_resp = MessagingResponse()
    twilio_resp.message()

    # Procesar en segundo plano
    threading.Thread(target=responder_en_segundo_plano, args=(incoming_msg, from_number)).start()

    return str(twilio_resp)

# --- Ejecutar servidor ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

