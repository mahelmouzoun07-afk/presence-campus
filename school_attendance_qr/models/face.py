"""Vérification du visage de l'étudiant, entièrement sur le serveur de l'école.

Principes (décidés avec le fondateur) :
- l'étudiant s'inscrit lui-même, une seule fois, avec des consignes guidées ;
- on ne garde JAMAIS les photos : seulement un vecteur de 128 nombres par image,
  et les images sont oubliées dès le calcul ;
- aucune personne (secrétariat, direction, administrateur) ne peut inscrire,
  modifier ou effacer un visage : aucun droit d'accès n'est donné sur le modèle ;
- le visage qui change lentement est suivi automatiquement (vecteurs « récents »
  qui tournent), sans intervention humaine ;
- un doute ne refuse jamais une présence : elle est enregistrée « à vérifier ».
"""
import base64
import json
import logging
import os
import random
import threading
import time

from odoo import api, fields, models
from odoo.exceptions import AccessError

from .helpers import icp

_logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
except ImportError:  # OpenCV est facultatif : sans lui, la vérification reste désactivée
    cv2 = np = None

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'face_models')
DETECTOR_FILE = 'face_detection_yunet_2023mar.onnx'
RECOGNIZER_FILE = 'face_recognition_sface_2021dec.onnx'

SESSION_KEY = 'school_face_challenge'
OK_SESSION_KEY = 'school_face_enrolled_ok'
CHALLENGE_TTL = 180          # secondes pendant lesquelles un défi reste valable
ENROLL_OK_TTL = 300          # après l'inscription, la confirmation en cours est acceptée
MAX_IMAGE_BYTES = 300_000
MAX_POSES = 10
CORE_MIN = 4                 # images exploitables minimum pour s'inscrire
CORE_MAX = 8
RECENT_MAX = 10
MIN_FACE_PX = 60             # visage plus petit = trop loin
DEFAULT_THRESHOLD = 0.363    # seuil conseillé pour SFace (similarité cosinus)
GRAY_MARGIN = 0.10           # entre seuil-marge et seuil : « à vérifier », pas un refus
STRONG_MATCH = 0.50          # au-dessus : le vecteur peut rejoindre les « récents »
REPLAY_LIMIT = 0.97          # quasi identique à un vecteur connu : on ne l'ajoute pas
COLORS = {'red': 0, 'green': 1, 'blue': 2}

_LOCK = threading.Lock()
_ENGINE = {}


# --------------------------------------------------------------- moteur
def engine_available():
    return cv2 is not None and all(
        os.path.exists(os.path.join(MODEL_DIR, f)) for f in (DETECTOR_FILE, RECOGNIZER_FILE))


def _recognizer():
    if 'rec' not in _ENGINE:
        _ENGINE['rec'] = cv2.FaceRecognizerSF.create(os.path.join(MODEL_DIR, RECOGNIZER_FILE), '')
    return _ENGINE['rec']


def decode_image(data):
    """Image JPEG reçue du téléphone (base64, avec ou sans préfixe) → tableau, ou None."""
    if not data:
        return None
    if isinstance(data, bytes):
        data = data.decode('ascii', 'ignore')
    if not isinstance(data, str):
        return None
    if data.startswith('data:'):
        data = data.split(',', 1)[-1]
    try:
        raw = base64.b64decode(data)
    except Exception:
        return None
    if not raw or len(raw) > MAX_IMAGE_BYTES * 20:
        return None
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > 1600:
        scale = 1600.0 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    return img


