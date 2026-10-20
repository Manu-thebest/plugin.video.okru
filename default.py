# -*- coding: utf-8 -*-
import os
import sys
import threading
import time

import xbmcaddon
_ADDON_PATH = xbmcaddon.Addon().getAddonInfo("path")
if _ADDON_PATH and _ADDON_PATH not in sys.path:
    sys.path.insert(0, os.path.join(_ADDON_PATH, "resources", "lib"))

from urllib.parse import parse_qsl, urlencode  # noqa: E402

import xbmc  # noqa: E402
import xbmcgui  # noqa: E402
import xbmcplugin  # noqa: E402

import okru  # noqa: E402

from kodiutils import ADDON_ID, HANDLE, ajuste, notificar  # noqa: E402

# OJO, ESTE ERA UN BUG GORDO: estos dos bloques usaban ajuste() y estaban
# COLOCADOS ANTES del "from kodiutils import ... ajuste" de la linea de arriba.
# En Python eso da NameError, y como el try/except se lo comia en silencio,
# las cookies y la direccion del buscador NUNCA se cargaban: el addon tiraba
# siempre de la lista de direcciones por defecto.
try:
    if ajuste("usar_sesion", "true") == "true":
        okru.set_cookies(ajuste("cookies_okru", ""))
except Exception:
    import traceback
    xbmc.log("OK.ru: no pude leer las cookies: " + traceback.format_exc(), xbmc.LOGERROR)

# donde esta el buscador (127.0.0.1 en este equipo; la IP del principal en los demas)
try:
    _srv = ajuste("servicio_url", "")
    if _srv:
        okru.set_servicio(_srv)
except Exception:
    import traceback
    xbmc.log("OK.ru: no pude leer el buscador: " + traceback.format_exc(), xbmc.LOGERROR)

# El ajuste de calidad guarda el TEXTO de la opcion ("720p (HD)"). Aqui se traduce
# al nombre interno que usa la pagina de ok.ru. Se aceptan tambien los nombres
# internos y los valores viejos, para que un ajuste ya guardado siga valiendo.
CALIDADES_UI = {
    "144p (la más baja)": "lowest", "144p (la mas baja)": "lowest", "144p": "lowest",
    "240p": "low", "480p": "sd", "720p (HD)": "hd", "720p": "hd",
    "1080p (Full HD)": "full", "1080p": "full",
    "1440p (2K)": "quad", "1440p": "quad", "2160p (4K)": "ultra", "2160p": "ultra",
}


def _calidad_pref():
    """Calidad preferida, en el nombre interno que entiende ok.ru."""
    v = (ajuste("calidad_defecto", "hd") or "").strip()
    if v in CALIDADES_UI:
        return CALIDADES_UI[v]
    if v in ("lowest", "low", "sd", "hd", "full", "quad", "ultra"):
        return v
    return "hd"

BASE = "plugin://%s/" % ADDON_ID


def url_for(**kw):
    return BASE + "?" + urlencode(kw)


def _idioma_pref():
    v = ajuste("idioma_preferido", "Castellano")
    return v if v else "Castellano"


