# -*- coding: utf-8 -*-
"""OK.ru: busqueda (via buscador) y metadatos del video.

Estructura basada en el funcionamiento del addon Alfa:
 - la pagina del video lleva un JSON incrustado con los caracteres escapados
   (&quot; en vez de " y u0026 en vez de &): hay que desescaparlo.
 - dentro esta el array "videos": [{"name":"hd","url":"..."}] con las calidades,
   y "hlsManifestUrl" con el manifiesto HLS.
"""
import os
import re
import html
import json
import urllib.parse
import time
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
TIMEOUT = 10

class BuscadorLimitado(Exception):
    """El buscador ha limitado las peticiones."""


CALIDADES_ORDEN = ["mobile", "lowest", "low", "sd", "hd", "full", "quad", "ultra", "1080", "2160"]
ETIQUETAS = {
    "mobile": "Movil", "lowest": "Minima (144p)", "low": "Baja (240p)", "sd": "SD (480p)",
    "hd": "HD (720p)", "full": "Full HD (1080p)", "quad": "2K (1440p)", "ultra": "4K (2160p)",
}
IDIOMAS = {"castellano": "Castellano", "castellà": "Castellano", "español": "Castellano",
           "latino": "Latino", "latina": "Latino", "vose": "VOSE", "subtitulad": "VOSE",
           "sub espa": "VOSE", "subs": "VOSE", "original": "VOSE", "ruso": "Ruso", "audio rus": "Ruso"}


def log(msg):
    try:
        import xbmc
        xbmc.log("[plugin.video.okru] %s" % msg, xbmc.LOGINFO)
    except Exception:
        print("[plugin.video.okru] %s" % msg)


_META_CACHE = {}           # url -> (cuando, (calidades, hls, info))
_META_TTL = 24 * 3600      # la ficha se guarda 24 h


def _cache_meta_fichero():
    """Ruta del fichero de cache, si estamos dentro de Kodi."""
    try:
        import xbmcvfs
        carpeta = xbmcvfs.translatePath("special://profile/addon_data/plugin.video.okru/")
        if not os.path.isdir(carpeta):
            os.makedirs(carpeta)
        return os.path.join(carpeta, "metadatos.json")
    except Exception:
        return ""


def _guardar_meta(url, calidades, hls, info, cuando):
    """Guarda la ficha en memoria y en disco (sin dejar crecer el fichero)."""
    _META_CACHE[url] = (cuando, (calidades, hls, info))
    fichero = _cache_meta_fichero()
    if not fichero:
        return
    try:
        guardado = {}
        if os.path.exists(fichero):
            with open(fichero, "r") as f:
                guardado = json.load(f)
        # poda: fuera lo caducado y como mucho 200 fichas
        guardado = {k: v for k, v in guardado.items()
                    if cuando - v.get("t", 0) < _META_TTL and k != url}
        if len(guardado) >= 200:
            for k in sorted(guardado, key=lambda x: guardado[x].get("t", 0))[:50]:
                guardado.pop(k, None)
        guardado[url] = {"t": cuando, "calidades": calidades, "hls": hls, "info": info}
        with open(fichero, "w") as f:
            json.dump(guardado, f)
    except Exception:
        pass


def _get(url, extra=None):
    h = {"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         # ok.ru manda esta pagina sin comprimir si no se pide: 1,2 MB.
         # Pidiendola con gzip baja a ~300 KB y tarda la mitad.
         "Accept-Encoding": "gzip"}
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read()
        if "gzip" in (r.headers.get("Content-Encoding") or "").lower():
            import gzip as _gzip
            try:
                data = _gzip.decompress(data)
            except Exception:
                pass
    try:
        return data.decode("utf-8")
    except Exception:
        return data.decode("cp1251", "replace")


# ---------------------------------------------------------------- idioma
def detectar_idioma(texto):
    t = (texto or "").lower()
    for clave, nombre in IDIOMAS.items():
        if clave in t:
            return nombre
    return ""


# ---------------------------------------------------------------- busqueda
MOTORES = [
    ("duckduckgo", "https://html.duckduckgo.com/html/?q=%s"),
    ("ddg-lite",   "https://lite.duckduckgo.com/lite/?q=%s"),
    ("mojeek",     "https://www.mojeek.com/search?q=%s"),
    ("bing",       "https://www.bing.com/search?q=%s"),
]

