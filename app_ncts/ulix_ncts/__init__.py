"""ULIX NCTS — génération d'annonces d'arrivée depuis les PDF déposés.

Modules :
  config     — configuration (dossiers, options, CargoWise)
  pdfio      — accès PDF (texte, images, OCR bandeau/zone, orientation)
  classify   — classification des pages (TRANSIT / EXPORT / AUTRE)
  extract    — extraction des données d'un document de transit (1..N MRN)
  render     — rendu PDF déterministe (réutilise generate_doc.py, gabarit figé)
  cw_client  — client MCP CargoWise (optionnel, enrichissement DM/date/dossier)
  pipeline   — orchestration : dépôt unique / dépôt multiple -> annonces
"""

__version__ = "1.0.1"
