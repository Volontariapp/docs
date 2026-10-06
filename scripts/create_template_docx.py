#!/usr/bin/env python3
"""Générateur de rapport template Word (.docx) pour le coaching.

Prend le rapport de référence, préserve 100% de la structure OpenXML,
des styles de paragraphes (Headings, listes, puces graphiques), des polices,
tableaux et métadonnées, et remplace tous les contenus par des balises
'Sprint <TODO>' et '[TODO]' explicites.
"""

import copy
import html
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def set_p_text(p, new_text):
    """Met à jour le texte d'un paragraphe en préservant w:pPr et le formatage du premier w:r."""
    w_t = '{' + NS['w'] + '}t'
    w_r = '{' + NS['w'] + '}r'
    w_pPr = '{' + NS['w'] + '}pPr'
    w_br = '{' + NS['w'] + '}br'

    # Conserver pPr s'il existe
    pPr = p.find(w_pPr)
    
    # Trouver le premier rPr pour hériter des styles
    first_r = p.find(w_r)
    rPr = first_r.find('{' + NS['w'] + '}rPr') if first_r is not None else None

    # Vider les enfants sauf pPr
    to_remove = [c for c in list(p) if c.tag != w_pPr]
    for c in to_remove:
        p.remove(c)

    # Créer le nouveau run avec le texte
    new_r = ET.SubElement(p, w_r)
    if rPr is not None:
        new_r.append(copy.deepcopy(rPr))

    # Gérer les retours à la ligne
    lines = new_text.split('\n')
    for idx, line in enumerate(lines):
        t_elem = ET.SubElement(new_r, w_t)
        t_elem.text = line
        if line.startswith(' ') or line.endswith(' '):
            t_elem.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        if idx < len(lines) - 1:
            ET.SubElement(new_r, w_br)