_CACHE = {}


def _extraer_generico(html_txt, limite, vistos):
    """Parser tolerante: busca enlaces a video de ok.ru y su texto cercano."""
    salida = []
    for m in re.finditer(r'href="([^"]*ok\.ru/video/\d+[^"]*)"[^>]*>(.{0,200}?)</a>', html_txt, re.S):
        href = html.unescape(m.group(1))
        if href.startswith("//"):
            href = "https:" + href
        if "uddg=" in href:
            href = _url_real(href)
        vid = re.search(r"/video/(\d+)", href or "")
        if not vid:
            continue
        vid = vid.group(1)
        if vid in vistos:
            continue
        titulo = html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        titulo = re.sub(r"\s+", " ", titulo).strip()
        titulo = re.sub(r"\s*-?\s*(Одноклассники|OK\.ru|ok\.ru)\s*$", "", titulo, flags=re.I).strip()
        if len(titulo) < 4:
            continue
        vistos.add(vid)
        salida.append({"id": vid, "url": "https://ok.ru/video/" + vid,
                       "titulo": titulo, "idioma": detectar_idioma(titulo)})
        if len(salida) >= limite:
            break
    return salida


def buscar(consulta, limite=30):
    """Busca videos de ok.ru. Prueba varios buscadores y cachea el resultado."""
    clave = (consulta.lower().strip(), limite)
    if clave in _CACHE:
        return _CACHE[clave]

    q = "site:ok.ru/video " + consulta
    codificada = urllib.parse.quote(q)
    ultimo_error = ""
    for nombre, plantilla in MOTORES:
        try:
            html_txt = _get(plantilla % codificada)
        except Exception as e:
            ultimo_error = "%s: %s" % (nombre, e)
            continue
        vistos, salida = set(), []
        # a) marcado estandar de DDG
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_txt, re.S):
            real = _url_real(m.group(1))
            vid = re.search(r"/video/(\d+)", real or "")
            if not vid or vid.group(1) in vistos:
                continue
            titulo = re.sub(r"<[^>]+>", " ", html.unescape(m.group(2)))
            titulo = re.sub(r"\s+", " ", titulo).strip()
            vistos.add(vid.group(1))
            salida.append({"id": vid.group(1), "url": "https://ok.ru/video/" + vid.group(1),
                           "titulo": titulo, "idioma": detectar_idioma(titulo)})
            if len(salida) >= limite:
                break
        # b) si no hubo nada, parser generico (sirve para lite/mojeek/bing)
        if not salida:
            salida = _extraer_generico(html_txt, limite, vistos)
        if salida:
            log("busqueda '%s': %d resultados via %s" % (consulta, len(salida), nombre))
            _CACHE[clave] = salida
            return salida
        ultimo_error = "%s: sin resultados" % nombre

    log("busqueda '%s' sin exito: %s" % (consulta, ultimo_error))
    raise BuscadorLimitado(ultimo_error or "sin resultados")


def _url_real(href):
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href or "uddg=" in href:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        v = qs.get("uddg")
        if v:
            return urllib.parse.unquote(v[0])
    return href if href.startswith("http") else ""


def _ficha_resultado(html_txt, url):
    """Descripcion del resultado, para usarla como sinopsis."""
    i = html_txt.find(urllib.parse.quote(url, safe=""))
    if i < 0:
        i = html_txt.find(url)
    if i < 0:
        return ""
    trozo = html_txt[i:i + 1500]
    m = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', trozo, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def sinopsis(titulo):
    """Busca descripcion corta para el listado (una sola peticion)."""
    try:
        if not titulo:
            return ""
        html_txt = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(titulo + " ok.ru"))
        m = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', html_txt, re.S)
        if m:
            return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()[:400]
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------- metadatos del video
def desescapar(texto):
    """Equivalente a lo que hace el resolver de Alfa: quitar &quot; y u0026 y los backslash."""
    t = texto.replace("&quot;", '"').replace("&#34;", '"').replace("&amp;", "&")
    t = t.replace("u0026", "&").replace("\\/", "/").replace("\\", "")
    return t


