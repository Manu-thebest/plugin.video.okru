# -*- coding: utf-8 -*-
import sys
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1


def L(sid):
    return ADDON.getLocalizedString(sid)


def ajuste(k, defecto=""):
    v = ADDON.getSetting(k)
    return v if v not in (None, "") else defecto


def notificar(titulo, mensaje):
    xbmcgui.Dialog().notification(titulo, mensaje, xbmcgui.NOTIFICATION_INFO, 3000)
