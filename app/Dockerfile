FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir gunicorn==21.2.0

# Copying the imported code
COPY app.py ./app.py
COPY core ./core
COPY services ./services

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000

# run gunicorn on 0.0.0.0:8000 
CMD ["gunicorn", "-w", "2", "-k", "gthread", "-b", "0.0.0.0:8000", "app:app"]
