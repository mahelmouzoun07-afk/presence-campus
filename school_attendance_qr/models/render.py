"""Rendu graphique : QR codes stylés, affiches imprimables et attestations PDF.

Aucune dépendance supplémentaire : qrcode, Pillow et reportlab sont déjà
installés avec Odoo. Le PDF est fabriqué directement par reportlab (et non par
wkhtmltopdf), pour fonctionner aussi sur un serveur hors ligne.
"""
import io

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_H
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles import colormasks as cm
from qrcode.image.styles import moduledrawers as md
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm as CM
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SHAPES = [
    ('rounded', 'Arrondis'), ('square', 'Carrés'), ('circle', 'Points'),
    ('gapped', 'Carrés espacés'), ('vertical', 'Barres verticales'), ('horizontal', 'Barres horizontales'),
]
COLOR_MODES = [
    ('radial', 'Dégradé du centre vers le bord'), ('solid', 'Couleur unie'),
    ('horizontal', 'Dégradé horizontal'), ('vertical', 'Dégradé vertical'),
    ('square', 'Dégradé carré'),
]
DEFAULT_COLOR_1 = '#14213D'   # bleu nuit
DEFAULT_COLOR_2 = '#8C5A0B'   # bronze doré, assez foncé pour rester lisible
DEFAULT_BG = '#FFFFFF'

_DRAWERS = {
    'square': md.SquareModuleDrawer, 'rounded': md.RoundedModuleDrawer, 'circle': md.CircleModuleDrawer,
    'gapped': md.GappedSquareModuleDrawer, 'vertical': md.VerticalBarsDrawer, 'horizontal': md.HorizontalBarsDrawer,
}


# --------------------------------------------------------------- couleurs
def hex_to_rgb(value, fallback=(0, 0, 0)):
    value = (value or '').strip().lstrip('#')
    if len(value) == 3:
        value = ''.join(ch * 2 for ch in value)
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return fallback


