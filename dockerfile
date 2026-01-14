FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
  "mcp>=1.0.0" \
  google-api-python-client \
  google-auth \
  google-auth-oauthlib

COPY gmail_mcp_server.py /app/gmail_mcp_server.py

# secrets klasörü volume ile gelecek ama klasörü hazır tutalım
RUN mkdir -p /app/secrets /app/generated_presentations

EXPOSE 3001

CMD ["python", "gmail_mcp_server.py", "-t", "http", "-p", "3001"]
