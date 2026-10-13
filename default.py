# -*- coding: utf-8 -*-
import os
import sys

import xbmcaddon
_ADDON_PATH = xbmcaddon.Addon().getAddonInfo("path")
if _ADDON_PATH and _ADDON_PATH not in sys.path:
    sys.path.insert(0, os.path.join(_ADDON_PATH, "resources", "lib"))

from urllib.parse import parse_qsl, urlencode  # noqa: E402

import xbmc  # noqa: E402
import xbmcgui  # noqa: E402
import xbmcplugin  # noqa: E402

import okru  # noqa: E402

# sesion de ok.ru: si el usuario la ha pegado en los ajustes, la usamos
try:
    if ajuste("usar_sesion", "true") == "true":
        okru.set_cookies(ajuste("cookies_okru", ""))
except Exception:
    pass

# donde esta el buscador (127.0.0.1 en este equipo; la IP del principal en los demas)
try:
    _srv = ajuste("servicio_url", "")
    if _srv:
        okru.set_servicio(_srv)
except Exception:
    pass
from kodiutils import ADDON_ID, HANDLE, ajuste, notificar  # noqa: E402

BASE = "plugin://%s/" % ADDON_ID


def url_for(**kw):
    return BASE + "?" + urlencode(kw)


def _idioma_pref():
    v = ajuste("idioma_preferido", "Castellano")
    return v if v else "Castellano"


def menu_principal():
    xbmcplugin.setContent(HANDLE, "files")
    items = [
        ("Buscar", {"action": "buscar"}, "DefaultAddonsSearch.png"),
        ("Novedades", {"action": "novedades"}, "DefaultRecentlyAddedMovies.png"),
        ("Por genero", {"action": "generos"}, "DefaultGenre.png"),
        ("Por anio", {"action": "anios"}, "DefaultYear.png"),
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


def buscar():
    teclado = xbmcgui.Dialog().input("Buscar en OK.ru", type=xbmcgui.INPUT_ALPHANUM)
    if not teclado:
        return
    _con_progreso(lambda lim: okru.buscar(teclado, lim), teclado)


def _con_progreso(fn, titulo_listado=""):
    limite = int(ajuste("resultados", "30") or 30)
    prog = xbmcgui.DialogProgressBG()
    prog.create("OK.ru", "Buscando en OK.ru...")
    try:
        resultados = fn(limite)
    except okru.BuscadorLimitado:
        notificar("OK.ru", "El buscador nos ha limitado. Espera un minuto y reintenta")
        return
    finally:
        prog.close()
    if not resultados:
        notificar("OK.ru", "Sin resultados")
        return
    pref = _idioma_pref()
    if pref and pref != "Cualquiera":
        con = [r for r in resultados if r["idioma"] == pref]
        if con:
            resultados = con
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
        xbmcplugin.addDirectoryItem(HANDLE, url_for(action="play", url=r["url"], titulo=r["titulo"]),
                                    li, isFolder=False)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def reproducir(url, titulo):
    calidades, hls, info = okru.metadatos(url)
    if not calidades and not hls:
        notificar("OK.ru", "No se han podido obtener los enlaces del video")
        return
    modo = ajuste("modo_reproduccion", "0")
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
        pref = ajuste("calidad_defecto", "hd")
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
            if c["nombre"] == ajuste("calidad_defecto", "hd"):
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


def router(params):
    a = params.get("action")
    if a == "buscar":
        buscar()
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
    else:
        menu_principal()


if __name__ == "__main__":
    try:
        router(dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {})
    except Exception:
        import traceback
        xbmc.log("OK.ru: error: " + traceback.format_exc(), xbmc.LOGERROR)
