FROM ubuntu
LABEL authors="vdsap"
RUN apt update
RUN apt install -y python3 ffmpeg
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN apt install < requirements.txt

CMD [ "python3", "./main.py" ]