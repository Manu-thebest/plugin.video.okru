# OK.ru para Kodi

Add-on de Kodi para **buscar y reproducir videos de ok.ru**, eligiendo **calidad** e **idioma**.
Pensado para verlo comodo en la tele, con la mecanica de los add-ons clasicos (buscar > listar > reproducir).

---

## Que trae

Al abrirlo, un menu:

- **Buscar** — escribes lo que quieras y te lista los videos (el idioma sale marcado en verde)
- **Novedades** — lo mas reciente, ordenado por anio
- **Por genero** — 14 generos
- **Por anio** — de 2027 hacia atras
- **Por idioma** — Castellano / Latino / VOSE
- **Ajustes**

En cada video: **calidad** (144p a 2160p, segun el video) o **HLS** (Kodi ajusta la calidad solo), con
titulo, anio, duracion y, cuando el video lo trae, caratula.

---

## El detalle que hay que entender: ok.ru pide sesion

Esto no es un capricho del add-on, es como funciona ok.ru:

1. **Buscar en ok.ru requiere estar identificado.** Su buscador, sin sesion, devuelve una pagina en
   blanco. No hay truco que lo evite (probado con navegador anti-deteccion, con y sin cabeceras).
2. **Los enlaces de video van firmados.** Sin la sesion, al reproducir dan error
   (`could not open file`). Con la sesion, responden bien.

Asi que el add-on necesita una sesion de ok.ru. Hay **dos formas** de darsela.

### Forma buena: la sesion en los ajustes (recomendada)

En los **Ajustes** del add-on hay un campo **"Sesion de ok.ru (cookies)"**: pega ahi la cabecera `Cookie:`
de tu navegador (F12 > Network > la primera peticion > Request Headers). La `AUTHCODE` de ok.ru dura
alrededor de un anio, asi que merece la pena.

Con eso el add-on busca **directamente en el buscador de la web de ok.ru** — el mismo que usa la propia
pagina al pulsar la pestaña "Video" — pidiendo los resultados **de 20 en 20**: 60 entradas en 3-4 segundos,
con caratula y sinopsis. No hace falta navegador ni ningun otro equipo encendido: solo la cookie.

> El add-on **no guarda tus cookies en el codigo**: solo las lee de sus ajustes. No se suben a ningun sitio.

### Opcional: el buscador local (carpeta `servicio/`)

Si no quieres copiar la cookie a mano, un pequenio servicio hace las busquedas **dentro de un navegador
ya identificado** y el add-on le pregunta. Sirve de reserva: solo se usa si el buscador directo falla.

Esta en la carpeta **`servicio/`**:

- `servicio/okru_buscar_service.py` — el servicio (escucha en `127.0.0.1:9223`; con `0.0.0.0` atiende a la red local)
- `servicio/instalar_servicio.sh` — lo instala como servicio de usuario, con su navegador propio

Pasos:

1. Instalar el servicio (en el equipo principal, normalmente el mas potente).
2. La primera vez, iniciar sesion en ok.ru **en la ventana del navegador que abre el servicio**
   (la contrasenia se escribe ahi, no se guarda en ningun sitio del add-on).
3. En Kodi, en los **Ajustes** del add-on, dejar **"Buscador"** con la direccion del servicio:
   - En el equipo principal: `http://127.0.0.1:9223`
   - En los demas equipos: `http://IP-DEL-PRINCIPAL:9223`

**Endpoints del servicio** (por si lo quieres probar a mano):

```
GET /estado              -> {"ok":true,"navegador":true,"sesion":true,"cache":N}
GET /buscar?q=texto&n=30 -> {"ok":true,"resultados":[{"id","url","titulo","idioma"}]}
GET /cookies             -> {"ok":true,"cookies":"..."}   (para que el add-on pueda reproducir)
```

### De reserva: buscadores externos

Si no hay servicio ni cookies, el add-on tira de buscadores (`DuckDuckGo` > `lite` > `Mojeek` > `Bing`)
con `site:ok.ru/video`. Funciona, pero **limitan por IP** cuando se abusa, y entonces sale "sin resultados"
durante un rato. Es el ultimo recurso, no el plan.

---

## Instalacion

1. Descarga el ZIP de la ultima *release*.
2. En Kodi: **Ajustes > Add-ons > Instalar desde archivo zip** (o copia la carpeta
   `plugin.video.okru` dentro de `addons/`).
3. **Activalo**: los add-ons recien instalados nacen desactivados.
4. Lo tienes en **Add-ons > Add-ons de video > OK.ru**.

Necesita `inputstream.adaptive` (Kodi lo trae de serie) para el HLS y para mandar las cabeceras al
reproducir.

---

## Ajustes

- **Modo de reproduccion** — preguntar cada vez / HLS (calidad automatica) / elegir fichero
- **Calidad por defecto** — 144p a 2160p
- **Idioma preferido** — Castellano / Latino / VOSE / Cualquiera
- **Numero de resultados** — 10 a 100
- **Mostrar caratulas** — si va lento, se desactiva
- **Buscador** — direccion del servicio local (arriba)
- **Usar mi sesion de ok.ru** — activado por defecto
- **Sesion de ok.ru (cookies)** — campo para pegarlas a mano (opcional)

---

## Como va por dentro (por si hay que tocarlo)

- `default.py` — el menu, el listado y la reproduccion.
- `resources/lib/okru.py` — todo lo demas: buscar (servicio > cookies > buscadores), sacar los metadatos
  de una pagina de video (calidades, HLS, caratula, duracion), detectar idioma y ordenar por anio.
- La pagina de un video de ok.ru trae el JSON **con las entidades escapadas** (`&quot;` en vez de `"`),
  hay que desescaparlo antes de buscar nada.
- **La busqueda buena es** `https://ok.ru/dk?st.cmd=searchResult&st.query=<texto>&st.mode=Video`.
  Las que se ven por ahi (`/video/search?st.query=`) **estan muertas**: devuelven vacio aunque tengas sesion.
- El add-on busca por **servicio local > cookies > buscadores**, en ese orden, y el servicio tiene
  **cache de 24 h**, asi que repetir una busqueda es instantaneo.
- Los textos van **en claro** (sin ficheros de idioma): en algunos Kodi esos ficheros no cargan y todo
  saldria en blanco.
- El servicio trae una lista de direcciones por defecto (`127.0.0.1` y la del equipo principal de esta
  casa); si tu red es distinta, cambia esas direcciones en `okru.py` o ponlas en el ajuste **Buscador**.

---

## Limites conocidos

- La caratula no sale en todos los videos (depende de lo que traiga la pagina).
- La eleccion de calidad solo aparece en los videos que traen varias; en otros hay una sola.
- Las busquedas tardan unos segundos la primera vez (se navega de verdad); repetidas son instantaneas.
- Sin sesion, la busqueda no puede funcionar. No hay forma de evitarlo.

---

## Aviso

Add-on personal. Los videos son de ok.ru; esto solo los busca y los reproduce.
