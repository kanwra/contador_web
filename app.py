import logging
import os
import re
import threading
from datetime import datetime, timezone

import bcrypt
from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from pymongo import MongoClient
from pymongo.errors import PyMongoError

import contador

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB por subida

# --- MongoDB (cambia la contraseña en Atlas y usa variable de entorno) ---
mongo_uri = os.environ.get("MONGO_URI", "tu_nueva_cadena_de_conexion_segura")
client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
db = client["usuarios_db"]
usuarios = db["usuarios"]
conteos = db["conteos"]

EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ===================== PÁGINAS =====================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video")
def video():
    return render_template("video.html")


@app.route("/foto")
def foto():
    return render_template("foto.html")


@app.route("/principal")
def principal():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    return render_template("principal.html")


# ===================== CUENTAS =====================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "usuario_id" in session:
            return redirect(url_for("principal"))
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    try:
        usuario = usuarios.find_one({"correo": email})
    except PyMongoError:
        flash("No se pudo conectar con la base de datos")
        return redirect(url_for("login"))

    # Mismo mensaje para correo inexistente y contraseña incorrecta
    # (no revela que correos estan registrados).
    password_guardada = usuario.get("contraseña") if usuario else None
    if isinstance(password_guardada, str):
        password_guardada = password_guardada.encode("utf-8")

    try:
        valido = bool(password_guardada) and bcrypt.checkpw(
            password.encode("utf-8"), password_guardada)
    except ValueError:  # hash invalido o contraseña > 72 bytes
        valido = False

    if not valido:
        flash("Correo o contraseña incorrectos")
        return redirect(url_for("login"))

    session["usuario_id"] = str(usuario["_id"])
    session["nombre_usuario"] = usuario.get("nombre", "usuario")
    session["correo_usuario"] = usuario.get("correo", email)
    return redirect(url_for("principal"))


@app.route("/sing", methods=["GET", "POST"])
def sing():
    if request.method == "GET":
        return render_template("sing.html")

    nombre = request.form.get("nombre", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirmar = request.form.get("confirmar", "")

    error = None
    if not nombre or not email or not password:
        error = "Completa todos los campos"
    elif not EMAIL_RE.match(email):
        error = "El correo no es valido"
    elif len(password) < 8:
        error = "La contraseña debe tener al menos 8 caracteres"
    elif len(password.encode("utf-8")) > 72:  # limite de bcrypt
        error = "La contraseña es demasiado larga (maximo 72 bytes)"
    elif password != confirmar:
        error = "Las contraseñas no coinciden"
    if error:
        flash(error)
        return redirect(url_for("sing"))

    try:
        if usuarios.find_one({"correo": email}):
            flash("Ese correo ya esta registrado")
            return redirect(url_for("sing"))
        usuarios.insert_one({
            "nombre": nombre,
            "correo": email,
            "contraseña": bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()),
            "creado": datetime.now(timezone.utc),
        })
    except PyMongoError:
        flash("No se pudo conectar con la base de datos")
        return redirect(url_for("sing"))

    flash("Cuenta creada. Ya puedes iniciar sesion")
    return redirect(url_for("login"))


@app.route("/registro")
def registro():
    return redirect(url_for("sing"))


@app.route("/recuperar")
def recuperar():
    # Pendiente: envio de correo para restablecer contraseña.
    flash("La recuperacion de contraseña estara disponible pronto")
    return redirect(url_for("login"))


@app.route("/cerrar_sesion")
def cerrar_sesion():
    session.clear()
    return redirect(url_for("index"))


# ===================== CONTEO DE FOTOS =====================

@app.route("/api/contar-foto", methods=["POST"])
def api_contar_foto():
    archivo = request.files.get("imagen")
    modo = request.form.get("modo", "texto")          # "texto" o "ejemplo"
    objetos = request.form.get("objetos", "").strip()
    devolver_imagen = request.form.get("devolver_imagen") == "1"

    if not archivo or not archivo.filename:
        return jsonify(error="Sube una foto primero"), 400
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in EXT_FOTO:
        return jsonify(error="Formato no permitido. Usa JPG, PNG, WebP o HEIC"), 400
    if modo not in ("texto", "ejemplo"):
        return jsonify(error="Modo no valido"), 400
    if modo == "texto" and not objetos:
        return jsonify(error="Escribe que quieres contar, por ejemplo: manzanas"), 400

    caja = None
    if modo == "ejemplo":
        caja = request.form.get("caja", "").split(",")   # x1,y1,x2,y2 normalizados (0-1)
        if len(caja) != 4:
            return jsonify(error="Dibuja un cuadro sobre un objeto de ejemplo"), 400

    try:
        confianza = min(max(float(request.form.get("confianza", 0.25)), 0.05), 0.95)
    except ValueError:
        confianza = 0.25

    try:
        data = archivo.read()
        if modo == "texto":
            resultado = contador.contar_por_texto(data, objetos, confianza,
                                                  devolver_imagen)
        else:
            resultado = contador.contar_por_ejemplo(data, caja, confianza,
                                                    devolver_imagen)
    except contador.ErrorConteo as e:
        return jsonify(error=str(e)), 400
    except Exception:
        app.logger.exception("Fallo el conteo de la foto")
        return jsonify(error="Error al procesar la imagen. Intenta de nuevo"), 500

    # Si hay sesion, se guarda el historial (solo datos, no la imagen).
    if "usuario_id" in session:
        try:
            conteos.insert_one({
                "usuario_id": session["usuario_id"],
                "tipo": "foto",
                "modo": modo,
                "objetos": objetos if modo == "texto" else "(ejemplo visual)",
                "total": resultado["total"],
                "grupos": [{"nombre": g["nombre"], "cantidad": g["cantidad"]}
                           for g in resultado["grupos"]],
                "fecha": datetime.now(timezone.utc),
            })
        except PyMongoError:
            app.logger.warning("No se pudo guardar el conteo en la base de datos")

    return jsonify(resultado)


@app.errorhandler(413)
def archivo_muy_grande(_e):
    return jsonify(error="La foto pesa mas de 15 MB"), 413


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Carga los modelos en segundo plano: el primer usuario no espera la descarga.
    threading.Thread(target=contador.precargar, daemon=True).start()
    # use_reloader=False para no cargar el modelo dos veces
    app.run(debug=True, host="0.0.0.0", port=5000,
            use_reloader=False, threaded=True)