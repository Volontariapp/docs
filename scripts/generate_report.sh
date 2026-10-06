#!/usr/bin/env bash
set -euo pipefail

# Couleurs pour l'affichage
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
META_DIR="$(cd "${DOCS_DIR}/.." && pwd)"
COACHING_DIR="${DOCS_DIR}/coaching"

# Option de nettoyage des fichiers temporaires
if [ "${1:-}" = "--clean" ]; then
  echo -e "${YELLOW}🧹 Nettoyage des fichiers temporaires en cours...${NC}"
  rm -f "${COACHING_DIR}"/*.bak*
  rm -f "${COACHING_DIR}"/*/*.zip "${COACHING_DIR}"/*/*.pdf
  rm -f "${SCRIPT_DIR}"/test_*.mjs "${SCRIPT_DIR}"/download_and_extract_gantt.mjs
  rm -rf /tmp/pw_test
  echo -e "${GREEN}✓ Tous les fichiers temporaires et archives ont été nettoyés.${NC}"
  exit 0
fi

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}   Générateur Automatisé de Rapport Coaching Volontariapp${NC}"
echo -e "${CYAN}======================================================${NC}\n"

# 1. Vérification du fichier .env
ENV_FILE="${DOCS_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
  echo -e "${RED}Erreur : Fichier ${ENV_FILE} introuvable !${NC}"
  echo "Veuillez créer docs/.env contenant NOTION_TOKEN=ntn_..."
  exit 1
fi

if ! grep -q "NOTION_TOKEN" "${ENV_FILE}"; then
  echo -e "${RED}Erreur : NOTION_TOKEN non trouvé dans ${ENV_FILE} !${NC}"
  exit 1
fi

# 2. Demande du Sprint / Coaching à traiter
echo -e "${YELLOW}Quel numéro de Coaching / Sprint terminé souhaitez-vous rapporter ?${NC}"
echo -e "${CYAN}Principe du rapport :${NC}"
echo -e "  - Bilan des tâches terminées : ${GREEN}Sprint N${NC} (ex: 7)"
echo -e "  - Diagrammes de Gantt & projection : ${GREEN}Sprint N+1${NC} (ex: 8)"
echo -e "  - Document généré : ${GREEN}Rapport de suivi coaching N.docx${NC}"
read -rp "Numéro du coaching (ex: 7) : " COACHING_NUM

if ! [[ "${COACHING_NUM}" =~ ^[0-9]+$ ]]; then
  echo -e "${RED}Erreur : Veuillez saisir un numéro entier valide.${NC}"
  exit 1
fi

SPRINT_BILAN="${COACHING_NUM}"
SPRINT_PROJ=$((COACHING_NUM + 1))
PREV_COACHING=$((COACHING_NUM - 1))

echo -e "\n${BLUE}ℹ️ Rapport : Coaching ${COACHING_NUM} | Bilan : Sprint ${SPRINT_BILAN} | Gantt & Projection : Sprint ${SPRINT_PROJ}${NC}"

mkdir -p "${COACHING_DIR}"

TARGET_DOCX="${COACHING_DIR}/Rapport de suivi coaching ${COACHING_NUM}.docx"
PREV_DOCX="${COACHING_DIR}/Rapport de suivi coaching ${PREV_COACHING}.docx"

# 3. Préparation du document DOCX
if [ ! -f "${TARGET_DOCX}" ]; then
  if [ -f "${COACHING_DIR}/template_rapport_coaching.docx" ]; then
    echo -e "${BLUE}📄 Duplication depuis le modèle de référence : template_rapport_coaching.docx${NC}"
    cp "${COACHING_DIR}/template_rapport_coaching.docx" "${TARGET_DOCX}"
    echo -e "${GREEN}✓ Créé : ${TARGET_DOCX}${NC}"
  elif [ -f "${PREV_DOCX}" ]; then
    echo -e "${BLUE}📄 Duplication du template depuis : ${PREV_DOCX}${NC}"
    cp "${PREV_DOCX}" "${TARGET_DOCX}"
    echo -e "${GREEN}✓ Créé : ${TARGET_DOCX}${NC}"
  else
    echo -e "${YELLOW}⚠️ Modèle template introuvable. Recherche d'un document existant alternatif...${NC}"
    EXISTING_DOCX=$(find "${COACHING_DIR}" -name "Rapport de suivi coaching *.docx" | head -n 1 || true)
    if [ -n "${EXISTING_DOCX}" ]; then
      echo -e "${BLUE}📄 Utilisation de ${EXISTING_DOCX} comme modèle...${NC}"
      cp "${EXISTING_DOCX}" "${TARGET_DOCX}"
    else
      echo -e "${RED}Erreur : Aucun document modèle .docx trouvé sous ${COACHING_DIR}${NC}"
      exit 1
    fi
  fi
else
  echo -e "${GREEN}✓ Le document cible existe déjà : ${TARGET_DOCX}${NC}"
fi

# 4. Extraction du Backlog Notion
CSV_OUTPUT="${COACHING_DIR}/sprint_${SPRINT_PROJ}_backlog.csv"
JSON_OUTPUT="${COACHING_DIR}/sprint_${SPRINT_BILAN}_completed.json"

echo -e "\n${BLUE}🔄 Extraction Notion en cours via l'API...${NC}"
python3 "${SCRIPT_DIR}/export_notion_backlog.py" \
  --sprint "${SPRINT_PROJ}" \
  --out-csv "${CSV_OUTPUT}" \
  --prev-sprint "${SPRINT_BILAN}" \
  --out-json "${JSON_OUTPUT}"

echo -e "${GREEN}✓ CSV généré pour le Gantt (Sprint ${SPRINT_PROJ}) : ${CSV_OUTPUT}${NC}"
echo -e "${GREEN}✓ Bilan des tâches terminées (Sprint ${SPRINT_BILAN}) : ${JSON_OUTPUT}${NC}"

# 5. Récupération automatisée des diagrammes de Gantt via Chromium
GANTT_DIR="${COACHING_DIR}/gantt_sprint_${SPRINT_PROJ}"
echo -e "\n${BLUE}📊 Récupération automatisée des diagrammes de Gantt pour le Sprint ${SPRINT_PROJ}...${NC}"
node "${SCRIPT_DIR}/fetch_gantt_images.mjs" \
  --sprint "${SPRINT_PROJ}" \
  --csv "${CSV_OUTPUT}" \
  --out "${GANTT_DIR}" || echo -e "${YELLOW}⚠️ La récupération directe a rencontré un avertissement. L'agent utilisera le fallback.${NC}"

# 6. Choix de l'agent
echo -e "\n${YELLOW}Quel agent IA souhaitez-vous lancer pour orchestrer les étapes ?${NC}"
echo "  1) claude (Claude Code CLI)"
echo "  2) agy (Antigravity CLI)"
read -rp "Votre choix (1 ou 2) [défaut: 1] : " AGENT_CHOICE
AGENT_CHOICE="${AGENT_CHOICE:-1}"

# 7. Rédaction du prompt complet
PROMPT_FILE="${COACHING_DIR}/PROMPT_COACHING_${COACHING_NUM}.md"

cat <<'EOF' > "${PROMPT_FILE}"
# MISSION : Automatisation du Rapport de Coaching __COACHING_NUM__

Tu dois mettre à jour le document Word `__TARGET_DOCX__` pour le **Coaching __COACHING_NUM__** :
- **Bilan** : Tâches terminées du **Sprint __SPRINT_BILAN__**
- **Projection & Gantt** : Planification du **Sprint __SPRINT_PROJ__**

> **IMPORTANT :**
> Tous les diagrammes de Gantt du **Sprint __SPRINT_PROJ__** ont DÉJÀ été téléchargés et décompressés avec succès dans :
> `docs/coaching/gantt_sprint___SPRINT_PROJ__/`
> **TU N'AS PAS BESOIN D'OUVRIR DE NAVIGATEUR NI D'ÉCRIRE DE SCRIPT PLAYWRIGHT.**
> Concentre-toi directement sur les modifications du document Word via `python3 docs/scripts/modify_docx.py`.

## Fichiers disponibles
- Document Word à modifier : `__TARGET_DOCX__`
- Récapitulatif JSON des tâches terminées du Sprint __SPRINT_BILAN__ : `__JSON_OUTPUT__`
- CSV exporté du Backlog Sprint __SPRINT_PROJ__ : `__CSV_OUTPUT__`
- Dossier des diagrammes de Gantt PNG du Sprint __SPRINT_PROJ__ : `docs/coaching/gantt_sprint___SPRINT_PROJ__/`
- Outil d'édition DOCX sécurisé : `python3 docs/scripts/modify_docx.py`

---

## ÉTAPE 1 : Insertion des diagrammes de Gantt du Sprint __SPRINT_PROJ__ dans le DOCX
Dans `docs/coaching/gantt_sprint___SPRINT_PROJ__/`, chaque fichier `image 1.png`, `image 2.png`, etc. correspond à un membre de l'équipe (par ordre alphabétique : Clément Pasteau, Victor Agahi, Victor Giroud).
Utilise la commande `insert-image` de `modify_docx.py` pour insérer chaque image PNG sous sa section respective :

```bash
# Exemple pour chaque membre sous son titre de section dans Diagrammes de Gantt :
python3 docs/scripts/modify_docx.py insert-image "__TARGET_DOCX__" --after-heading "Victor Giroud" --image "docs/coaching/gantt_sprint___SPRINT_PROJ__/image 3.png"
python3 docs/scripts/modify_docx.py insert-image "__TARGET_DOCX__" --after-heading "Victor Agahi" --image "docs/coaching/gantt_sprint___SPRINT_PROJ__/image 2.png"
python3 docs/scripts/modify_docx.py insert-image "__TARGET_DOCX__" --after-heading "Clément PASTEAU" --image "docs/coaching/gantt_sprint___SPRINT_PROJ__/image 1.png"
```
*(Adapte les index d'images selon les membres présents dans le sprint).*

---

## ÉTAPE 2 : Rédaction des synthèses techniques du Sprint __SPRINT_BILAN__
Consulte `__JSON_OUTPUT__` qui contient toutes les tâches terminées du Sprint __SPRINT_BILAN__ :
1. Pour chaque membre (**Victor Agahi**, **Clément Pasteau**, **Victor Giroud**) :
   - Rédige un paragraphe de synthèse technique dense et soigné, exactement dans le style du rapport (vocabulaire d'architecture précis, microservices, gRPC, outbox, workers, CI/CD, React Native, etc.).
2. Mets à jour la section d'introduction du sprint précédent, le total de charge/heures réalisées, et la conclusion.
3. Applique ces modifications textuelles sur `__TARGET_DOCX__` via `python3 docs/scripts/modify_docx.py replace`.

---

## ÉTAPE 3 : Remplissage de la projection du Sprint __SPRINT_PROJ__
1. Lis les tâches prévues pour le Sprint __SPRINT_PROJ__ dans `__CSV_OUTPUT__`.
2. Mets à jour :
   - Les axes de développement prévus pour le Sprint __SPRINT_PROJ__.
   - Le tableau de répartition des tâches (Tâche, Assigné, Lead).
   - Les dates de début et fin du Sprint __SPRINT_PROJ__.
3. Applique ces mises à jour via `python3 docs/scripts/modify_docx.py replace`.

---

## ÉTAPE 4 : Validation finale
Vérifie la cohérence du document avec :
```bash
python3 docs/scripts/modify_docx.py view "__TARGET_DOCX__" --limit 100
```
Assure-toi que toutes les sections, en-têtes, tableaux et images sont en place sans aucune altération de mise en page.
EOF

# Remplacer les placeholders dans le prompt de façon portable (macOS / Linux / WSL)
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s|__COACHING_NUM__|${COACHING_NUM}|g" "${PROMPT_FILE}"
  sed -i '' "s|__SPRINT_BILAN__|${SPRINT_BILAN}|g" "${PROMPT_FILE}"
  sed -i '' "s|__SPRINT_PROJ__|${SPRINT_PROJ}|g" "${PROMPT_FILE}"
  sed -i '' "s|__TARGET_DOCX__|${TARGET_DOCX}|g" "${PROMPT_FILE}"
  sed -i '' "s|__CSV_OUTPUT__|${CSV_OUTPUT}|g" "${PROMPT_FILE}"
  sed -i '' "s|__JSON_OUTPUT__|${JSON_OUTPUT}|g" "${PROMPT_FILE}"
else
  sed -i "s|__COACHING_NUM__|${COACHING_NUM}|g" "${PROMPT_FILE}"
  sed -i "s|__SPRINT_BILAN__|${SPRINT_BILAN}|g" "${PROMPT_FILE}"
  sed -i "s|__SPRINT_PROJ__|${SPRINT_PROJ}|g" "${PROMPT_FILE}"
  sed -i "s|__TARGET_DOCX__|${TARGET_DOCX}|g" "${PROMPT_FILE}"
  sed -i "s|__CSV_OUTPUT__|${CSV_OUTPUT}|g" "${PROMPT_FILE}"
  sed -i "s|__JSON_OUTPUT__|${JSON_OUTPUT}|g" "${PROMPT_FILE}"
fi

# Copie dans le presse-papier si pbcopy, clip.exe (WSL), wl-copy ou xclip est disponible
if command -v pbcopy &>/dev/null; then
  pbcopy < "${PROMPT_FILE}"
  echo -e "${GREEN}✓ Prompt copié dans le presse-papier macOS (pbcopy).${NC}"
elif command -v clip.exe &>/dev/null; then
  clip.exe < "${PROMPT_FILE}"
  echo -e "${GREEN}✓ Prompt copié dans le presse-papier Windows/WSL (clip.exe).${NC}"
elif command -v wl-copy &>/dev/null; then
  wl-copy < "${PROMPT_FILE}"
  echo -e "${GREEN}✓ Prompt copié dans le presse-papier (wl-copy).${NC}"
elif command -v xclip &>/dev/null; then
  xclip -selection clipboard < "${PROMPT_FILE}"
  echo -e "${GREEN}✓ Prompt copié dans le presse-papier (xclip).${NC}"
fi

PROMPT_CONTENT=$(cat "${PROMPT_FILE}")

# Fonction générique de localisation des binaires (macOS, Linux, WSL, NVM)
find_bin() {
  local name="$1"
  shift
  if command -v "${name}" &>/dev/null; then
    command -v "${name}"
    return 0
  fi
  for candidate in "$@"; do
    if [ -n "${candidate}" ] && [ -x "${candidate}" ]; then
      echo "${candidate}"
      return 0
    fi
  done
  # Recherche dans nvm si présent (très fréquent sous WSL / Linux)
  if [ -d "${HOME}/.nvm/versions/node" ]; then
    local nvm_bin
    nvm_bin=$(find "${HOME}/.nvm/versions/node" -maxdepth 3 -name "${name}" -type f -perm -111 2>/dev/null | head -n 1 || true)
    if [ -n "${nvm_bin}" ] && [ -x "${nvm_bin}" ]; then
      echo "${nvm_bin}"
      return 0
    fi
  fi
  return 1
}

# 7. Déclenchement de l'agent sélectionné
if [ "${AGENT_CHOICE}" = "1" ]; then
  CLAUDE_BIN=$(find_bin claude "${HOME}/.local/bin/claude" "/usr/local/bin/claude" "${HOME}/.npm-global/bin/claude" || true)
  if [ -n "${CLAUDE_BIN}" ] && [ -x "${CLAUDE_BIN}" ]; then
    echo -e "\n${GREEN}🚀 Lancement de Claude Code CLI (mode sans restrictions)...${NC}"
    exec "${CLAUDE_BIN}" --dangerously-skip-permissions "${PROMPT_CONTENT}"
  else
    echo -e "${RED}Erreur : Claude CLI non trouvé dans le PATH ni sous ~/.local/bin/claude.${NC}"
    echo -e "${YELLOW}Installation : npm install -g @anthropic-ai/claude-code${NC}"
    echo "Le prompt est disponible dans : ${PROMPT_FILE}"
  fi
elif [ "${AGENT_CHOICE}" = "2" ]; then
  AGY_BIN=$(find_bin agy "${HOME}/.local/bin/agy" "${HOME}/.antigravity/bin/agy" "/usr/local/bin/agy" || true)
  if [ -n "${AGY_BIN}" ] && [ -x "${AGY_BIN}" ]; then
    echo -e "\n${GREEN}🚀 Lancement d'Antigravity CLI (mode sans restrictions)...${NC}"
    exec "${AGY_BIN}" --dangerously-skip-permissions --prompt-interactive="${PROMPT_CONTENT}"
  else
    echo -e "${RED}Erreur : agy CLI non trouvé dans le PATH ni sous ~/.local/bin/agy.${NC}"
    echo -e "${YELLOW}Installation : curl -fsSL https://antigravity.google/cli/install.sh | bash${NC}"
    echo "Le prompt est disponible dans : ${PROMPT_FILE}"
  fi
else
  echo -e "${YELLOW}Choix inconnu. Le prompt est disponible dans : ${PROMPT_FILE}${NC}"
fi

