FROM ghcr.io/hassio-addons/debian-base:7.8.3

RUN apt-get update && \
    apt-get install -y python3 python3-pip cec-utils udev libudev-dev && \
    pip3 install --break-system-packages paho-mqtt==1.6.1 && \
    apt-get clean

COPY cec_mqtt.py /cec_mqtt.py
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD [ "/run.sh" ]
