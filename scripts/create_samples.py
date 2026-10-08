"""Reproducible, synthetic shared-workflow fixtures. No real legal authorities."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / 'frontend' / 'samples'
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / 'service-agreement.txt').write_text('''SERVICE AGREEMENT

1. PARTIES
This sample agreement is between Cedar Labs (Client) and Northstar Services (Supplier).

2. PAYMENT
The Client shall pay INR 150,000 on 15 October 2026. Invoice disputes must be notified within seven days.

3. TERMINATION
Either party may terminate by giving 30 days written notice. The termination schedule referenced in Annexure B is not attached.

4. GOVERNING LAW
The parties identify India as the jurisdiction for this sample agreement.

Synthetic demonstration source. This document is not legal advice or an executed agreement.
''', encoding='utf-8')
(ROOT / 'payment-amendment.txt').write_text('''PAYMENT AMENDMENT

1. PARTIES
Cedar Labs and Northstar Services record the following sample payment amendment.

2. PAYMENT DATE
The Client shall pay INR 150,000 on 30 October 2026. This date differs from the payment date stated in the service agreement.

3. SIGNATURES
The supplied copy has no signatures. Whether this amendment is effective cannot be established from this source alone.

Synthetic demonstration source. No finding about enforceability is made.
''', encoding='utf-8')
image = Image.new('RGB', (1240, 1754), 'white')
draw = ImageDraw.Draw(image)
font_path = Path('C:/Windows/Fonts/arial.ttf')
font = ImageFont.truetype(str(font_path), 31) if font_path.exists() else ImageFont.load_default(size=31)
lines = ['ANNEXURE A - DELIVERY SCHEDULE', '', 'Cedar Labs / Northstar Services', '', 'Milestone 1: Source documents delivered on 10 October 2026.', '', 'Milestone 2: Review meeting scheduled for 20 October 2026.', '', 'Payment reference: INR 150,000.', '', 'Annexure B: Not included in this scanned copy.', '', 'Synthetic demonstration source.']
for index, line in enumerate(lines):
    draw.text((90, 120 + index * 75), line, fill='#202020', font=font)
image.save(ROOT / 'scanned-annexure.pdf', 'PDF', resolution=150)
image.save(ROOT / 'scanned-annexure.png')
