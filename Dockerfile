FROM alpine:3.7

RUN apk --no-cache add python3

COPY requirements.txt /requirements.txt
RUN python3 -m pip install -r requirements.txt

COPY docker_exporter.py /usr/bin/docker_exporter

CMD ["/usr/bin/docker_exporter"]
