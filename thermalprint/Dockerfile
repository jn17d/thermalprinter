ARG BUILD_FROM
FROM $BUILD_FROM

# HA add-on base images are Alpine-based.
# If you switch to a Debian-based BUILD_FROM, swap apk for apt-get.
RUN apk add --no-cache \
    python3 \
    py3-pip \
    git \
    dbus \
    bash

WORKDIR /app

# Pull in TiMini Print's CLI/protocol code directly.
RUN git clone --depth 1 https://github.com/Dejniel/TiMini-Print.git /app/timini

RUN pip install --no-cache-dir --break-system-packages -r /app/timini/requirements.txt \
    && pip install --no-cache-dir --break-system-packages flask

COPY run.sh /run.sh
COPY app/print_server.py /app/print_server.py
# Monospace bold font used by the "Font size" slider for text printing.
# The Alpine base image ships no fonts, so upstream TiMini Print can't scale
# text without this pinned copy (see TEXT_FONT in print_server.py).
COPY app/assets/DejaVuSansMono-Bold.ttf /app/DejaVuSansMono-Bold.ttf
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