def _enhance(img):
    """Éclaircit les zones sombres (salle mal éclairée, peau foncée) avant l'analyse."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    l_chan = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(l_chan)
    return cv2.cvtColor(cv2.merge((l_chan, a_chan, b_chan)), cv2.COLOR_LAB2BGR)


def analyse_image(img):
    """Un visage dans l'image → {'vector', 'sharp', 'face_px', 'mean_rgb'} ou None."""
    h, w = img.shape[:2]
    enhanced = _enhance(img)
    detector = cv2.FaceDetectorYN.create(os.path.join(MODEL_DIR, DETECTOR_FILE), '', (w, h), 0.7, 0.3, 50)
    _, faces = detector.detect(enhanced)
    if faces is None or len(faces) == 0:
        return None
    face = max(faces, key=lambda f: f[2] * f[3])
    with _LOCK:
        rec = _recognizer()
        feature = rec.feature(rec.alignCrop(enhanced, face))
    vec = feature.flatten().astype('float64')
    norm = float(np.linalg.norm(vec))
    if norm == 0:
        return None
    x, y, bw, bh = [max(int(v), 0) for v in face[:4]]
    crop = img[y:y + bh, x:x + bw]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mean_bgr = crop.reshape(-1, 3).mean(axis=0)
    return {
        'vector': (vec / norm).tolist(),
        'sharp': float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        'face_px': min(bw, bh),
        'mean_rgb': [float(mean_bgr[2]), float(mean_bgr[1]), float(mean_bgr[0])],
    }


def _dot(a, b):
    return float(sum(x * y for x, y in zip(a, b)))


def _centroid(vectors):
    n = len(vectors[0])
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(n)]
    norm = sum(x * x for x in mean) ** 0.5 or 1.0
    return [x / norm for x in mean]


