FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README-placeholder.md ./
COPY brain ./brain
# ".[identity]" — see the root Dockerfile: without the google-auth extra every
# Google sign-in fails at import time with the same message as a bad token.
RUN pip install --no-cache-dir ".[identity]"
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["uvicorn", "brain.main:app", "--host", "0.0.0.0", "--port", "8000"]

