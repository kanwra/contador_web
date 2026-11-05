(function () {
  const MAX_ORIGINAL = 40 * 1024 * 1024;  // lo que se acepta elegir
  const MAX_ENVIO = 15 * 1024 * 1024;     // lo que acepta el servidor
  const MAX_LADO = 1280;                  // la foto se reduce antes de subirla
  const EXTENSIONES = ["jpg", "jpeg", "png", "webp", "heic", "heif"];
  const UMBRAL_ARRASTRE = 6;              // px: menos que esto es un toque, no un arrastre
  const COLOR_MANUAL = "#ffffff";

  const zona = document.getElementById("zona-drop");
  const input = document.getElementById("input-foto");
  const btnElegir = document.getElementById("btn-elegir");
  const btnContar = document.getElementById("btn-contar");
  const objetos = document.getElementById("objetos");
  const sensibilidad = document.getElementById("confianza");
  const valorSens = document.getElementById("valor-confianza");
  const panelTexto = document.getElementById("panel-texto");
  const panelEjemplo = document.getElementById("panel-ejemplo");
  const estadoCaja = document.getElementById("estado-caja");
  const contenedor = document.getElementById("contenedor-vista");
  const vista = document.getElementById("vista-previa");
  const capa = document.getElementById("capa");
  const ctx = capa.getContext("2d");
  const nombreArchivo = document.getElementById("nombre-archivo");
  const textoDrop = document.getElementById("texto-drop");
  const estado = document.getElementById("estado");
  const panelResultado = document.getElementById("resultado");
  const total = document.getElementById("total");
  const lista = document.getElementById("lista-grupos");
  const detalle = document.getElementById("detalle-correcciones");

  let archivo = null;        // lo que se sube (ya reducido)
  let urlPrevia = null;
  let previewFallo = false;  // el navegador no pudo mostrar la foto (HEIC)
  let contando = false;
  let cajaEjemplo = null;    // [x1, y1, x2, y2] normalizada 0-1
  let resultado = null;      // respuesta del servidor
  let quitadas = new Set();  // indices de cajas que el usuario quito
  let manuales = [];         // puntos que el usuario anadio {x, y} normalizados
  let inicio = null;         // pointerdown actual
  let arrastre = null;       // {a, b} mientras se dibuja el cuadro de ejemplo

  // ---------------------------------------------------------------- utilidades

  function mostrarEstado(msg, clase) {
    estado.textContent = msg;
    estado.className = "small mt-3 " + (clase || "text-gray");
  }
  function ocultarEstado() { estado.className = "d-none"; }

  function modo() {
    return document.querySelector('input[name="modo"]:checked').value;
  }
  function extension(nombre) {
    return (nombre.split(".").pop() || "").toLowerCase();
  }
  function limitar(v) { return Math.min(1, Math.max(0, v)); }

  function actualizarBoton() {
    const listo = archivo && (modo() === "texto" ? objetos.value.trim() : cajaEjemplo);
    btnContar.disabled = contando || !listo;
  }

  function actualizarEstadoCaja() {
    estadoCaja.textContent = cajaEjemplo
      ? "Ejemplo marcado. Puedes dibujarlo de nuevo si quieres cambiarlo."
      : "Aun no marcas ningun ejemplo.";
  }

  function actualizarModo() {
    const ejemplo = modo() === "ejemplo";
    panelTexto.classList.toggle("d-none", ejemplo);
    panelEjemplo.classList.toggle("d-none", !ejemplo);
    capa.classList.toggle("modo-ejemplo", ejemplo);
    actualizarEstadoCaja();
    actualizarBoton();
    dibujar();
  }

  // Reduce la foto en el navegador: sube mucho mas rapido y el servidor trabaja menos.
  // Si el navegador no puede leerla (HEIC), se manda tal cual y el servidor la convierte.
  async function reducir(f) {
    try {
      const bmp = await createImageBitmap(f);
      const esc = Math.min(1, MAX_LADO / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas");
      c.width = Math.round(bmp.width * esc);
      c.height = Math.round(bmp.height * esc);
      const g = c.getContext("2d");
      g.fillStyle = "#fff";              // PNG con transparencia -> fondo blanco
      g.fillRect(0, 0, c.width, c.height);
      g.drawImage(bmp, 0, 0, c.width, c.height);
      if (bmp.close) bmp.close();
      const blob = await new Promise(function (ok) { c.toBlob(ok, "image/jpeg", 0.9); });
      if (!blob) return f;
      return new File([blob], f.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
    } catch (_) {
      return f;
    }
  }

  // ---------------------------------------------------------------- elegir foto

  async function elegirArchivo(f) {
    if (!EXTENSIONES.includes(extension(f.name))) {
      mostrarEstado("Formato no permitido. Usa JPG, PNG, WebP o HEIC.", "text-danger");
      return;
    }
    if (f.size > MAX_ORIGINAL) {
      mostrarEstado("La foto pesa demasiado (maximo 40 MB).", "text-danger");
      return;
    }
    mostrarEstado("Preparando la foto...");
    const listo = await reducir(f);
    if (listo.size > MAX_ENVIO) {
      mostrarEstado("La foto pesa mas de 15 MB.", "text-danger");
      return;
    }
    ocultarEstado();

    archivo = listo;
    resultado = null;
    quitadas = new Set();
    manuales = [];
    cajaEjemplo = null;
    panelResultado.classList.add("d-none");
    actualizarEstadoCaja();

    previewFallo = false;
    if (urlPrevia) URL.revokeObjectURL(urlPrevia);
    urlPrevia = URL.createObjectURL(archivo);
    vista.onload = function () {
      contenedor.classList.remove("d-none");
      ajustarCapa();
    };
    vista.onerror = function () {          // HEIC: casi ningun navegador lo muestra
      previewFallo = true;
      contenedor.classList.add("d-none");
    };
    vista.src = urlPrevia;

    nombreArchivo.textContent = f.name;
    nombreArchivo.classList.remove("d-none");
    textoDrop.textContent = "Arrastra otra foto para cambiarla";
    btnElegir.textContent = "Cambiar foto";
    actualizarBoton();
  }

  btnElegir.addEventListener("click", function (e) { e.stopPropagation(); input.click(); });
  zona.addEventListener("click", function () { input.click(); });
  contenedor.addEventListener("click", function (e) { e.stopPropagation(); });
  input.addEventListener("change", function () {
    if (input.files && input.files[0]) elegirArchivo(input.files[0]);
    input.value = "";
  });

  ["dragenter", "dragover"].forEach(function (ev) {
    zona.addEventListener(ev, function (e) { e.preventDefault(); zona.classList.add("arrastrando"); });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    zona.addEventListener(ev, function (e) { e.preventDefault(); zona.classList.remove("arrastrando"); });
  });
  zona.addEventListener("drop", function (e) {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) elegirArchivo(f);
  });
  ["dragover", "drop"].forEach(function (ev) {
    window.addEventListener(ev, function (e) { e.preventDefault(); });
  });

  // ---------------------------------------------------------------- dibujo

  function ajustarCapa() {
    const w = vista.clientWidth, h = vista.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    capa.width = Math.round(w * dpr);
    capa.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    dibujar();
  }
  window.addEventListener("resize", ajustarCapa);

  function etiqueta(texto, x, y, color) {
    ctx.font = "bold 12px sans-serif";
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(0,0,0,.8)";
    ctx.strokeText(texto, x, y);
    ctx.fillStyle = color;
    ctx.fillText(texto, x, y);
  }

  function rectEjemplo() {
    if (arrastre) {
      return [Math.min(arrastre.a.x, arrastre.b.x), Math.min(arrastre.a.y, arrastre.b.y),
              Math.max(arrastre.a.x, arrastre.b.x), Math.max(arrastre.a.y, arrastre.b.y)];
    }
    return cajaEjemplo;
  }

  function dibujar() {
    const w = capa.clientWidth, h = capa.clientHeight;
    ctx.clearRect(0, 0, w, h);

    if (resultado) {
      const numerar = resultado.cajas.length - quitadas.size <= 60;
      let n = 0;
      resultado.cajas.forEach(function (c, i) {
        const x = c.b[0] * w, y = c.b[1] * h;
        const ancho = (c.b[2] - c.b[0]) * w, alto = (c.b[3] - c.b[1]) * h;
        if (quitadas.has(i)) {             // quitada: solo un contorno tenue
          ctx.setLineDash([4, 4]);
          ctx.lineWidth = 1;
          ctx.strokeStyle = "rgba(255,255,255,.6)";
          ctx.strokeRect(x, y, ancho, alto);
          ctx.setLineDash([]);
          return;
        }
        n += 1;
        const color = resultado.grupos[c.g].color;
        ctx.lineWidth = 2;
        ctx.strokeStyle = color;
        ctx.strokeRect(x, y, ancho, alto);
        if (numerar) etiqueta(String(n), x + 3, y + 13, color);
      });
      manuales.forEach(function (m) {
        ctx.beginPath();
        ctx.arc(m.x * w, m.y * h, 7, 0, 2 * Math.PI);
        ctx.fillStyle = COLOR_MANUAL;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#000";
        ctx.stroke();
      });
    }

    const r = rectEjemplo();
    if (r) {
      const x = r[0] * w, y = r[1] * h, ancho = (r[2] - r[0]) * w, alto = (r[3] - r[1]) * h;
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(0,0,0,.7)";
      ctx.strokeRect(x, y, ancho, alto);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "#fff";
      ctx.strokeRect(x, y, ancho, alto);
      ctx.setLineDash([]);
      etiqueta("ejemplo", x + 3, Math.max(12, y - 4), "#fff");
    }
  }

  // ---------------------------------------------------------------- interaccion con la foto

  function punto(e) {
    const r = capa.getBoundingClientRect();
    return { x: limitar((e.clientX - r.left) / r.width),
             y: limitar((e.clientY - r.top) / r.height),
             px: e.clientX, py: e.clientY };
  }

  capa.addEventListener("pointerdown", function (e) {
    if (e.button !== undefined && e.button !== 0) return;
    inicio = punto(e);
    arrastre = null;
    capa.setPointerCapture(e.pointerId);
  });

  capa.addEventListener("pointermove", function (e) {
    if (!inicio || modo() !== "ejemplo") return;
    const p = punto(e);
    if (arrastre || Math.hypot(p.px - inicio.px, p.py - inicio.py) > UMBRAL_ARRASTRE) {
      arrastre = { a: inicio, b: p };
      dibujar();
    }
  });

  capa.addEventListener("pointerup", function (e) {
    if (!inicio) return;
    const p = punto(e);
    if (arrastre) {
      arrastre.b = p;
      confirmarEjemplo();
    } else {
      alToque(p);
    }
    inicio = null;
    arrastre = null;
    dibujar();
  });

  capa.addEventListener("pointercancel", function () {
    inicio = null;
    arrastre = null;
    dibujar();
  });

  function confirmarEjemplo() {
    const r = rectEjemplo();
    if ((r[2] - r[0]) < 0.01 || (r[3] - r[1]) < 0.01) {
      mostrarEstado("El cuadro es muy pequeno. Dibujalo alrededor de un objeto completo.", "text-danger");
      return;
    }
    cajaEjemplo = r;
    ocultarEstado();
    actualizarEstadoCaja();
    actualizarBoton();
  }

  // Correccion manual: toque en caja = quitar/restaurar; toque vacio = anadir; toque en punto = borrar
  function alToque(p) {
    if (!resultado) return;
    const w = capa.clientWidth, h = capa.clientHeight;

    for (let i = manuales.length - 1; i >= 0; i--) {
      if (Math.hypot((manuales[i].x - p.x) * w, (manuales[i].y - p.y) * h) <= 12) {
        manuales.splice(i, 1);
        actualizarResumen();
        return;
      }
    }

    let mejor = -1, menorArea = Infinity;
    resultado.cajas.forEach(function (c, i) {
      const b = c.b;
      if (p.x >= b[0] && p.x <= b[2] && p.y >= b[1] && p.y <= b[3]) {
        const area = (b[2] - b[0]) * (b[3] - b[1]);
        if (area < menorArea) { menorArea = area; mejor = i; }
      }
    });

    if (mejor >= 0) {
      if (quitadas.has(mejor)) quitadas.delete(mejor); else quitadas.add(mejor);
    } else {
      manuales.push({ x: p.x, y: p.y });
    }
    actualizarResumen();
  }

  // ---------------------------------------------------------------- resumen

  function filaGrupo(nombre, color, cantidad) {
    const fila = document.createElement("div");
    fila.className = "grupo-fila";

    const izq = document.createElement("span");
    const punto = document.createElement("span");
    punto.className = "grupo-punto";
    punto.style.backgroundColor = color;
    izq.appendChild(punto);
    izq.appendChild(document.createTextNode(nombre));   // texto del usuario: nunca innerHTML

    const der = document.createElement("strong");
    der.textContent = cantidad;

    fila.appendChild(izq);
    fila.appendChild(der);
    return fila;
  }

  function actualizarResumen() {
    const porGrupo = resultado.grupos.map(function () { return 0; });
    resultado.cajas.forEach(function (c, i) {
      if (!quitadas.has(i)) porGrupo[c.g] += 1;
    });
    const totalFinal = porGrupo.reduce(function (a, b) { return a + b; }, 0) + manuales.length;

    total.textContent = totalFinal;
    lista.textContent = "";
    resultado.grupos.forEach(function (g, i) {
      lista.appendChild(filaGrupo(g.nombre, g.color, porGrupo[i]));
    });
    if (manuales.length) lista.appendChild(filaGrupo("Anadidos a mano", COLOR_MANUAL, manuales.length));

    detalle.textContent = (quitadas.size || manuales.length)
      ? "La IA encontro " + resultado.cajas.length + "; quitaste " + quitadas.size +
        " y anadiste " + manuales.length + "."
      : "";
    dibujar();
  }

  // ---------------------------------------------------------------- contar

  async function contar() {
    if (contando || !archivo) return;
    const m = modo();
    if (m === "ejemplo" && !cajaEjemplo) return;

    contando = true;
    actualizarBoton();
    panelResultado.classList.add("d-none");
    mostrarEstado("Analizando la foto... la primera vez puede tardar un poco.");
    btnContar.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Contando...';

    const fd = new FormData();
    fd.append("imagen", archivo);
    fd.append("modo", m);
    fd.append("confianza", sensibilidad.value);
    if (m === "texto") {
      fd.append("objetos", objetos.value.trim());
    } else {
      fd.append("caja", cajaEjemplo.map(function (v) { return v.toFixed(4); }).join(","));
    }
    if (previewFallo) fd.append("devolver_imagen", "1");

    try {
      const resp = await fetch("/api/contar-foto", { method: "POST", body: fd });
      let data = {};
      try { data = await resp.json(); } catch (_) { /* no era JSON */ }
      if (!resp.ok) throw new Error(data.error || "No se pudo procesar la foto.");

      resultado = data;
      quitadas = new Set();
      manuales = [];
      if (data.imagen) {            // HEIC: el servidor devuelve la foto ya convertida
        previewFallo = false;
        vista.src = data.imagen;
      }
      panelResultado.classList.remove("d-none");
      actualizarResumen();
      if (data.total === 0) {
        mostrarEstado("No se encontro nada. Baja la sensibilidad o cambia la palabra o el ejemplo.");
      } else {
        ocultarEstado();
      }
    } catch (err) {
      mostrarEstado(err.message || "Error de conexion con el servidor.", "text-danger");
    } finally {
      contando = false;
      btnContar.innerHTML = '<i class="bi bi-stars me-2"></i> Contar con IA';
      actualizarBoton();
    }
  }

  btnContar.addEventListener("click", contar);
  objetos.addEventListener("input", actualizarBoton);
  objetos.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !btnContar.disabled) contar();
  });
  sensibilidad.addEventListener("input", function () {
    valorSens.textContent = Number(sensibilidad.value).toFixed(2);
  });
  document.querySelectorAll('input[name="modo"]').forEach(function (r) {
    r.addEventListener("change", actualizarModo);
  });

  actualizarModo();
})();