FROM python:3.10-slim

# Atur direktori kerja di dalam container
WORKDIR /app

# Salin file ke dalam container
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Jalankan aplikasi
CMD ["python", "app.py"]
