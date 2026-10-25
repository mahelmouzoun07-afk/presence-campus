"""Petites fonctions partagées : lecture des réglages et adresse publique."""
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


def client_ip():
    """IP réelle du visiteur. Derrière un proxy (nginx, Cloudflare, tunnel...),
    remote_addr donne l'IP du proxy : on lit donc X-Forwarded-For en priorité,
    en ne gardant que le PREMIER maillon (le plus proche du visiteur)."""
    try:
        if request and request.httprequest:
            xff = request.httprequest.headers.get('X-Forwarded-For')
            if xff:
                return xff.split(',')[0].strip()
            return request.httprequest.remote_addr
    except Exception:
        pass
    return False
