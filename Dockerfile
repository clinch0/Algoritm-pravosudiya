FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VO_DATA_DIR=/var/lib/second-opinion
WORKDIR /opt/app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt && useradd --uid 10001 --create-home app && mkdir -p /var/lib/second-opinion && chown app /var/lib/second-opinion
COPY app ./app
COPY mcp_server ./mcp_server
COPY tools/container_start.py ./tools/container_start.py
COPY data/*.json ./seed/
COPY samples/*.docx ./samples/
USER app
EXPOSE 8000
CMD ["python", "tools/container_start.py"]
