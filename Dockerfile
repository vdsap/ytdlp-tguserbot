FROM python:3.11-slim
LABEL authors="vdsap"

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

CMD [ "python3", "./main.py" ]
