#!/usr/bin/env python3
"""Script de manipulation et modification sécurisée de documents Word (.docx).

Préserve 100% de la structure OpenXML, des styles, polices, tableaux et métadonnées
sans introduire de corruption de namespaces (ns0/ns1) en opérant au niveau des nœuds <w:t>
au sein des paragraphes <w:p>.
Supporte également l'insertion et le remplacement d'images (diagrammes Gantt).
"""

import argparse
import html
import io
import json
import os
import re
import shutil
import struct
import sys
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def extract_paragraphs(xml_content: str):
    """Extrait la liste des paragraphes et leurs textes concaténés."""
    p_pattern = re.compile(r'(<w:p\b[^>]*>.*?</w:p>)', re.DOTALL)
    t_pattern = re.compile(r'<w:t\b[^>]*>(.*?)</w:t>', re.DOTALL)
    
    paragraphs = []
    for i, p_match in enumerate(p_pattern.finditer(xml_content)):
        p_xml = p_match.group(1)
        raw_runs = t_pattern.findall(p_xml)
        text = ''.join(html.unescape(t) for t in raw_runs)
        paragraphs.append((i, p_xml, text, raw_runs))
    return paragraphs


def replace_in_paragraph(p_xml: str, old_text: str, new_text: str) -> tuple[str, int]:
    """Remplace old_text par new_text au sein d'un paragraphe XML <w:p>.
    
    Gère les remplacements mono-run et multi-runs avec offset d'avancement pour éviter
    les boucles infinies lorsque old_text est contenu dans new_text.
    """
    t_pattern = re.compile(r'(<w:t\b[^>]*>)(.*?)(</w:t>)', re.DOTALL)
    matches = list(t_pattern.finditer(p_xml))
    if not matches:
        return p_xml, 0

    runs_text = [html.unescape(m.group(2)) for m in matches]
    full_text = ''.join(runs_text)

    if old_text not in full_text:
        return p_xml, 0

    replacement_count = 0
    search_offset = 0

    while True:
        start_pos = full_text.find(old_text, search_offset)
        if start_pos == -1:
            break

        end_pos = start_pos + len(old_text)

        curr = 0
        new_runs = list(runs_text)
        first_run = None

        for i, r in enumerate(runs_text):
            r_len = len(r)
            r_start = curr
            r_end = curr + r_len
            curr = r_end

            if r_end <= start_pos or r_start >= end_pos:
                continue

            local_start = max(0, start_pos - r_start)
            local_end = min(r_len, end_pos - r_start)

            if first_run is None:
                first_run = i
                prefix = r[:local_start]
                if r_end >= end_pos:
                    suffix = r[local_end:]
                    new_runs[i] = prefix + new_text + suffix
                else:
                    new_runs[i] = prefix + new_text
            else:
                if r_end >= end_pos:
                    suffix = r[local_end:]
                    new_runs[i] = suffix
                else:
                    new_runs[i] = ''

        # Reconstruire le XML du paragraphe
        res = p_xml
        for idx in reversed(range(len(matches))):
            m = matches[idx]
            open_tag = m.group(1)
            close_tag = m.group(3)
            raw_val = new_runs[idx]
            escaped_val = html.escape(raw_val, quote=False)

            if (raw_val.startswith(' ') or raw_val.endswith(' ')) and 'xml:space' not in open_tag:
                open_tag = open_tag[:-1] + ' xml:space="preserve">'

            formatted_val = escaped_val.replace('\n', '</w:t><w:br/><w:t xml:space="preserve">')
            res = res[:m.start()] + open_tag + formatted_val + close_tag + res[m.end():]

        p_xml = res
        replacement_count += 1

        matches = list(t_pattern.finditer(p_xml))
        runs_text = [html.unescape(m.group(2)) for m in matches]
        full_text = ''.join(runs_text)
        search_offset = start_pos + len(new_text)

    return p_xml, replacement_count


