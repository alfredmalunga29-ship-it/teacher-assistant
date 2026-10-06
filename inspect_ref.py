from zipfile import ZipFile
from xml.etree import ElementTree as ET
import os

root = os.path.join(os.getcwd(), 'Lesson Plans')
files = [os.path.join(root, f) for f in os.listdir(root) if f.lower().endswith('.docx')]
with open('inspect_ref_output.txt', 'w', encoding='utf-8') as out:
    if not files:
        out.write('NO_DOCX_FOUND')
        raise SystemExit
    file = files[0]
    out.write(f'FILE: {os.path.basename(file)}\n')
    with ZipFile(file) as z:
        if 'word/document.xml' not in z.namelist():
            out.write('NO_DOCUMENT_XML')
            raise SystemExit
        xml = z.read('word/document.xml')
        rootxml = ET.fromstring(xml)
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paras = []
        for p in rootxml.findall('.//w:p', ns):
            txt = ''.join(t.text or '' for t in p.findall('.//w:t', ns))
            if txt.strip():
                paras.append(txt.strip())
        out.write(f'PARAS: {len(paras)}\n')
        for i, txt in enumerate(paras[:40], 1):
            out.write(f'{i}: {txt}\n')
        tbls = rootxml.findall('.//w:tbl', ns)
        out.write(f'TBLS: {len(tbls)}\n')
        for ti, tbl in enumerate(tbls[:5], 1):
            cells = []
            for cell in tbl.findall('.//w:tc', ns):
                val = ''.join(t.text or '' for t in cell.findall('.//w:t', ns))
                if val.strip():
                    cells.append(val.strip())
            if cells:
                out.write(f'TBL {ti}: {cells}\n')
print('done')