def metadatos(url, _forzar=False):
    """Devuelve (calidades, hls, info) de un video de ok.ru.

    Va cacheado: la pagina pesa ~1,2 MB y tarda ~1 s, asi que la segunda vez
    que se abre el mismo video (volver a mirarlo, cambiar de calidad, volver
    atras y entrar otra vez) es instantanea.
    """
    ahora = time.time()

    # 1) cache en memoria
    d = _META_CACHE.get(url)
    if d and not _forzar and ahora - d[0] < _META_TTL:
        return d[1]

    # 2) cache en disco, por si Kodi se reinicia entre medias
    fichero = _cache_meta_fichero()
    if fichero and not _forzar:
        try:
            if os.path.exists(fichero):
                with open(fichero, "r") as f:
                    guardado = json.load(f)
                reg = guardado.get(url)
                if reg and ahora - reg.get("t", 0) < _META_TTL:
                    dato = (reg["calidades"], reg["hls"], reg["info"])
                    _META_CACHE[url] = (reg["t"], dato)
                    return dato
        except Exception:
            pass

    pagina = _get(url)
    d = desescapar(pagina)

    info = {"titulo": "", "duracion": "", "imagen": "", "idioma": ""}
    for campo, patron in (("titulo", r'"movie"\s*:\s*\{[^}]*?"title"\s*:\s*"([^"]{3,200})"'),
                          ("imagen", r'"poster"\s*:\s*"(https?[^"]{10,500})"'),
                          ("duracion", r'"duration"\s*:\s*"?(\d+)"?')):
        m = re.search(patron, d, re.S)
        if m:
            info[campo] = m.group(1)
    info["idioma"] = detectar_idioma(info.get("titulo") or url)

    calidades = []
    i = d.find('"videos"')
    if i >= 0:
        for m in re.finditer(r'\{"name":"([^"]{1,20})","url":"([^"]{10,600})"', d[i:i + 20000]):
            nombre = m.group(1).strip()
            enlace = m.group(2).replace("\\/", "/").strip()
            if not enlace.startswith("http"):
                continue
            calidades.append({"nombre": nombre,
                              "etiqueta": ETIQUETAS.get(nombre, nombre.upper()),
                              "url": enlace,
                              "orden": CALIDADES_ORDEN.index(nombre) if nombre in CALIDADES_ORDEN else 99})
    calidades.sort(key=lambda c: c["orden"])

    m = re.search(r'"hlsManifestUrl"\s*:\s*"(https?[^"]{20,900})"', d)
    hls = m.group(1).replace("\\/", "/") if m else ""

    log("metadatos: %d calidades, hls=%s" % (len(calidades), "si" if hls else "no"))
    _guardar_meta(url, calidades, hls, info, ahora)
    return calidades, hls, info


def caratula(url):
    """Caratula (poster) de un video, leyendo su pagina."""
    try:
        d = desescapar(_get(url))
        m = re.search(r'"poster"\s*:\s*"(https?[^"]{10,500})"', d, re.S)
        if not m:
            m = re.search(r'og:image"\s+content="(https?[^"]{10,500})"', d)
        return m.group(1).replace("\\/", "/") if m else ""
    except Exception:
        return ""


# ---------------------------------------------------------------- secciones (categorias)
GENEROS = ["Accion", "Comedia", "Terror", "Ciencia ficcion", "Thriller", "Drama", "Aventura",
           "Animacion", "Documental", "Belica", "Western", "Fantastico", "Romance", "Policiaca"]

SUFIJOS_IDIOMA = ["castellano", "latino", "espanol", "español", "vose", "subtitulado"]


def extraer_anio(titulo):
    m = re.findall(r"(19\d{2}|20\d{2})", titulo or "")
    return int(m[-1]) if m else 0


def _buscar_multi(consultas, limite):
    """Varias busquedas en cascada, deduplicando (tolera el limite del buscador)."""
    salida, vistos = [], set()
    for q in consultas:
        try:
            for r in buscar_inteligente(q, limite):
                if r["id"] not in vistos:
                    vistos.add(r["id"])
                    salida.append(r)
        except BuscadorLimitado as e:
            log("limite en '%s': %s" % (q, e))
            break
        if len(salida) >= limite:
            break
        time.sleep(0.8)
    return salida[:limite]


def por_genero(genero, limite=30, idioma="Castellano"):
    i = idioma if idioma and idioma != "Cualquiera" else "castellano"
    return _buscar_multi(["pelicula %s %s" % (genero, i)], limite)


