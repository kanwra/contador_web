import os
from flask import (Flask, flash, redirect, render_template, request,
                   session, url_for, Response, jsonify)
import bcrypt
from pymongo import MongoClient

from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")

# --- MongoDB (cambia la contraseña en Atlas y usa variable de entorno) ---
mongo_uri = os.environ.get("MONGO_URI", "tu_nueva_cadena_de_conexion_segura")
client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
db = client["usuarios_db"]
usuarios = db["usuarios"]
#conteos = db["conteos"]
conteos_guardados = [] 

# ===================== PÁGINAS =====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video')
def video():
    return render_template('video.html')

@app.route('/sing')
def sing():
    return render_template('sing.html')


@app.route('/registro')
def registro():
    return render_template('registro.html')


@app.route('/foto')
def foto():
    return render_template('foto.html')

@app.route('/principal')
def principal():
    if "usuario_id" not in session:
        return redirect(url_for('login'))
    # Cambia 'principal.html' por tu plantilla real
    return render_template('principal.html')


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        try:
            usuario = usuarios.find_one({"correo": email})
        except Exception:
            flash("No se pudo conectar con la base de datos")
            return render_template("inicio.html")

        if not usuario:
            flash("Correo no registrado")
            return render_template("inicio.html")

        password_guardada = usuario.get("contraseña")
        if isinstance(password_guardada, str):
            password_guardada = password_guardada.encode("utf-8")

        if not bcrypt.checkpw(password.encode("utf-8"), password_guardada):
            flash("Contraseña incorrecta")
            return render_template("inicio.html")

        session["usuario_id"] = str(usuario["_id"])
        session["nombre_usuario"] = usuario.get("nombre", "usuario")
        session["correo_usuario"] = usuario.get("correo", email)
        return redirect("/principal")

    return render_template("inicio.html")


if __name__ == '__main__':
    # use_reloader=False es OBLIGATORIO para no abrir la cámara dos veces
    app.run(debug=True, host='0.0.0.0', port=5000,
            use_reloader=False, threaded=True)