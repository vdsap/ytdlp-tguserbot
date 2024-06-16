FROM ubuntu
LABEL authors="vdsap"
RUN apt update
RUN apt install -y python3 ffmpeg python-pip
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN apt install -y < requirements.txt
RUN pip3 install yt-dlp

CMD [ "python3", "./main.py" ]