def por_anio(anio, limite=30, idioma="Castellano"):
    i = idioma if idioma and idioma != "Cualquiera" else "castellano"
    return _buscar_multi(["pelicula %s %s" % (anio, i)], limite)


def novedades(limite=30, idioma="Castellano"):
    import datetime
    a = datetime.date.today().year
    i = idioma if idioma and idioma != "Cualquiera" else "castellano"
    consultas = ["pelicula %s %s" % (a, i)]
    return ordenar(_buscar_multi(consultas, limite), "anio")


def por_idioma(idioma, limite=30):
    return _buscar_multi(["pelicula %s" % idioma], limite)


def ordenar(resultados, criterio="anio"):
    for r in resultados:
        r["anio"] = extraer_anio(r.get("titulo", ""))
        r["idioma"] = r.get("idioma") or detectar_idioma(r.get("titulo", ""))
    if criterio == "anio":
        resultados.sort(key=lambda r: (-(r.get("anio") or 0), r.get("titulo", "").lower()))
    else:
        resultados.sort(key=lambda r: r.get("titulo", "").lower())
    return resultados


# ---------------------------------------------------------------- busqueda con sesion de ok.ru
COOKIES = ""          # lo rellena el add-on desde los ajustes


def set_cookies(valor):
    global COOKIES
    COOKIES = (valor or "").strip()


