#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Buscador de ok.ru para Kodi, usando la sesion del navegador del usuario.

Corre en el propio equipo (Chuwi/RPi) y escucha en 127.0.0.1:9223.
El add-on de Kodi le pide las busquedas por HTTP y este servicio las hace
dentro del navegador, que ya tiene la sesion de ok.ru iniciada.

Endpoints:
  GET /estado              -> {"ok":true,"sesion":true|false}
  GET /buscar?q=texto&n=30 -> {"ok":true,"resultados":[{"id","url","titulo","idioma"}]}
"""
import base64
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CDP = "http://127.0.0.1:9222"
PUERTO = 9223
PAUSA_CARGA = 9.0
CACHE_TTL = 24 * 3600   # 24 h: lo que se repite no se vuelve a buscar en todo el dia
_CACHE = {}             # (consulta, limite) -> (momento, resultados)
_TAB = {"id": None}     # pestana reutilizada para las busquedas


def _cache_get(consulta, limite):
    clave = (consulta.strip().lower(), limite)
    dato = _CACHE.get(clave)
    if not dato:
        return None
    momento, resultados = dato
    if time.time() - momento > CACHE_TTL:
        _CACHE.pop(clave, None)
        return None
    return resultados


def _cache_set(consulta, limite, resultados):
    _CACHE[(consulta.strip().lower(), limite)] = (time.time(), resultados)
    if len(_CACHE) > 500:                       # no crecer sin freno (se tiran las mas viejas)
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:100]:
            _CACHE.pop(k, None)


# ------------------------------------------------------------------ CDP por websocket
class Cdp:
    def __init__(self, ws_url):
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)", ws_url)
        self.s = socket.create_connection((m.group(1), int(m.group(2))), timeout=30)
        clave = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(
            ("GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
             % (m.group(3), m.group(1), m.group(2), clave)).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError("no se pudo abrir el websocket de control")
        self._id = 0

    def _enviar(self, texto):
        datos = texto.encode()
        cab = bytearray([0x81])
        n = len(datos)
        if n < 126:
            cab.append(0x80 | n)
        elif n < 65536:
            cab.append(0x80 | 126)
            cab += struct.pack(">H", n)
        else:
            cab.append(0x80 | 127)
            cab += struct.pack(">Q", n)
        mascara = os.urandom(4)
        cab += mascara
        self.s.sendall(bytes(cab) + bytes(b ^ mascara[i % 4] for i, b in enumerate(datos)))

    def _recibir(self):
        while True:
            b1, b2 = self._exacto(2)
            opcode = b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exacto(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exacto(8))[0]
            datos = self._exacto(n)
            if opcode == 0x8:
                raise RuntimeError("el navegador cerro la conexion")
            if opcode in (0x1, 0x2):
                return datos.decode("utf-8", "replace")

    def _exacto(self, n):
        buf = b""
        while len(buf) < n:
            t = self.s.recv(n - len(buf))
            if not t:
                raise RuntimeError("conexion cerrada")
            buf += t
        return buf

    def llamar(self, metodo, params=None):
        self._id += 1
        self._enviar(json.dumps({"id": self._id, "method": metodo, "params": params or {}}))
        while True:
            msg = json.loads(self._recibir())
            if msg.get("id") == self._id:
                return msg

    def cerrar(self):
        try:
            self.s.close()
        except Exception:
            pass


def _version():
    with urllib.request.urlopen(CDP + "/json/version", timeout=10) as r:
        return json.load(r)


def _pestanas():
    with urllib.request.urlopen(CDP + "/json/list", timeout=10) as r:
        return json.load(r)


def _navegador_vivo():
    try:
        _version()
        return True
    except Exception:
        return False


def arrancar_navegador(perfil=None, puerto_cdp=9222):
    """Levanta el navegador del add-on si no esta en marcha."""
    if perfil is None:
        perfil = os.path.expanduser("~/.config/chrome-okru-kodi")
    """Levanta el navegador del add-on si no esta en marcha (X11 necesario)."""
    import subprocess
    subprocess.Popen([
        "google-chrome",
        "--user-data-dir=" + perfil,
        "--remote-debugging-port=%d" % puerto_cdp,
        "--no-first-run", "--no-default-browser-check", "--bwsi", "--disable-sync",
        "https://ok.ru/",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        time.sleep(2)
        if _navegador_vivo():
            return True
    return False


def abrir_pestana(url):
    """Abre una pestana nueva en el navegador del usuario."""
    peticion = urllib.request.Request(CDP + "/json/new?" + urllib.parse.quote(url, safe=""), method="PUT")
    with urllib.request.urlopen(peticion, timeout=15) as r:
        return json.load(r)["id"]


def cerrar_pestana(tab_id):
    try:
        urllib.request.urlopen(CDP + "/json/close/" + tab_id, timeout=8).read()
    except Exception:
        pass


JS_RESULTADOS = r"""
(() => {
  const fuera = [];
  const vistos = new Set();
  const limpia = (t) => (t || '').replace(/\s+/g, ' ').trim();
  for (const a of document.querySelectorAll('a[href*="/video/"]')) {
    const m = (a.getAttribute('href') || '').match(/\/video\/(\d+)/);
    if (!m) continue;
    const id = m[1];
    if (vistos.has(id)) continue;
    let texto = limpia(a.innerText || a.textContent || '');
    if (texto.length < 4) {
      const caja = a.closest('[class*="video"], [data-id], li, div');
      if (caja) texto = limpia(caja.innerText || '').slice(0, 160);
    }
    if (texto.length < 4) continue;
    vistos.add(id);
    fuera.push({ id: id, titulo: texto.slice(0, 160), url: 'https://ok.ru/video/' + id });
  }
  return JSON.stringify({
    titulo: document.title,
    url: location.href,
    logueado: !/anonymLogin|Sign in|Войти/i.test(document.documentElement.outerHTML.slice(0, 40000)),
    resultados: fuera
  });
})()
"""


def _tab_reutilizable():
    """Devuelve la pestana de busqueda, reutilizandola entre consultas."""
    if _TAB["id"]:
        for t in _pestanas():
            if t.get("id") == _TAB["id"]:
                return _TAB["id"], False
    _TAB["id"] = abrir_pestana("about:blank")
    return _TAB["id"], True


def buscar(q, limite=30):
    """Busca en ok.ru dentro del navegador con sesion (con cache y pestana reutilizada)."""
    guardado = _cache_get(q, limite)
    if guardado is not None:
        print("cache: '%s' servido de memoria" % q, flush=True)
        return guardado
    if not _navegador_vivo():
        if not arrancar_navegador():
            raise RuntimeError("no he podido arrancar el navegador del add-on")
    tab, nueva = _tab_reutilizable()
    url = "https://ok.ru/dk?st.cmd=searchResult&st.query=" + urllib.parse.quote(q) + "&st.mode=Video"
    try:
        if not nueva:
            info = [t for t in _pestanas() if t.get("id") == tab]
            if info:
                c = Cdp(info[0]["webSocketDebuggerUrl"])
                try:
                    c.llamar("Page.enable")
                    c.llamar("Page.navigate", {"url": url})
                finally:
                    c.cerrar()
        time.sleep(PAUSA_CARGA)
        for intento in range(5):
            with urllib.request.urlopen(CDP + "/json/list", timeout=10) as r:
                info = [t for t in json.load(r) if t.get("id") == tab]
            if not info:
                raise RuntimeError("la pestana se cerro")
            c = Cdp(info[0]["webSocketDebuggerUrl"])
            try:
                r = c.llamar("Runtime.evaluate", {"expression": JS_RESULTADOS, "returnByValue": True})
                valor = r.get("result", {}).get("result", {}).get("value")
                if valor:
                    datos = json.loads(valor)
                    if datos.get("resultados"):
                        res = datos["resultados"][:limite]
                        _cache_set(q, limite, res)
                        return res
                    if intento < 4:
                        time.sleep(4 + intento * 2)
                        continue
                    return []
            finally:
                c.cerrar()
        return []
    finally:
        if nueva:
            cerrar_pestana(tab)
            _TAB["id"] = None


def cookies_okru():
    """Le pide al navegador las cookies de ok.ru (el las tiene y las descifra el)."""
    tabs = [t for t in _pestanas() if t.get("type") == "page" and "ok.ru" in t.get("url", "")]
    if not tabs:
        raise RuntimeError("no hay pestaña de ok.ru abierta")
    c = Cdp(tabs[0]["webSocketDebuggerUrl"])
    try:
        r = c.llamar("Network.getCookies", {"urls": ["https://ok.ru/", "https://okcdn.ru/"]})
        galletas = r.get("result", {}).get("cookies", [])
        partes = ["%s=%s" % (g["name"], g["value"]) for g in sorted(galletas, key=lambda g: g["name"])]
        return "; ".join(partes)
    finally:
        c.cerrar()


# ------------------------------------------------------------------ idioma
def detectar_idioma(titulo):
    t = (titulo or "").lower()
    if "castellano" in t or "español" in t or "espanol" in t:
        return "Castellano"
    if "latino" in t or "latinoamerica" in t:
        return "Latino"
    if "vose" in t or "subtitulad" in t or "v.o.s" in t:
        return "VOSE"
    return ""


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _responder(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        partes = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(partes.query)
        if partes.path == "/estado":
            vivo = _navegador_vivo()
            sesion = False
            if vivo:
                try:
                    tabs = [t for t in _pestanas() if t.get("type") == "page" and "ok.ru" in t.get("url", "")]
                    sesion = bool(tabs)
                except Exception:
                    pass
            return self._responder({"ok": True, "navegador": vivo, "sesion": sesion,
                                    "cache": len(_CACHE)})
        if partes.path == "/cookies":
            try:
                ck = cookies_okru()
                return self._responder({"ok": True, "cookies": ck})
            except Exception as e:
                return self._responder({"ok": False, "error": str(e)[:150]})
        if partes.path == "/buscar":
            q = (params.get("q") or [""])[0].strip()
            n = int((params.get("n") or ["30"])[0])
            if not q:
                return self._responder({"ok": False, "error": "falta q"}, 400)
            try:
                res = buscar(q, n)
                for r in res:
                    r["idioma"] = detectar_idioma(r.get("titulo"))
                return self._responder({"ok": True, "resultados": res})
            except Exception as e:
                return self._responder({"ok": False, "error": str(e)[:200]}, 200)
        return self._responder({"ok": False, "error": "ruta desconocida"}, 404)


def main():
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else PUERTO
    srv = ThreadingHTTPServer(("0.0.0.0", puerto), Manejador)
    print("buscador de ok.ru escuchando en 127.0.0.1:%d" % puerto, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
