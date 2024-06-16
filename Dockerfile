FROM ubuntu
LABEL authors="vdsap"
RUN apt update
RUN apt install -y python3 ffmpeg python3-pip
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

CMD [ "python3", "./main.py" ]