"""Passkey (WebAuthn) : l'étudiant déverrouille son téléphone (empreinte,
Face ID, ou code PIN — peu importe lequel, le navigateur choisit lui-même)
pour prouver, de façon cryptographique, que c'est bien SON appareil qui
confirme la présence. Aucune donnée biométrique ne nous parvient jamais :
seule une preuve mathématique de déverrouillage transite.
"""
import base64

from odoo import fields

from webauthn import (generate_authentication_options, generate_registration_options,
                      options_to_json, verify_authentication_response, verify_registration_response)
from webauthn.helpers import parse_authentication_credential_json, parse_registration_credential_json
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

SESSION_KEY = 'school_webauthn_challenge'


def _b64url_decode(s):
    padded = s + '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(padded)


def rp_id_from_request(httprequest):
    """L'identifiant du site pour WebAuthn : le nom de domaine, sans port ni
    schéma. Une clé enregistrée sur un domaine ne fonctionne que sur ce même
    domaine — normal et voulu en production (domaine fixe), mais veut dire
    qu'une clé créée via un tunnel de test doit être recréée si l'adresse
    du tunnel change."""
    return httprequest.host.split(':')[0]


def _user_handle(holder):
    """Identifiant opaque de l'utilisateur pour la clé : les clés des
    enseignants et des étudiants ne doivent pas pouvoir se confondre."""
    prefix = 't' if holder._name == 'school.teacher' else ''
    return f"{prefix}{holder.id}".encode()


def _user_name(holder):
    return holder.identifiant if holder._name == 'school.student' else (holder.email or holder.name)


def build_registration_options(session, httprequest, holder, company_name):
    """`holder` : l'étudiant, ou l'enseignant (pour la présence relayée) —
    tout enregistrement portant les champs webauthn_*."""
    options = generate_registration_options(
        rp_id=rp_id_from_request(httprequest), rp_name=company_name or "École",
        user_id=_user_handle(holder), user_name=_user_name(holder), user_display_name=holder.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=ResidentKeyRequirement.PREFERRED),
    )
    session[SESSION_KEY] = base64.b64encode(options.challenge).decode()
    return options_to_json(options)


def build_authentication_options(session, httprequest, holder):
    options = generate_authentication_options(
        rp_id=rp_id_from_request(httprequest),
        allow_credentials=[PublicKeyCredentialDescriptor(id=_b64url_decode(holder.webauthn_credential_id))],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    session[SESSION_KEY] = base64.b64encode(options.challenge).decode()
    return options_to_json(options)


def verify_registration(session, httprequest, credential_json):
    challenge_b64 = session.pop(SESSION_KEY, None)
    if not challenge_b64:
        return None, "Session expirée, réessayez."
    try:
        credential = parse_registration_credential_json(credential_json)
        verification = verify_registration_response(
            credential=credential, expected_challenge=base64.b64decode(challenge_b64),
            expected_rp_id=rp_id_from_request(httprequest),
            expected_origin=httprequest.host_url.rstrip('/'), require_user_verification=True,
        )
    except InvalidRegistrationResponse as e:
        return None, f"Vérification de l'appareil refusée : {e}"
    except Exception as e:
        return None, f"Erreur de vérification : {e}"
    return {
        'credential_id': base64.urlsafe_b64encode(verification.credential_id).rstrip(b'=').decode(),
        'public_key': base64.b64encode(verification.credential_public_key).decode(),
        'sign_count': verification.sign_count,
    }, None


def verify_authentication(session, httprequest, holder, credential_json):
    challenge_b64 = session.pop(SESSION_KEY, None)
    if not challenge_b64:
        return False, "Session expirée, réessayez."
    return verify_assertion(httprequest, holder, credential_json, base64.b64decode(challenge_b64))


def verify_assertion(httprequest, holder, credential_json, challenge):
    """Vérifie une signature WebAuthn pour un défi connu. Sert aussi aux
    confirmations hors ligne, signées sur un défi préchargé à l'avance."""
    try:
        credential = parse_authentication_credential_json(credential_json)
        verification = verify_authentication_response(
            credential=credential, expected_challenge=challenge,
            expected_rp_id=rp_id_from_request(httprequest),
            expected_origin=httprequest.host_url.rstrip('/'),
            credential_public_key=base64.b64decode(holder.webauthn_public_key),
            credential_current_sign_count=holder.webauthn_sign_count, require_user_verification=True,
        )
    except InvalidAuthenticationResponse as e:
        return False, f"Vérification refusée : {e}"
    except Exception as e:
        return False, f"Erreur de vérification : {e}"
    holder.sudo().write({'webauthn_sign_count': verification.new_sign_count})
    return True, None


def store_registration(holder, result):
    holder.sudo().write({
        'webauthn_credential_id': result['credential_id'],
        'webauthn_public_key': result['public_key'],
        'webauthn_sign_count': result['sign_count'],
        'webauthn_registered_at': fields.Datetime.now(),
    })
