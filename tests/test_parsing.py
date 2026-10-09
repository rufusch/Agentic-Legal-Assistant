import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.parsing import ParseFailure, extract


def text_pdf(text='Payment is due on 15 October 2026.'):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 16 Tf 40 700 Td ({text}) Tj ET'.encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    return writer


def raw(writer):
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_text_pdf_and_mixed_pdf_preserve_page_anchors(monkeypatch):
    writer = text_pdf()
    writer.add_blank_page(width=600,height=800)
    monkeypatch.setattr('backend.parsing.ocr_image', lambda image: ('Scanned payment annexure', .91))
    result = extract(raw(writer),'application/pdf')
    assert len(result['pages']) == 2
    assert result['pages'][0]['ocr'] is False
    assert '15 October' in result['pages'][0]['text']
    assert result['pages'][1]['ocr'] is True and result['pages'][1]['number'] == 2
    assert result['warnings']


def test_partial_ocr_failure_keeps_usable_text(monkeypatch):
    writer = text_pdf()
    writer.add_blank_page(width=600,height=800)
    def fail(image):
        raise RuntimeError('OCR engine failure')
    monkeypatch.setattr('backend.parsing.ocr_image',fail)
    result=extract(raw(writer),'application/pdf')
    assert result['pages'][0]['text']
    assert result['pages'][1]['text'] == ''
    assert any(w[0]=='partial_processing' for w in result['warnings'])


def test_active_pdf_and_encrypted_pdf_are_rejected():
    writer=text_pdf()
    writer.add_js('app.alert("active")')
    with pytest.raises(ParseFailure,match='Active PDF'):
        extract(raw(writer),'application/pdf')
    writer=text_pdf()
    writer.encrypt('password')
    with pytest.raises(ParseFailure,match='unlocked'):
        extract(raw(writer),'application/pdf')
def test_upright_scan_keeps_readable_text():
    from PIL import Image, ImageDraw, ImageFont
    from backend.parsing import ocr_image
    image=Image.new('RGB',(1200,180),'white')
    ImageDraw.Draw(image).text((30,40),'Alpha Ltd pays Beta Ltd INR 5000.',fill='black',font=ImageFont.load_default(size=32))
    text,quality=ocr_image(image)
    assert '5000' in text and 'Alpha' in text
    assert quality>.8
