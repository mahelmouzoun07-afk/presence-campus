"""Application installable (PWA), hors ligne et notifications push."""
import base64
import io
import json

from odoo import http
from odoo.http import request
from odoo.tools import file_open

from ..models.attendance import _is_on_campus_network
from ..models.helpers import client_ip
from .portal import current_student, portal_gate

ICON_SIZES = (192, 512)


class SchoolPwaController(http.Controller):

    # ------------------------------------------------------------- manifest
    @http.route('/presence/manifest.webmanifest', type='http', auth='public', sitemap=False)
    def manifest(self):
        """Manifest propre à chaque école : son nom et son logo deviennent le
        nom et l'icône de l'application sur le téléphone."""
        company = request.env['res.company'].sudo().search([], limit=1)
        name = company.name or "Présence"
        data = {
            'name': name, 'short_name': name[:12], 'lang': 'fr',
            'description': "Présence, emploi du temps et vie scolaire",
            'start_url': '/presence', 'scope': '/presence', 'display': 'standalone',
            'orientation': 'portrait', 'background_color': '#F2F3F1', 'theme_color': '#14213D',
            'icons': [{'src': f'/presence/icone/{s}.png', 'sizes': f'{s}x{s}', 'type': 'image/png',
                       'purpose': 'any maskable'} for s in ICON_SIZES],
        }
        return request.make_response(json.dumps(data, ensure_ascii=False), headers=[
            ('Content-Type', 'application/manifest+json; charset=utf-8'), ('Cache-Control', 'public, max-age=3600')])

    @http.route('/presence/icone/<int:size>.png', type='http', auth='public', sitemap=False)
    def icon(self, size):
        from PIL import Image, ImageDraw, ImageFont
        size = size if size in ICON_SIZES + (180,) else 192
        company = request.env['res.company'].sudo().search([], limit=1)
        canvas = Image.new('RGB', (size, size), '#14213D')
        if company.school_logo:
            logo = Image.open(io.BytesIO(base64.b64decode(company.school_logo))).convert('RGBA')
            inner = int(size * 0.62)  # marge « maskable » : le logo reste entier même découpé en rond
            logo.thumbnail((inner, inner))
            plate = Image.new('RGB', (size, size), '#FFFFFF')
            plate.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
            canvas = plate
        else:
            letters = ''.join(w[0] for w in (company.name or 'P').split()[:2]).upper()
            draw = ImageDraw.Draw(canvas)
            try:
                font = ImageFont.truetype('DejaVuSans-Bold.ttf', int(size * 0.38))
            except OSError:
                font = ImageFont.load_default()
            box = draw.textbbox((0, 0), letters, font=font)
            draw.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
                      letters, fill='#FFFFFF', font=font)
        out = io.BytesIO()
        canvas.save(out, format='PNG')
        return request.make_response(out.getvalue(), headers=[
            ('Content-Type', 'image/png'), ('Cache-Control', 'public, max-age=86400')])

    @http.route('/presence/sw.js', type='http', auth='public', sitemap=False)
    def service_worker(self):
        with file_open('school_attendance_qr/static/src/js/sw.js', 'rb') as f:
            body = f.read()
        return request.make_response(body, headers=[
            ('Content-Type', 'application/javascript; charset=utf-8'),
            ('Service-Worker-Allowed', '/presence'), ('Cache-Control', 'no-cache')])

    @http.route('/presence/hors-ligne', type='http', auth='public', website=True, sitemap=False)
    def offline_page(self):
        return request.render('school_attendance_qr.portal_offline', {})

    @http.route('/presence/installer', type='http', auth='user', website=True)
    def install_guide(self):
        return request.render('school_attendance_qr.portal_install', {})

    # ------------------------------------------------- connexion et hors ligne
    @http.route('/presence/ping', type='http', auth='public', sitemap=False, csrf=False)
    def ping(self):
        """Le téléphone teste la connexion avant de basculer hors ligne :
        - pas de réponse du tout = vraie panne → hors ligne autorisé ;
        - réponse « pas sur le Wi-Fi de l'école » = refus normal, PAS une panne."""
        data = {'ok': True, 'campus': _is_on_campus_network(request.env, client_ip())}
        return request.make_response(json.dumps(data), headers=[
            ('Content-Type', 'application/json'), ('Cache-Control', 'no-store')])

    @http.route('/presence/hors-ligne/defis', type='json', auth='user')
    def offline_challenges(self):
        student = current_student()
        if not student or student.must_change_password:
            return {'challenges': []}
        if not student.webauthn_credential_id:
            return {'challenges': [], 'reason': 'Confirmez une première fois en ligne pour activer le hors ligne.'}
        challenges = request.env['school.offline.challenge'].top_up(student)
        return {
            'rp_id': request.httprequest.host.split(':')[0],
            'credential_id': student.webauthn_credential_id,
            'challenges': [{'id': c.id, 'challenge': c.challenge, 'expires_at': c.expires_at.isoformat() + 'Z'}
                           for c in challenges],
        }

    @http.route('/presence/hors-ligne/synchroniser', type='json', auth='user')
    def offline_sync(self, items):
        """Reçoit la file d'attente du téléphone. Chaque élément est vérifié et
        enregistré séparément : une confirmation refusée n'empêche pas les autres."""
        student = current_student()
        if not student:
            return {'error': "Aucun profil étudiant associé à ce compte."}
        Record = request.env['school.attendance.record'].sudo()
        results = []
        for item in (items or [])[:20]:
            try:
                with request.env.cr.savepoint():
                    res = Record.register_offline(student, item, request.httprequest)
                results.append(dict(res, key=item.get('key'), ok=True))
            except Exception as e:
                request.env['school.audit.log'].log('presence_refused', f"Hors ligne : {e}", student=student)
                results.append({'key': item.get('key'), 'ok': False, 'error': str(e)})
        return {'results': results}

    # ------------------------------------------------------------ notifications
    @http.route('/presence/push/cle', type='json', auth='user')
    def push_key(self):
        return {'key': request.env['school.push.subscription'].sudo().vapid_public_key()}

    @http.route('/presence/push/abonner', type='json', auth='user')
    def push_subscribe(self, subscription):
        request.env['school.push.subscription'].subscribe(
            request.env.user, subscription, request.httprequest.headers.get('User-Agent', ''))
        return {'ok': True}

    @http.route('/presence/push/desabonner', type='json', auth='user')
    def push_unsubscribe(self, endpoint):
        request.env['school.push.subscription'].sudo().search(
            [('endpoint', '=', endpoint), ('user_id', '=', request.env.uid)]).unlink()
        return {'ok': True}

    @http.route('/presence/notifications', type='http', auth='user', website=True)
    def notifications(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        Notif = request.env['school.notification'].sudo()
        notes = Notif.search([('user_id', '=', request.env.uid)], limit=50)
        page = request.render('school_attendance_qr.portal_notifications', {
            'student': student, 'notes': notes, 'unread_ids': set(notes.filtered(lambda n: not n.is_read).ids),
            'user': request.env.user, 'active_nav': 'notifications'})
        notes.filtered(lambda n: not n.is_read).write({'is_read': True})
        return page

    @http.route('/presence/notifications/preferences', type='json', auth='user')
    def notification_preferences(self, **prefs):
        allowed = {'school_notify_reminders', 'school_notify_results', 'school_notify_summaries'}
        vals = {k: bool(v) for k, v in prefs.items() if k in allowed}
        if vals:
            request.env.user.sudo().write(vals)
        return {'ok': True}