def process_docx_replacements(docx_path: str, replacements: list[tuple[str, str]], output_path: str = None, make_backup: bool = True) -> dict[str, int]:
    """Applique une liste de couples (ancien_texte, nouveau_texte) sur un fichier docx."""
    docx_file = Path(docx_path).resolve()
    if not docx_file.exists():
        raise FileNotFoundError(f"Fichier introuvable : {docx_path}")

    out_file = Path(output_path).resolve() if output_path else docx_file

    if make_backup and out_file == docx_file:
        backup_path = docx_file.with_suffix('.bak.docx')
        shutil.copy2(docx_file, backup_path)
        print(f"Sauvegarde créée : {backup_path}")

    normalized = []
    for r in replacements:
        if isinstance(r, dict):
            normalized.append((r["old"], r["new"], r.get("p_index")))
        elif isinstance(r, (list, tuple)):
            p_idx = r[2] if len(r) > 2 else None
            normalized.append((r[0], r[1], p_idx))

    with zipfile.ZipFile(docx_file, 'r') as zin:
        xml_entries = {}
        other_entries = {}
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename.startswith('word/') and item.filename.endswith('.xml'):
                xml_entries[item] = content.decode('utf-8')
            else:
                other_entries[item] = content

    results = {}
    for old_txt, _, p_idx in normalized:
        key = f"{old_txt} [P{p_idx:03d}]" if p_idx is not None else old_txt
        results[key] = 0

    modified_xmls = {}
    for item, xml_str in xml_entries.items():
        curr_xml = xml_str
        for old_txt, new_txt, target_p in normalized:
            key = f"{old_txt} [P{target_p:03d}]" if target_p is not None else old_txt
            parts = re.split(r'(<w:p\b[^>]*>.*?</w:p>)', curr_xml, flags=re.DOTALL)
            new_parts = []
            p_idx = 0
            for part in parts:
                if part.startswith('<w:p'):
                    if target_p is None or p_idx == target_p:
                        new_p, count = replace_in_paragraph(part, old_txt, new_txt)
                        results[key] += count
                        new_parts.append(new_p)
                    else:
                        new_parts.append(part)
                    p_idx += 1
                else:
                    new_parts.append(part)
            curr_xml = ''.join(new_parts)
        modified_xmls[item] = curr_xml.encode('utf-8')

    # Écrire le nouveau docx
    tmp_out = out_file.with_suffix('.tmp.docx')
    with zipfile.ZipFile(tmp_out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item, content in other_entries.items():
            zout.writestr(item, content)
        for item, content in modified_xmls.items():
            zout.writestr(item, content)

    # Validation du zip généré
    with zipfile.ZipFile(tmp_out, 'r') as zval:
        doc_xml = zval.read('word/document.xml')
        ET.fromstring(doc_xml)

    tmp_out.replace(out_file)
    print(f"Document mis à jour avec succès : {out_file}")
    return results


def get_image_dimensions(img_bytes: bytes) -> tuple[int, int]:
    """Extrait la largeur et hauteur en pixels d'un fichier PNG ou JPEG."""
    if img_bytes.startswith(b'\x89PNG\r\n\x1a\n') and len(img_bytes) >= 24:
        return struct.unpack('>II', img_bytes[16:24])
    elif img_bytes.startswith(b'\xff\xd8'):
        # JPEG basic search
        idx = 2
        while idx < len(img_bytes) - 9:
            if img_bytes[idx] == 0xff and img_bytes[idx+1] in (0xc0, 0xc2):
                h, w = struct.unpack('>HH', img_bytes[idx+5:idx+9])
                return w, h
            idx += 1
    return 1600, 900


def insert_image_after_heading(docx_path: str, heading_query: str, image_path: str, output_path: str = None, make_backup: bool = True) -> bool:
    """Insère ou remplace une image directement sous le titre indiqué."""
    docx_file = Path(docx_path).resolve()
    img_file = Path(image_path).resolve()

    if not docx_file.exists():
        raise FileNotFoundError(f"Fichier docx introuvable : {docx_path}")
    if not img_file.exists():
        raise FileNotFoundError(f"Fichier image introuvable : {image_path}")

    out_file = Path(output_path).resolve() if output_path else docx_file

    if make_backup and out_file == docx_file:
        backup_path = docx_file.with_suffix('.bak.docx')
        shutil.copy2(docx_file, backup_path)
        print(f"Sauvegarde créée : {backup_path}")

    img_bytes = img_file.read_bytes()
    img_w, img_h = get_image_dimensions(img_bytes)

    # Dimensions en EMUs (1 inch = 914400 EMUs). Largeur standard : 5.8 pouces = 5303520 EMUs
    target_cx = 5303520
    target_cy = int(target_cx * (img_h / max(1, img_w)))

    media_ext = img_file.suffix.lower() or ".png"
    unique_id = uuid.uuid4().hex[:8]
    media_name = f"gantt_{unique_id}{media_ext}"
    rel_id = f"rIdGantt{unique_id}"
    doc_pr_id = int(unique_id, 16) % 1000000 + 100

    drawing_xml = f'''<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"><wp:extent cx="{target_cx}" cy="{target_cy}" /><wp:effectExtent l="0" t="0" r="0" b="0" /><wp:docPr id="{doc_pr_id}" name="Diagramme Gantt" /><wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1" /></wp:cNvGraphicFramePr><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="{doc_pr_id}" name="Diagramme Gantt" /><pic:cNvPicPr /></pic:nvPicPr><pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rel_id}" /><a:stretch><a:fillRect /></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0" /><a:ext cx="{target_cx}" cy="{target_cy}" /></a:xfrm><a:prstGeom prst="rect"><a:avLst /></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'''

    with zipfile.ZipFile(docx_file, 'r') as zin:
        entries = {}
        for item in zin.infolist():
            entries[item.filename] = zin.read(item.filename)

    doc_xml = entries['word/document.xml'].decode('utf-8')
    rels_xml = entries['word/_rels/document.xml.rels'].decode('utf-8')

    # 1. Ajouter la relation dans word/_rels/document.xml.rels
    new_rel = f'<Relationship Id="{rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{media_name}" />'
    if '</Relationships>' not in rels_xml:
        raise ValueError("Fichier document.xml.rels invalide")
    rels_xml = rels_xml.replace('</Relationships>', f'  {new_rel}\n</Relationships>')
    entries['word/_rels/document.xml.rels'] = rels_xml.encode('utf-8')

    # 2. Ajouter l'image dans word/media/
    entries[f'word/media/{media_name}'] = img_bytes

    # 3. Insérer le drawing_xml sous le paragraphe contenant heading_query
    p_pattern = re.compile(r'(<w:p\b[^>]*>.*?</w:p>)', re.DOTALL)
    t_pattern = re.compile(r'<w:t\b[^>]*>(.*?)</w:t>', re.DOTALL)

    parts = p_pattern.split(doc_xml)
    inserted = False
    new_parts = []

    # Recherche du paragraphe cible le plus pertinent
    candidates = []
    in_gantt = False
    for idx, part in enumerate(parts):
        if part.startswith('<w:p'):
            raw_runs = t_pattern.findall(part)
            text = ''.join(html.unescape(t) for t in raw_runs).strip()
            if text.lower() == 'diagrammes de gantt':
                in_gantt = True
            if heading_query.lower() in text.lower():
                candidates.append((idx, text, in_gantt))

    target_idx = None
    if candidates:
        gantt_candidates = [c for c in candidates if c[2]]
        if gantt_candidates:
            target_idx = gantt_candidates[0][0]
        else:
            # Hors section gantt, préférer le dernier candidat (évite la page de garde ou la TOC)
            target_idx = candidates[-1][0]

    if target_idx is None:
        print(f"Avertissement : Titre '{heading_query}' non trouvé dans document.xml")
        return False

    for idx, part in enumerate(parts):
        new_parts.append(part)
        if idx == target_idx:
            new_parts.append(drawing_xml)
            inserted = True

    entries['word/document.xml'] = ''.join(new_parts).encode('utf-8')

    # Écrire le nouveau docx
    tmp_out = out_file.with_suffix('.tmp.docx')
    with zipfile.ZipFile(tmp_out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for fname, content in entries.items():
            zout.writestr(fname, content)

    # Validation
    with zipfile.ZipFile(tmp_out, 'r') as zval:
        ET.fromstring(zval.read('word/document.xml'))

    tmp_out.replace(out_file)
    print(f"Image insérée avec succès sous '{heading_query}' : {out_file}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Outil de manipulation et d'édition sécurisée de fichiers DOCX.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Commande view
    view_parser = subparsers.add_parser("view", help="Affiche les paragraphes du document")
    view_parser.add_argument("docx", help="Chemin du document .docx")
    view_parser.add_argument("--search", "-s", help="Filtre sur un mot ou expression")
    view_parser.add_argument("--limit", "-n", type=int, default=50, help="Nombre max de paragraphes affichés")

    # Commande replace
    repl_parser = subparsers.add_parser("replace", help="Effectue des remplacements de texte")
    repl_parser.add_argument("docx", help="Chemin du document .docx")
    repl_parser.add_argument("--find", "-f", help="Texte à chercher")
    repl_parser.add_argument("--replace-with", "-r", help="Texte de remplacement")
    repl_parser.add_argument("--json", "-j", help="Fichier JSON ou chaîne JSON contenant les paires {ancien: nouveau}")
    repl_parser.add_argument("--out", "-o", help="Fichier de sortie (par défaut modifie sur place)")
    repl_parser.add_argument("--no-backup", action="store_true", help="Désactive la création de sauvegarde .bak.docx")

    # Commande insert-image
    img_parser = subparsers.add_parser("insert-image", help="Insère une image (ex: Gantt) sous un titre")
    img_parser.add_argument("docx", help="Chemin du document .docx")
    img_parser.add_argument("--after-heading", "-H", required=True, help="Texte du titre sous lequel insérer l'image")
    img_parser.add_argument("--image", "-i", required=True, help="Chemin de l'image (PNG ou JPEG)")
    img_parser.add_argument("--out", "-o", help="Fichier de sortie")
    img_parser.add_argument("--no-backup", action="store_true", help="Désactive la sauvegarde")

    args = parser.parse_args()

    if args.command == "view":
        docx_path = Path(args.docx).resolve()
        with zipfile.ZipFile(docx_path, 'r') as z:
            doc_xml = z.read('word/document.xml').decode('utf-8')
        paragraphs = extract_paragraphs(doc_xml)
        count = 0
        for i, _, text, runs in paragraphs:
            if not text.strip():
                continue
            if args.search and args.search.lower() not in text.lower():
                continue
            print(f"[P{i:03d}] {text}")
            count += 1
            if count >= args.limit:
                break
        print(f"\nTotal affiché : {count} paragraphe(s)")

    elif args.command == "replace":
        replacements = []
        if args.json:
            j_str = args.json
            if os.path.exists(j_str):
                with open(j_str, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = json.loads(j_str)
            
            if isinstance(data, dict):
                replacements = list(data.items())
            elif isinstance(data, list):
                replacements = data
        elif args.find and args.replace_with is not None:
            replacements = [(args.find, args.replace_with)]
        else:
            parser.error("Spécifiez soit --find et --replace-with, soit --json.")

        results = process_docx_replacements(
            args.docx,
            replacements,
            output_path=args.out,
            make_backup=not args.no_backup
        )
        print("\nBilan des remplacements :")
        for key, cnt in results.items():
            status = "✓" if cnt > 0 else "✗ (0 match)"
            print(f"  {status} [{cnt}] '{key[:60]}'")

    elif args.command == "insert-image":
        insert_image_after_heading(
            args.docx,
            args.after_heading,
            args.image,
            output_path=args.out,
            make_backup=not args.no_backup
        )


if __name__ == '__main__':
    main()
