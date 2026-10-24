"""Passkey (WebAuthn) : l'étudiant déverrouille son téléphone (empreinte,
Face ID, ou code PIN — peu importe lequel, le navigateur choisit lui-même)
pour prouver, de façon cryptographique, que c'est bien SON appareil qui
confirme la présence. Aucune donnée biométrique ne nous parvient jamais :
seule une preuve mathématique de déverrouillage transite.
"""
import base64

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


def build_registration_options(session, httprequest, student, company_name):
    options = generate_registration_options(
        rp_id=rp_id_from_request(httprequest), rp_name=company_name or "École",
        user_id=str(student.id).encode(), user_name=student.identifiant, user_display_name=student.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=ResidentKeyRequirement.PREFERRED),
    )
    session[SESSION_KEY] = base64.b64encode(options.challenge).decode()
    return options_to_json(options)


def build_authentication_options(session, httprequest, student):
    options = generate_authentication_options(
        rp_id=rp_id_from_request(httprequest),
        allow_credentials=[PublicKeyCredentialDescriptor(id=_b64url_decode(student.webauthn_credential_id))],
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


def verify_authentication(session, httprequest, student, credential_json):
    challenge_b64 = session.pop(SESSION_KEY, None)
    if not challenge_b64:
        return False, "Session expirée, réessayez."
    try:
        credential = parse_authentication_credential_json(credential_json)
        verification = verify_authentication_response(
            credential=credential, expected_challenge=base64.b64decode(challenge_b64),
            expected_rp_id=rp_id_from_request(httprequest),
            expected_origin=httprequest.host_url.rstrip('/'),
            credential_public_key=base64.b64decode(student.webauthn_public_key),
            credential_current_sign_count=student.webauthn_sign_count, require_user_verification=True,
        )
    except InvalidAuthenticationResponse as e:
        return False, f"Vérification refusée : {e}"
    except Exception as e:
        return False, f"Erreur de vérification : {e}"
    student.sudo().write({'webauthn_sign_count': verification.new_sign_count})
    return True, None
