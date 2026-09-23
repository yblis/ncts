# Image CPU pour ULIX NCTS. Les modèles PaddleOCR sont préparés pendant le build.
FROM python:3.12-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    TZ=Europe/Paris \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/cache \
    ULIX_PROJET=/opt/ulix-ncts

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        poppler-utils \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ulix-ncts

COPY app_ncts/requirements.txt /tmp/requirements.txt
RUN python -m pip install -r /tmp/requirements.txt

COPY app_ncts/lancer.py /opt/ulix-ncts/app_ncts/lancer.py
COPY app_ncts/ulix_ncts/ /opt/ulix-ncts/app_ncts/ulix_ncts/
COPY app_ncts/Documentation/skills/ulix-doc-arrivee-ncts/scripts/generate_doc.py \
    /opt/ulix-ncts/app_ncts/Documentation/skills/ulix-doc-arrivee-ncts/scripts/generate_doc.py
COPY deploy/container-entrypoint.sh /opt/ulix-ncts/container-entrypoint.sh

# Aucun téléchargement de modèle ne sera nécessaire au démarrage du conteneur.
RUN mkdir -p /opt/ulix-ncts/ocr_models \
    && cd /opt/ulix-ncts/app_ncts \
    && python -m ulix_ncts.ocr_paddle --exporter /opt/ulix-ncts/ocr_models

RUN useradd --system --uid 10001 --create-home --home-dir /home/ncts ncts \
    && chmod 0555 /opt/ulix-ncts/container-entrypoint.sh

ENV ULIX_OCR_MODELES=/opt/ulix-ncts/ocr_models

USER 10001:10001
ENTRYPOINT ["/opt/ulix-ncts/container-entrypoint.sh"]
CMD ["--surveiller", "--sans-couleur"]
