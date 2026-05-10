FROM python:3.12-slim

WORKDIR /app/orders

COPY orders/requirements.txt /app/orders/requirements.txt
RUN pip install --no-cache-dir -r /app/orders/requirements.txt

COPY . /app