def _get_sesion(url, cookies=None):
    """GET con la cookie de sesion del usuario (asi ok.ru nos deja buscar)."""
    ck = (cookies if cookies is not None else COOKIES) or ""
    peticion = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Cookie": ck,
    })
    with urllib.request.urlopen(peticion, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def buscar_con_sesion(consulta, limite=30):
    """Busca en ok.ru usando la sesion (cookies) del usuario."""
    if not COOKIES:
        raise BuscadorLimitado("sin cookies de sesion")
    url = "https://ok.ru/dk?st.cmd=searchResult&st.query=" + urllib.parse.quote(consulta) + "&st.mode=Video"
    h = _get_sesion(url)
    if len(h) < 5000:
        log("busqueda con sesion: respuesta vacia (%d bytes). La sesion habra caducado" % len(h))
        raise BuscadorLimitado("sesion caducada o sin acceso")
    vistos, salida = set(), []
    for m in re.finditer(r'href="([^"]*?/video/(\d+)[^"]*)"[^>]*>(.{0,300}?)</a>', h, re.S):
        vid = m.group(2)
        if vid in vistos:
            continue
        titulo = re.sub(r"<[^>]+>", " ", html.unescape(m.group(3)))
        titulo = re.sub(r"\s+", " ", titulo).strip()
        titulo = re.sub(r"\s*[-–—]\s*(Одноклассники|OK\.ru).*$", "", titulo, flags=re.I).strip()
        if len(titulo) < 4:
            continue
        vistos.add(vid)
        salida.append({"id": vid, "url": "https://ok.ru/video/" + vid,
                       "titulo": titulo, "idioma": detectar_idioma(titulo)})
        if len(salida) >= limite:
            break
    log("busqueda con sesion '%s': %d resultados" % (consulta, len(salida)))
    if not salida:
        raise BuscadorLimitado("la busqueda no devolvio videos")
    return salida


def buscar_inteligente(consulta, limite=30):
    """Servicio local (navegador con sesion) primero; luego cookies; luego buscadores."""
    try:
        return buscar_servicio(consulta, limite)
    except BuscadorLimitado as e:
        log("servicio local no util (%s); sigo con lo demas" % e)
    if COOKIES:
        try:
            return buscar_con_sesion(consulta, limite)
        except BuscadorLimitado as e:
            log("sesion no utilizable (%s); paso a buscadores" % e)
    return buscar(consulta, limite)


# ---------------------------------------------------------------- servicio local (navegador)
SERVICIO = "http://127.0.0.1:9223"
CANDIDATOS_SERVICIO = ["http://127.0.0.1:9223", "http://192.168.1.64:9223"]  # propio y el principal
_SERVICIO_BUENO = ""    # recordamos el que funciona para no volver a probar los otros


def set_servicio(url):
    """Ajusta donde esta el buscador. Acepta varias separadas por comas o espacios."""
    global SERVICIO, CANDIDATOS_SERVICIO
    if not url:
        return   # sin ajuste se queda la lista por defecto (propio + principal)
    lista = [u.strip().rstrip("/") for u in re.split(r"[,\s]+", url) if u.strip()]
    if lista:
        SERVICIO = lista[0]
        # el propio equipo, luego lo que diga el ajuste, y de reserva el principal
        CANDIDATOS_SERVICIO = _lista_candidatos(lista)


def _lista_candidatos(preferidos=None):
    """Orden de direcciones a probar: el propio equipo, lo que diga el ajuste y el principal."""
    base = ["http://127.0.0.1:9223", "http://192.168.1.64:9223"]
    salida = []
    for u in (base[:1] + (preferidos or []) + base[1:]):
        u = u.rstrip("/")
        if u and u not in salida:
            salida.append(u)
    return salida


def _probar_servicios():
    """Devuelve el primer buscador que responde con sesion."""
    for base in CANDIDATOS_SERVICIO:
        try:
            with urllib.request.urlopen(base + "/estado", timeout=6) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            if d.get("ok"):
                log("buscador utilizable en %s (sesion=%s)" % (base, d.get("sesion")))
                return base
        except Exception:
            continue
    return ""


def buscar_servicio(consulta, limite=30):
    """Pide la busqueda al servicio local, que la hace en el navegador con la sesion."""
    global _SERVICIO_BUENO
    orden = ([_SERVICIO_BUENO] if _SERVICIO_BUENO else []) + \
            [b for b in CANDIDATOS_SERVICIO if b != _SERVICIO_BUENO]
    ultimo = ""
    for base in orden:
        url = "%s/buscar?q=%s&n=%d" % (base, urllib.parse.quote(consulta), limite)
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                datos = json.loads(r.read().decode("utf-8", "replace"))
            ultimo = base
            _SERVICIO_BUENO = base      # este funciona: la proxima vez, primero
            break
        except Exception as e:
            ultimo = ""
            log("buscador %s no responde: %s" % (base, type(e).__name__))
            datos = None
    if not datos:
        raise BuscadorLimitado("ningun buscador local responde (%s)" % ultimo)
    if not datos.get("ok"):
        raise BuscadorLimitado(str(datos.get("error"))[:80])
    res = datos.get("resultados") or []
    if not res:
        raise BuscadorLimitado("la busqueda no devolvio videos")
    for r in res:
        r["idioma"] = r.get("idioma") or detectar_idioma(r.get("titulo", ""))
    return res


def servicio_disponible():
    try:
        with urllib.request.urlopen(SERVICIO + "/estado", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return bool(d.get("ok") and d.get("sesion"))
    except Exception:
        return False


def cookies_del_servicio():
    """Pide al buscador las cookies de ok.ru (las tiene el navegador)."""
    orden = ([_SERVICIO_BUENO] if _SERVICIO_BUENO else []) + \
            [b for b in CANDIDATOS_SERVICIO if b != _SERVICIO_BUENO]
    for base in orden:
        try:
            with urllib.request.urlopen(base + "/cookies", timeout=25) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            if d.get("ok") and d.get("cookies"):
                return d["cookies"]
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------- descarga
def cabeceras_video():
    """Cabeceras que exige un enlace firmado de ok.ru (Cookie + Referer)."""
    h = {"User-Agent": UA, "Referer": "https://ok.ru/"}
    ck = cookies_del_servicio() or COOKIES
    if ck:
        h["Cookie"] = ck
    return h


def descargar_video(url, destino, progreso=None, cancelado=None):
    """Descarga un enlace de ok.ru a un fichero. Devuelve True si acabo entero.

    Los enlaces van FIRMADOS y exigen Cookie + Referer: por eso no vale una
    descarga normal (Kodi no sabe mandar esas cabeceras) y la hace el addon.
    progreso(leidos, total) se llama con cada trozo (total=0 si el servidor no
    lo dice). cancelado() devuelve True para parar.
    """
    peticion = urllib.request.Request(url, headers=cabeceras_video())
    with urllib.request.urlopen(peticion, timeout=60) as r:
        try:
            total = int(r.headers.get("Content-Length") or 0)
        except Exception:
            total = 0
        leidos = 0
        with open(destino, "wb") as f:
            while True:
                if cancelado and cancelado():
                    return False
                trozo = r.read(256 * 1024)
                if not trozo:
                    break
                f.write(trozo)
                leidos += len(trozo)
                if progreso:
                    try:
                        progreso(leidos, total)
                    except Exception:
                        pass
    return True
