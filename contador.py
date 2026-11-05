"""Conteo de objetos con ultralytics.

Modo texto (YOLO-World): el usuario escribe que contar ("manzanas, platanos"),
se traduce a ingles y se detectan solo esos grupos.
Modo ejemplo (YOLOE): el usuario marca un objeto con una caja y se buscan
los que se le parecen.
Se devuelven conteos + cajas normalizadas (0-1); el dibujo lo hace el navegador.
"""
import base64
import io
import logging
import math
import os
import re
import threading
import unicodedata

import cv2
import numpy as np

log = logging.getLogger(__name__)

MODELO_TEXTO = os.environ.get("MODELO_CONTEO", "yolov8s-worldv2.pt")
MODELO_EJEMPLO = os.environ.get("MODELO_EJEMPLO", "yoloe-11s-seg.pt")
MAX_LADO = int(os.environ.get("MAX_LADO", 1280))   # la foto se reduce a este lado maximo
IMGSZ = int(os.environ.get("IMGSZ", 960))          # resolucion de inferencia (menor = mas rapido)
MAX_GRUPOS = 6       # maximo de grupos distintos por consulta
MAX_DETECCIONES = 300

# un color por grupo (el navegador dibuja las cajas)
COLORES = ["#e74c3c", "#2ecc71", "#3498db", "#f1c40f", "#9b59b6", "#1abc9c"]

# Diccionario basico es -> en (claves en singular y sin acentos).
# Si una palabra no esta aqui se usa tal cual, asi que el usuario tambien
# puede escribir en ingles. Ampliar libremente.
ES_EN = {
    "persona": "person", "gente": "person", "nino": "child", "ninos": "child",
    "manzana": "apple", "platano": "banana", "banana": "banana",
    "naranja": "orange", "limon": "lemon", "uva": "grape", "fresa": "strawberry",
    "pera": "pear", "sandia": "watermelon", "pina": "pineapple",
    "tomate": "tomato", "jitomate": "tomato", "cebolla": "onion",
    "zanahoria": "carrot", "papa": "potato", "aguacate": "avocado",
    "huevo": "egg", "pan": "bread", "pizza": "pizza", "dona": "donut",
    "galleta": "cookie", "pastel": "cake", "botella": "bottle", "lata": "can",
    "vaso": "cup", "taza": "mug", "plato": "plate", "cuchara": "spoon",
    "tenedor": "fork", "cuchillo": "knife", "caja": "box", "paquete": "package",
    "bolsa": "bag", "costal": "sack", "barril": "barrel", "pallet": "pallet",
    "palet": "pallet", "tubo": "pipe", "tuberia": "pipe", "varilla": "rebar",
    "tornillo": "screw", "tuerca": "nut", "clavo": "nail", "ladrillo": "brick",
    "bloque": "block", "tabla": "wooden board", "tronco": "log",
    "madera": "wood plank", "arbol": "tree", "planta": "plant", "flor": "flower",
    "hoja": "leaf", "moneda": "coin", "billete": "banknote", "llave": "key",
    "lapiz": "pencil", "pluma": "pen", "libro": "book", "papel": "paper",
    "telefono": "cell phone", "celular": "cell phone", "laptop": "laptop",
    "silla": "chair", "mesa": "table", "cama": "bed", "puerta": "door",
    "ventana": "window", "coche": "car", "carro": "car", "auto": "car",
    "camion": "truck", "moto": "motorcycle", "motocicleta": "motorcycle",
    "bicicleta": "bicycle", "autobus": "bus", "avion": "airplane",
    "barco": "boat", "perro": "dog", "gato": "cat", "vaca": "cow",
    "res": "cow", "toro": "bull", "caballo": "horse", "oveja": "sheep",
    "borrego": "sheep", "cabra": "goat", "cerdo": "pig", "puerco": "pig",
    "pollo": "chicken", "gallina": "chicken", "pato": "duck", "pajaro": "bird",
    "ave": "bird", "pez": "fish", "pescado": "fish", "abeja": "bee",
    "mariposa": "butterfly", "pastilla": "pill", "tableta": "pill",
    "celula": "cell", "semilla": "seed", "piedra": "rock", "balon": "ball",
    "pelota": "ball", "zapato": "shoe", "camisa": "shirt", "casco": "helmet",
    "sombrero": "hat", "bolsillo": "pocket", "asiento": "seat",
    "boleto": "ticket", "entrada": "ticket", "contenedor": "shipping container",
}


