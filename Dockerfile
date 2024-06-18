FROM ubuntu
LABEL authors="vdsap"
RUN apt update
RUN apt install -y python3 ffmpeg pip g++
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip3 install --break-system-packages -r requirements.txt

CMD [ "python3", "./main.py" ]
