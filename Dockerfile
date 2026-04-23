FROM python:3.12-alpine
WORKDIR /app
# On ajoute 'git' à la liste des paquets à installer
RUN apk add --no-cache \
    gcc \
    musl-dev \
    postgresql-dev \
    git

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# On ne met pas de flag ici, on les mettra dans le compose
CMD ["python", "main.py"]