class ErrorConteo(Exception):
    """Error 'esperado' (entrada invalida) que se muestra al usuario."""


def _sin_acentos(texto):
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _a_ingles(termino):
    """Devuelve el termino en ingles (o el mismo si no esta en el diccionario)."""
    t = _sin_acentos(termino.lower().strip())
    candidatos = [t]
    if t.endswith("es"):
        candidatos.append(t[:-2])
    if t.endswith("s"):
        candidatos.append(t[:-1])
    for c in candidatos:
        if c in ES_EN:
            return ES_EN[c]
    return t


def interpretar_objetos(texto):
    """'manzanas, platanos' -> [('manzanas', 'apple'), ('platanos', 'banana')]"""
    partes = re.split(r"[,;\n]+|\s+y\s+", texto or "")
    grupos, vistos = [], set()
    for p in partes:
        p = p.strip()
        if not p or len(p) > 60:
            continue
        en = _a_ingles(p)
        if en in vistos:
            continue
        vistos.add(en)
        grupos.append((p, en))
    if not grupos:
        raise ErrorConteo("Escribe que quieres contar, por ejemplo: manzanas")
    if len(grupos) > MAX_GRUPOS:
        raise ErrorConteo(f"Maximo {MAX_GRUPOS} grupos a la vez")
    return grupos


def _decodificar(data):
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # respeta la orientacion EXIF
    if img is None:
        try:  # HEIC / HEIF
            import pillow_heif
            from PIL import Image, ImageOps
            pillow_heif.register_heif_opener()
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
            img = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
        except Exception:
            raise ErrorConteo("No se pudo leer la imagen. Prueba con JPG, PNG o WebP.")
    h, w = img.shape[:2]
    lado = max(h, w)
    if lado > MAX_LADO:
        f = MAX_LADO / lado
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    return img


def interpretar_caja(caja):
    """Caja de ejemplo normalizada (0-1): [x1, y1, x2, y2] -> tupla validada."""
    try:
        x1, y1, x2, y2 = [float(v) for v in caja]
    except (TypeError, ValueError):
        raise ErrorConteo("Caja de ejemplo invalida")
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        raise ErrorConteo("Caja de ejemplo invalida")
    x1, x2 = sorted((min(max(x1, 0.0), 1.0), min(max(x2, 0.0), 1.0)))
    y1, y2 = sorted((min(max(y1, 0.0), 1.0), min(max(y2, 0.0), 1.0)))
    if (x2 - x1) < 0.01 or (y2 - y1) < 0.01:
        raise ErrorConteo("Dibuja un cuadro un poco mas grande sobre un solo objeto")
    return x1, y1, x2, y2


# ---------------------------------------------------------------- modelos

_modelo_texto = None
_modelo_ejemplo = None
_clases_activas = None
_lock = threading.Lock()   # los modelos guardan estado: una consulta a la vez


def _extraer(res):
    if res.boxes is None or len(res.boxes) == 0:
        return np.zeros(0, int), np.zeros((0, 4))
    return (res.boxes.cls.cpu().numpy().astype(int),
            res.boxes.xyxy.cpu().numpy())


def _detectar_texto(img, clases_en, conf):
    """YOLO-World: detecta solo las clases dadas. Devuelve (indices, cajas_xyxy)."""
    global _modelo_texto, _clases_activas
    with _lock:
        if _modelo_texto is None:
            from ultralytics import YOLOWorld
            _modelo_texto = YOLOWorld(MODELO_TEXTO)
            _clases_activas = None
        if _clases_activas != list(clases_en):  # set_classes es lo caro: solo si cambian
            _modelo_texto.set_classes(list(clases_en))
            _clases_activas = list(clases_en)
        res = _modelo_texto.predict(img, conf=conf, iou=0.5, imgsz=IMGSZ,
                                    max_det=MAX_DETECCIONES, verbose=False)[0]
    return _extraer(res)


