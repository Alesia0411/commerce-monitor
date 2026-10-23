FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY web web
COPY run.py .
RUN python -c "import pathlib,urllib.request; pathlib.Path('web/vendor').mkdir(exist_ok=True); urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/vue@3.5.13/dist/vue.global.prod.js','web/vendor/vue.global.prod.js')"
RUN useradd -m demo && chown -R demo:demo /app
USER demo
ENV HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "run.py"]