class SchoolStudentFace(models.Model):
    """Vecteurs du visage d'un étudiant. Aucune règle d'accès : seul le code
    (en sudo) lit et écrit ici, aucun humain, administrateur compris."""
    _name = 'school.student.face'
    _description = "Vecteur du visage d'un étudiant"
    _order = 'id'

    student_id = fields.Many2one('school.student', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([('core', "Inscription"), ('recent', "Récent")], required=True, default='core')
    vector = fields.Text(required=True)

    # ------------------------------------------------------------ réglages
    @api.model
    def policy(self):
        return icp(self.env, 'face_policy', 'block')

    @api.model
    def threshold(self):
        try:
            return float(icp(self.env, 'face_threshold', DEFAULT_THRESHOLD))
        except (TypeError, ValueError):
            return DEFAULT_THRESHOLD

    # --------------------------------------------------------------- défi
    @api.model
    def new_challenge(self, session):
        """Trois couleurs d'écran tirées au hasard : leur reflet sur le visage
        prouve qu'il s'agit d'une personne filmée en direct."""
        colors = random.sample(list(COLORS), 3)
        session[SESSION_KEY] = {'colors': colors, 'ts': time.time()}
        return colors

    @api.model
    def _take_challenge(self, session):
        challenge = session.pop(SESSION_KEY, None)
        if not challenge or time.time() - challenge['ts'] > CHALLENGE_TTL:
            return None
        return challenge['colors']

    @api.model
    def _analyse(self, data):
        """Point d'entrée unique vers le moteur (remplaçable dans les tests)."""
        img = decode_image(data)
        return analyse_image(img) if img is not None else None

    @api.model
    def _liveness_ok(self, analyses, colors):
        """Le reflet de la couleur affichée doit se retrouver sur le visage,
        pour au moins deux des trois couleurs."""
        if len(analyses) != len(colors) or any(a is None for a in analyses):
            return False
        shares = []
        for a in analyses:
            total = sum(a['mean_rgb']) or 1.0
            shares.append([c / total for c in a['mean_rgb']])
        hits = 0
        for i, color in enumerate(colors):
            ch = COLORS[color]
            others = [shares[j][ch] for j in range(len(colors)) if j != i]
            if shares[i][ch] > sum(others) / len(others) + 0.004:
                hits += 1
        return hits >= 2

    # ------------------------------------------------------------ galerie
    @api.model
    def _gallery(self, student):
        return [json.loads(v) for v in self.sudo().search([('student_id', '=', student.id)]).mapped('vector')]

    @api.model
    def _remember(self, student, vector):
        """Le visage change doucement (coupe, barbe, âge) : un vecteur très sûr
        rejoint les « récents », les plus anciens sortent. Le noyau d'inscription
        ne bouge jamais."""
        recent = self.sudo().search([('student_id', '=', student.id), ('kind', '=', 'recent')], order='id')
        self.sudo().create({'student_id': student.id, 'kind': 'recent', 'vector': json.dumps(vector)})
        if len(recent) >= RECENT_MAX:
            recent[:len(recent) - RECENT_MAX + 1].unlink()

    # -------------------------------------------------------- inscription
    @api.model
    def enroll(self, student, poses, flash, session):
        """Inscription unique. Renvoie (ok, message)."""
        student = student.sudo()
        if not engine_available():
            return False, "La vérification du visage n'est pas disponible sur ce serveur."
        if student.face_enrolled_at:
            return False, "Votre visage est déjà enregistré."
        colors = self._take_challenge(session)
        if not colors:
            return False, "Session expirée, recommencez."

        poses = (poses or [])[:MAX_POSES]
        results = [r for r in (self._analyse(p) for p in poses) if r and r['face_px'] >= MIN_FACE_PX]
        if len(results) < CORE_MIN:
            return False, ("Votre visage n'a pas été assez net sur les images. Placez-vous face à la lumière, "
                           "retirez lunettes et casquette, rapprochez le téléphone et recommencez.")
        results.sort(key=lambda r: r['sharp'], reverse=True)
        results = results[:CORE_MAX]
        vectors = [r['vector'] for r in results]
        centroid = _centroid(vectors)
        thr = self.threshold()
        if any(_dot(v, _centroid(vectors[:i] + vectors[i + 1:])) < thr for i, v in enumerate(vectors)):
            return False, "Les images ne semblent pas montrer la même personne. Recommencez seul(e), devant la caméra."

        flash_analyses = [self._analyse(f) for f in (flash or [])]
        if not self._liveness_ok(flash_analyses, colors):
            return False, ("Le test de présence en direct n'a pas réussi. Recommencez dans un endroit mieux éclairé, "
                           "sans bouger pendant que l'écran change de couleur.")

        duplicate = self._find_duplicate(student, centroid, thr)
        if duplicate:
            self._flag_duplicate(student, duplicate)
            return False, ("Ce visage est déjà enregistré pour un autre compte. L'établissement en a été informé.")

        photo_check = 'none'
        if student.photo:
            official = self._analyse(student.photo)
            if official:
                photo_check = 'yes' if _dot(centroid, official['vector']) >= thr else 'no'
        if photo_check == 'no' and self.policy() == 'block':
            return False, "Votre visage ne correspond pas à la photo de votre dossier. Réessayez en pleine lumière."

        for r in results:
            self.sudo().create({'student_id': student.id, 'kind': 'core', 'vector': json.dumps(r['vector'])})
        student.write({'face_enrolled_at': fields.Datetime.now(), 'face_photo_check': photo_check})
        session[OK_SESSION_KEY] = time.time()
        self.env['school.audit.log'].log('other', f"Visage inscrit (photo du dossier : {photo_check})", student=student)
        if photo_check == 'no':
            self.env['school.attendance.task'].create_unique(
                'face_mismatch', student, f"Visage différent de la photo du dossier : {student.name}",
                "Le visage inscrit ne ressemble pas à la photo officielle.")
        return True, None

    @api.model
    def _find_duplicate(self, student, centroid, thr):
        others = self.sudo().search([('kind', '=', 'core'), ('student_id', '!=', student.id)])
        for rec in others:
            if _dot(json.loads(rec.vector), centroid) >= max(thr + 0.1, 0.45):
                return rec.student_id
        return False

    @api.model
    def _flag_duplicate(self, student, other):
        Task = self.env['school.attendance.task']
        for a, b in ((student, other), (other, student)):
            Task.create_unique('face_duplicate', a, f"Même visage que {b.name}",
                               f"Une inscription de visage pour {student.name} ressemble à celle de {other.name}.")
        self.env['school.audit.log'].log('fraud', f"Même visage pour {student.name} et {other.name}", student=student)

    # ------------------------------------------------------- vérification
    @api.model
    def verify(self, student, frames, session):
        """Renvoie {'result': 'match'|'unclear'|'mismatch', 'score', 'reason'}."""
        colors = self._take_challenge(session)
        if not colors:
            return {'result': 'unclear', 'score': None, 'reason': "Vérification du visage expirée"}
        analyses = [self._analyse(f) for f in (frames or [])[:len(colors)]]
        usable = [a for a in analyses if a and a['face_px'] >= MIN_FACE_PX]
        if not usable:
            return {'result': 'unclear', 'score': None, 'reason': "Visage non détecté ou trop flou"}
        gallery = self._gallery(student)
        if not gallery:
            return {'result': 'unclear', 'score': None, 'reason': "Visage non inscrit"}
        best = max(usable, key=lambda a: a['sharp'])
        score = max(_dot(best['vector'], g) for g in gallery)
        thr = self.threshold()
        live = self._liveness_ok(analyses, colors)
        if score >= thr:
            if not live:
                return {'result': 'unclear', 'score': score, 'reason': "Test de présence en direct non concluant"}
            if score >= STRONG_MATCH and score < REPLAY_LIMIT:
                self._remember(student, best['vector'])
            return {'result': 'match', 'score': score, 'reason': False}
        if score >= thr - GRAY_MARGIN:
            return {'result': 'unclear', 'score': score, 'reason': "Visage incertain (lumière ou angle)"}
        return {'result': 'mismatch', 'score': score, 'reason': "Visage différent de celui de l'étudiant"}

    @api.model
    def check_for_scan(self, student, frames, no_camera, session):
        """Contrôle du visage à la confirmation. Renvoie (erreur, motif_à_signaler).
        `erreur` : refus (réglage « bloquer » et visage clairement différent)."""
        student = student.sudo()
        policy = self.policy()
        if policy == 'off':
            return None, None
        if not engine_available():
            # Panne du serveur : on ne refuse jamais l'étudiant pour ça, mais on ne valide pas non plus.
            return None, "Vérification du visage indisponible"
        ok_at = session.pop(OK_SESSION_KEY, None)
        if ok_at and time.time() - ok_at < ENROLL_OK_TTL:
            return None, None
        if not student.face_enrolled_at:
            if policy == 'block':
                return "Inscrivez d'abord votre visage pour confirmer votre présence.", None
            return None, "Visage non inscrit"
        if no_camera or not frames:
            return None, "Caméra indisponible : visage non vérifié"
        outcome = self.verify(student, frames, session)
        if outcome['result'] == 'match':
            return None, None
        if outcome['result'] == 'mismatch':
            self.env['school.attendance.task'].create_unique(
                'face_mismatch', student, f"Visage différent : {student.name}",
                "Le visage présenté à la confirmation ne correspond pas à celui de l'étudiant.")
            self.env['school.audit.log'].log('fraud', outcome['reason'], student=student)
            if policy == 'block':
                return "Visage non reconnu. Réessayez face à la lumière, sans lunettes ni casquette.", None
        return None, outcome['reason']


class SchoolStudentFaceFields(models.Model):
    _inherit = 'school.student'

    face_enrolled_at = fields.Datetime(string="Visage inscrit le", readonly=True, copy=False)
    face_photo_check = fields.Selection(
        [('yes', "Conforme à la photo du dossier"), ('no', "Différent de la photo du dossier"),
         ('none', "Pas de photo du dossier")],
        string="Visage / photo du dossier", readonly=True, copy=False)

    def write(self, vals):
        # Personne (administrateur compris) ne peut effacer ni refaire une inscription de visage.
        if ('face_enrolled_at' in vals or 'face_photo_check' in vals) and not self.env.su:
            raise AccessError("L'inscription du visage ne peut pas être modifiée.")
        return super().write(vals)
