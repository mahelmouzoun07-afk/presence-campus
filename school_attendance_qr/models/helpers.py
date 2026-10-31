"""Petites fonctions partagées : lecture des réglages et adresse publique."""
from zoneinfo import ZoneInfo

from odoo.http import request


def icp(env, key, default=''):
    """Lit un réglage du module (Paramètres > École)."""
    return env['ir.config_parameter'].sudo().get_param('school_attendance_qr.' + key, default)


def icp_bool(env, key):
    return icp(env, key, '') == 'True'


def icp_int(env, key, default):
    try:
        return int(icp(env, key, default))
    except (TypeError, ValueError):
        return default


def get_base_url(env):
    """Adresse publique à mettre dans les liens des QR : celle utilisée par la
    personne connectée (donc le domaine ou le tunnel en cours), sinon l'adresse
    système web.base.url."""
    try:
        if request and request.httprequest:
            url = request.httprequest.host_url.rstrip('/')
            if request.httprequest.headers.get('X-Forwarded-Proto') == 'https' and url.startswith('http://'):
                url = 'https://' + url[len('http://'):]
            return url
    except Exception:
        pass
    return (env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')


def gps_float(value):
    """Coordonnée reçue du téléphone. None (ou vide) veut dire « hors zone » :
    le téléphone a vérifié lui-même qu'il n'était dans aucune zone prévue et
    n'a pas transmis sa position (voir confirm.js, minimizePosition)."""
    if value is None or value is False or value == '':
        return None
    return float(value)


def zone_of(place):
    """Zone envoyée au téléphone (salle ou site de stage) pour qu'il vérifie
    lui-même s'il y est avant de transmettre sa position."""
    return {'lat': place.latitude, 'lng': place.longitude, 'radius': place.radius_meters}


def client_ip():
    """IP réelle du visiteur. Odoo lancé avec --proxy-mode corrige déjà
    remote_addr d'après X-Forwarded-For en ne gardant que le DERNIER maillon,
    celui ajouté par notre propre proxy (Cloudflare, Tailscale, nginx). Le
    premier maillon, lui, peut être écrit par le téléphone : ne jamais le lire."""
    try:
        if request and request.httprequest:
            return request.httprequest.remote_addr
    except Exception:
        pass
    return False


def local_time(env, dt, fmt='%Hh%M'):
    """Odoo enregistre les heures en UTC : on les affiche à l'heure de l'école
    (Africa/Porto-Novo par défaut, réglable dans Paramètres > École)."""
    if not dt:
        return ''
    try:
        tz = ZoneInfo(icp(env, 'timezone', 'Africa/Porto-Novo'))
    except Exception:
        tz = ZoneInfo('Africa/Porto-Novo')
    return dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(tz).strftime(fmt)
