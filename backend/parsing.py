"""Bounded parsers executed in a separate process. Stored spans refer to extracted text."""
import io
import re
import zipfile
from dataclasses import dataclass

MAX_PAGES = 150
MAX_TEXT = 2_000_000
PARSER_VERSION = 'sources-v2'


class ParseFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


@dataclass
class Page:
    number: int
    text: str
    ocr: bool = False
    quality: float | None = None


def ocr_image(image):
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    # Bundled models, local CPU inference, no runtime network/model download.
    global _ocr
    if '_ocr' not in globals():
        _ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
    pixels=np.asarray(image.convert('RGB'))
    result, _ = _ocr(pixels)
    def quality(rows):
        meaningful=[row for row in (rows or []) if row[1].strip()]
        return float(sum(row[2] for row in meaningful)/len(meaningful)) if meaningful else 0.0
    # An erroneous orientation classification can turn clear upright text into
    # whitespace. Retry the original orientation before declaring it unreadable.
    if quality(result)<.65:
        upright, _ = _ocr(pixels,use_cls=False)
        if quality(upright)>quality(result):result=upright
    if not result:
        return '', 0.0
    return '\n'.join(row[1] for row in result), quality(result)


def extract(raw, media_type):
    pages, warnings = [], []
    if media_type == 'text/plain':
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ParseFailure('INVALID_ENCODING', 'Text files must use UTF-8 encoding.')
        if '\x00' in text:
            raise ParseFailure('INVALID_CONTENT', 'The uploaded file is not readable plain text.')
        pages = [Page(1, text)]
    elif media_type == 'application/pdf':
        from pypdf import PdfReader
        import pypdfium2 as pdfium
        if not raw.lstrip().startswith(b'%PDF-'):
            raise ParseFailure('INVALID_CONTENT', 'The file is not a PDF.')
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ParseFailure('ENCRYPTED_DOCUMENT', 'Upload an unlocked PDF.')
        catalog = reader.trailer['/Root']
        names = catalog.get('/Names', {})
        if hasattr(names, 'get_object'):
            names = names.get_object()
        if '/OpenAction' in catalog or '/AA' in catalog or '/JavaScript' in names or '/EmbeddedFiles' in names:
            raise ParseFailure('UNSAFE_DOCUMENT', 'Active PDF content or embedded files are not supported. Upload a flattened PDF.')
        if len(reader.pages) > MAX_PAGES:
            raise ParseFailure('PROCESSING_LIMIT', f'Documents must contain at most {MAX_PAGES} pages.')
        raster = None
        try:
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                if len(text.strip()) >= 15:
                    pages.append(Page(number, text))
                    continue
                if raster is None:
                    raster = pdfium.PdfDocument(raw)
                rendered = raster[number - 1]
                if rendered.get_width() * rendered.get_height() * 4 > 30_000_000:
                    rendered.close()
                    raise ParseFailure('PROCESSING_LIMIT', 'PDF page exceeds rasterization limits.')
                bitmap = rendered.render(scale=2)
                try:
                    try:
                        text, quality = ocr_image(bitmap.to_pil())
                        pages.append(Page(number, text, True, quality))
                    except Exception:
                        pages.append(Page(number, '', True, 0))
                        warnings.append(('partial_processing', 'warning', f'Page {number} could not be read', 'OCR failed for this page. Its page anchor is preserved; supply a clearer copy.'))
                finally:
                    bitmap.close()
                    rendered.close()
        finally:
            if raster is not None:
                raster.close()
    elif media_type.endswith('wordprocessingml.document'):
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(z.file_size for z in archive.infolist()) > 100 * 1024 * 1024 or len(archive.infolist()) > 5000:
                    raise ParseFailure('PROCESSING_LIMIT', 'Expanded DOCX exceeds processing limits.')
                if any('vbaProject' in z.filename or '/embeddings/' in z.filename for z in archive.infolist()):
                    raise ParseFailure('UNSAFE_DOCUMENT', 'Embedded programs or objects are not supported.')
            source = Document(io.BytesIO(raw))
        except (zipfile.BadZipFile, KeyError):
            raise ParseFailure('INVALID_CONTENT', 'The file is not a valid DOCX document.')
        parts = []
        for node in source.element.body.iterchildren():
            if node.tag.endswith('}p'):
                paragraph = Paragraph(node, source)
                parts.append(paragraph.text)
            elif node.tag.endswith('}tbl'):
                table = Table(node, source)
                parts.extend(' | '.join(cell.text for cell in row.cells) for row in table.rows)
        pages = [Page(1, '\n'.join(parts))]
        if source.sections or source.inline_shapes:
            warnings.append(('partial_processing', 'info', 'DOCX layout', 'Page numbers are not available for DOCX. Text and tables preserve body order; embedded images, headers, footers and comments are not indexed.'))
    elif media_type == 'application/msword':
        import shutil
        import subprocess
        import tempfile
        converter = shutil.which('antiword')
        if not converter:
            raise ParseFailure('DOC_PARSER_UNAVAILABLE', 'This server has no legacy DOC parser. Use the supplied cloud image or convert the file to DOCX/PDF.')
        if not raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            raise ParseFailure('INVALID_CONTENT', 'The file is not a supported binary Word document. Export as DOCX or PDF.')
        # Antiword extracts text; it does not launch Word or execute document macros.
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run([converter, '-m', 'UTF-8.txt', '-w', '0', '-'], input=raw, stdout=output, stderr=subprocess.DEVNULL, timeout=60, check=False)
            except subprocess.TimeoutExpired:
                raise ParseFailure('PROCESSING_LIMIT', 'Legacy DOC parsing exceeded 60 seconds.')
            if result.returncode:
                raise ParseFailure('INVALID_CONTENT', 'The DOC could not be read. Export an unlocked DOCX or PDF.')
            if output.tell() > MAX_TEXT * 4:
                raise ParseFailure('PROCESSING_LIMIT', 'Extracted DOC text exceeds processing limits.')
            output.seek(0)
            pages = [Page(1, output.read().decode('utf-8'))]
        warnings.append(('partial_processing', 'warning', 'Legacy DOC extraction', 'Text only; page numbers, embedded images and layout are unavailable. Verify against the original document.'))
    else:
        from PIL import Image, ImageSequence
        with Image.open(io.BytesIO(raw)) as image:
            expected = {'image/png':'PNG', 'image/jpeg':'JPEG', 'image/tiff':'TIFF'}
            if image.format != expected.get(media_type):
                raise ParseFailure('INVALID_CONTENT', 'Image content does not match its declared format.')
            if image.width * image.height > 30_000_000:
                raise ParseFailure('PROCESSING_LIMIT', 'Image exceeds 30 million pixels.')
            for number, frame in enumerate(ImageSequence.Iterator(image), 1):
                if number > MAX_PAGES:
                    raise ParseFailure('PROCESSING_LIMIT', 'Image has too many frames.')
                try:
                    text, quality = ocr_image(frame)
                    pages.append(Page(number, text, True, quality))
                except Exception:
                    pages.append(Page(number, '', True, 0))
    if sum(len(p.text) for p in pages) > MAX_TEXT:
        raise ParseFailure('PROCESSING_LIMIT', 'Extracted text exceeds two million characters.')
    if not any(p.text.strip() for p in pages):
        raise ParseFailure('NO_READABLE_TEXT', 'No readable text found. Upload a clearer document.')
    for page in pages:
        if not page.text.strip():
            warnings.append(('partial_processing', 'warning', f'Page {page.number} has no readable text', 'This page was preserved but could not be indexed; check the original source.'))
        if page.ocr:
            warnings.append(('ocr_quality', 'warning' if (page.quality or 0) < .85 else 'info', f'OCR used on page {page.number}', 'Extracted text may contain recognition errors; compare cited passages with the original.'))
    return {'pages': [vars(p) for p in pages], 'warnings': warnings, 'parser_version': PARSER_VERSION}


def chunks(text, maximum=1200):
    """Prefer paragraph/sentence boundaries while keeping exact, contiguous offsets."""
    start = 0
    while start < len(text):
        end = min(start + maximum, len(text))
        if end < len(text):
            boundary = text.rfind('\n', start + maximum // 3, end)
            if boundary < 0:
                candidates = list(re.finditer(r'[.!?]\s+', text[start + maximum // 3:end]))
                boundary = start + maximum // 3 + candidates[-1].end() - 1 if candidates else -1
            if boundary >= 0:
                end = boundary + 1
        yield start, end, text[start:end]
        start = end
