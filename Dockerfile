FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY schemas/ schemas/
COPY I2/ I2/
COPY main.py .
ENV PYTHONPATH=/app/I2
ENTRYPOINT ["python", "-u", "main.py"]
