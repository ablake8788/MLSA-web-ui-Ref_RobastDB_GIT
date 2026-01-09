
FROM python:3.12-slim

# System deps:
# - unixodbc: runtime ODBC
# - unixodbc-dev + build-essential: allows pyodbc wheel/build if needed
# - curl + gnupg: to add Microsoft repo for msodbcsql18 (SQL Server driver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg2 ca-certificates \
    unixodbc unixodbc-dev \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Install Microsoft ODBC Driver 18 for SQL Server
RUN set -eux; \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg; \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list; \
    apt-get update; \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Container Apps commonly uses 8080
EXPOSE 8080

# Run Flask via Gunicorn (production)
# If your app factory name differs, adjust this import path accordingly.
CMD ["gunicorn", "-b", "0.0.0.0:8080", "tga_web.app_factory:create_app()"]



#FROM python:3.12-slim
#WORKDIR /app
#
#COPY requirements.txt .
#RUN pip install --no-cache-dir -r requirements.txt
#
#COPY . .
#
#EXPOSE 5000
#
#CMD ["gunicorn", "-b", "0.0.0.0:5000", "tga_web.app_factory:create_app()"]