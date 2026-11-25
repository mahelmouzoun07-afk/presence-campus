import json
from unittest.mock import patch

from odoo.exceptions import AccessError

from .common import SchoolCase

DIM = 128


def unit(index):
    """Vecteur unitaire sur un axe : deux axes différents = personnes différentes."""
    v = [0.0] * DIM
    v[index] = 1.0
    return v


def near(index, other=1, weight=0.2):
    """Même personne, légèrement différente (angle, lumière)."""
    v = unit(index)
    v[other] = weight
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


def analysis(vector, rgb=(120, 110, 100), sharp=100.0, px=120):
    return {'vector': vector, 'sharp': sharp, 'face_px': px, 'mean_rgb': list(rgb)}


# Faux visage éclairé en rouge / vert / bleu selon la couleur affichée
LIT = {'red': (190, 100, 90), 'green': (100, 190, 90), 'blue': (90, 100, 190)}


class FakeSession(dict):
    pass


class TestFace(SchoolCase):
    """La logique de décision, avec un moteur simulé : les images sont des mots
    de code (« A1 »…) que le faux moteur transforme en vecteurs. L'extraction
    réelle du visage se teste sur de vrais téléphones."""

    def setUp(self):
        super().setUp()
        self.Face = self.env['school.student.face']
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.face_policy', 'flag')
        self.table = {}
        self.engine_patch = patch('odoo.addons.school_attendance_qr.models.face.engine_available', return_value=True)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)
        self.analyse_patch = patch.object(type(self.Face), '_analyse', lambda _self, data: self.table.get(data))
        self.analyse_patch.start()
        self.addCleanup(self.analyse_patch.stop)

    # -------------------------------------------------------------- aides
    def session_with_challenge(self):
        session = FakeSession()
        colors = self.Face.new_challenge(session)
        return session, colors

    def flash_frames(self, colors, vector, key, lit=True):
        frames = []
        for i, color in enumerate(colors):
            name = f'{key}-flash-{i}'
            self.table[name] = analysis(vector, rgb=LIT[color] if lit else (120, 110, 100))
            frames.append(name)
        return frames

    def pose_frames(self, key, vectors):
        frames = []
        for i, v in enumerate(vectors):
            name = f'{key}-pose-{i}'
            self.table[name] = analysis(v)
            frames.append(name)
        return frames

    def enroll(self, student, axis, key=None, other_axis=1):
        key = key or f'e{student.id}'
        session, colors = self.session_with_challenge()
        poses = self.pose_frames(key, [near(axis, other_axis, 0.05 * (i + 1)) for i in range(5)])
        flash = self.flash_frames(colors, near(axis, other_axis), key)
        return self.Face.enroll(student, poses, flash, session)

    def verify(self, student, vector, key, lit=True):
        session, colors = self.session_with_challenge()
        return self.Face.verify(student, self.flash_frames(colors, vector, key, lit), session)

    # -------------------------------------------------------------- tests
    def test_enrollment_stores_vectors_not_photos(self):
        ok, error = self.enroll(self.student, 0)
        self.assertTrue(ok, error)
        faces = self.Face.sudo().search([('student_id', '=', self.student.id)])
        self.assertEqual(len(faces), 5)
        self.assertTrue(all(len(json.loads(f.vector)) == DIM for f in faces))
        self.assertTrue(self.student.face_enrolled_at)
        self.assertFalse(self.env['ir.attachment'].search([('res_model', '=', 'school.student.face')]))

    def test_enrollment_only_once_and_nobody_can_reset_it(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        ok, error = self.enroll(self.student, 5)
        self.assertFalse(ok)
        self.assertIn('déjà', error)
        admin = self.env['res.users'].create({
            'name': 'Admin Ecole', 'login': 'admin.ecole.face',
            'groups_id': [(6, 0, [self.env.ref('school_base.group_school_admin').id, self.env.ref('base.group_user').id])]})
        with self.assertRaises(AccessError):
            self.student.with_user(admin).write({'face_enrolled_at': False})
        with self.assertRaises(AccessError):
            self.Face.with_user(admin).search([])

    def test_enrollment_refused_when_images_show_different_people(self):
        session, colors = self.session_with_challenge()
        poses = self.pose_frames('mix', [unit(0), unit(0), unit(7), unit(7), unit(7)])
        flash = self.flash_frames(colors, unit(0), 'mix')
        ok, error = self.Face.enroll(self.student, poses, flash, session)
        self.assertFalse(ok)
        self.assertIn('même personne', error)

    def test_enrollment_refused_without_live_test(self):
        session, colors = self.session_with_challenge()
        poses = self.pose_frames('flat', [near(0, 1, 0.05 * (i + 1)) for i in range(5)])
        flash = self.flash_frames(colors, near(0), 'flat', lit=False)
        ok, error = self.Face.enroll(self.student, poses, flash, session)
        self.assertFalse(ok)
        self.assertIn('direct', error)

    def test_same_face_for_two_students_is_flagged_and_refused(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        ok, error = self.enroll(self.student2, 0, key='copy', other_axis=2)
        self.assertFalse(ok)
        self.assertIn('déjà enregistré', error)
        tasks = self.env['school.attendance.task'].search([('task_type', '=', 'face_duplicate')])
        self.assertEqual(set(tasks.mapped('student_id')), {self.student, self.student2})

    def test_official_photo_is_optional_and_compared_when_present(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        self.assertEqual(self.student.face_photo_check, 'none')
        self.student2.photo = b'UEhPVE8='  # contenu quelconque : le faux moteur sait le lire
        self.table[self.student2.photo] = analysis(unit(9))
        self.assertTrue(self.enroll(self.student2, 3)[0])
        self.assertEqual(self.student2.face_photo_check, 'no')
        self.assertTrue(self.env['school.attendance.task'].search([('task_type', '=', 'face_mismatch')]))

    def test_same_person_matches_and_other_person_does_not(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        self.assertEqual(self.verify(self.student, near(0, 4, 0.3), 'ok')['result'], 'match')
        self.assertEqual(self.verify(self.student, unit(50), 'ko')['result'], 'mismatch')

    def test_doubtful_image_is_unclear_not_refused(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        # un peu en dessous du seuil : zone grise
        v = [0.0] * DIM
        v[0], v[60] = 0.30, (1 - 0.30 ** 2) ** 0.5
        self.assertEqual(self.verify(self.student, v, 'gris')['result'], 'unclear')
        self.assertEqual(self.Face.verify(self.student, [], FakeSession())['result'], 'unclear')

    def test_no_live_reflection_makes_a_match_unclear(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        out = self.verify(self.student, near(0), 'photo', lit=False)
        self.assertEqual(out['result'], 'unclear')
        self.assertIn('direct', out['reason'])

    def test_challenge_is_single_use(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        session, colors = self.session_with_challenge()
        frames = self.flash_frames(colors, near(0), 'rejeu')
        self.assertEqual(self.Face.verify(self.student, frames, session)['result'], 'match')
        self.assertEqual(self.Face.verify(self.student, frames, session)['result'], 'unclear')

    def test_recent_vectors_follow_the_face_but_core_never_moves(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        core_ids = self.Face.sudo().search([('student_id', '=', self.student.id), ('kind', '=', 'core')]).ids
        for i in range(14):
            self.verify(self.student, near(0, 10 + i, 0.5), f'drift{i}')
        recent = self.Face.sudo().search([('student_id', '=', self.student.id), ('kind', '=', 'recent')])
        self.assertLessEqual(len(recent), 10)
        self.assertTrue(recent)
        self.assertEqual(
            self.Face.sudo().search([('student_id', '=', self.student.id), ('kind', '=', 'core')]).ids, core_ids)

    # --------------------------------------------- à la confirmation de présence
    def check(self, student, frames=None, no_camera=False, session=None):
        return self.Face.check_for_scan(student, frames, no_camera, session if session is not None else FakeSession())

    def test_policy_off_changes_nothing(self):
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.face_policy', 'off')
        self.assertEqual(self.check(self.student), (None, None))

    def test_not_enrolled_is_flagged_or_blocked_by_policy(self):
        self.assertEqual(self.check(self.student), (None, 'Visage non inscrit'))
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.face_policy', 'block')
        error, flag = self.check(self.student)
        self.assertTrue(error and not flag)

    def test_enrollment_lets_the_current_confirmation_through(self):
        session = FakeSession()
        session2, colors = self.session_with_challenge()
        poses = self.pose_frames('now', [near(0, 1, 0.05 * (i + 1)) for i in range(5)])
        flash = self.flash_frames(colors, near(0), 'now')
        self.assertTrue(self.Face.enroll(self.student, poses, flash, session2)[0])
        self.assertEqual(self.check(self.student, session=session2), (None, None))

    def test_no_camera_or_missing_images_never_easier_than_normal_path(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        error, flag = self.check(self.student, no_camera=True)
        self.assertIsNone(error)
        self.assertIn('non vérifié', flag)
        self.assertIn('non vérifié', self.check(self.student)[1])

    def test_mismatch_flags_then_blocks_only_in_block_mode(self):
        self.assertTrue(self.enroll(self.student, 0)[0])
        session, colors = self.session_with_challenge()
        frames = self.flash_frames(colors, unit(80), 'autre')
        error, flag = self.check(self.student, frames, session=session)
        self.assertIsNone(error)
        self.assertIn('différent', flag)
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.face_policy', 'block')
        session, colors = self.session_with_challenge()
        error, flag = self.check(self.student, self.flash_frames(colors, unit(81), 'autre2'), session=session)
        self.assertTrue(error)

    def test_flagged_face_gives_flagged_attendance_with_lower_proof(self):
        res = self.env['school.attendance.record'].sudo().with_context(face_flag='Visage non inscrit').register_scan(
            room_token=self.room.qr_token, student_id=self.student.id, latitude=6.3703, longitude=2.3912,
            device_fingerprint='dev-face', accuracy=5.0, client_ip=False)
        self.assertEqual(res['state'], 'flagged')
        self.assertIn('Visage non inscrit', res['flag_reason'])
        record = self.env['school.attendance.record'].search([('student_id', '=', self.student.id)])
        self.assertEqual(record.proof_level, 'E')