def _detectar_ejemplo(img, caja_px, conf):
    """YOLOE con 'visual prompt': busca objetos parecidos al de la caja.

    OJO: esta es la parte que depende de la API de ultralytics (YOLOE).
    Si en tu version cambia, solo hay que ajustar esta funcion.
    """
    global _modelo_ejemplo
    from ultralytics.models.yolo.yoloe import YOLOEVPSegPredictor
    with _lock:
        if _modelo_ejemplo is None:
            from ultralytics import YOLOE
            _modelo_ejemplo = YOLOE(MODELO_EJEMPLO)
        _modelo_ejemplo.predictor = None   # reinicia: no arrastrar prompts anteriores
        prompts = {"bboxes": np.array([caja_px], dtype=np.float32),
                   "cls": np.array([0])}
        res = _modelo_ejemplo.predict(
            img, refer_image=img, visual_prompts=prompts,
            predictor=YOLOEVPSegPredictor, conf=conf, iou=0.5, imgsz=IMGSZ,
            max_det=MAX_DETECCIONES, verbose=False)[0]
    return _extraer(res)


def precargar():
    """Carga los modelos con una inferencia de prueba (llamar en un hilo al arrancar)."""
    img = np.zeros((IMGSZ, IMGSZ, 3), np.uint8)
    try:
        _detectar_texto(img, ["object"], 0.5)
        log.info("Modelo de texto listo")
    except Exception:
        log.exception("No se pudo precargar el modelo de texto")
    try:
        _detectar_ejemplo(img, [IMGSZ * .25, IMGSZ * .25, IMGSZ * .5, IMGSZ * .5], 0.5)
        log.info("Modelo de ejemplo listo")
    except Exception:
        log.exception("No se pudo precargar el modelo de ejemplo")


# ---------------------------------------------------------------- resultado

def _n(valor, total):
    return round(min(max(float(valor) / total, 0.0), 1.0), 4)


def _resultado(img, grupos, clases, cajas, devolver_imagen):
    """JSON para el navegador: cajas normalizadas (0-1), el dibujo lo hace el front."""
    h, w = img.shape[:2]
    out = {
        "total": int(len(clases)),
        "ancho": w, "alto": h,
        "grupos": [{"nombre": nombre, "clase": en,
                    "cantidad": int((clases == i).sum()),
                    "color": COLORES[i % len(COLORES)]}
                   for i, (nombre, en) in enumerate(grupos)],
        "cajas": [{"g": int(c),
                   "b": [_n(x1, w), _n(y1, h), _n(x2, w), _n(y2, h)]}
                  for c, (x1, y1, x2, y2) in zip(clases, cajas)],
    }
    if devolver_imagen:  # solo si el navegador no pudo mostrar la foto (p. ej. HEIC)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ErrorConteo("No se pudo preparar la imagen")
        out["imagen"] = "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    return out


def contar_por_texto(data, texto, conf=0.25, devolver_imagen=False):
    """Cuenta los grupos pedidos en `texto` (bytes de imagen en `data`)."""
    grupos = interpretar_objetos(texto)
    img = _decodificar(data)
    clases, cajas = _detectar_texto(img, [en for _, en in grupos], conf)
    return _resultado(img, grupos, clases, cajas, devolver_imagen)


def contar_por_ejemplo(data, caja, conf=0.25, devolver_imagen=False):
    """Cuenta objetos parecidos al de `caja` ([x1, y1, x2, y2] normalizada 0-1)."""
    x1, y1, x2, y2 = interpretar_caja(caja)
    img = _decodificar(data)
    h, w = img.shape[:2]
    _, cajas = _detectar_ejemplo(img, [x1 * w, y1 * h, x2 * w, y2 * h], conf)
    clases = np.zeros(len(cajas), int)   # un solo grupo
    return _resultado(img, [("como tu ejemplo", "ejemplo")], clases, cajas,
                      devolver_imagen)