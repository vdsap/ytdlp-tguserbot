FROM ubuntu
LABEL authors="vdsap"
RUN apt update
RUN apt install -y python3 ffmpeg pip
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip3 install --break-system-packages yt-dlp telethon

CMD [ "python3", "./main.py" ]