def build_template():
    coaching_dir = Path("docs/coaching")
    src_docx = coaching_dir / "Rapport de suivi coaching 7.docx"
    dest_docx = coaching_dir / "template_rapport_coaching.docx"
    alt_docx = coaching_dir / "Rapport de suivi coaching template.docx"

    if not src_docx.exists():
        print(f"Erreur : {src_docx} introuvable.", file=sys.stderr)
        sys.exit(1)

    print(f"Extraction et analyse de : {src_docx}")
    with zipfile.ZipFile(src_docx, "r") as z_in:
        files = {name: z_in.read(name) for name in z_in.namelist()}

    xml_bytes = files["word/document.xml"]
    root = ET.fromstring(xml_bytes)
    body = root.find('w:body', NS)

    # 1. Mise à jour de la Table des matières (SDT)
    for sdt in body.findall('w:sdt', NS):
        for p in sdt.findall('.//w:p', NS):
            text = ''.join(p.itertext()).strip()
            if 'SPRINT 7' in text:
                for t in p.findall('.//w:t', NS):
                    if t.text and 'SPRINT 7' in t.text:
                        t.text = t.text.replace('SPRINT 7', 'SPRINT <TODO_BILAN>')
            elif 'SPRINT 8' in text:
                for t in p.findall('.//w:t', NS):
                    if t.text and 'SPRINT 8' in t.text:
                        t.text = t.text.replace('SPRINT 8', 'SPRINT <TODO_PROJ>')
            elif 'VICTOR AGAHI' in text:
                for t in p.findall('.//w:t', NS):
                    if t.text:
                        t.text = re.sub(r'VICTOR AGAHI – .*', 'VICTOR AGAHI – <TODO>', t.text)
            elif 'VICTOR GIROUD' in text:
                for t in p.findall('.//w:t', NS):
                    if t.text:
                        t.text = re.sub(r'VICTOR GIROUD – .*', 'VICTOR GIROUD – <TODO>', t.text)
            elif 'CLÉMENT PASTEAU' in text:
                for t in p.findall('.//w:t', NS):
                    if t.text:
                        t.text = re.sub(r'CLÉMENT PASTEAU – .*', 'CLÉMENT PASTEAU – <TODO>', t.text)
            elif 'Victor Giroud' in text and 'Gantt' not in text:
                for t in p.findall('.//w:t', NS):
                    if t.text:
                        t.text = re.sub(r'Victor Giroud.*', 'Victor Giroud : <TODO>', t.text)
            elif 'Victor Agahi' in text:
                for t in p.findall('.//w:t', NS):
                    if t.text:
                        t.text = re.sub(r'Victor Agahi.*', 'Victor Agahi : <TODO>', t.text)
            elif 'Clément PASTEAU' in text:
                for t in p.findall('.//w:t', NS):
                    if t.text:
                        t.text = re.sub(r'Clément PASTEAU.*', 'Clément PASTEAU : <TODO>', t.text)

    # 2. Mise à jour des Tableaux
    tables = body.findall('w:tbl', NS)
    if len(tables) >= 3:
        # Tableau 0 : Propriétés
        for tr in tables[0].findall('w:tr', NS):
            cells = tr.findall('w:tc', NS)
            if len(cells) == 2:
                c0 = ''.join(cells[0].itertext()).strip()
                if c0 == 'Nom fichier':
                    set_p_text(cells[1].find('w:p', NS), 'Rapport de suivi coaching <TODO>')
                elif c0 == 'Version':
                    set_p_text(cells[1].find('w:p', NS), '1.0')

        # Tableau 2 : Répartition des Tâches
        tr_list = tables[2].findall('w:tr', NS)
        if len(tr_list) >= 4:
            # Ligne 1
            cells = tr_list[1].findall('w:tc', NS)
            if len(cells) == 3:
                set_p_text(cells[0].find('w:p', NS), '[TODO Tâche 1]')
                set_p_text(cells[1].find('w:p', NS), '[TODO Membres]')
                set_p_text(cells[2].find('w:p', NS), '[TODO Lead]')
            # Ligne 2
            cells = tr_list[2].findall('w:tc', NS)
            if len(cells) == 3:
                set_p_text(cells[0].find('w:p', NS), '[TODO Tâche 2]')
                set_p_text(cells[1].find('w:p', NS), '[TODO Membres]')
                set_p_text(cells[2].find('w:p', NS), '[TODO Lead]')
            # Ligne 3
            cells = tr_list[3].findall('w:tc', NS)
            if len(cells) == 3:
                set_p_text(cells[0].find('w:p', NS), '[TODO Tâche 3]')
                set_p_text(cells[1].find('w:p', NS), '[TODO Membres]')
                set_p_text(cells[2].find('w:p', NS), '[TODO Lead]')

    # 3. Parcours des paragraphes du document
    paragraphs = body.findall('w:p', NS)
    
    # Page de garde (P0)
    if len(paragraphs) > 0:
        for t in paragraphs[0].findall('.//w:t', NS):
            if t.text:
                t.text = re.sub(r'Coaching \d+ - PLIC', 'Coaching <TODO> - PLIC', t.text)
                t.text = re.sub(r'\d{2}/\d{2}/\d{4}', '<DATE_TODO>', t.text)

    # Mapper les sections clés par contenu
    for i, p in enumerate(paragraphs):
        text = ''.join(p.itertext()).strip()

        # Section SPRINT BILAN
        if text.startswith('SPRINT 7'):
            set_p_text(p, 'SPRINT <TODO_BILAN>')
        elif text.startswith('Côté backend'):
            set_p_text(p, "[TODO] Synthèse globale de l'avancement et des objectifs atteints lors du Sprint <TODO_BILAN> (périmètre backend, frontend, infrastructure et coordination).")
        elif text.startswith('Côté frontend'):
            set_p_text(p, "")

        # Victor Agahi
        elif 'VICTOR AGAHI' in text and ('–' in text or '-' in text):
            set_p_text(p, 'VICTOR AGAHI – <TODO>')
        elif text.startswith('Observabilité Datadog') or text.startswith('Monitoring (avec Clément)'):
            set_p_text(p, "[TODO] Synthèse détaillée des réalisations techniques de Victor Agahi pour le Sprint <TODO_BILAN> (architecture, microservices, DevOps, Kubernetes, observabilité, etc.).")
        elif text.startswith('Déploiement GitOps') or text.startswith('Configuration de l\'agent Datadog'):
            set_p_text(p, "[TODO] Réalisation clé 1 (ex: déploiement d'infrastructure, intégration réseau)")
        elif text.startswith('Résolution des blocages') or text.startswith('Résolution des blocages techniques'):
            set_p_text(p, "[TODO] Réalisation clé 2 (ex: configuration de services, métriques)")
        elif text.startswith('Objectif atteint'):
            set_p_text(p, "[TODO] Objectif atteint pour le Sprint <TODO_BILAN>")
        elif text.startswith('Stockage de fichiers - Prise en charge') or text.startswith('Stockage de fichiers Prise en charge'):
            set_p_text(p, "")
        elif text.startswith('Création et intégration du submodule') or text.startswith('Création des dépôts GitHub'):
            set_p_text(p, "")
        elif text.startswith('Rédaction des manifests Kustomize') or text.startswith('Connexion de chaque service'):
            set_p_text(p, "")
        elif text.startswith('Conteneurisation Docker') or text.startswith('Conteneurisation (Docker)'):
            set_p_text(p, "")
        elif text.startswith('Configuration et durcissement des Network Policies') or text.startswith('Configuration des Network Policies'):
            set_p_text(p, "")

        # Victor Giroud
        elif 'VICTOR GIROUD' in text and ('–' in text or '-' in text):
            set_p_text(p, 'VICTOR GIROUD – <TODO>')
        elif text.startswith('Durant le Sprint') or text == 'TODO':
            set_p_text(p, "[TODO] Synthèse détaillée des réalisations techniques de Victor Giroud pour le Sprint <TODO_BILAN> (features mobiles, React Native, UI/UX, navigation, gamification, etc.).")

        # Clément Pasteau
        elif 'CLÉMENT PASTEAU' in text and ('–' in text or '-' in text):
            set_p_text(p, 'CLÉMENT PASTEAU – <TODO>')
        elif text.startswith('Pendant ce sprint de'):
            set_p_text(p, "[TODO] Synthèse détaillée des réalisations techniques de Clément Pasteau pour le Sprint <TODO_BILAN> (backend, gRPC, domain packages, stockage S3/MinIO, tests d'intégration, etc.).")
        elif text.startswith('En parallèle, j\'ai pris en charge'):
            set_p_text(p, "")

        # Section SPRINT PROJECTION
        elif text.startswith('SPRINT 8'):
            set_p_text(p, 'SPRINT <TODO_PROJ>')
        elif text.startswith('Pour la prochaine période, nous allons présenter le Sprint'):
            set_p_text(p, "Pour la prochaine période, nous allons présenter le Sprint <TODO_PROJ> qui s’étale du <DATE_DEBUT_TODO> au <DATE_FIN_TODO>, pour une durée de <DUREE_SEMAINES_TODO> semaines.")
        elif text.startswith('Stockage de fichiers') and i > 50 and i < 65:
            set_p_text(p, "[TODO] Axe 1 de développement")
        elif text.startswith('Observabilité & Monitoring') and i > 50 and i < 65:
            set_p_text(p, "[TODO] Axe 2 de développement")
        elif (text.startswith('Système de Badges') or text.startswith('TODO')) and i > 50 and i < 65:
            set_p_text(p, "[TODO] Axe 3 de développement")
        elif text.startswith('Vous trouverez via le lien ci-joint la page vers le backlog'):
            set_p_text(p, "Vous trouverez via le lien ci-joint la page vers le backlog du Sprint <TODO_PROJ> :")
        elif text.startswith('https://') and i > 55 and i < 65:
            set_p_text(p, "[TODO_URL_NOTION_BACKLOG]")
        elif text.startswith('Comme mentionné plus haut'):
            set_p_text(p, "Comme mentionné plus haut, chaque tâche se voit associée à deux membres, qui joueront des rôles différents dans la réalisation de cette tâche. Pour ce Sprint <TODO_PROJ>, la répartition est la suivante :")

        # Section Diagrammes de Gantt
        elif text.startswith('Victor Giroud') and ('Gantt' in text or 'Badges' in text or 'TODO' in text or ':' in text) and i > 65:
            set_p_text(p, 'Victor Giroud : <TODO>')
            if i + 1 < len(paragraphs):
                set_p_text(paragraphs[i + 1], '[TODO - Diagramme de Gantt PNG]')
        elif text.startswith('Victor Agahi') and i > 65:
            set_p_text(p, 'Victor Agahi : <TODO>')
        elif 'Clément PASTEAU' in text and i > 65:
            set_p_text(p, 'Clément PASTEAU : <TODO>')

        # Conclusion
        elif text.startswith('Ce Sprint') or text.startswith('Nous sommes très confiants'):
            set_p_text(p, "[TODO] Synthèse conclusive de l'avancement global de l'équipe, métriques consolidées et perspectives d'atterrissage pour le Sprint <TODO_PROJ>.")

        # Supprimer les images existantes dans la section Gantt pour un template propre
        if i > 67 and i < 94:
            drawings = p.findall('.//{' + NS['w'] + '}drawing')
            if drawings:
                set_p_text(p, "[TODO - Diagramme de Gantt PNG]")

    # Sérialisation sans corrompre le XML
    xml_output = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    files["word/document.xml"] = xml_output

    dest_docx.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_docx, "w", zipfile.ZIP_DEFLATED) as z_out:
        for name, data in files.items():
            z_out.writestr(name, data)

    print(f"✓ Template DOCX finalisé : {dest_docx} ({dest_docx.stat().st_size} octets)")
    
    import shutil
    shutil.copyfile(dest_docx, alt_docx)
    print(f"✓ Copie conforme : {alt_docx}")


if __name__ == "__main__":
    build_template()