def _luminance(rgb):
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a, hex_b):
    la, lb = _luminance(hex_to_rgb(hex_a)), _luminance(hex_to_rgb(hex_b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _rl_color(value, fallback):
    return colors.Color(*[v / 255.0 for v in hex_to_rgb(value, fallback)])


# --------------------------------------------------------------- QR stylé
def _color_mask(mode, c1, c2, bg):
    back, a, b = hex_to_rgb(bg, (255, 255, 255)), hex_to_rgb(c1, (20, 33, 61)), hex_to_rgb(c2, (140, 90, 11))
    if mode == 'solid':
        return cm.SolidFillColorMask(back_color=back, front_color=a)
    if mode == 'horizontal':
        return cm.HorizontalGradiantColorMask(back_color=back, left_color=a, right_color=b)
    if mode == 'vertical':
        return cm.VerticalGradiantColorMask(back_color=back, top_color=a, bottom_color=b)
    if mode == 'square':
        return cm.SquareGradiantColorMask(back_color=back, center_color=a, edge_color=b)
    return cm.RadialGradiantColorMask(back_color=back, center_color=a, edge_color=b)


def render_qr_image(data, shape='rounded', color_mode='radial', color_1=DEFAULT_COLOR_1,
                    color_2=DEFAULT_COLOR_2, background=DEFAULT_BG, logo_bytes=None,
                    logo_scale=22, box_size=12, border=3):
    """Renvoie une image PIL (RGBA) du QR. Le niveau de correction d'erreur
    maximal (H) permet de masquer jusqu'à ~30 % du code sans le rendre illisible,
    ce qui rend possible un logo au centre."""
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_H, box_size=box_size, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    drawer = _DRAWERS.get(shape, md.RoundedModuleDrawer)()
    img = qr.make_image(image_factory=StyledPilImage, module_drawer=drawer,
                        color_mask=_color_mask(color_mode, color_1, color_2, background))
    img = img.convert('RGBA')
    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes)).convert('RGBA')
        except Exception:
            return img
        scale = max(12, min(int(logo_scale or 22), 28))   # au-delà, le QR risque de ne plus se lire
        side = int(img.width * scale / 100)
        logo.thumbnail((side, side))
        pad = max(6, side // 8)
        plate = Image.new('RGBA', (logo.width + 2 * pad, logo.height + 2 * pad), (0, 0, 0, 0))
        ImageDraw.Draw(plate).rounded_rectangle(
            (0, 0, plate.width - 1, plate.height - 1), radius=pad * 1.5,
            fill=hex_to_rgb(background, (255, 255, 255)) + (255,))
        plate.alpha_composite(logo, (pad, pad))
        img.alpha_composite(plate, ((img.width - plate.width) // 2, (img.height - plate.height) // 2))
    return img


def image_to_png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


# ------------------------------------------------------------- utilitaires PDF
def _wrap(text, font, size, max_width):
    return simpleSplit(text or '', font, size, max_width)


def _gradient_rect(pdf, x, y, w, h, color_from, color_to):
    """Dégradé limité à un rectangle (sinon reportlab remplit toute la page)."""
    pdf.saveState()
    path = pdf.beginPath()
    path.rect(x, y, w, h)
    pdf.clipPath(path, stroke=0, fill=0)
    pdf.linearGradient(x, y + h, x + w, y, [color_from, color_to], extend=True)
    pdf.restoreState()


def _fit_font(text, font, max_size, min_size, max_width):
    size = max_size
    while size > min_size and pdfmetrics.stringWidth(text or '', font, size) > max_width:
        size -= 1
    return size


def _darker(color, factor=0.65):
    return colors.Color(color.red * factor, color.green * factor, color.blue * factor)


# ------------------------------------------------------------- affiche A4
def build_poster_pdf(posters):
    """posters : liste de dicts {room_name, building, qr_png, title, subtitle,
    school_name, logo_bytes, color_1, color_2}. Une page A4 par salle."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    grey = colors.Color(0.35, 0.38, 0.45)
    for p in posters:
        c1 = _rl_color(p.get('color_1'), (20, 33, 61))
        c2 = _rl_color(p.get('color_2'), (140, 90, 11))

        band_h = 120
        _gradient_rect(pdf, 0, height - band_h, width, band_h, c1, _darker(c1))
        pdf.setFillColor(c2)
        pdf.rect(0, height - band_h - 6, width, 6, stroke=0, fill=1)

        text_x = 50
        if p.get('logo_bytes'):
            try:
                logo = ImageReader(io.BytesIO(p['logo_bytes']))
                r = 38
                cx, cy = 50 + r, height - band_h / 2
                pdf.setFillColor(colors.white)
                pdf.circle(cx, cy, r, stroke=0, fill=1)
                lw, lh = logo.getSize()
                ratio = min((2 * r - 14) / lw, (2 * r - 14) / lh)
                pdf.drawImage(logo, cx - lw * ratio / 2, cy - lh * ratio / 2, lw * ratio, lh * ratio, mask='auto')
                text_x = 50 + 2 * r + 22
            except Exception:
                pass
        pdf.setFillColor(colors.white)
        pdf.setFont('Helvetica-Bold', 24)
        name_lines = _wrap(p.get('school_name') or '', 'Helvetica-Bold', 24, width - text_x - 40)[:2]
        y = height - band_h / 2 + (len(name_lines) - 1) * 13 - 8
        for line in name_lines:
            pdf.drawString(text_x, y, line)
            y -= 27

        pdf.setFillColor(c1)
        pdf.setFont('Helvetica-Bold', 28)
        y = height - band_h - 62
        for line in _wrap(p.get('title') or '', 'Helvetica-Bold', 28, width - 120)[:2]:
            pdf.drawCentredString(width / 2, y, line)
            y -= 34
        pdf.setFillColor(grey)
        pdf.setFont('Helvetica', 13)
        y -= 2
        for line in _wrap(p.get('subtitle') or '', 'Helvetica', 13, width - 170)[:2]:
            pdf.drawCentredString(width / 2, y, line)
            y -= 18

        card = 300
        card_x, card_y = (width - card) / 2, y - 14 - card
        pdf.setFillColor(colors.white)
        pdf.setStrokeColor(c2)
        pdf.setLineWidth(3)
        pdf.roundRect(card_x, card_y, card, card, 22, stroke=1, fill=1)
        pdf.setStrokeColor(c1)
        pdf.setLineWidth(1)
        pdf.roundRect(card_x + 7, card_y + 7, card - 14, card - 14, 16, stroke=1, fill=0)
        pdf.drawImage(ImageReader(io.BytesIO(p['qr_png'])), card_x + 18, card_y + 18, card - 36, card - 36, mask='auto')

        pdf.setFillColor(c1)
        room = p.get('room_name') or ''
        pdf.setFont('Helvetica-Bold', _fit_font(room, 'Helvetica-Bold', 32, 18, width - 110))
        y = card_y - 40
        pdf.drawCentredString(width / 2, y, room)
        if p.get('building'):
            pdf.setFillColor(grey)
            pdf.setFont('Helvetica', 14)
            pdf.drawCentredString(width / 2, y - 24, p['building'])

        steps = ["Scannez ce code avec l'appareil photo", "Connectez-vous avec votre identifiant et matricule",
                 "Appuyez sur « Confirmer »"]
        col_w = (width - 100) / 3
        for i, label in enumerate(steps):
            cx = 50 + col_w * i + col_w / 2
            pdf.setFillColor(c2)
            pdf.circle(cx, 120, 14, stroke=0, fill=1)
            pdf.setFillColor(colors.white)
            pdf.setFont('Helvetica-Bold', 15)
            pdf.drawCentredString(cx, 115, str(i + 1))
            pdf.setFillColor(colors.Color(0.2, 0.22, 0.28))
            pdf.setFont('Helvetica', 10.5)
            ly = 92
            for line in _wrap(label, 'Helvetica', 10.5, col_w - 16)[:3]:
                pdf.drawCentredString(cx, ly, line)
                ly -= 13

        pdf.setStrokeColor(c2)
        pdf.setLineWidth(1)
        pdf.line(50, 44, width - 50, 44)
        pdf.setFillColor(grey)
        pdf.setFont('Helvetica-Oblique', 10.5)
        pdf.drawCentredString(width / 2, 28, "Scannez à l'entrée ET à la sortie du cours pour valider votre présence complète.")
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


# --------------------------------------------------------- attestation PDF
def build_certificate_pdf(data):
    """data : {school_name, logo_bytes, reference, student_name, matricule, promotion,
    date_from, date_to, issue_date, expected, attended, rate, rows:[(cours, attendu, present, taux)],
    city, color_1, color_2}"""
    buf = io.BytesIO()
    navy = _rl_color(data.get('color_1'), (20, 33, 61))
    gold = _rl_color(data.get('color_2'), (140, 90, 11))
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * CM, rightMargin=2.2 * CM,
                            topMargin=5.2 * CM, bottomMargin=2.4 * CM,
                            title="Attestation de présence", author=data.get('school_name') or '')

    h_title = ParagraphStyle('t', fontName='Helvetica-Bold', fontSize=21, textColor=navy, alignment=1, spaceAfter=18)
    body = ParagraphStyle('b', fontName='Helvetica', fontSize=11.5, leading=19, textColor=colors.Color(0.12, 0.13, 0.17))
    small = ParagraphStyle('s', fontName='Helvetica', fontSize=9, leading=12, textColor=colors.Color(0.4, 0.42, 0.48))

    def header_footer(pdf, _doc):
        w, h = A4
        pdf.saveState()
        _gradient_rect(pdf, 0, h - 3.6 * CM, w, 3.6 * CM, navy, _darker(navy))
        pdf.setFillColor(gold)
        pdf.rect(0, h - 3.6 * CM - 4, w, 4, stroke=0, fill=1)
        x = 2.2 * CM
        if data.get('logo_bytes'):
            try:
                logo = ImageReader(io.BytesIO(data['logo_bytes']))
                lw, lh = logo.getSize()
                r = 1.25 * CM
                cx, cy = x + r, h - 1.8 * CM
                pdf.setFillColor(colors.white)
                pdf.circle(cx, cy, r, stroke=0, fill=1)
                ratio = min((2 * r - 10) / lw, (2 * r - 10) / lh)
                pdf.drawImage(logo, cx - lw * ratio / 2, cy - lh * ratio / 2, lw * ratio, lh * ratio, mask='auto')
                x += 2 * r + 0.6 * CM
            except Exception:
                pass
        pdf.setFillColor(colors.white)
        pdf.setFont('Helvetica-Bold', 17)
        for i, line in enumerate(_wrap(data.get('school_name') or '', 'Helvetica-Bold', 17, w - x - 2.2 * CM)[:2]):
            pdf.drawString(x, h - 1.65 * CM - i * 20, line)
        pdf.setStrokeColor(gold)
        pdf.setLineWidth(0.8)
        pdf.line(2.2 * CM, 1.7 * CM, w - 2.2 * CM, 1.7 * CM)
        pdf.setFillColor(colors.Color(0.4, 0.42, 0.48))
        pdf.setFont('Helvetica', 8.5)
        pdf.drawString(2.2 * CM, 1.2 * CM, f"Référence : {data.get('reference', '')}")
        pdf.drawRightString(w - 2.2 * CM, 1.2 * CM, "Document généré par le système de présence de l'établissement")
        pdf.restoreState()

    rate = data.get('rate', 0)
    story = [Paragraph("ATTESTATION DE PRÉSENCE", h_title)]
    story.append(Paragraph(
        f"Nous soussignés, <b>{data.get('school_name') or ''}</b>, attestons que l'étudiant(e) "
        f"<b>{data.get('student_name', '')}</b>, matricule <b>{data.get('matricule', '')}</b>"
        + (f", promotion <b>{data['promotion']}</b>" if data.get('promotion') else '')
        + f", a été enregistré(e) comme présent(e) à <b>{data.get('attended', 0)}</b> séance(s) sur "
          f"<b>{data.get('expected', 0)}</b> séance(s) programmée(s) entre le <b>{data.get('date_from', '')}</b> "
          f"et le <b>{data.get('date_to', '')}</b>, soit un taux de présence de <b>{rate:.1f} %</b>.", body))
    story.append(Spacer(1, 16))

    rows = [["Cours", "Séances programmées", "Séances présentes", "Taux"]]
    rows += [[r[0], str(r[1]), str(r[2]), f"{r[3]:.1f} %"] for r in data.get('rows', [])]
    rows.append(["Total", str(data.get('expected', 0)), str(data.get('attended', 0)), f"{rate:.1f} %"])
    table = Table(rows, colWidths=[6.4 * CM, 4.6 * CM, 3.6 * CM, 2.0 * CM], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (-1, -1), 1.2, gold),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.Color(0.96, 0.96, 0.94)]),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.Color(0.82, 0.83, 0.8)),
    ]))
    story += [table, Spacer(1, 26)]
    story.append(Paragraph(
        "Une séance est comptée « présente » lorsque l'étudiant a confirmé son entrée par scan du code de la salle, "
        "avec une position et un appareil vérifiés par le système.", small))
    story.append(Spacer(1, 30))
    place = (data.get('city') + ', ') if data.get('city') else ''
    story.append(Paragraph(f"Fait à {place}le {data.get('issue_date', '')}", body))
    story.append(Spacer(1, 40))
    sign = Table([["", "Le responsable de la scolarité\n\n\n______________________________"]],
                 colWidths=[8.4 * CM, 8.2 * CM])
    sign.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'Helvetica'), ('FONTSIZE', (0, 0), (-1, -1), 10),
                              ('ALIGN', (1, 0), (1, 0), 'CENTER')]))
    story.append(sign)

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return buf.getvalue()