def menu_principal():
    xbmcplugin.setContent(HANDLE, "files")
    items = [
        ("Buscar", {"action": "buscar_menu"}, "DefaultAddonsSearch.png"),
        ("Novedades", {"action": "novedades"}, "DefaultRecentlyAddedMovies.png"),
        ("Por genero", {"action": "generos"}, "DefaultGenre.png"),
        ("Por año", {"action": "anios"}, "DefaultYear.png"),
        ("Por idioma", {"action": "idiomas"}, "DefaultLanguage.png"),
        ("Ajustes", {"action": "config"}, "DefaultAddonProgram.png"),
    ]
    n = 0
    for etiqueta, params, icono in items:
        li = xbmcgui.ListItem(label=etiqueta)
        li.setArt({"icon": icono})
        ok = xbmcplugin.addDirectoryItem(HANDLE, url_for(**params), li, isFolder=True)
        n += 1
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def generos():
    xbmcplugin.setContent(HANDLE, "files")
    for g in okru.GENEROS:
        li = xbmcgui.ListItem(label=g)
        li.setArt({"icon": "DefaultGenre.png"})
        xbmcplugin.addDirectoryItem(HANDLE, url_for(action="listar_genero", genero=g), li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def anios():
    import datetime
    xbmcplugin.setContent(HANDLE, "files")
    for a in range(datetime.date.today().year + 1, 1969, -1):
        li = xbmcgui.ListItem(label=str(a))
        li.setArt({"icon": "DefaultYear.png"})
        xbmcplugin.addDirectoryItem(HANDLE, url_for(action="listar_anio", anio=str(a)), li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def idiomas():
    xbmcplugin.setContent(HANDLE, "files")
    for i in ("Castellano", "Latino", "VOSE"):
        li = xbmcgui.ListItem(label=i)
        li.setArt({"icon": "DefaultLanguage.png"})
        xbmcplugin.addDirectoryItem(HANDLE, url_for(action="listar_idioma", idioma=i), li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


MAX_HISTORIAL = 12


def _ruta_historial():
    return "special://profile/addon_data/%s/historial_busquedas.json" % ADDON_ID


def _leer_historial():
    """Lista de busquedas guardadas, la mas reciente primero."""
    import json
    import xbmcvfs
    try:
        ruta = _ruta_historial()
        if not xbmcvfs.exists(ruta):
            return []
        with xbmcvfs.File(ruta) as f:
            datos = json.loads(f.read() or "[]")
        if isinstance(datos, list):
            return [str(x) for x in datos if str(x).strip()]
    except Exception:
        import traceback
        xbmc.log("OK.ru: no pude leer el historial: " + traceback.format_exc(), xbmc.LOGERROR)
    return []


def _guardar_historial(lista):
    import json
    import xbmcvfs
    try:
        xbmcvfs.mkdirs("special://profile/addon_data/%s/" % ADDON_ID)
        with xbmcvfs.File(_ruta_historial(), "w") as f:
            f.write(json.dumps(lista, ensure_ascii=False))
        return True
    except Exception:
        import traceback
        xbmc.log("OK.ru: no pude guardar el historial: " + traceback.format_exc(), xbmc.LOGERROR)
    return False


def _anadir_busqueda(termino):
    """Guarda el termino arriba del todo, sin duplicados y con tope."""
    t = (termino or "").strip()
    if not t:
        return
    lista = [x for x in _leer_historial() if x.lower() != t.lower()]
    lista.insert(0, t)
    _guardar_historial(lista[:MAX_HISTORIAL])


def buscar_menu():
    """Lista de busquedas: escribir una nueva o repetir una guardada."""
    xbmcplugin.setContent(HANDLE, "files")
    historial = _leer_historial()

    li = xbmcgui.ListItem(label="Escribir una búsqueda nueva")
    li.setArt({"icon": "DefaultAddonsSearch.png"})
    xbmcplugin.addDirectoryItem(HANDLE, url_for(action="buscar"), li, isFolder=True)

    for t in historial:
        li = xbmcgui.ListItem(label=t)
        li.setArt({"icon": "DefaultAddonsSearch.png"})
        li.addContextMenuItems([("Borrar esta búsqueda", "RunPlugin(%s)" % url_for(
            action="borrar_busqueda", q=t))])
        xbmcplugin.addDirectoryItem(HANDLE, url_for(action="repetir_busqueda", q=t), li, isFolder=True)

    if historial:
        li = xbmcgui.ListItem(label="Borrar todo el historial")
        li.setArt({"icon": "DefaultAddonProgram.png"})
        xbmcplugin.addDirectoryItem(HANDLE, url_for(action="borrar_historial"), li, isFolder=True)

    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def borrar_busqueda(termino):
    lista = [x for x in _leer_historial() if x.lower() != (termino or "").strip().lower()]
    _guardar_historial(lista)
    xbmc.executebuiltin("Container.Refresh")


def borrar_historial():
    _guardar_historial([])
    xbmc.executebuiltin("Container.Refresh")


def buscar(termino=None):
    teclado = (termino or "").strip()
    if not teclado:
        teclado = xbmcgui.Dialog().input("Buscar en OK.ru", type=xbmcgui.INPUT_ALPHANUM)
        if not teclado:
            return
    teclado = teclado.strip()
    _anadir_busqueda(teclado)
    # Antes esto llamaba a okru.buscar(), que son SOLO los buscadores externos:
    # y esos se limitan por IP, asi que la busqueda manual era la que mas fallaba.
    # Ahora va por el mismo camino que las secciones: primero el buscador con tu
    # sesion y, si no esta, los buscadores externos de respaldo.
    _con_progreso(lambda lim: okru.buscar_inteligente(teclado, lim), teclado)


def _con_progreso(fn, titulo_listado=""):
    limite = int(ajuste("resultados", "30") or 30)
    prog = xbmcgui.DialogProgressBG()
    prog.create("OK.ru", "Buscando en OK.ru...")
    try:
        resultados = fn(limite)
    except okru.BuscadorLimitado as e:
        # se guarda el motivo en el registro: "sin resultados" a secas no permite
        # saber si el buscador no responde, si la sesion ha caducado o si de verdad
        # no hay nada.
        xbmc.log("OK.ru: no he podido buscar: %s" % e, xbmc.LOGERROR)
        notificar("OK.ru", "No he podido buscar. %s" % str(e)[:70])
        return
    except Exception:
        import traceback
        xbmc.log("OK.ru: error buscando: " + traceback.format_exc(), xbmc.LOGERROR)
        notificar("OK.ru", "Error buscando. Mira el registro de Kodi")
        return
    finally:
        prog.close()
    if not resultados:
        xbmc.log("OK.ru: la busqueda no devolvio nada", xbmc.LOGERROR)
        notificar("OK.ru", "OK.ru no ha encontrado esa busqueda")
        return
    # El idioma preferido es una PRIORIDAD, no un filtro: ok.ru rotula los
    # titulos de forma desigual (muchos en ruso o ingles sin etiqueta), y
    # descartar el resto dejaba la lista casi vacia.
    pref = _idioma_pref()
    if pref and pref != "Cualquiera":
        con_preferido = [r for r in resultados if r["idioma"] == pref]
        otros = [r for r in resultados if r["idioma"] != pref]
        resultados = con_preferido + otros
    listar(resultados)


def listar(resultados):
    xbmcplugin.setContent(HANDLE, "videos")
    caratulas = ajuste("mostrar_caratulas", "true") == "true"
    n_carat = 0
    for r in resultados:
        etiqueta = r["titulo"]
        if r.get("idioma"):
            etiqueta = "[COLOR limegreen][%s][/COLOR] %s" % (r["idioma"], etiqueta)
        if r.get("anio"):
            etiqueta = "%s [COLOR gray](%s)[/COLOR]" % (etiqueta, r["anio"])
        li = xbmcgui.ListItem(label=etiqueta)
        art = {"icon": "DefaultVideo.png"}
        if caratulas and n_carat < 12:
            img = r.get("imagen") or okru.caratula(r["url"])
            n_carat += 1
            if img:
                art = {"thumb": img, "poster": img, "icon": "DefaultVideo.png"}
        li.setArt(art)
        li.setInfo("video", {"title": r["titulo"], "plot": r.get("sinopsis", ""),
                             "genre": r.get("idioma", ""), "year": r.get("anio") or 0})
        li.setProperty("IsPlayable", "true")
        # menú contextual (botón derecho, o tecla C en el mando): Descargar
        li.addContextMenuItems([
            ("Descargar este vídeo", "RunPlugin(%s)" % url_for(
                action="descargar", url=r["url"], titulo=r["titulo"])),
            ("Cancelar las descargas", "RunPlugin(%s)" % url_for(action="cancelar_descargas")),
        ])
        xbmcplugin.addDirectoryItem(HANDLE, url_for(action="play", url=r["url"], titulo=r["titulo"]),
                                    li, isFolder=False)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def reproducir(url, titulo):
    calidades, hls, info = okru.metadatos(url)
    if not calidades and not hls:
        notificar("OK.ru", "No se han podido obtener los enlaces del video")
        return
    modo = ajuste("modo_reproduccion", "2")
    # el ajuste es una lista: 0 preguntar, 1 HLS, 2 MP4, 3 solo MP4.
    # (los ajustes viejos guardaban el texto "hls"/"preguntar": se respetan)
    if modo in ("1", "hls"):
        modo = "hls"
    elif modo == "2":
        modo = "mp4"
    elif modo == "3":
        modo = "solo_mp4"
    else:
        modo = "preguntar"
    elegido, es_hls = None, False
    pref = _calidad_pref()          # calidad preferida, ya traducida al nombre interno
    if modo == "hls" and hls:
        elegido, es_hls = hls, True
    if elegido is None and modo == "preguntar":
        opciones, valores = [], []
        if hls:
            opciones.append("HLS (calidad automatica)")
            valores.append(("hls", hls))
        for c in calidades:
            opciones.append("%s [%s]" % (c["etiqueta"], c["nombre"]))
            valores.append(("mp4", c["url"]))
        if not opciones:
            notificar("OK.ru", "No se han podido obtener los enlaces del video")
            return
        pref = _calidad_pref()
        indice = 0
        for n, (tipo, v) in enumerate(valores):
            if tipo == "mp4" and pref in opciones[n]:
                indice = n
                break
        sel = xbmcgui.Dialog().select("Elige calidad", opciones, preselect=indice)
        if sel < 0:
            return
        tipo, elegido = valores[sel]
        es_hls = (tipo == "hls")
    elif elegido is None:
        for c in calidades:
            if c["nombre"] == pref:
                elegido = c["url"]
                break
        if elegido is None and calidades:
            elegido = calidades[0]["url"]
    if not elegido:
        notificar("OK.ru", "No se han podido obtener los enlaces del video")
        return
    li = xbmcgui.ListItem(label=titulo or info.get("titulo") or "OK.ru", path=elegido)

    # el enlace de ok.ru va firmado: hay que mandarle las cookies y el referer
    cookies = okru.cookies_del_servicio()
    cabeceras = "Referer=https://ok.ru/&User-Agent=%s" % okru.UA
    if cookies:
        cabeceras += "&Cookie=%s" % cookies

    if es_hls:
        # HLS: calidad automatica, pero el reproductor adaptativo tarda en soltar
        # el hilo al cancelar (Kodi se queda en "waiting for threads to exit").
        li.setInfo("video", {"title": titulo or info.get("titulo", "")})
        li.setProperty("inputstream", "inputstream.adaptive")
        li.setProperty("inputstream.adaptive.stream_headers", cabeceras)
        li.setProperty("inputstream.adaptive.manifest_headers", cabeceras)
        li.setMimeType("application/vnd.apple.mpegurl")
    else:
        # mp4 directo: lo reproduce el reproductor normal de Kodi y al cancelar
        # cierra al instante. Necesita las cabeceras por el enlace firmado.
        li.setInfo("video", {"title": titulo or info.get("titulo", "")})
        li.setMimeType("video/mp4")
        # la barra vertical separa la direccion de sus cabeceras (formato de Kodi)
        li.setPath("%s|%s" % (elegido, cabeceras))
    li.setProperty("IsPlayable", "true")
    xbmcplugin.setResolvedUrl(HANDLE, True, li)


def _nombre_fichero(texto):
    """Nombre de fichero limpio a partir del titulo del video."""
    import re as _re
    t = _re.sub(r"\[/?COLOR[^\]]*\]", " ", texto or "")   # quitar el color del listado
    t = _re.sub(r"\[[^\]]{1,20}\]", " ", t)               # quitar [1080p], [4K], etc.
    t = _re.sub(r'[\\/:*?"<>|]+', " ", t)                 # caracteres que no valen
    t = _re.sub(r"\s+", " ", t).strip()
    return (t or "video ok.ru")[:120]


def _mb(n):
    try:
        return "%.1f MB" % (n / 1048576.0) if n else "?"
    except Exception:
        return "?"


def _ruta_datos():
    """Carpeta de datos del addon: ahi van el cerrojo y la marca de cancelar."""
    import xbmcvfs
    base = xbmcvfs.translatePath("special://profile/addon_data/%s/" % ADDON_ID)
    try:
        if not os.path.isdir(base):
            os.makedirs(base)
    except Exception:
        pass
    return base


def _limpiar_cancelar():
    try:
        p = os.path.join(_ruta_datos(), "cancelar")
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def _pedir_cancelar():
    try:
        with open(os.path.join(_ruta_datos(), "cancelar"), "w") as f:
            f.write("1")
    except Exception:
        pass


_ULT_CANCEL = [0.0, False]


def _esta_cancelado():
    """True si se ha pedido cancelar. Se mira como mucho una vez por segundo."""
    ahora = time.time()
    if ahora - _ULT_CANCEL[0] < 1.0:
        return _ULT_CANCEL[1]
    _ULT_CANCEL[0] = ahora
    _ULT_CANCEL[1] = os.path.exists(os.path.join(_ruta_datos(), "cancelar"))
    return _ULT_CANCEL[1]


def descargar(url, titulo):
    """Descarga un video a la carpeta que diga el ajuste.

    Se hace aqui y no con una descarga normal de Kodi porque los enlaces de
    ok.ru van firmados y exigen mandar Cookie + Referer.
    """
    try:
        calidades, hls, info = okru.metadatos(url)
    except Exception:
        import traceback
        xbmc.log("OK.ru: error leyendo la ficha para descargar: " + traceback.format_exc(),
                 xbmc.LOGERROR)
        notificar("OK.ru", "No he podido leer el vídeo")
        return
    # Solo el mp4 directo. El HLS son trocitos (m3u8) que habría que bajar
    # todos y unirlos: se puede, pero es otro trabajo.
    if not calidades:
        notificar("OK.ru", "Este vídeo no tiene enlace directo para descargar")
        return

    pref = _calidad_pref()
    opciones = ["%s [%s]" % (c["etiqueta"], c["nombre"]) for c in calidades]
    indice = 0
    for n, c in enumerate(calidades):
        if c["nombre"] == pref:
            indice = n
            break
    sel = xbmcgui.Dialog().select("Calidad para descargar", opciones, preselect=indice)
    if sel < 0:
        return
    elegido = calidades[sel]

    # Carpeta: la del ajuste. Si esta vacia se usa una por defecto SIN preguntar
    # nada (el que quiera otra la cambia en Ajustes > Descargas).
    import xbmcvfs
    carpeta = (ajuste("carpeta_descargas", "") or "").strip()
    if not carpeta:
        casa = os.path.expanduser("~")
        for candidata in ("Descargas", "Downloads", "Vídeos", "Videos"):
            posible = os.path.join(casa, candidata)
            if os.path.isdir(posible):
                carpeta = posible
                break
        if not carpeta:
            carpeta = xbmcvfs.translatePath(
                "special://profile/addon_data/%s/descargas" % ADDON_ID)
    carpeta = xbmcvfs.translatePath(carpeta)
    if not os.path.isdir(carpeta):
        try:
            os.makedirs(carpeta)
        except Exception:
            notificar("OK.ru", "No puedo escribir en la carpeta de descargas")
            return

    nombre = _nombre_fichero(titulo or info.get("titulo") or "video ok.ru") + ".mp4"
    destino = os.path.join(carpeta, nombre)
    # Se lanza en un hilo aparte: el addon termina al momento y Kodi sigue
    # usable (puedes seguir navegando o poner una pelicula mientras baja).
    _limpiar_cancelar()
    hilo = threading.Thread(target=_hilo_descarga, args=(elegido["url"], destino, nombre))
    hilo.daemon = True
    hilo.start()
    notificar("OK.ru", "Descargando en segundo plano: %s" % nombre[:40])


def _hilo_descarga(url_video, destino, nombre):
    """Baja el video en un hilo aparte, con barra de FONDO (no bloquea Kodi)."""
    datos = _ruta_datos()
    cerrojo = None
    barra = None
    ok = False
    try:
        # de una en una: si ya hay una descarga en marcha, esta espera su turno
        cerrojo = open(os.path.join(datos, "descarga.lock"), "w")
        try:
            import fcntl
            try:
                fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except Exception:
                notificar("OK.ru", "En cola: %s" % nombre[:40])
                fcntl.flock(cerrojo, fcntl.LOCK_EX)   # espera a que acabe la otra
        except ImportError:
            pass

        barra = xbmcgui.DialogProgressBG()
        barra.create("OK.ru", nombre)
        ultimo = [0.0]

        def _prog(leidos, total):
            ahora = time.time()
            if ahora - ultimo[0] < 1.0:          # una actualizacion por segundo basta
                return
            ultimo[0] = ahora
            pct = int(leidos * 100 / total) if total else 0
            txt = ("%s / %s" % (_mb(leidos), _mb(total))) if total else _mb(leidos)
            try:
                barra.update(pct, message="%s  %s" % (nombre[:42], txt))
            except Exception:
                pass

        ok = okru.descargar_video(url_video, destino, progreso=_prog,
                                  cancelado=_esta_cancelado)
    except Exception:
        import traceback
        xbmc.log("OK.ru: error descargando en segundo plano: " + traceback.format_exc(),
                 xbmc.LOGERROR)
        ok = False
    finally:
        if barra is not None:
            try:
                barra.close()
            except Exception:
                pass
        if cerrojo is not None:
            try:
                cerrojo.close()                  # al cerrar se suelta el cerrojo
            except Exception:
                pass

    if ok:
        xbmc.log("OK.ru: descargado %s" % destino, xbmc.LOGINFO)
        notificar("OK.ru", "Descargado: %s" % nombre[:45])
    else:
        try:
            if os.path.exists(destino):
                os.remove(destino)               # no dejar medio fichero suelto
        except Exception:
            pass
        cancelado = os.path.exists(os.path.join(datos, "cancelar"))
        notificar("OK.ru", "Descarga cancelada" if cancelado else "Error al descargar")
    _limpiar_cancelar()


def cancelar_descargas():
    """Pide parar la descarga en curso (la barra de fondo no tiene boton)."""
    datos = _ruta_datos()
    en_curso = True
    try:
        import fcntl
        with open(os.path.join(datos, "descarga.lock"), "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                en_curso = False                 # el cerrojo estaba libre
            except Exception:
                en_curso = True
    except Exception:
        pass
    if not en_curso:
        notificar("OK.ru", "No hay ninguna descarga en curso")
        return
    _pedir_cancelar()
    notificar("OK.ru", "Cancelando la descarga...")


def router(params):
    a = params.get("action")
    if a == "buscar":
        buscar()
    elif a == "buscar_menu":
        buscar_menu()
    elif a == "repetir_busqueda":
        buscar(params.get("q", ""))
    elif a == "borrar_busqueda":
        borrar_busqueda(params.get("q", ""))
    elif a == "borrar_historial":
        borrar_historial()
    elif a == "novedades":
        _con_progreso(lambda lim: okru.novedades(lim, _idioma_pref()))
    elif a == "generos":
        generos()
    elif a == "listar_genero":
        _con_progreso(lambda lim: okru.por_genero(params.get("genero", ""), lim, _idioma_pref()))
    elif a == "anios":
        anios()
    elif a == "listar_anio":
        _con_progreso(lambda lim: okru.por_anio(params.get("anio", ""), lim, _idioma_pref()))
    elif a == "idiomas":
        idiomas()
    elif a == "listar_idioma":
        _con_progreso(lambda lim: okru.por_idioma(params.get("idioma", "Castellano"), lim))
    elif a == "config":
        import xbmcaddon
        xbmcaddon.Addon().openSettings()
    elif a == "play":
        reproducir(params.get("url", ""), params.get("titulo", ""))
    elif a == "descargar":
        descargar(params.get("url", ""), params.get("titulo", ""))
    elif a == "cancelar_descargas":
        cancelar_descargas()
    else:
        menu_principal()


if __name__ == "__main__":
    try:
        router(dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {})
    except Exception:
        import traceback
        xbmc.log("OK.ru: error: " + traceback.format_exc(), xbmc.LOGERROR)
