#!/bin/bash
# Instala en el Chuwi el buscador de ok.ru para Kodi:
#  - el script en ~/.local/bin
#  - un servicio de usuario que lo arranca solo y lo mantiene vivo
#  - el Chrome del add-on (perfil propio, con sesion de ok.ru) lo levanta el propio servicio
set -e

# Ajusta esto a tu usuario si hace falta: se instala como servicio DE USUARIO
DEST="$HOME/.local/bin"
mkdir -p "$DEST"
cp /tmp/okru_buscar_service.py "$DEST/okru_buscar_service.py"
chmod 755 "$DEST/okru_buscar_service.py"

mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/okru-buscador.service <<'UNIT'
[Unit]
Description=Buscador de ok.ru para Kodi (usa el navegador con tu sesion)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/.local/bin/okru_buscar_service.py
Restart=always
RestartSec=5
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus

[Install]
WantedBy=default.target
UNIT

# el Chrome del add-on tambien como servicio, para que sobreviva a cierres
cat > ~/.config/systemd/user/okru-navegador.service <<'UNIT'
[Unit]
Description=Navegador de ok.ru para el add-on de Kodi (sesion propia)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/google-chrome --user-data-dir=%h/.config/chrome-okru-kodi --remote-debugging-port=9222 --no-first-run --no-default-browser-check --bwsi --disable-sync https://ok.ru/
Restart=always
RestartSec=10
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus

[Install]
WantedBy=default.target
UNIT

export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
systemctl --user daemon-reload
systemctl --user enable --now okru-navegador.service
sleep 12
systemctl --user enable --now okru-buscador.service
sleep 5

echo "--- navegador:"; systemctl --user is-active okru-navegador.service
echo "--- buscador:"; systemctl --user is-active okru-buscador.service
echo "--- estado:"; curl -s -m 10 http://127.0.0.1:9223/estado; echo
